"""tokenize —— 正则分词（模式由配置提供，默认=历史 sw 口径）。

`word_tokens` 的 pattern 参数来自 `Config.token_pattern`（语言 yaml 可 pin，
缺省时用脚本家族的正则）。不传 pattern 时保持历史行为（`[A-Za-z'\\-]+`）——
既有测试与 sw 基线报告依赖该口径，不得漂移。
"""
from __future__ import annotations

import regex as re   # 需要 \p{scx=...} 等 Unicode 属性时 stdlib re 不支持

# 历史口径（sw 基线冻结值；sw.yaml 的 token_pattern 与其逐字一致）
TOKEN_RE = re.compile(r"[A-Za-z'\-]+")

_cache: dict[str, re.Pattern] = {}


def _compile(pattern: str) -> re.Pattern:
    pat = _cache.get(pattern)
    if pat is None:
        pat = re.compile(pattern)
        _cache[pattern] = pat
    return pat


def word_tokens(text: str, pattern: str | None = None) -> list[str]:
    """词法 token：小写、保留撇号与连字符。

    pattern 必填：传 Config(lang).token_pattern（sw 为历史 [A-Za-z'-]+）。
    不再在 pattern 缺失时静默回退到拉丁 TOKEN_RE（非拉丁会得到 0 token）。
    需要 sw 历史口径时请显式传入 TOKEN_RE.pattern 或 Config("sw").token_pattern。
    """
    if not pattern:
        raise ValueError(
            "word_tokens(pattern=...) is required; pass Config(lang).token_pattern "
            "(Latin-only TOKEN_RE is not an implicit default)."
        )
    return _compile(pattern).findall(text.lower())


def whitespace_words(text: str) -> list[str]:
    """单句词数口径：直接按空白切（对无空格语言如中文，此口径≈按字块，报告如实披露）。"""
    return [w for w in text.split()]