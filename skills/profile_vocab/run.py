"""profile_vocab —— 词频/外来/实虚/NSW。records+sentences → dims/vocab.json，句子回写 nsw_types。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.config import Config
from corpus_kit.g2p import load_ipa_dict
from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl
from corpus_kit.stats import entropy_norm, gini, top_share
from corpus_kit.tokenize import word_tokens


def main(argv=None):
    ap = argparse.ArgumentParser(description="词汇分布")
    ap.add_argument("--records", required=True, help="records.jsonl")
    ap.add_argument("--sentences", required=True, help="sentences.jsonl")
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    records = read_jsonl(args.records)
    sents = read_jsonl(args.sentences)
    outdir = ensure_dir(args.out)

    # ---------------- 词频（行级口径，对齐 37.2 万 token） ----------------
    toks: list[str] = []
    for r in records:
        toks.extend(word_tokens(r.get("text", "")))
    cnt: Counter = Counter(toks)
    N = len(toks)
    V = len(cnt)
    dict_words = load_ipa_dict(cfg.ipa_dict_path)
    dict_hit = sum(1 for t in toks if t in dict_words)
    sw_hit = sum(1 for t in toks if t in cfg.function_words)
    en_hit = sum(1 for t in toks if t in cfg.en_function_words)
    dims = {
        "tokens": N,
        "types": V,
        "ttr": round(V / N, 4) if N else 0.0,
        "h_norm": entropy_norm(cnt),
        "gini": gini(cnt),
        "top10_share": top_share(cnt, 0.1),
        "dict_hit_ratio": round(dict_hit / N, 4) if N else 0.0,
        "sw_ratio": round(sw_hit / N, 4) if N else 0.0,
        "en_ratio": round(en_hit / N, 4) if N else 0.0,
        "nsw_sent_ratio": 0.0,
        "top": cnt.most_common(100),
    }

    # ---------------- NSW（句级，句内任一命中即算） ----------------
    nsw_sents = 0
    for s in sents:
        text = s.get("text", "")
        hit_names: list[str] = []
        for name, pat in cfg.nsw_patterns:
            try:
                if re.search(pat, text, re.IGNORECASE if name != "全大写缩写" else 0):
                    hit_names.append(name)
            except re.error:
                continue
        s["nsw_types"] = list(dict.fromkeys(hit_names))
        if hit_names:
            nsw_sents += 1
    dims["nsw_sent_ratio"] = round(nsw_sents / len(sents), 4) if sents else 0.0
    dims["nsw_sents"] = nsw_sents
    write_jsonl(outdir / "sentences.jsonl", sents)

    ensure_dir(outdir / "dims")
    (outdir / "dims" / "vocab.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "tokens": N, "types": V, "h_norm": dims["h_norm"], "gini": dims["gini"],
        "top10_share": dims["top10_share"], "dict_hit_ratio": dims["dict_hit_ratio"],
        "sw_ratio": dims["sw_ratio"], "en_ratio": dims["en_ratio"],
        "nsw_sent_ratio": dims["nsw_sent_ratio"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
