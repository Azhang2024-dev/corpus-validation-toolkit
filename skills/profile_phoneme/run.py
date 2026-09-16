"""profile_phoneme —— G2P（查表→epitran→补丁）+ 单字母/单音素/双音素分布。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.config import Config
from corpus_kit.g2p import G2P
from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl
from corpus_kit.phonemes import letter_stats, phoneme_dist, split_phonemes


def main(argv=None):
    ap = argparse.ArgumentParser(description="音素分布（G2P）")
    ap.add_argument("--sentences", required=True, help="sentences.jsonl")
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="只音素化前 N 个句子（开发用）")
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
                phs.extend(split_phonemes(ipa))
            elif t.isalpha() or "'" in t:
                n_miss += 1
        s["n_phonemes"] = len(phs)
        s["phoneme_types"] = len(set(phs))
        ipa_list.append("".join(phs))
    write_jsonl(outdir / "sentences.jsonl", sents)

    pd = phoneme_dist(ipa_list)
    letters = letter_stats([s.get("text", "") for s in sents])
    dims = {
        "n_single": pd["n_single"],
        "n_bi": pd["n_bi"],
        "total_bi": pd["total_bi"],
        "n_longtail_bi": sum(1 for v in pd["bi"].values() if v < 3),
        "single": pd["single"],
        "bi": pd["bi"],
        "letters": letters,
        "g2p_miss": n_miss,
        "epitran_enabled": g2p._epitran is not None or True,
    }
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "phoneme.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "n_single": pd["n_single"], "n_bi": pd["n_bi"], "total_bi": pd["total_bi"],
        "longtail_bi": dims["n_longtail_bi"], "letters_total": letters["total"],
        "g2p_miss": n_miss,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
