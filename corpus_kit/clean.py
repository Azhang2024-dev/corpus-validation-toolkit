"""clean —— 语料清洗：归一 / 质检 / 去重（语言无关）。

硬约束（本模块不得违反）：
- 不出现任何语言专有词表（stopword / 白名单 / 脏词表）；
- 不出现 Latin-only 字符类字面量（`[A-Za-z]` / `a-z` / `A-Z`），
  一律走 Unicode 属性 `\\p{L}` `\\p{Nd}` `\\p{Alpha}` `\\p{P}` `\\p{M}` `\\p{Cc}` `\\p{Cf}`；
- 长度一律按字素簇 `\\X` 计，不按码点（防拆散组合变音符 / emoji ZWJ 序列）。
守卫测试见 tests/test_corpus_clean.py::TestLanguageAgnostic。

步骤遵循业界口径（C4 / Gopher / CCNet / RefinedWeb / FineWeb / Dolma / NeMo Curator），
KEEP/DROP 判定与出处见 docs/语料清洗步骤调研_v1.md。
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import regex
import yaml

from .charset import NOISE_RE

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# ── Unicode 属性正则（语言无关）─────────────────────────────
GRAPHEME_RE = regex.compile(r"\X")
LETTER_RE = regex.compile(r"\p{L}")
ALNUM_RE = regex.compile(r"[\p{L}\p{N}]")
WORD_RE = regex.compile(r"\p{L}[\p{L}\p{M}'\-]*")     # 词含字母，允许词内标点/变音
MARK_RE = regex.compile(r"\p{M}")
PUNCT_RE = regex.compile(r"\p{P}")
ND_RE = regex.compile(r"\p{Nd}")
CTRL_RE = regex.compile(r"[\p{Cc}\p{Cf}]")
WS_RE = regex.compile(r"\s+")


def load_clean_config(path: Path | None = None) -> dict:
    """读 data/clean.yaml；缺失则返回内置默认（与文件同值，保证可跑）。"""
    p = Path(path) if path else DATA_DIR / "clean.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
    return {}


@dataclass
class CleanConfig:
    """清洗配置：从 clean.yaml 逐项取值，缺项用业界默认。"""
    raw: dict = field(default_factory=dict)

    def _get(self, *keys, default):
        cur = self.raw
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    # ① 重建
    @property
    def join_with(self) -> str:
        return str(self._get("reconstruct", "join_with", default=","))

    @property
    def quotechar(self) -> str:
        return str(self._get("reconstruct", "quotechar", default='"'))

    @property
    def doublequote(self) -> bool:
        return bool(self._get("reconstruct", "doublequote", default=True))

    # ② 归一
    @property
    def unicode_form(self) -> str:
        return str(self._get("normalize", "unicode_form", default="NFC"))

    @property
    def strip_control(self) -> bool:
        return bool(self._get("normalize", "strip_control", default=True))

    @property
    def strip_noise(self) -> bool:
        return bool(self._get("normalize", "strip_noise", default=True))

    @property
    def unwrap_quotes(self) -> bool:
        return bool(self._get("normalize", "unwrap_quotes", default=True))

    @property
    def newline_to_space(self) -> bool:
        return bool(self._get("normalize", "newline_to_space", default=True))

    @property
    def max_repeat_run(self) -> int:
        return int(self._get("normalize", "max_repeat_run", default=100))

    # ③ 质检
    @property
    def min_graphemes(self) -> int:
        return int(self._get("quality", "min_graphemes", default=2))

    @property
    def min_letters(self) -> int:
        return int(self._get("quality", "min_letters", default=1))

    @property
    def max_nonalnum_ratio(self) -> float:
        return float(self._get("quality", "max_nonalnum_ratio", default=0.25))

    @property
    def max_symbol_word_ratio(self) -> float:
        return float(self._get("quality", "max_symbol_word_ratio", default=0.1))

    @property
    def min_words_with_alpha(self) -> float:
        return float(self._get("quality", "min_words_with_alpha", default=0.8))

    # ④ 去重
    @property
    def dedup_exact(self) -> bool:
        return bool(self._get("dedup", "exact", default=True))

    @property
    def dedup_fuzzy(self) -> bool:
        return bool(self._get("dedup", "fuzzy", default=False))

    @property
    def keep_policy(self) -> str:
        return str(self._get("dedup", "keep_policy", default="first"))

    @property
    def key_opts(self) -> dict:
        return dict(self._get("dedup", "key", default={}) or {})

    @property
    def fuzzy_params(self) -> dict:
        return dict(self._get("dedup", "fuzzy_params", default={}) or {})


def clean_config(**overrides) -> CleanConfig:
    raw = load_clean_config()
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                raw.setdefault(k, {})
                if isinstance(raw[k], dict):
                    raw[k].update(v)
    return CleanConfig(raw=raw)


# ── ② 归一 ─────────────────────────────────────────────────

def fold_repeats(s: str, max_run: int) -> str:
    """把同字符重复超过 max_run 的连续串折成 max_run 个（Dolma：>100 → 折叠）。

    按「分裂成连续段」处理，语言无关（任何字符都适用）。
    """
    if max_run <= 0 or not s:
        return s
    out = []
    prev = None
    run = 0
    for ch in s:
        if ch == prev:
            run += 1
            if run <= max_run:
                out.append(ch)
        else:
            prev = ch
            run = 1
            out.append(ch)
    return "".join(out)


def _is_wrapped_quoted(s: str) -> bool:
    """s 是否恰为「一对包裹引号包住整个记录」（而非正文首尾恰好是引号）。

    判据：首尾都是 `"`，且内部除 `""` 转义对之外不含落单的 `"`。
    仅看首尾会把 `"hi" alisema "bye"` 这类正文当包裹引号切掉首尾，损坏内容；
    故必须校验配对——内部一旦出现落单引号，就说明首尾不是一对包裹引号。
    """
    if len(s) < 2 or not (s.startswith('"') and s.endswith('"')):
        return False
    body = s[1:-1]
    i = 0
    while i < len(body):
        if body[i] == '"':
            if i + 1 < len(body) and body[i + 1] == '"':
                i += 2          # 双写转义对内，跳过
                continue
            return False        # 落单引号 → 首尾不是包裹对
        i += 1
    return True


def normalize_text(text: str, cfg: CleanConfig) -> str:
    """归一：去包裹引号 → 换行转空格 → 控制/格式字符剥离 → 噪声剥离 → NFC → 折重复 → 空白归一。

    注意顺序：换行（\\n 属 \\p{Cc}）必须在剥控制字符**之前**转成空格，
    否则 `Habari\\n\\nza leo` 会被粘成 `Habariza leo`（丢词边界）。
    """
    s = text
    if cfg.unwrap_quotes:
        s = s.strip()
        # 仅在确认为包裹引号时去引号并还原双写转义。
        # 原先 `replace('""','"')` 无条件执行：dump 路径的 csv.reader 已还原过一次，
        # 这里再转一次会把正文里真实的相邻双引号也破坏（重复转义）。
        if _is_wrapped_quoted(s):
            s = s[1:-1].replace('""', '"')
    if cfg.newline_to_space:
        s = s.replace("\n", " ")
    if cfg.strip_control:
        s = CTRL_RE.sub("", s)
    if cfg.strip_noise:
        s = NOISE_RE.sub("", s)
    if cfg.unicode_form:
        s = unicodedata.normalize(cfg.unicode_form, s)
    if cfg.max_repeat_run:
        s = fold_repeats(s, cfg.max_repeat_run)
    s = WS_RE.sub(" ", s).strip()
    return s


# ── ③ 质检（产出 flags，不必然删）───────────────────────────

def quality_flags(text: str, cfg: CleanConfig, raw: str | None = None) -> list[str]:
    """语言无关的短句质检。返回 flag 列表（空 = 无异常）。

    分两档，因为两者的处置应当不同（这也是「不轻删」的落点）：
      hard  —— 结构上不成立，无法作为 TTS 文本：`empty` / `no_letters` / `no_words`。
      soft  —— 统计上可疑，但文本本身合法：占比类 flag（`nonalnum_ratio` /
               `symbol_word_ratio` / `words_with_alpha` / `too_short`）。
               业界这些阈值是为「文档」定的，短句上天然偏高（实测 Swahili 的
               `Sawa..`、`Mungu..` 只是标点密度高，仍是合法语料）——故默认只记录、不剔除。

    `raw` 是归一前的原文（clean_records 会传）。两项 Gopher 比值必须用它：
      · 符号（`#`）会在 normalize 阶段被 NOISE_RE 剥掉，用归一后的 text 计数恒为 0；
      · 分母必须是**空白切词**（数字词/符号词要进分母），
        用 `WORD_RE`（以字母开头）会把它们全部滤掉，导致比值恒不越界（检查形同虚设）。
    不传 `raw` 时退化为用 `text`（直调场景可接受，仅符号计数会偏 0）。
    """
    flags: list[str] = []
    if not text.strip():
        return ["hard:empty"]
    src = raw if raw is not None else text

    n_graphemes = len(GRAPHEME_RE.findall(text))
    n_letters = len(LETTER_RE.findall(text))
    if n_letters < cfg.min_letters:
        flags.append("hard:no_letters")
    elif n_graphemes < cfg.min_graphemes:
        flags.append(f"soft:too_short:{n_graphemes}")

    # 非字母数字比（NeMo NonAlphaNumericFilter 0.25）
    # 分子分母**同一计量单位**（字素簇）——否则复合字符脚本会算出负数：
    # 例如天城文 क्ष 是 1 字素簇 / 3 码点，若分子数码点、分母数字素簇，
    # ratio = 1 - 3/1 = -1.0（实测）。这是语言无关的硬要求。
    # 分母再排除空白：空白是结构分隔而非内容，短句里空格占比高，
    # 含进分母会让「正常带标点的句子」全部越界（实测 Swahili 会被误杀 82 条）。
    content = [g for g in GRAPHEME_RE.findall(text) if not g.isspace()]
    n_content = len(content)
    n_alnum = len([g for g in content if ALNUM_RE.search(g)])
    nonalnum_ratio = 1.0 - (n_alnum / n_content) if n_content else 1.0
    if nonalnum_ratio > cfg.max_nonalnum_ratio:
        flags.append(f"soft:nonalnum_ratio:{nonalnum_ratio:.2f}")

    # Gopher 两项比值（符号/词比 0.1、含字母词比 0.8）：分母统一为空白切词。
    # 符号 = `#` 与省略号（`…` / `...`），计数走原文 `src`（见 docstring）。
    words = WORD_RE.findall(text)        # 字母词：仅用于下面的结构性 no_words 判定
    words_ws = src.split()               # 空白切词：数字词/符号词进分母
    if words_ws:
        n_symbol = src.count("#") + src.count("…") + src.count("...")
        sym_ratio = n_symbol / len(words_ws)
        if sym_ratio > cfg.max_symbol_word_ratio:
            flags.append(f"soft:symbol_word_ratio:{sym_ratio:.2f}")
        # 含字母词比（Gopher 0.8）：词数 > 1 时才有意义
        if len(words_ws) > 1:
            with_alpha = sum(1 for w in words_ws if LETTER_RE.search(w))
            frac = with_alpha / len(words_ws)
            if frac < cfg.min_words_with_alpha:
                flags.append(f"soft:words_with_alpha:{frac:.2f}")
    if not words:
        flags.append("hard:no_words")

    return flags


def is_hard(flag: str) -> bool:
    return flag.startswith("hard:")


def has_hard_flag(flags: list[str]) -> bool:
    return any(is_hard(f) for f in flags)


# ── ④ 去重 ──────────────────────────────────────────────────

def dedup_key(text: str, cfg: CleanConfig) -> str:
    """去重键归一（datatrove simplify_text / CCNet normalize_for_dedup 系谱）。

    casefold → 数字→0 → 去标点 →（可选）去变音符 → 折叠空白。
    语言无关：[\\p{Nd}] / [\\p{P}] / [\\p{M}] 都是 Unicode 属性。
    """
    o = cfg.key_opts
    s = text
    if o.get("casefold", True):
        s = s.casefold()
    if o.get("digits_to_zero", True):
        s = ND_RE.sub("0", s)
    if o.get("strip_punct", True):
        s = PUNCT_RE.sub(" ", s)
    if o.get("strip_marks", False):
        s = MARK_RE.sub("", s)
    if o.get("collapse_whitespace", True):
        s = WS_RE.sub(" ", s)
    return s.strip()


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def dedup_exact(texts: list[str], cfg: CleanConfig) -> dict:
    """精确去重：按去重键分组，每组按 keep_policy 留一条。返回 {keep:[i], drop:[(i,kept_i)]}。"""
    seen: dict[str, int] = {}
    keep: list[int] = []
    drop: list[tuple[int, int]] = []
    for i, t in enumerate(texts):
        k = _hash(dedup_key(t, cfg))
        if k in seen:
            if cfg.keep_policy == "last":
                # 保留后者：把先前那条挪进 drop
                prev = seen[k]
                keep.remove(prev)
                drop.append((prev, i))
                seen[k] = i
                keep.append(i)
            else:
                drop.append((i, seen[k]))
        else:
            seen[k] = i
            keep.append(i)
    return {"keep": keep, "drop": drop}


def minhash_signature(text: str, n_grams: int, n_hashes: int, cfg: CleanConfig) -> list[int]:
    """MinHash 签名：词级 n-gram → 多哈希取最小。用于可选模糊去重。

    去重键归一用调用方的 cfg（而非全局默认），否则 `dedup.key` 覆盖会被静默忽略。
    """
    toks = dedup_key(text, cfg).split()
    if len(toks) < n_grams:
        grams = [" ".join(toks)] if toks else []
    else:
        grams = [" ".join(toks[i:i + n_grams]) for i in range(len(toks) - n_grams + 1)]
    sig = []
    for h in range(n_hashes):
        m = None
        for g in grams:
            v = int(hashlib.sha256(f"{h}:{g}".encode("utf-8")).hexdigest()[:12], 16)
            m = v if m is None else min(m, v)
        sig.append(m if m is not None else 0)
    return sig


def dedup_fuzzy(texts: list[str], cfg: CleanConfig) -> dict:
    """模糊近重：MinHash 分桶（FineWeb 口径：n-gram / 桶 × 每桶哈希数 → 分桶碰撞即近重）。"""
    fp = cfg.fuzzy_params
    n_grams = int(fp.get("n_grams", 5))
    n_buckets = int(fp.get("num_buckets", 14))
    per_bucket = int(fp.get("hashes_per_bucket", 8))
    n_hashes = n_buckets * per_bucket
    buckets: dict[tuple, int] = {}
    keep: list[int] = []
    drop: list[tuple[int, int]] = []
    for i, t in enumerate(texts):
        sig = minhash_signature(t, n_grams, n_hashes, cfg)
        hit = None
        for b in range(n_buckets):
            key = (b, tuple(sig[b * per_bucket:(b + 1) * per_bucket]))
            if key in buckets:
                hit = buckets[key]
                break
        if hit is None:
            for b in range(n_buckets):
                buckets[(b, tuple(sig[b * per_bucket:(b + 1) * per_bucket]))] = i
            keep.append(i)
        else:
            drop.append((i, hit))
    return {"keep": keep, "drop": drop}


# ── 统一入口 ────────────────────────────────────────────────

def clean_records(records: list[str], cfg: CleanConfig, fuzzy: bool | None = None) -> dict:
    """对逻辑记录依次做 归一 → 质检 → 去重，返回结构化结果（不落盘）。

    剔除判据是 **hard flag 或 重复**；soft flag 只记录（`kept` 仍为 True），
    因为业界占比阈值是为文档定的，短句上偏高（见 quality_flags docstring）。
    """
    rows = []
    for i, raw in enumerate(records):
        text = normalize_text(raw, cfg)
        flags = quality_flags(text, cfg, raw=raw)
        rows.append({
            "index": i,
            "raw": raw,
            "text": text,
            "flags": flags,
            "hard": has_hard_flag(flags),
        })

    texts = [r["text"] for r in rows]
    # 精确与模糊去重互斥（fuzzy 取代 exact），但 fuzzy 不再嵌在 exact 之下——
    # 否则 `dedup.exact: false` + `--fuzzy` 会静默变成「完全不去重」。
    want_fuzzy = fuzzy if fuzzy is not None else cfg.dedup_fuzzy
    if want_fuzzy:
        dd = dedup_fuzzy(texts, cfg)
    elif cfg.dedup_exact:
        dd = dedup_exact(texts, cfg)
    else:
        dd = {"keep": list(range(len(rows))), "drop": []}

    keep_set = set(dd["keep"])
    for r in rows:
        r["kept"] = (r["index"] in keep_set) and not r["hard"]
    return {"rows": rows, "dedup": dd}


def summarize(rows: list[dict], dedup: dict) -> dict:
    """统计：逐 flag 命中数、硬/软档、去重数与保留数。"""
    hard_counts: dict[str, int] = {}
    soft_counts: dict[str, int] = {}
    for r in rows:
        for f in r["flags"]:
            bucket = hard_counts if is_hard(f) else soft_counts
            bucket[f] = bucket.get(f, 0) + 1
    n_kept = sum(1 for r in rows if r["kept"])
    return {
        "n_in": len(rows),
        "n_kept": n_kept,
        "n_quarantined": len(rows) - n_kept,
        "n_dedup_dropped": len(dedup.get("drop", [])),
        "hard_flag_counts": hard_counts,
        "soft_flag_counts": soft_counts,
    }