"""g2p —— G2P 管线：发音词典查表 → epitran 兜底 → 补丁。

多语种口径（2026-09-18）：
- `WORD_RE` 词形判据由配置提供（`Config.word_pattern`）：sw 保持 `^[a-z']+$`（冻结），
  其他语系按本语脚本（如 `^[\\p{scx=Arab}\\p{M}']+$`），否则非拉丁词永不走兜底。
- 词典加载兼容两种格式：`词\t/IPA/`（ipa-dict）与 `词\t音素 空格分隔`（WikiPron，
  规范化已去空格，直接可用）；一词多写取首个。
- `strip_marks`（去组合符）默认 true（sw 行为）；对鼻化元音等有意义的语系
  （fr 的 ɔ̃ 等）由语言 yaml 关闭，防误剥。
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import regex as re

# 历史口径（sw 基线冻结值；sw.yaml 的 word_pattern 与其逐字一致）
WORD_RE = re.compile(r"^[a-z']+$")
STRESS = str.maketrans({"ˈ": "", "ˌ": "", " ": ""})

_cache: dict[str, re.Pattern] = {}


def _compile(pattern: str) -> re.Pattern:
    pat = _cache.get(pattern)
    if pat is None:
        pat = re.compile(pattern)
        _cache[pattern] = pat
    return pat


def word_pattern_for(cfg) -> re.Pattern:
    """按配置取词形判据；无配置时历史 sw 口径。"""
    p = getattr(cfg, "word_pattern", None)
    return _compile(p) if p else WORD_RE


def has_letter(word: str) -> bool:
    """token 是否「需要 IPA」的词形：含至少一个字母。

    判据比 `WORD_RE` 宽：连字符词（`well-known`）与撇号词都算词形，
    尽管 phonemize 因 WORD_RE 不含 `-` 而对连字符词返回 None。
    用于统计「词级 IPA 未覆盖」——用 str.isalpha() 会漏掉连字符词，
    用 WORD_RE 会漏掉所有它拒绝的词，两者都会让未覆盖率系统性偏低。

    多语种下 `isalpha()` 对绝大多数脚本（天城/孟加拉/阿拉伯/西里尔/汉字）均成立
    （Unicode 属性），故本判据天然语言无关。
    """
    return any(c.isalpha() for c in (word or ""))


def load_ipa_dict(path) -> dict:
    """data/ipa/<lang>.txt：每行『词\tIPA』，词小写作 key，IPA 去斜杠、小写。

    兼容 `词\t/IPA/`（ipa-dict）与 `词\t音素序列`（WikiPron 已去空格）。
    """
    d: dict = {}
    if path is None:
        return d
    p = Path(path)
    if not p.exists():
        return d
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        w = parts[0].strip().lower()
        ipa = parts[1].strip().strip("/").lower()
        if w and ipa:
            d.setdefault(w, ipa)
    return d


class G2P:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dict = load_ipa_dict(getattr(cfg, "ipa_dict_path", None))
        self._epitran = None
        # 兜底器开关：config 的 g2p.fallback 现在真的生效（原先声明了却没人读）。
        # "epitran" 走 epitran；"none"/"null"/"" → 只查表，查不到即未覆盖。
        self.fallback = (getattr(cfg, "g2p_fallback", "epitran") or "").strip().lower()
        self.use_epitran = self.fallback in ("epitran", "true", "1")
        # epitran 级故障（import/初始化/转写抛异常）只记一次，避免逐词重复；
        # 与「词形本就不该音素化」区分开——原实现两者都 return None，无法分辨。
        self.epitran_error: str | None = None

    def _get_epitran(self):
        if self._epitran is None:
            import epitran

            self._epitran = epitran.Epitran(self.cfg.epitran_lang)
        return self._epitran

    def phonemize(self, word: str):
        """单词 → IPA 字符串；查不到又非纯字母（数字/缩写/符号）或 epitran 不可用则返回 None。"""
        w = word.strip().lower()
        if not w:
            return None
        if w in self.dict:
            return self.dict[w]
        if not word_pattern_for(self.cfg).fullmatch(w):
            return None
        if not self.use_epitran or not getattr(self.cfg, "epitran_lang", None):
            return None
        try:
            out = self._get_epitran().transliterate(w).lower().translate(STRESS)
            # 剥掉组合/附加符号（如 t͡ʃ 的连字线 U+0361）：sw 无鼻化元音等合法组合符，安全；
            # 法语鼻化元音等由 yaml 关 strip_marks，防误剥。
            if getattr(self.cfg, "g2p_strip_marks", True):
                out = "".join(c for c in out if unicodedata.category(c) != "Mn")
        except Exception as e:
            # 记首次故障（含类型与信息），让「未覆盖」能区分「词形被拒」与「epitran 挂了」
            if self.epitran_error is None:
                self.epitran_error = f"{type(e).__name__}: {e}"
            return None
        for src, dst in self.cfg.g2p_patch:
            out = out.replace(src, dst)
        return out or None

    def phonemize_many(self, words) -> dict:
        """批量：唯一次数缓存后回填，返回 {word: ipa|None}。"""
        uniq = sorted({w.strip().lower() for w in words if w and w.strip().lower()})
        cache = {w: self.phonemize(w) for w in uniq}
        return cache

    def miss_breakdown(self, words) -> dict:
        """把「未覆盖」按原因拆开：非词形 / 无兜底器 / epitran 故障。

        n_miss 汇总数只回答「多少没覆盖」，回答不了「为什么」——本方法补上归因。
        判据是**实际结果**：只有 phonemize(w) 为 None 才算未覆盖；能被 epitran 转写出来的
        是已覆盖，绝不记进 epitran_failed（否则会把成功的也算成故障）。

        口径：**按去重词（type）计**，与 g2p_miss（按 token 出现次数计）不同——
        g2p_miss 回答「整批多少处没覆盖」，本表回答「多少种词、为什么」。
        """
        uniq = sorted({w.strip().lower() for w in words if w and w.strip().lower()})
        wpat = word_pattern_for(self.cfg)
        no_shape = no_fallback = epi_fail = 0
        for w in uniq:
            if w in self.dict:
                continue
            if not wpat.fullmatch(w):
                no_shape += 1
            elif not self.use_epitran or not getattr(self.cfg, "epitran_lang", None):
                no_fallback += 1
            elif self.phonemize(w) is None:
                epi_fail += 1      # 走了 epitran 仍拿不到 IPA = 真故障
        return {
            "not_a_word_shape": no_shape,
            "no_fallback_configured": no_fallback,
            "epitran_failed": epi_fail,
            "epitran_error": self.epitran_error,
        }