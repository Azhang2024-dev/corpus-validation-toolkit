"""gate_validity —— 合法性 gate：目标语言判定 + 字符检查（准入，标记不下车）。
输入：INPUT.txt(+meta.json) → 输出：records.jsonl + dims/gate.json"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.charset import check_charset
from corpus_kit.config import Config
from corpus_kit.io import ensure_dir, read_input_rows, write_jsonl
from corpus_kit.lang import check_lang


def main(argv=None):
    ap = argparse.ArgumentParser(description="合法性 gate")
    ap.add_argument("--input", required=True, help="INPUT.txt 路径")
    ap.add_argument("--meta", default=None, help="INPUT.meta.json 路径（保留原表字段）")
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--out", required=True, help="output 运行目录")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 行（开发用）")
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    rows = read_input_rows(args.input, args.meta, args.limit)
    outdir = ensure_dir(args.out)
    if args.meta and Path(args.meta).exists():
        shutil.copyfile(args.meta, outdir / "input_meta.json")

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
    charset_pass = sum(1 for x in records if x["gate"]["charset"]["status"] == "pass")
    emoji = sum(1 for x in records if x["gate"]["charset"]["has_emoji"])
    dims = {
        "rows": n,
        "lang_pass": lang_pass,
        "lang_pass_ratio": round(lang_pass / n, 4) if n else 0.0,
        "lang_fail": n - lang_pass,
        "charset_pass": charset_pass,
        "charset_pass_ratio": round(charset_pass / n, 4) if n else 0.0,
        "charset_fail": n - charset_pass,
        "emoji_rows": emoji,
        "emoji_ratio": round(emoji / n, 4) if n else 0.0,
    }
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "gate.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(dims, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
