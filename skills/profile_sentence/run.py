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

TAIL_CHARS = ".!?…。！？؟۔।॥"      # 历史 sw 口径的超集（缺 cfg 时只用 .!?… 做兜底判定）


def classify(s: str, qwords: list[str], q_marks: str = "?", ex_marks: str = "!",
             tail_chars: str | None = None) -> tuple[str, str]:
    chars = tail_chars or ".!?…"
    tail_re = re.compile("[" + re.escape(chars) + "]+$")
    tail = tail_re.search(s)
    tail = tail.group(0) if tail else ""
    has_q = any(c in tail for c in q_marks)
    has_ex = any(c in tail for c in ex_marks)
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
    tail_chars = cfg.sentence_enders + "…"
    for s in sents:
        st, tail = classify(s.get("text", ""), cfg.question_words,
                            cfg.q_marks, cfg.ex_marks, tail_chars)
        s["sentence_type"] = st
        s["tail_punct"] = tail
        types[st] += 1
    write_jsonl(outdir / "sentences.jsonl", sents)

    n = len(sents)
    # 与目标配比差距 + 偏差告警（V2）：目标区间来自 config sentence_targets
    dist = []
    warn_count = 0
    for k, c in types.items():
        ratio = round(c / n, 4) if n else 0.0
        tgt = cfg.sentence_targets.get(k)
        item = {"句式": k, "句数": c, "占比": ratio}
        if tgt:
            lo, hi = tgt
            item["目标下"] = lo
            item["目标上"] = hi
            if ratio < lo:
                item["差距"] = round(ratio - lo, 4)
                item["告警"] = "偏低"
                warn_count += 1
            elif ratio > hi:
                item["差距"] = round(ratio - hi, 4)
                item["告警"] = "偏高"
                warn_count += 1
            else:
                item["差距"] = 0.0
                item["告警"] = ""
        dist.append(item)

    dims = {"n": n, "types": types, "targets": cfg.sentence_targets,
            "distribution": dist, "n_warn": warn_count,
            "status": "pass" if warn_count == 0 else "warn"}
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "sentence.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n": n, "types": types, "n_warn": warn_count, "status": dims["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
