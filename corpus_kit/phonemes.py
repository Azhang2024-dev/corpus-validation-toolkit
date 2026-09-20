"""phonemes —— IPA 音素统计：切分 / 单双音素计数 / 字母分布。

切分策略（2026-09-18 多语种）分三条，按优先级：
1. **规则 pin（sw）**：历史 sw 口径——上标前鼻化 + tʃ/dʒ 双字母按单音素（冻结）。
2. **空白切分**：词典值本身带音素边界时（WikiPron 的 `m ə ɾ d̪`、ipa-dict zh 的
   `i˥ pu˧˥`）直接按空白切——**信任词典的边界**，不重新猜。
3. **通用字素簇**：其余（如 fr 的 `bɔ̃ʒuʀ`）按 `\\X` 切——组合符（鼻化 ̃、齿音 ̪）
   与基字符合并为单音素。

字母分布（letter_stats）同样由配置提供正则：默认历史 [a-z']，其余语言按本语脚本。
"""
from __future__ import annotations

import regex as re
from collections import Counter

SUP = "ⁿᵐᶮᵑᶬ"
LEGACY = "sw_legacy"

GRAPHEME_RE = re.compile(r"\X")


def _split_legacy(ipa: str) -> list[str]:
    """sw 历史口径：上标前鼻化合并、tʃ/dʒ 双字母单音素、去掉连字符。"""
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


def _split_by_space(ipa: str) -> list[str]:
    return [p for p in ipa.split() if p]


def _split_graphemes(ipa: str) -> list[str]:
    return [g for g in GRAPHEME_RE.findall(ipa) if not g.isspace()]


def split_phonemes(ipa: str, cfg=None) -> list[str]:
    """IPA 串 → 音素列表。

    cfg 决定切分方式（`phoneme_rules.mode`）；sw 保持历史规则（见模块 docstring）。
    不传 cfg 时**默认历史 sw 行为**——既有测试与 sw 基线依赖。
    """
    ipa = (ipa or "").lower()
    if not ipa:
        return []
    rules = getattr(cfg, "phoneme_rules", None) or {}
    mode = str(rules.get("mode") or LEGACY)
    if mode == LEGACY:
        return _split_legacy(ipa)
    if any(c.isspace() for c in ipa):
        return _split_by_space(ipa)
    return _split_graphemes(ipa)


def phoneme_dist(ipa_list, normalize=None, cfg=None) -> dict:
    """输入 IPA 串列表 → {single, bi, n_single, n_bi, total_bi}。

    normalize：可选 `ipa -> list[str]` 归一键（见 phonotactics.normalize_sequence）。
    不给时用原生 split_phonemes（保留词典原样）。
    """
    single: Counter = Counter()
    bi: Counter = Counter()
    for ipa in ipa_list:
        ps = normalize(ipa) if normalize else split_phonemes(ipa, cfg)
        single.update(ps)
        bi.update(zip(ps, ps[1:]))
    return {
        "single": dict(single.most_common()),
        "bi": {"".join(k): v for k, v in bi.most_common()},
        "n_single": len(single),
        "n_bi": len(bi),
        "total_bi": sum(bi.values()),
    }


# 历史口径（sw 基线冻结值）
LETTER_RE = re.compile(r"[a-z']")

_letter_cache: dict[str, re.Pattern] = {}


def letter_pattern_for(pattern: str | None = None) -> re.Pattern:
    if not pattern:
        return LETTER_RE
    pat = _letter_cache.get(pattern)
    if pat is None:
        pat = re.compile(pattern)
        _letter_cache[pattern] = pat
    return pat


def letter_stats(texts, pattern: str | None = None) -> dict:
    """全语料字母分布：默认 [a-z'] 小写计数；非拉丁语言由 config 传本语脚本正则。"""
    pat = letter_pattern_for(pattern)
    c = Counter()
    total = 0
    for t in texts:
        for m in pat.findall(t.lower()):
            c[m] += 1
            total += 1
    return {"total": total, "letters": dict(c.most_common()), "n_types": len(c)}