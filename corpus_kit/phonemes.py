"""phonemes —— IPA 音素统计：前鼻化合并单音位、tʃ/dʒ 双字母单音素、单/双音素计数。"""
from __future__ import annotations

import re
from collections import Counter

SUP = "ⁿᵐᶮᵑᶬ"


def split_phonemes(ipa: str) -> list[str]:
    """IPA 串 → 音素列表。规则（对齐实测口径）：
    上标前鼻化（ⁿᵐᶮᵑᶬ）+ 后随字符合并为单音位；tʃ / dʒ 双字母按单音素；去掉连字符。"""
    ipa = (ipa or "").lower()
    out: list[str] = []
    i, n = 0, len(ipa)
    while i < n:
        ch = ipa[i]
        if ch in SUP and i + 1 < n:
            out.append(ch + ipa[i + 1])
            i += 2
            continue
        if ch == "t" and ipa[i : i + 2] == "tʃ":
            out.append("tʃ")
            i += 2
            continue
        if ch == "d" and ipa[i : i + 2] == "dʒ":
            out.append("dʒ")
            i += 2
            continue
        out.append(ch)
        i += 1
    return [p for p in out if p not in ("-", " ")]


def phoneme_dist(ipa_list) -> dict:
    """输入 IPA 串列表 → {single: Counter→dict, bi: Counter→dict, n_single, n_bi, total_bi}。"""
    single: Counter = Counter()
    bi: Counter = Counter()
    for ipa in ipa_list:
        ps = split_phonemes(ipa)
        single.update(ps)
        bi.update(zip(ps, ps[1:]))
    return {
        "single": dict(single.most_common()),
        "bi": {"".join(k): v for k, v in bi.most_common()},
        "n_single": len(single),
        "n_bi": len(bi),
        "total_bi": sum(bi.values()),
    }


LETTER_RE = re.compile(r"[a-z']")


def letter_stats(texts) -> dict:
    """全语料字母分布：[a-z'] 小写计数（26 字母 + 撇号）。"""
    c = Counter()
    total = 0
    for t in texts:
        for m in LETTER_RE.findall(t.lower()):
            c[m] += 1
            total += 1
    return {"total": total, "letters": dict(c.most_common()), "n_types": len(c)}
