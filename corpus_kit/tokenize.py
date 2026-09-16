"""tokenize —— 正则分词。两种口径：词法 token（小写保留 ' 与 -）与空白切词。"""
from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z'\-]+")


def word_tokens(text: str) -> list[str]:
    """词法 token：小写、保留撇号与连字符（对齐 37.2 万 token / 2.48 万型符口径）。"""
    return TOKEN_RE.findall(text.lower())


def whitespace_words(text: str) -> list[str]:
    """单句词数口径：直接按空白切（斯语词边界天然是空格）。"""
    return [w for w in text.split()]
