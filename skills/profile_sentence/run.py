"""profile_sentence —— 句式分布：疑问/感叹/陈述/短语。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.config import Config
from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl

TAIL_RE = re.compile(r"[.!?…]+$")


def classify(s: str, qwords: list[str]) -> tuple[str, str]:
    tail = TAIL_RE.search(s)
    tail = tail.group(0) if tail else ""
    has_q = "?" in tail
    has_ex = "!" in tail
    first = s.lstrip().lower()
    qw = any(first == w or first.startswith(w + " ") for w in qwords)
    n_words = len(s.split())
    if has_q or qw:
        return "疑问", tail
    if has_ex:
        return "感叹", tail
    if not tail and n_words < 5:
        return "短语", tail
    return "陈述", tail


def main(argv=None):
    ap = argparse.ArgumentParser(description="句式分布")
    ap.add_argument("--sentences", required=True, help="sentences.jsonl 路径")
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    sents = read_jsonl(args.sentences)
    outdir = ensure_dir(args.out)
    types = {"疑问": 0, "感叹": 0, "陈述": 0, "短语": 0}
    for s in sents:
        st, tail = classify(s.get("text", ""), cfg.question_words)
        s["sentence_type"] = st
        s["tail_punct"] = tail
        types[st] += 1
    write_jsonl(outdir / "sentences.jsonl", sents)
    dims = {"n": len(sents), "types": types}
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "sentence.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(dims, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
