"""gate_validity —— 合法性 gate：目标语言判定 + 字符检查（准入，标记不下车）。
输入：INPUT.txt(+meta.json) → 输出：records.jsonl + dims/gate.json

多语种（2026-09-18）：
- `--lang auto`：从数据检测语言（判不出就按判不出报，不瞎猜）；
- gate.json 增记**指令校验**（--lang 与数据脚本是否相符）与**能力缺口**（缺哪些资源、
  哪些判定因此降级），供报告「能力与口径」块。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.charset import check_charset
from corpus_kit.config import Config
from corpus_kit.detect import detect_language, detect_script, verify_lang_command
from corpus_kit.io import ensure_dir, read_input_rows, write_jsonl
from corpus_kit.lang import check_lang


def _available_langs() -> list[str]:
    data_dir = Path(__file__).resolve().parents[2] / "data" / "lang"
    return sorted(p.stem for p in data_dir.glob("*.yaml")) if data_dir.exists() else []


def _resolve_lang(args, texts: list[str]) -> tuple[str, dict]:
    """--lang auto → 依据数据检测（选不出就报选不出）；否则按指令并做相符性核对。"""
    if args.lang != "auto":
        cfg = Config(args.lang)
        det = detect_script("\n".join(texts[:200]))
        return args.lang, verify_lang_command(
            args.lang, cfg.script, det, detect_language("\n".join(texts[:50])),
            getattr(cfg, "langdetect_aliases", None))
    from corpus_kit.detect import pick_language
    avail = _available_langs()
    families = {c: Config(c).script for c in avail}
    aliases = {c: getattr(Config(c), "langdetect_aliases", []) for c in avail}
    pick = pick_language("\n".join(texts[:200]), avail, families, aliases)
    if not pick.get("lang"):
        raise SystemExit(
            f"[gate] --lang auto 无法确定语言：{pick.get('reason')}；"
            f"候选={pick.get('candidates')}。请显式 --lang 指定后重跑。")
    return pick["lang"], {"status": "auto", "picked": pick["lang"], "method": pick["method"],
                          "confidence": pick.get("confidence"), "detected_script": pick.get("detected_script"),
                          "detected_lang": pick.get("detected_lang"), "notes": []}


def main(argv=None):
    ap = argparse.ArgumentParser(description="合法性 gate")
    ap.add_argument("--input", required=True, help="INPUT.txt 路径")
    ap.add_argument("--meta", default=None, help="INPUT.meta.json 路径（保留原表字段）")
    ap.add_argument("--lang", default="sw", help="语言码，或 auto（按数据检测）")
    ap.add_argument("--out", required=True, help="output 运行目录")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 行（开发用）")
    args = ap.parse_args(argv)

    rows = read_input_rows(args.input, args.meta, args.limit)
    outdir = ensure_dir(args.out)
    if args.meta and Path(args.meta).exists():
        shutil.copyfile(args.meta, outdir / "input_meta.json")

    texts = [r.text for r in rows]
    lang_code, lang_check = _resolve_lang(args, texts)
    cfg = Config(lang_code)

    records = []
    for r in rows:
        lang = check_lang(r.text, cfg)
        charset = check_charset(r.text, cfg)
        records.append({
            "row_id": r.row_id, "text": r.text, "fields": r.fields,
            "gate": {"lang": lang, "charset": charset},
        })
    write_jsonl(outdir / "records.jsonl", records)

    n = len(records)
    lang_pass = sum(1 for x in records if x["gate"]["lang"]["status"] == "pass")
    lang_warn = sum(1 for x in records if x["gate"]["lang"]["status"] == "warn")
    lang_fail = sum(1 for x in records if x["gate"]["lang"]["status"] == "fail")
    charset_pass = sum(1 for x in records if x["gate"]["charset"]["status"] == "pass")
    charset_warn = sum(1 for x in records if x["gate"]["charset"]["status"] == "warn")
    charset_fail = sum(1 for x in records if x["gate"]["charset"]["status"] == "fail")
    emoji = sum(1 for x in records if x["gate"]["charset"]["has_emoji"])
    dims = {
        "rows": n,
        "lang": lang_code,
        "script_family": cfg.script,
        "lang_check": lang_check,
        "lang_pass": lang_pass,
        "lang_pass_ratio": round(lang_pass / n, 4) if n else 0.0,
        "lang_warn": lang_warn,
        # 三档分开计：原 `n - pass` 会把 warn 并进 fail，让「重度混杂建议复核」被误报成硬失败。
        "lang_fail": lang_fail,
        "charset_pass": charset_pass,
        "charset_pass_ratio": round(charset_pass / n, 4) if n else 0.0,
        "charset_warn": charset_warn,
        "charset_fail": charset_fail,
        "emoji_rows": emoji,
        "emoji_ratio": round(emoji / n, 4) if n else 0.0,
        "function_words_available": bool(cfg.function_words),
        "dict_available": bool(cfg.ipa_dict_path and cfg.ipa_dict_path.exists()),
        # 能力缺口（诚实留痕）：缺什么、哪些判定因此降级
        "capability_gaps": list(cfg.capability_gaps),
        "degraded": bool(cfg.capability_gaps),
        "degraded_reasons": list(cfg.capability_gaps),
    }
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "gate.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: dims[k] for k in ("rows", "lang", "lang_pass_ratio", "charset_pass_ratio",
                                           "degraded")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
