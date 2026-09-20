"""charset —— Unicode 字符检查 / 噪声剥离（越界块与核心字符由配置提供）。

口径（2026-09-18 多语种通用化）：
- **越界块**（foreign_blocks）由语言/家族配置给出。要点：越界目录 = 全块目录**减去本语脚本**
  ——原实现把目标语脚本（如阿拉伯、天城）也列为「外语」，对 ur/hi/bn 目标语必然误杀。
- **核心字符**（core_pattern）同样来自配置：sw 保持历史 `[A-Za-z\\u00C0-\\u024F\\u1E00-\\u1EFF0-9]`，
  其他语系按本语脚本 + 数字。
- **零宽/格式符**：`keep_chars` 里的字符不剥离（bn/hi 正字法必需的 ZWNJ/ZWJ、RTL 的 bidi 标记）。
"""
from __future__ import annotations

from collections import Counter

import regex as re

# 非拉丁脚本块（Block 名）——**保留为缺省**：语言/家族未给 foreign_blocks 时的兜底。
# 注意：新语言请在自己的配置里显式列「全块目录减去本语脚本」，勿依赖本缺省。
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

# 全脚本块目录（主要文字体系）：家族给 `script_blocks`（本族自己的块）后，
# 越界目录 = 全集 − 本族块。这样「目标语字符被当外语」的缺陷在配置层被结构性消除，
# 新语言只要声明自己的脚本块，不必手写几十项的越界清单。
ALL_SCRIPT_BLOCKS = [
    # 拉丁系
    "Basic Latin", "Latin-1 Supplement", "Latin Extended-A", "Latin Extended-B",
    "IPA Extensions", "Latin Extended Additional", "Latin Extended-C", "Latin Extended-D",
    "Latin Extended-E", "Phonetic Extensions", "Phonetic Extensions Supplement",
    "Spacing Modifier Letters", "Modifier Tone Letters",
    # 阿拉伯系
    "Arabic", "Arabic Supplement", "Arabic Extended-A", "Arabic Extended-B",
    "Arabic Presentation Forms-A", "Arabic Presentation Forms-B",
    # 印度系
    "Devanagari", "Devanagari Extended", "Vedic Extensions",
    "Bengali", "Gurmukhi", "Gujarati", "Oriya", "Tamil", "Tamil Supplement",
    "Telugu", "Kannada", "Malayalam", "Sinhala",
    # 其他
    "Cyrillic", "Cyrillic Supplement", "Cyrillic Extended-A", "Cyrillic Extended-B",
    "Greek and Coptic", "Greek Extended", "Hebrew", "Thai", "Lao",
    "Tibetan", "Myanmar", "Khmer", "Georgian", "Armenian", "Ethiopic",
    "Syriac", "Thaana", "NKo",
    "CJK Unified Ideographs", "CJK Unified Ideographs Extension A",
    "CJK Unified Ideographs Extension B", "CJK Symbols and Punctuation", "CJK Compatibility",
    "Kangxi Radicals", "CJK Radicals Supplement", "Halfwidth and Fullwidth Forms",
    "Hiragana", "Katakana", "Katakana Phonetic Extensions",
    "Hangul Syllables", "Hangul Jamo", "Hangul Compatibility Jamo",
]

# 噪声/格式字符：emoji、变体选择符、零宽、软连字符、全角、行分隔、markdown 结构符
# 注：\u200C\u200D\u200E\u200F 在 keep_chars 命中时会被排除（见 _noise_pattern）
_NOISE_BASE = (
    r"[\p{Emoji_Presentation}\p{So}\p{Sk}\p{Cs}\uFE0F\u200D\u200B\u200C\u200E\u200F"
    r"\u00AD\u2060\uFF00-\uFFEF\u2028\u2029]|[*#>\u2022]|\[|\]|\||_{2,}|\*{2,}"
)
NOISE_RE = re.compile(_NOISE_BASE)

# 历史核心字符口径（sw 基线冻结值；sw.yaml 显式 pin 同值）
CORE_RE = re.compile(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF0-9]")

# 零宽/格式符全集（keep_chars 要从噪声里豁免的就是这些）
ZERO_WIDTH = "\u200b\u200c\u200d\u200e\u200f"

_noise_cache: dict[str, re.Pattern] = {}


def noise_pattern(keep: list | None = None) -> re.Pattern:
    """噪声正则。keep 命中的字符从零宽组里豁免。

    为什么需要豁免：孟加拉/天城正字法里 ZWNJ/ZWJ 是有意义的组成（拆合体字），
    阿拉伯语 RTL 文本的 bidi 标记同理——一刀切剥离会改变原文与统计。
    """
    keep_set = {c for c in (keep or []) if c}
    if not keep_set:
        return NOISE_RE
    key = "".join(sorted(keep_set))
    pat = _noise_cache.get(key)
    if pat is None:
        zw = "".join(c for c in ZERO_WIDTH if c not in keep_set)
        base = _NOISE_BASE
        if zw != ZERO_WIDTH:
            # 把被豁免的字符从字符类里去掉（它们在 _NOISE_BASE 里是 \uXXXX 形式）
            for c in keep_set:
                if c in ZERO_WIDTH:
                    base = base.replace(f"\\u{ord(c):04X}", "")
        pat = re.compile(base)
        _noise_cache[key] = pat
    return pat


