"""charset —— Unicode Block 字符检查 / 噪声剥离（regex \\p{Block=...}，对齐实测口径）。"""
from __future__ import annotations

import regex as re

# 非拉丁脚本块（Block 名，取自 UnicodeBlocks.txt；加载时逐个探测，缺失块自动跳过）
DEFAULT_FOREIGN_BLOCKS = [
    "Arabic", "Syriac", "Thaana", "NKo",
    "CJK Unified Ideographs", "CJK Unified Ideographs Extension A",
    "CJK Symbols and Punctuation", "Hiragana", "Katakana", "Katakana Phonetic Extensions",
    "Cyrillic", "Cyrillic Supplement", "Hebrew", "Arabic Supplement", "Arabic Extended-A",
    "Devanagari", "Bengali", "Gurmukhi", "Gujarati", "Oriya", "Tamil", "Telugu",
    "Kannada", "Malayalam", "Sinhala", "Thai", "Lao", "Tibetan", "Myanmar", "Khmer",
    "Georgian", "Armenian", "Hangul Syllables", "Hangul Jamo", "Ethiopic",
    "Greek and Coptic",
]

# 噪声/格式字符：emoji、变体选择符、零宽、软连字符、全角、行分隔、markdown 结构符
NOISE_RE = re.compile(
    r"[\p{Emoji_Presentation}\p{So}\p{Sk}\p{Cs}\uFE0F\u200D\u200B\u200C\u200E\u200F"
    r"\u00AD\u2060\uFF00-\uFFEF\u2028\u2029]|[*#>\u2022]|\[|\]|\||_{2,}|\*{2,}"
)
CORE_RE = re.compile(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF0-9]")


def _compile_foreign(blocks: list) -> re.Pattern | None:
    parts = []
    for b in blocks:
        try:
            re.compile(rf"\p{{Block={b}}}")
            parts.append(rf"\p{{Block={b}}}")
        except Exception:
            continue
    return re.compile("[" + "".join(parts) + "]") if parts else None


_foreign_cache: dict = {}


def foreign_pattern(blocks: list | None = None):
    key = tuple(blocks or DEFAULT_FOREIGN_BLOCKS)
    if key not in _foreign_cache:
        _foreign_cache[key] = _compile_foreign(key)
    return _foreign_cache[key]


def check_charset(text: str, cfg, blocks: list | None = None) -> dict:
    """返回 {status, reason, foreign_ratio, foreign_chars, noise_chars, has_emoji, cleaned, core_after}。"""
    fpat = foreign_pattern(blocks or (cfg.charset_blocks or DEFAULT_FOREIGN_BLOCKS))
    foreign = fpat.findall(text) if fpat else []
    ns = len(re.sub(r"\s", "", text))
    ratio = len(foreign) / ns if ns else (1.0 if foreign else 0.0)
    noise = NOISE_RE.findall(text)
    cleaned = NOISE_RE.sub("", text)
    core_after = len(CORE_RE.findall(cleaned))
    emoji_re = re.compile(r"[\p{Emoji_Presentation}\u2600-\u27BF\U0001F000-\U0001FAFF]")
    has_emoji = bool(emoji_re.search(text))

    if ratio >= cfg.charset_warn_ratio:
        status = "fail"
        reason = f"foreign_ratio={ratio:.2f}>={cfg.charset_warn_ratio}（整行外语/重度混杂）"
    elif ratio >= cfg.charset_pass_ratio:
        status = "warn"
        reason = f"foreign_ratio={ratio:.2f}（斯语主体+外语引用/中度混杂，建议人工复核）"
    else:
        status = "pass"
        reason = f"foreign_ratio={ratio:.2f}<{cfg.charset_pass_ratio}"
        if core_after < 5:
            status = "warn"
            reason = f"mostly_noise（剥离噪声后核心字符仅 {core_after} 个）"
    return {
        "status": status,
        "reason": reason,
        "foreign_ratio": round(ratio, 4),
        "foreign_chars": sorted(set(foreign))[:20],
        "noise_chars": sorted(set(noise))[:20],
        "has_emoji": has_emoji,
        "cleaned": cleaned,
        "core_after": core_after,
    }
