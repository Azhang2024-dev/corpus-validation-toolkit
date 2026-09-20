"""profile_phoneme —— G2P（查表→epitran→补丁）+ 单字母/单音素/双音素分布 + 组合空间 + G2P 抽验。"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.config import Config
from corpus_kit.g2p import G2P, has_letter, load_ipa_dict
from corpus_kit.g2p_audit import audit as g2p_audit
from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl
from corpus_kit.phonemes import letter_stats, phoneme_dist, split_phonemes
from corpus_kit.phonotactics import normalize_sequence, phonotactics_report


def main(argv=None):
    ap = argparse.ArgumentParser(description="音素分布（G2P）")
    ap.add_argument("--sentences", required=True, help="sentences.jsonl")
    ap.add_argument("--lang", required=True, help="language code or auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="只音素化前 N 个句子（开发用）")
    ap.add_argument("--audit-n", type=int, default=200, help="G2P 一致性抽验样本数（0=跳过）")
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    sents = read_jsonl(args.sentences)
    if args.limit:
        sents = sents[: args.limit]
    outdir = ensure_dir(args.out)

    g2p = G2P(cfg)
    all_tokens = [t for s in sents for t in (s.get("tokens") or [])]
    uniq = sorted({t for t in all_tokens if t})
    token_ipa = g2p.phonemize_many(uniq)
    (outdir / "token_ipa.json").write_text(
        json.dumps(token_ipa, ensure_ascii=False, indent=1), encoding="utf-8")

    ipa_list: list[str] = []
    n_miss = 0
    for s in sents:
        phs: list[str] = []
        for t in s.get("tokens") or []:
            ipa = token_ipa.get(t)
            if ipa:
                phs.extend(split_phonemes(ipa, cfg))
            elif has_letter(t):
                # 含字母却拿不到 IPA = 未覆盖。判据用 has_letter（含连字符词），
                # 不用 isalpha()——后者对 `well-known` 为 False，会漏计。
                n_miss += 1
        s["n_phonemes"] = len(phs)
        s["phoneme_types"] = len(set(phs))
        ipa_list.append("".join(phs))
    write_jsonl(outdir / "sentences.jsonl", sents)

    # 音素分布：原始口径（保留词典写法，对齐历史数字）——句级拼接口径
    pd = phoneme_dist(ipa_list, cfg=cfg)
    # 归一口径（异写归并 + 前鼻化拆分）——同样句级拼接，与原始口径可比
    pd_norm = phoneme_dist(ipa_list, normalize=lambda s: normalize_sequence(s, cfg), cfg=cfg)

    # 归一后重建 bigram（键为真音素对），算理论组合空间/缺失组合
    # 注意：组合空间必须按**词内**音素序列统计——把整句音素拼起来会跨词边界造出伪组合
    from collections import Counter
    obs_bi: Counter = Counter()
    for t in uniq:
        ipa = token_ipa.get(t)
        if not ipa:
            continue
        ps = normalize_sequence(ipa, cfg)
        obs_bi.update(zip(ps, ps[1:]))
    ph_report = phonotactics_report(obs_bi, cfg)

    letters = letter_stats([s.get("text", "") for s in sents], cfg.letter_pattern)
    dims = {
        "n_single": pd["n_single"],
        "n_bi": pd["n_bi"],
        "total_bi": pd["total_bi"],
        "n_longtail_bi": sum(1 for v in pd["bi"].values() if v < 3),
        "single": pd["single"],
        "bi": pd["bi"],
        # 归一后（异写归并+前鼻化拆分），用于音素清单与组合空间
        "n_single_norm": pd_norm["n_single"],
        "n_bi_norm": pd_norm["n_bi"],
        "single_norm": pd_norm["single"],
        "bi_norm": pd_norm["bi"],
        "letters": letters,
        "g2p_miss": n_miss,
        # 未覆盖归因：区分「词形本就不音素化」「没配兜底器」「epitran 真故障」，
        # 否则 g2p_miss 只是个数，看不出是否发生了系统性 G2P 故障。
        "g2p_miss_breakdown": g2p.miss_breakdown(uniq),
        "phonotactics": ph_report,
    }

    # G2P 一致性抽验（V4.4）
    if args.audit_n:
        ipa_dict = load_ipa_dict(cfg.ipa_dict_path)
        dims["g2p_audit"] = g2p_audit(g2p, ipa_dict, cfg, n=args.audit_n)
        with (outdir / "g2p_audit.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["word", "dict_ipa", "epitran_ipa", "kind"])
            for m in dims["g2p_audit"]["mismatches"]:
                w.writerow([m["word"], m["dict_ipa"], m["epitran_ipa"], m["kind"]])

    ensure_dir(outdir / "dims")
    (outdir / "dims" / "phoneme.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    au = dims.get("g2p_audit") or {}
    print(json.dumps({
        "n_single": pd["n_single"], "n_single_norm": pd_norm["n_single"],
        "n_bi": pd["n_bi"], "n_bi_norm": pd_norm["n_bi"], "total_bi": pd["total_bi"],
        "longtail_bi": dims["n_longtail_bi"], "letters_total": letters["total"],
        "g2p_miss": n_miss,
        "space": ph_report["n_space"], "missing": ph_report["n_missing"], "out_of_space": ph_report["n_out_of_space"],
        "g2p_audit": {"n": au.get("n_sample"), "rate_folded": au.get("rate_folded"), "rate_phoneme": au.get("rate_phoneme"), "status_folded": au.get("status_folded"), "status_phoneme": au.get("status_phoneme"), "status_overall": au.get("status_overall", au.get("status")), "status": au.get("status_overall", au.get("status"))},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())