def blocks_outside(family_blocks: list) -> list:
    """全块目录 − 本族脚本块 = 越界块目录（家族层用，结构性防误杀）。"""
    own = set(family_blocks or [])
    return [b for b in ALL_SCRIPT_BLOCKS if b not in own]


def _compile_foreign(blocks: list, letters_only: bool = True) -> re.Pattern | None:
    """越界模式。letters_only=True 时只取块内**字母/组合符**。

    为什么要过滤类别：`Basic Latin` 块包含空格、ASCII 标点与数字——若按块全量匹配，
    任何语言的越界比率都会被空白/标点污染（实测 ur 文本被算出 foreign_ratio=0.26 全来自空格）。
    越界的语义是「用了他语文字」，故默认只取 \\p{L} 与 \\p{M}。
    sw 为保历史基线传 letters_only=False（2026-09-16 口径：块全量）。
    """
    parts = []
    for b in blocks:
        try:
            re.compile(rf"\p{{Block={b}}}")
            parts.append(rf"\p{{Block={b}}}")
        except Exception:
            continue
    if not parts:
        return None
    if letters_only:
        return re.compile("[[" + "".join(parts) + r"]&[\p{L}\p{M}]]")
    return re.compile("[" + "".join(parts) + "]")


_foreign_cache: dict = {}
_core_cache: dict[str, re.Pattern] = {}


def foreign_pattern(blocks: list | None = None, letters_only: bool = True):
    key = (tuple(blocks or DEFAULT_FOREIGN_BLOCKS), bool(letters_only))
    if key not in _foreign_cache:
        _foreign_cache[key] = _compile_foreign(key[0], key[1])
    return _foreign_cache[key]


def core_pattern(pattern: str | None = None) -> re.Pattern:
    """核心字符正则：无配置时保持历史 sw 口径（CORE_RE）。"""
    if not pattern:
        return CORE_RE
    pat = _core_cache.get(pattern)
    if pat is None:
        pat = re.compile(pattern)
        _core_cache[pattern] = pat
    return pat


def _char_counts(chars: list) -> list:
    """字符频次表：[[字符, 次数], ...] 按次数降序，**不截断**。

    原先 `sorted(set(foreign))[:20]`：`set` 丢掉频次（出现 900 次与 1 次无差别），
    `[:20]` 丢掉尾部，且未记录丢了多少。现改为完整频次表，另附 distinct 数。
    """
    return [[c, n] for c, n in Counter(chars).most_common()]


def check_charset(text: str, cfg, blocks: list | None = None) -> dict:
    """返回 {status, reason, foreign_ratio, foreign_chars, noise_chars, has_emoji, cleaned, core_after}。

    foreign_chars / noise_chars 是**完整**频次表（`[[字符, 次数], ...]`，次数降序），
    不截断——截断会掩盖高频越界字符，而它正是判断「整行外语 vs 个别夹带」的依据。
    """
    cfg_blocks = getattr(cfg, "charset_blocks", None) or []
    letters_only = bool(getattr(cfg, "foreign_letters_only", True))
    fpat = foreign_pattern(blocks or (cfg_blocks or DEFAULT_FOREIGN_BLOCKS), letters_only)
    foreign = fpat.findall(text) if fpat else []
    ns = len(re.sub(r"\s", "", text))
    ratio = len(foreign) / ns if ns else (1.0 if foreign else 0.0)
    npat = noise_pattern(getattr(cfg, "keep_chars", None))
    noise = npat.findall(text)
    cleaned = npat.sub("", text)
    cpat = core_pattern(getattr(cfg, "core_pattern", None))
    core_after = len(cpat.findall(cleaned))
    emoji_re = re.compile(r"[\p{Emoji_Presentation}\u2600-\u27BF\U0001F000-\U0001FAFF]")
    has_emoji = bool(emoji_re.search(text))
    lang_label = getattr(cfg, "label", "") or "目标语言"

    if ratio >= cfg.charset_warn_ratio:
        status = "fail"
        reason = f"foreign_ratio={ratio:.2f}>={cfg.charset_warn_ratio}（整行外语/重度混杂）"
    elif ratio >= cfg.charset_pass_ratio:
        status = "warn"
        reason = f"foreign_ratio={ratio:.2f}（{lang_label}主体+外语引用/中度混杂，建议人工复核）"
    else:
        status = "pass"
        reason = f"foreign_ratio={ratio:.2f}<{cfg.charset_pass_ratio}"
        if core_after < 5:
            status = "warn"
            reason = f"mostly_noise（剥离噪声后核心字符仅 {core_after} 个）"
    fchars = _char_counts(foreign)
    nchars = _char_counts(noise)
    return {
        "status": status,
        "reason": reason,
        "foreign_ratio": round(ratio, 4),
        "foreign_chars": fchars,
        "noise_chars": nchars,
        "foreign_distinct": len(fchars),
        "noise_distinct": len(nchars),
        "has_emoji": has_emoji,
        "cleaned": cleaned,
        "core_after": core_after,
    }