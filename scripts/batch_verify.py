"""batch_verify —— 批量验证入口：单文件或文件夹 → 逐文件报告 + 索引。

口径（对应用户口径「给什么处理什么；处理不了就诚实说」）：
- **不做隐式合并**：一个文件 = 一份报告，保留测试集身份（跨文件同源/复刻结构在 INDEX 里提示）；
- `--lang auto`：按数据检测语言；判不出就报判不出（不瞎猜）；
- 适配（实测的上游文件形态）：
  · BOM 容忍（utf-8-sig）；
  · ID 前缀剥离：行首「字母+数字 ID」在全文件占多数时才剥（如 `guIn_google_0000001 <文本>`）；
  · `_inline_doc` 文件：同目录存在其他语料文件时视为元信息跳过；是唯一文件时当数据；
- INDEX.md 汇总：逐文件 语言/行数/句数/gate/字符/词汇/音素/能力缺口，附跨文件重复提示。

用法：
  python scripts/batch_verify.py --input <文件或目录> --out <输出根目录> [--lang auto|sw|...]
  python scripts/batch_verify.py --input <目录> --out <out> --only fr ur bn   # 只跑指定语言目录
  python scripts/batch_verify.py --input <目录> --out <out> --skip-g2p        # 跳过 G2P（快跑）
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corpus_kit.config import Config
from corpus_kit.io import ensure_dir, read_jsonl
from corpus_kit.detect import detect_script
from corpus_kit.reconstruct import normalize_newlines

PY = sys.executable

# 行首 ID 前缀：字母名 + 数字编号（如 guIn_google_0000001 / taIn_google_0000003）
ID_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z_\-]{1,20}\d{3,}\s+")
# 语言目录名 → 语言码（上游用大写目录名 / 中文前缀文件名）
DIR_LANG = {
    "AR": "ar", "BN": "bn", "EN": "en", "ES": "es", "FIL": "fil", "FR": "fr", "GU": "gu",
    "HA": "ha", "HI": "hi", "ID": "id", "MR": "mr", "PT": "pt", "RU": "ru", "SW": "sw",
    "TA": "ta", "TE": "te", "TR": "tr", "UR": "ur", "ZH": "zh",
}


def read_text(p: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return normalize_newlines(p.read_bytes().decode(enc))
        except UnicodeDecodeError:
            continue
    return p.read_bytes().decode("utf-8", errors="replace")


def strip_id_prefix(lines: list[str]) -> tuple[list[str], int]:
    """行首 ID 前缀剥离。只在「全文件多数行命中」时生效（防把正文误剥）。

    返回 (剥离后的行, 剥离数)。
    """
    nonblank = [l for l in lines if l.strip()]
    if not nonblank:
        return lines, 0
    n_hit = sum(1 for l in nonblank if ID_PREFIX_RE.match(l))
    if n_hit / len(nonblank) < 0.5:
        return lines, 0
    out = []
    n = 0
    for l in lines:
        m = ID_PREFIX_RE.match(l)
        if m:
            out.append(l[m.end():].strip())
            n += 1
        else:
            out.append(l)
    return out, n


def prepare_one(src: Path, dst_dir: Path) -> dict:
    """单文件 → INPUT.txt（清洗+去重沿用 prepare_input 链路）。返回统计。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    from prepare_input import read_source  # noqa: E402  复用同一读取口径
    from corpus_kit.clean import clean_config, clean_records, summarize
    from corpus_kit.reconstruct import reconstruct

    text = read_source(src)
    lines = [l for l in text.splitlines()]
    lines, n_id_stripped = strip_id_prefix(lines)
    text2 = "\n".join(lines)

    cfg = clean_config()
    recon = reconstruct(text2, "auto", quotechar=cfg.quotechar, doublequote=cfg.doublequote,
                        join_with=cfg.join_with, text_col=-1)
    if recon.content_preserved is False:
        raise SystemExit(f"[batch] {src.name} 重建丢内容（差 {recon.dropped_chars} 字符），已拦截")
    res = clean_records(recon.records, cfg)
    rows, dedup = res["rows"], res["dedup"]
    summary = summarize(rows, dedup)
    kept = [r for r in rows if r["kept"]]

    dst_dir.mkdir(parents=True, exist_ok=True)
    with (dst_dir / "INPUT.txt").open("w", encoding="utf-8", newline="\n") as f:
        for r in kept:
            f.write(json.dumps(r["text"], ensure_ascii=False) + "\n")
    (dst_dir / "INPUT.meta.json").write_text(json.dumps({
        "source": src.name, "columns": ["__text__"], "text_column": "__text__",
        "rows": len(kept), "id_prefix_stripped": n_id_stripped,
        "clean": {"detected_format": recon.detected_format, "n_in": recon.n_records,
                  "n_kept": len(kept), "n_dedup_dropped": summary["n_dedup_dropped"],
                  "n_quarantined": summary["n_quarantined"]},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"n_in": recon.n_records, "n_kept": len(kept), "n_dedup": summary["n_dedup_dropped"],
            "n_quarantined": summary["n_quarantined"], "n_id_stripped": n_id_stripped,
            "fmt": recon.detected_format}


def collect_files(root: Path, only: list[str] | None = None) -> list[tuple[str, Path]]:
    """目录 → [(语种码, 文件)]。单文件 → [(推断语种, 文件)]。

    两种目录形态都支持：
    · 语种子目录（AR/FR/…）——目录名即语言码；
    · 目录直接含文件——按文件名推断语言，或落到 --lang。
    """
    if root.is_file():
        code = infer_lang_from_name(root.name)
        return [(code, root)]

    def files_of(d: Path, code: str) -> list[tuple[str, Path]]:
        files = sorted(f for f in d.glob("*.txt") if f.is_file())
        if not files:
            return []
        data_files = [f for f in files if "_inline_doc" not in f.name]
        used = data_files or files     # _inline_doc 是唯一文件时当数据（实测 GU/TA/ZH 如此）
        return [(code, f) for f in used]

    out: list[tuple[str, Path]] = []
    subs = [d for d in sorted(root.iterdir()) if d.is_dir()]
    if not subs:
        # 目录本身含文件
        code = infer_lang_from_name(root.name)
        if only and code != "auto" and code not in only:
            return []
        return files_of(root, code)
    for sub in subs:
        code = DIR_LANG.get(sub.name.upper(), sub.name.lower())
        if only and code not in only:
            continue
        out.extend(files_of(sub, code))
    return out


def infer_lang_from_name(name: str) -> str:
    """从文件名/目录名推断语言码（如 `法语__fr_cv3_Jean.lst.txt` → fr；`FR` → fr）。"""
    low = name.lower()
    for code in sorted(DIR_LANG.values(), key=len, reverse=True):
        if f"__{code}" in low or f"__{code}_" in low:
            return code
    up = name.upper()
    if up in DIR_LANG:
        return DIR_LANG[up]
    return "auto"


def run_stage(cmd: list[str], desc: str) -> tuple[bool, str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def verify_one(code: str, src: Path, out_root: Path, args) -> dict:
    """单文件全流程：prepare → gate → length → sentence → vocab → [phoneme] → report。"""
    tag = src.stem[:60]
    run_dir = ensure_dir(out_root / f"{code}" / tag)
    info: dict = {"lang": code, "file": src.name, "run_dir": str(run_dir)}

    try:
        st = prepare_one(src, run_dir)
        info.update(st)
    except SystemExit as e:
        info["error"] = str(e)
        return info

    lang = code if code != "auto" else "auto"
    stages = [
        ("gate", [PY, str(ROOT / "skills" / "gate_validity" / "run.py"),
                  "--input", str(run_dir / "INPUT.txt"), "--meta", str(run_dir / "INPUT.meta.json"),
                  "--lang", lang, "--out", str(run_dir)]),
        ("length", [PY, str(ROOT / "skills" / "profile_length" / "run.py"),
                    "--records", str(run_dir / "records.jsonl"), "--lang", lang, "--out", str(run_dir)]),
        ("sentence", [PY, str(ROOT / "skills" / "profile_sentence" / "run.py"),
                      "--sentences", str(run_dir / "sentences.jsonl"), "--lang", lang, "--out", str(run_dir)]),
        ("vocab", [PY, str(ROOT / "skills" / "profile_vocab" / "run.py"),
                   "--records", str(run_dir / "records.jsonl"), "--sentences", str(run_dir / "sentences.jsonl"),
                   "--lang", lang, "--out", str(run_dir)]),
    ]
    if not args.skip_g2p:
        stages.append(("phoneme", [PY, str(ROOT / "skills" / "profile_phoneme" / "run.py"),
                                   "--sentences", str(run_dir / "sentences.jsonl"), "--lang", lang,
                                   "--out", str(run_dir), "--audit-n", str(args.audit_n)]))
    if not args.skip_etymology:
        stages.append(("etymology", [PY, str(ROOT / "skills" / "etymology_llm" / "run.py"),
                                     "--sentences", str(run_dir / "sentences.jsonl"), "--lang", lang,
                                     "--out", str(run_dir), "--verify"]))

    for name, cmd in stages:
        ok, log = run_stage(cmd, name)
        if not ok:
            # 语言判定失败要区分「auto 判不出」（诚实报告）与真实故障
            if "auto" in lang and name == "gate" and "无法确定语言" in log:
                info["error"] = "语言无法自动确定：" + log.strip().splitlines()[-1][:200]
            else:
                info["error"] = f"{name} 失败：" + log.strip().splitlines()[-1][:200]
            return info

    # report（gate 若为 auto 已落定语言）
    real_lang = lang
    gj = run_dir / "dims" / "gate.json"
    if gj.exists():
        real_lang = json.loads(gj.read_text(encoding="utf-8-sig")).get("lang") or lang
    info["lang"] = real_lang
    r = subprocess.run([PY, "-m", "corpus_kit.report", "--out", str(run_dir), "--lang", real_lang,
                        "--input", str(run_dir / "INPUT.txt"), "--meta", str(run_dir / "INPUT.meta.json")],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        info["error"] = "report 失败：" + (r.stderr or r.stdout).strip().splitlines()[-1][:200]
        return info

    # 汇总关键数字
    for dim in ("gate", "length", "vocab", "phoneme"):
        f = run_dir / "dims" / f"{dim}.json"
        if f.exists():
            info[dim] = json.loads(f.read_text(encoding="utf-8-sig"))
    return info


def brief(info: dict) -> dict:
    g = info.get("gate") or {}
    l = info.get("length") or {}
    v = info.get("vocab") or {}
    p = info.get("phoneme") or {}
    return {
        "lang": info.get("lang"), "file": info.get("file"),
        "run_dir": info.get("run_dir"),
        "rows_in": info.get("n_in"), "rows_kept": info.get("n_kept"),
        "dedup_dropped": info.get("n_dedup"), "id_stripped": info.get("n_id_stripped"),
        "sents": l.get("n_sents"), "lang_pass": g.get("lang_pass_ratio"),
        "charset_pass": g.get("charset_pass_ratio"),
        "tokens": v.get("tokens"), "types": v.get("types"),
        "dict_hit": v.get("dict_hit_ratio"),
        "g2p_miss": p.get("g2p_miss"),
        "syll_method": l.get("syll_method"),
        "gaps": g.get("capability_gaps") or [],
        "error": info.get("error"),
    }


def write_index(rows: list[dict], out_root: Path, src_root: Path) -> None:
    lines = ["# 批量验证索引（逐文件）", "",
             f"- 语料源：`{src_root}`",
             f"- 生成方式：`scripts/batch_verify.py`（不合并；一文件一报告）",
             f"- 共 {len(rows)} 个文件；成功 {sum(1 for r in rows if not r.get('error'))}，"
             f"失败/无法判定 {sum(1 for r in rows if r.get('error'))}", ""]
    # 按语言分组
    by_lang: dict = {}
    for r in rows:
        by_lang.setdefault(r.get("lang") or "?", []).append(r)
    for lang in sorted(by_lang):
        lines.append(f"## {lang}")
        lines.append("")
        lines.append("| 文件 | 行(入→留) | 去重丢 | 句数 | 语言pass | 字符pass | 词典命中 | G2P未覆盖 | 音节口径 | 备注 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
        for r in by_lang[lang]:
            note = r.get("error") or ("；".join(r.get("gaps") or []) or "")
            lines.append("| {file} | {rows_in}→{rows_kept} | {dedup_dropped} | {sents} | {lang_pass} | "
                         "{charset_pass} | {dict_hit} | {g2p_miss} | {syll_method} | {note} |".format(
                             file=r.get("file"), rows_in=r.get("rows_in"), rows_kept=r.get("rows_kept"),
                             dedup_dropped=r.get("dedup_dropped"), sents=r.get("sents"),
                             lang_pass=r.get("lang_pass"), charset_pass=r.get("charset_pass"),
                             dict_hit=r.get("dict_hit"), g2p_miss=r.get("g2p_miss"),
                             syll_method=r.get("syll_method"), note=note))
        lines.append("")
    # 跨文件同源提示（精确重复行）
    lines.append("## 跨文件提示（精确重复行数 ≥ 50 的文件对）")
    lines.append("")
    pairs = []
    texts: dict = {}
    for r in rows:
        rd = Path(r.get("run_dir") or "")
        f = rd / "INPUT.txt"
        if f.exists():
            texts[r["file"]] = set(l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip())
    names = sorted(texts)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = texts[names[i]], texts[names[j]]
            common = len(a & b)
            if common >= 50:
                pairs.append((names[i], names[j], common, min(len(a), len(b))))
    if pairs:
        lines.append("| 文件A | 文件B | 共同句数 | 较小文件规模 | 提示 |")
        lines.append("|---|---|---:|---:|---|")
        for a, b, c, m in sorted(pairs, key=lambda x: -x[2]):
            pct = c / m if m else 0
            tip = "几乎同一文本池（同池异声/复刻）" if pct >= 0.9 else "存在大量共用句"
            lines.append(f"| {a} | {b} | {c} | {m} | {tip} |")
    else:
        lines.append("（未发现 ≥50 句的跨文件精确重复）")
    lines.append("")
    (out_root / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    (out_root / "index.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="批量验证：逐文件报告 + 索引（不合并）")
    ap.add_argument("--input", required=True, help="单个文件，或包含语种子目录的目录")
    ap.add_argument("--out", required=True, help="输出根目录")
    ap.add_argument("--lang", default="auto", help="语言码或 auto（默认 auto）")
    ap.add_argument("--only", nargs="*", default=None, help="只处理这些语言码（目录模式下）")
    ap.add_argument("--skip-g2p", action="store_true")
    ap.add_argument("--skip-etymology", action="store_true", default=True)
    ap.add_argument("--audit-n", type=int, default=100)
    args = ap.parse_args(argv)

    src_root = Path(args.input)
    if not src_root.exists():
        raise SystemExit(f"输入不存在：{src_root}")
    out_root = ensure_dir(args.out)
    files = collect_files(src_root, args.only)
    if not files:
        raise SystemExit("未找到可处理的语料文件（检查 --input / --only）")
    print(f"[batch] {len(files)} 个文件 → {out_root}", flush=True)

    rows = []
    for i, (code, f) in enumerate(files, 1):
        # 命令行显式 --lang 优先；否则用目录推断（推断不出才 auto）
        lang = args.lang if args.lang != "auto" else (code or "auto")
        print(f"[{i}/{len(files)}] {f.name[:64]} (lang={lang})", flush=True)
        try:
            info = verify_one(lang, f, out_root, args)
        except Exception as e:
            info = {"lang": lang, "file": f.name, "error": f"{type(e).__name__}: {e}"}
        rows.append(brief(info))
        st = rows[-1]
        if st.get("error"):
            print(f"     {st['error'][:120]}", flush=True)
        else:
            print(f"    ✓ rows {st['rows_in']}→{st['rows_kept']}, sents {st['sents']}, "
                  f"lang {st['lang_pass']}, charset {st['charset_pass']}", flush=True)

    write_index(rows, out_root, src_root)
    print(f"\n[batch] INDEX: {out_root / 'INDEX.md'}")
    n_err = sum(1 for r in rows if r.get("error"))
    print(f"[batch] 完成：{len(rows) - n_err} 成功 / {n_err} 失败或无法判定")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())