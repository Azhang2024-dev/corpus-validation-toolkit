"""fetch_dicts —— 发音词典 / 音节数据获取与规范化（多语种，可复现）。

来源与许可（逐条记录进 data/ipa/SOURCES.md）：
- **ipa-dict**（MIT, open-dict-data/ipa-dict）：sw / fr / en / es / pt / zh
  格式 `词\t/IPA/`，与工具集加载格式同构，直接取用。
- **WikiPron**（数据按 Wiktionary 条款 CC BY-SA 系；代码 Apache-2.0，CUNY-CL/wikipron）：
  其余语种。格式 `词\t音素 空格分隔`，规范化为 `词\tIPA`（去空格；一词多行的取首条）。
- **Lexique383**（CC BY-SA 4.0, lexique.org）：法语音节数（ortho → nbsyll）。

下载通道：cdn.jsdelivr.net（GitHub 仓库 CDN，raw.githubusercontent 直连不通时的可用通道）；
lexique.org 走 http（其 https 证书 altname 不含 www 前缀）。网络不可达时如实报错退出，不静默。

用法：
  python scripts/fetch_dicts.py            # 拉取全部并规范化
  python scripts/fetch_dicts.py --check    # 只检查现有文件（不联网）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IPA_DIR = ROOT / "data" / "ipa"
SYLL_DIR = ROOT / "data" / "syll"

JSDELIVR_IPA = "https://cdn.jsdelivr.net/gh/open-dict-data/ipa-dict@master/data/{name}.txt"
JSDELIVR_WIKIPRON = "https://cdn.jsdelivr.net/gh/CUNY-CL/wikipron@master/data/scrape/tsv/{name}.tsv"
# jsdelivr 对 >20MB 文件不放行（实测 rus_cyrl_narrow.tsv 21MB）→ 大文件走 GitHub 原始地址
GITHUB_WIKIPRON = "https://raw.githubusercontent.com/CUNY-CL/wikipron/master/data/scrape/tsv/{name}.tsv"
RAW_FALLBACK = {"ru"}    # 需要走 GitHub 原始地址的语种
LEXIQUE_TSV = "http://www.lexique.org/databases/Lexique383/Lexique383.tsv"

# ── 语种 → 来源规格 ──────────────────────────────────────────
# kind: ipa_dict | wikipron；remote 为远端文件名；note 记入口径说明
SPECS: dict[str, dict] = {
    "sw": {"kind": "ipa_dict", "remote": "sw", "note": "斯瓦希里语（已入库，跳过）"},
    "fr": {"kind": "ipa_dict", "remote": "fr_FR", "note": "法语（法国）"},
    "en": {"kind": "ipa_dict", "remote": "en_US", "note": "英语（美式）"},
    "es": {"kind": "ipa_dict", "remote": "es_ES", "note": "西班牙语（卡斯蒂利亚）"},
    "pt": {"kind": "ipa_dict", "remote": "pt_BR", "note": "葡萄牙语（巴西）"},
    "zh": {"kind": "ipa_dict", "remote": "zh_hans", "note": "中文（简体；字/词级，覆盖有限）"},
    "ar": {"kind": "wikipron", "remote": "ara_arab_broad", "note": "阿拉伯语（宽式）"},
    "bn": {"kind": "wikipron", "remote": "ben_beng_dhaka_broad", "note": "孟加拉语（达卡方言，与语料来源地区一致）"},
    "gu": {"kind": "wikipron", "remote": "guj_gujr_broad", "note": "古吉拉特语（宽式）"},
    "ha": {"kind": "wikipron", "remote": "hau_latn_broad", "note": "豪萨语（宽式）"},
    "hi": {"kind": "wikipron", "remote": "hin_deva_broad", "note": "印地语（宽式）"},
    "id": {"kind": "wikipron", "remote": "ind_latn_broad", "note": "印尼语（宽式）"},
    "mr": {"kind": "wikipron", "remote": "mar_deva_broad", "note": "马拉地语（宽式）"},
    "ru": {"kind": "wikipron", "remote": "rus_cyrl_narrow", "note": "俄语（**仅窄式**——WikiPron 无宽式，口径限制已披露）"},
    "ta": {"kind": "wikipron", "remote": "tam_taml_broad", "note": "泰米尔语（宽式）"},
    "te": {"kind": "wikipron", "remote": "tel_telu_broad", "note": "泰卢固语（宽式；上游语料为空，备用）"},
    "tr": {"kind": "wikipron", "remote": "tur_latn_broad", "note": "土耳其语（宽式）"},
    "ur": {"kind": "wikipron", "remote": "urd_arab_broad", "note": "乌尔都语（宽式）"},
    "fil": {"kind": "wikipron", "remote": "tgl_latn_broad", "note": "菲律宾语（**以塔加洛 tgl 代理**——WikiPron 无 fil 条目，口径限制已披露）"},
}


def _download(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "corpus-kit-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download_curl(url: str, timeout: int = 300) -> bytes:
    """urllib 失败时的 curl 回退。

    两个 Windows 实操要点（实测踩到）：
    - `--ssl-no-revoke`：schannel 吊销查询在离线环境报 CRYPT_E_REVOCATION_OFFLINE；
    - jsdelivr 对 >20MB 文件返回错误（GitHub 大文件如 rus_cyrl_narrow.tsv 需走
      raw.githubusercontent + 本 flag）。
    """
    out = subprocess.run(["curl", "-sSL", "--ssl-no-revoke", "--max-time", str(timeout), url],
                         capture_output=True, timeout=timeout + 20)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"curl 下载失败 rc={out.returncode}: {url} :: {out.stderr[:200]!r}")
    return out.stdout


def fetch_bytes(url: str) -> bytes:
    for fn in (_download, _download_curl):
        try:
            data = fn(url)
            if data:
                return data
        except Exception as e:
            last = e
    raise RuntimeError(f"下载失败（urllib+curl 均不可用）：{url} :: {last}")


def convert_wikipron(raw: bytes) -> tuple[str, int, int]:
    """WikiPron tsv → `词\tIPA`。去音素间空格；一词多条取首条并计数。"""
    text = raw.decode("utf-8-sig")
    seen: dict[str, str] = {}
    n_multi = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        w, _, ph = line.partition("\t")
        w = w.strip()
        ph = ph.strip()
        if not w or not ph:
            continue
        if "/" in ph:  # 多发音（斜杠分隔）取首条，口径记录
            ph = ph.split("/", 1)[0].strip()
            n_multi += 1
        ph = ph.replace(" ", "")
        if not ph:
            continue
        if w in seen:
            if seen[w] != ph:
                n_multi += 1
            continue
        seen[w] = ph
    out = "".join(f"{w}\t{p}\n" for w, p in seen.items())
    return out, len(seen), n_multi


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="发音词典/音节数据获取与规范化")
    ap.add_argument("--only", nargs="*", default=None, help="只处理这些语种（默认全部）")
    ap.add_argument("--check", action="store_true", help="只检查现有文件，不联网")
    args = ap.parse_args(argv)

    IPA_DIR.mkdir(parents=True, exist_ok=True)
    SYLL_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    targets = [c for c in SPECS if (not args.only or c in args.only)]

    for code in targets:
        spec = SPECS[code]
        dst = IPA_DIR / f"{code}.txt"
        if args.check:
            if dst.exists():
                n = sum(1 for _ in dst.open(encoding="utf-8"))
                print(f"[check] {code}: {dst.name} {n} 条")
            else:
                print(f"[check] {code}: 缺失 {dst}")
            continue
        if code == "sw" and dst.exists():
            n = sum(1 for _ in dst.open(encoding="utf-8"))
            manifest[code] = {"source": "ipa-dict", "remote": spec["remote"], "note": spec["note"],
                              "entries": n, "kept": n, "multi": 0, "sha256": _sha256(dst.read_bytes()),
                              "fetched_at": "已入库（本次跳过）"}
            print(f"[skip] sw: 已存在 {n} 条")
            continue

        if spec["kind"] == "ipa_dict":
            url = JSDELIVR_IPA.format(name=spec["remote"])
            raw = fetch_bytes(url)
            text = raw.decode("utf-8")
            dst.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            n = sum(1 for l in text.splitlines() if l.strip())
            manifest[code] = {"source": "ipa-dict(MIT)", "remote": spec["remote"], "note": spec["note"],
                              "entries": n, "kept": n, "multi": 0,
                              "sha256": _sha256(dst.read_bytes()),
                              "fetched_at": datetime.now().isoformat(timespec="seconds")}
            print(f"[ok] {code}: ipa-dict {spec['remote']} → {n} 条")
        else:
            url = (GITHUB_WIKIPRON if code in RAW_FALLBACK else JSDELIVR_WIKIPRON).format(name=spec["remote"])
            raw = fetch_bytes(url)
            out, n_kept, n_multi = convert_wikipron(raw)
            dst.write_text(out, encoding="utf-8")
            n_in = len([l for l in raw.decode("utf-8-sig").splitlines() if l.strip()])
            manifest[code] = {"source": "WikiPron(Apache-2.0 code; data CC BY-SA via Wiktionary)",
                              "remote": spec["remote"], "note": spec["note"],
                              "entries": n_in, "kept": n_kept, "multi": n_multi,
                              "sha256": _sha256(dst.read_bytes()),
                              "fetched_at": datetime.now().isoformat(timespec="seconds")}
            print(f"[ok] {code}: WikiPron {spec['remote']} → {n_kept} 条（多发音/重复 {n_multi}）")

    if args.check:
        return 0

    # ─ 法语音节（Lexique383 nbsyll）───────────────────────────
    fr_syll = SYLL_DIR / "fr.txt"
    if (not args.only or "fr" in args.only) and not fr_syll.exists():
        try:
            raw = fetch_bytes(LEXIQUE_TSV)
            text = raw.decode("utf-8-sig")
            lines = text.splitlines()
            header = lines[0].split("\t")
            i_ortho, i_nbsyll = header.index("ortho"), header.index("nbsyll")
            seen: dict[str, str] = {}
            for line in lines[1:]:
                cells = line.split("\t")
                if len(cells) <= i_nbsyll:
                    continue
                w = cells[i_ortho].strip().lower()
                n = cells[i_nbsyll].strip()
                if w and n and w not in seen:
                    seen[w] = n
            fr_syll.write_text("".join(f"{w}\t{n}\n" for w, n in seen.items()), encoding="utf-8")
            manifest["fr_syll"] = {"source": "Lexique383(CC BY-SA 4.0)", "remote": "Lexique383.tsv",
                                   "note": "法语音节数 nbsyll（词形→音节数）",
                                   "entries": len(seen), "kept": len(seen), "multi": 0,
                                   "sha256": _sha256(fr_syll.read_bytes()),
                                   "fetched_at": datetime.now().isoformat(timespec="seconds")}
            print(f"[ok] fr 音节: Lexique383 → {len(seen)} 条")
        except Exception as e:
            print(f"[warn] fr 音节下载失败（法语音节将按近似口径并披露）：{e}", file=sys.stderr)

    # ── 落 manifest（供 SOURCES.md / INFO 引用）────────────────
    mpath = IPA_DIR / "_sources.json"
    old = {}
    if mpath.exists():
        try:
            old = json.loads(mpath.read_text(encoding="utf-8-sig"))
        except Exception:
            old = {}
    old.update(manifest)
    mpath.write_text(json.dumps(old, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"manifest: {mpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())