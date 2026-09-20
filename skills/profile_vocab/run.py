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
    ap.add_argument("--lang", required=True, help="language code or auto")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    records = read_jsonl(args.records)
    sents = read_jsonl(args.sentences)
    outdir = ensure_dir(args.out)

    # ---------------- 词频（行级口径，对齐 37.2 万 token） ----------------
    toks: list[str] = []
    for r in records:
        toks.extend(word_tokens(r.get("text", ""), cfg.token_pattern))
    cnt: Counter = Counter(toks)
    N = len(toks)
    V = len(cnt)
    dict_words = load_ipa_dict(cfg.ipa_dict_path)
    dict_hit = sum(1 for t in toks if t in dict_words)
    fw_hit = sum(1 for t in toks if t in cfg.function_words)
    en_hit = sum(1 for t in toks if t in cfg.en_function_words)
    dims = {
        "tokens": N,
        "types": V,
        "ttr": round(V / N, 4) if N else 0.0,
        "h_norm": entropy_norm(cnt),
        "gini": gini(cnt),
        "top10_share": top_share(cnt, 0.1),
        "dict_hit_ratio": round(dict_hit / N, 4) if N else 0.0,
        "dict_available": bool(cfg.ipa_dict_path and cfg.ipa_dict_path.exists()),
        # 键名 fw_ratio（虚词=function word）；sw_ratio 为旧名，读端兼容
        "fw_ratio": round(fw_hit / N, 4) if N else 0.0,
        "sw_ratio": round(fw_hit / N, 4) if N else 0.0,
        "has_function_words": bool(cfg.function_words),
        "en_ratio": round(en_hit / N, 4) if N else 0.0,
        "nsw_sent_ratio": 0.0,
        # top 只留前 100 供展示；截断必须自证，否则读者会以为 top100 就是全部型符。
        # 全量「词→频次」表在 词级明细.jsonl / 数据集_词级明细.csv（两处均含全部型符）。
        "top": cnt.most_common(100),
        "top_n": min(100, V),
        "top_truncated": V > 100,
        "top_full_source": "词级明细.jsonl / 数据集_词级明细.csv",
    }

    # ---------------- NSW（句级，句内任一命中即算） ----------------
    # 记录命中的具体串，而不是只留类别名：否则报告里只剩「纯数字/全大写缩写」标签，
    # 看不到到底是 17 还是 2026、是 KH 还是 NU，规则误报（如年份区间被号码规则命中）也无从复核。
    nsw_sents = 0
    cat_sent = Counter()      # 类别 → 命中句数
    cat_hits = Counter()      # 类别 → 命中串总次数
    cat_samples: dict = {}    # 类别 → 命中串频次 Counter（供示例/排序）
    for s in sents:
        text = s.get("text", "")
        hits: dict = {}
        for name, pat in cfg.nsw_patterns:
            try:
                found = [m.group(0) for m in re.finditer(pat, text, re.IGNORECASE if name != "全大写缩写" else 0)]
            except re.error:
                continue
            if found:
                hits[name] = list(dict.fromkeys(found))  # 同类去重、保留出现顺序
                cat_sent[name] += 1
                cat_hits[name] += len(found)
                sc = cat_samples.setdefault(name, Counter())
                sc.update(found)
        s["nsw_types"] = list(hits.keys())
        s["nsw_hits"] = hits
        if hits:
            nsw_sents += 1
    dims["nsw_by_category"] = [
        {"category": name, "sentences": cat_sent[name], "hits": cat_hits[name],
         "top": cat_samples.get(name, Counter()).most_common(20)}
        for name, _ in cfg.nsw_patterns if cat_sent[name]
    ]
    dims["nsw_sent_ratio"] = round(nsw_sents / len(sents), 4) if sents else 0.0
    dims["nsw_sents"] = nsw_sents
    write_jsonl(outdir / "sentences.jsonl", sents)

    ensure_dir(outdir / "dims")
    (outdir / "dims" / "vocab.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "tokens": N, "types": V, "h_norm": dims["h_norm"], "gini": dims["gini"],
        "top10_share": dims["top10_share"], "dict_hit_ratio": dims["dict_hit_ratio"],
        "fw_ratio": dims["fw_ratio"], "en_ratio": dims["en_ratio"],
        "nsw_sent_ratio": dims["nsw_sent_ratio"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
