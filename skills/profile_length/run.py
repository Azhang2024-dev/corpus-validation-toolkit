"""profile_length —— 切句 + 四类长度分布（字符/词/音节）。records.jsonl → sentences.jsonl + dims/length.json"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl
from corpus_kit.segment import split_sents
from corpus_kit.stats import summary
from corpus_kit.tokenize import whitespace_words, word_tokens

SYLL_RE = re.compile(r"[aeiou]")


def syll(t: str) -> int:
    return len(SYLL_RE.findall(t.lower()))


def main(argv=None):
    ap = argparse.ArgumentParser(description="长度分布（含切句）")
    ap.add_argument("--records", required=True, help="records.jsonl 路径")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 行（开发用）")
    args = ap.parse_args(argv)

    records = read_jsonl(args.records)
    if args.limit:
        records = records[: args.limit]
    outdir = ensure_dir(args.out)

    sentences = []
    sent_id = 0
    para_chars, para_words, para_sents = [], [], []
    for r in records:
        text = r.get("text", "")
        ss = [s for s in split_sents(text) if s]
        para_chars.append(len(text))
        para_words.append(len(whitespace_words(text)))
        para_sents.append(len(ss))
        for s in ss:
            sent_id += 1
            sentences.append({
                "sent_id": sent_id,
                "row_id": r["row_id"],
                "text": s,
                "n_chars": len(s),
                "n_words": len(whitespace_words(s)),
                "n_syllables": syll(s),
                "tokens": word_tokens(s),
            })
    write_jsonl(outdir / "sentences.jsonl", sentences)

    cs = [x["n_chars"] for x in sentences]
    ws = [x["n_words"] for x in sentences]
    sy = [x["n_syllables"] for x in sentences]
    dims = {
        "n_sents": len(sentences),
        "n_rows": len(records),
        "char": summary(cs),
        "word": summary(ws),
        "syll": summary(sy),
        "over_300": sum(1 for v in cs if v > 300),
        "over_30w": sum(1 for v in ws if v > 30),
        "over_60syll": sum(1 for v in sy if v > 60),
        "para": {"char": summary(para_chars), "word": summary(para_words), "sents": summary(para_sents)},
    }
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "length.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_sents": len(sentences), "over_300": dims["over_300"],
                      "over_30w": dims["over_30w"], "over_60syll": dims["over_60syll"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
