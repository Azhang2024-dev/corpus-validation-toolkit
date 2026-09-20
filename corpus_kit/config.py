"""config —— 两级配置加载：脚本家族（data/script/*.yaml）→ 语言薄层（data/lang/*.yaml）。

设计（2026-09-18 多语种通用化）：
- **家族层**承载「同一文字体系所有语言共享」的规则（token 正则、核心字符、越界块、
  句末标点、词形判据…），语言无关、可跨语言复用；
- **语言层**只写本语言特有项（虚词表、词典、G2P 码、音节口径、词源清单…），
  缺省时按家族规则跑，**不再静默回落 sw 资源**——缺什么就标缺什么（诚实原则）。

新语言上线 = 加一个 `data/lang/<code>.yaml`（引用已有家族）；新文字体系 = 加一个
`data/script/<family>.yaml`。两者都不需要改代码。
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# 语言码 → 家族名。未列出的语言由 yaml 的 `script:` 字段自述；
# 都缺省时用 generic（Unicode 属性近似 + 报告披露）。
LANG_FAMILY_HINT = {
    "sw": "latin", "fr": "latin", "en": "latin", "es": "latin", "pt": "latin",
    "id": "latin", "tr": "latin", "ha": "latin", "fil": "latin",
    "ar": "arabic", "ur": "arabic",
    "hi": "devanagari", "mr": "devanagari",
    "bn": "bengali", "gu": "gujarati", "ta": "tamil",
    "ru": "cyrillic", "zh": "han", "te": "telugu",
}


def _load_yaml(p: Path) -> dict:
    if not p.exists():
        return {}
    loaded = yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
    return loaded if isinstance(loaded, dict) else {}


class Config:
    """语言配置。两级：script family（脚本级规则）+ language（语言级资源）。"""

    def __init__(self, lang: str = "sw", data_dir: Path | None = None,
                 script: str | None = None):
        self.lang = (lang or "sw").strip().lower()
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._raw: dict = {}
        self._script_raw: dict = {}
        self._yaml_present = False
        self._script_present = False
        self._forced_script = script
        self._load()
        self._apply()

    # ─ 加载 ────────────────────────────────────────────────
    def _load(self):
        lp = self.data_dir / "lang" / f"{self.lang}.yaml"
        self.config_path = lp
        if lp.exists():
            self._raw = _load_yaml(lp)
            self._yaml_present = True
        # 家族名：显式参数 > 语言 yaml 的 script 字段 > 提示表 > generic
        fam = (self._forced_script
               or self._raw.get("script")
               or LANG_FAMILY_HINT.get(self.lang)
               or "generic")
        self.script = str(fam).strip().lower()
        sp = self.data_dir / "script" / f"{self.script}.yaml"
        self.script_config_path = sp
        if sp.exists():
            self._script_raw = _load_yaml(sp)
            self._script_present = True

    def _d(self, key: str, default=None):
        """取配置值：语言层优先，缺则家族层，都缺用默认。"""
        if key in self._raw and self._raw[key] is not None:
            return self._raw[key]
        if key in self._script_raw and self._script_raw[key] is not None:
            return self._script_raw[key]
        return default

    # ── 应用 ────────────────────────────────────────────────
    def _apply(self):
        d = self._raw
        s = self._script_raw
        self.code = str(d.get("code") or self.lang)
        self.label = str(d.get("name") or self.code)
        self.script_label = str(s.get("name") or self.script)
        self.langdetect_code = str(d.get("langdetect_code") or self.code)
        self.langdetect_aliases: list = [str(x) for x in (d.get("langdetect_aliases") or [])]
        self.direction: str = str(d.get("direction") or s.get("direction") or "ltr")

        # ── 语言级资源（缺 = 空/None，不再回落他语）──
        self.function_words: set = set(d.get("function_words", []) or [])
        self.function_word_threshold: float = float(d.get("function_word_threshold", 0.15))
        self.question_words: list = list(d.get("question_words", []) or [])
        self.en_function_words: set = set(d.get("en_function_words", []) or [])
        nsw = d.get("nsw_patterns", {}) or {}
        self.nsw_patterns: list = [(str(k), str(v)) for k, v in nsw.items()]

        # ── 脚本级规则（家族提供，语言可覆盖）──
        self.token_pattern: str = str(self._d("token_pattern", r"[\p{L}\p{M}'\-]+"))
        self.core_pattern: str = str(self._d("core_pattern", r"[\p{L}\p{N}]"))
        self.letter_pattern: str = str(self._d("letter_pattern", r"\p{L}"))
        self.word_pattern: str = str(self._d("word_pattern", r"^[\p{L}\p{M}']+$"))
        self.sentence_enders: str = str(self._d("sentence_enders", ".!?"))
        self.enders_greedy: str = str(self._d("enders_greedy", ""))   # 句末标点后不需空格也断（如 。！？）
        self.q_marks: str = str(self._d("q_marks", "?"))               # 疑问标记（ur 加 ؟）
        self.ex_marks: str = str(self._d("ex_marks", "!"))             # 感叹标记（zh 加 ！）
        self.quote_pairs: list = [str(x) for x in (self._d("quote_pairs", []) or ['""', "''"])]
        self.keep_chars: list = [str(x) for x in (self._d("keep_chars", []) or [])]
        self.vowel_letters: str = str(self._d("vowel_letters", ""))   # 拼音法音节计数的元音字母集

        # 字符检查：越界块 + 阈值
        ch = d.get("charset", {}) or {}
        self.charset_pass_ratio = float(ch.get("pass_ratio", self._d("charset_pass_ratio", 0.05)))
        self.charset_warn_ratio = float(ch.get("warn_ratio", self._d("charset_warn_ratio", 0.20)))
        blocks = ch.get("foreign_blocks", None)
        if blocks is None:
            blocks = self._d("foreign_blocks", [])
        if not blocks:
            # 家族声明了自己的脚本块 → 结构性推导越界目录（全集 − 本族块）
            own = self._d("script_blocks", []) or []
            if own:
                from .charset import blocks_outside
                blocks = blocks_outside([str(x) for x in own])
        self.charset_blocks: list = [str(x) for x in (blocks or [])]
        self.charset_blocks_explicit: bool = bool(blocks)
        # 越界块是否只按「字母/组合符」计（语言无关的修复：块含空格/标点/数字会被误算）。
        # sw 为保 2026-09-16 历史基线，显式 pin 为 false（旧行为：块全量匹配）。
        self.foreign_letters_only: bool = bool(
            d.get("charset", {}).get("letters_only",
                                     self._d("charset_letters_only", self.lang != "sw")))

        # ── G2P（缺 = None，不回落 swa-Latn）──
        ipa_rel = d.get("ipa_dict")
        self.ipa_dict_rel: str | None = str(ipa_rel) if ipa_rel else None
        self.ipa_dict_path: Path | None = (
            self.data_dir / str(ipa_rel) if ipa_rel else None)
        if self.ipa_dict_path is None:
            # 约定优于配置：data/ipa/<code>.txt 存在即用，且**只认本语言的文件**
            cand = self.data_dir / "ipa" / f"{self.lang}.txt"
            if cand.exists():
                self.ipa_dict_path = cand
                self.ipa_dict_rel = f"ipa/{self.lang}.txt"
        g = d.get("g2p", {}) or {}
        self.g2p_fallback: str = str(g.get("fallback", "epitran"))
        self.epitran_lang: str | None = str(g["epitran_lang"]) if g.get("epitran_lang") else None
        patch = g.get("patch", {}) or {}
        self.g2p_patch: list = [(str(k), str(v)) for k, v in patch.items()]
        self.g2p_strip_marks: bool = bool(g.get("strip_marks", self._d("g2p_strip_marks", True)))

        # ── 音节口径（长度维度）──
        syll = d.get("syllable", {}) or {}
        self.syllable_method: str = str(syll.get("method", "vowel_groups"))
        self.syllable_dict_path: Path | None = None
        if syll.get("dict"):
            self.syllable_dict_path = self.data_dir / str(syll["dict"])
        elif self.lang == "fr" and (self.data_dir / "syll" / "fr.txt").exists():
            self.syllable_dict_path = self.data_dir / "syll" / "fr.txt"

        # ── 词源（LLM）──
        ety = d.get("etymology", {}) or {}
        self.ety_prompt_name: str = str(ety.get("prompt_name") or self.label)
        self.ety_valid_origins: list = [str(x) for x in (ety.get("valid_origins") or [])]
        self.ety_candidate_hint: str = str(ety.get("candidate_hint") or "")

        # 句式目标配比（V2）：{句式: [下, 上]}
        st = d.get("sentence_targets", {}) or {}
        self.sentence_targets: dict = {
            str(k): [float(v[0]), float(v[1])] for k, v in st.items() if isinstance(v, (list, tuple)) and len(v) == 2
        }

        # 音位学（V4.3）：理论组合空间 + 归并/拆分表（语言级；非 sw 首版可缺）
        pt = d.get("phonotactics", {}) or {}
        self.ph_vowels: list = [str(x) for x in (pt.get("vowels", []) or [])]
        self.ph_consonants: list = [str(x) for x in (pt.get("consonants", []) or [])]
        self.ph_glides: list = [str(x) for x in (pt.get("glides", []) or [])]
        pn = pt.get("prenasal", {}) or {}
        self.ph_prenasal: dict = {
            str(k): [str(x) for x in (v or [])] for k, v in pn.items() if isinstance(v, (list, tuple))
        }
        self.ph_equivalences: dict = {str(k): str(v) for k, v in (pt.get("equivalences", {}) or {}).items()}
        self.ph_prenasal_decompose: dict = {
            str(k): [str(x) for x in v] for k, v in (pt.get("prenasal_decompose", {}) or {}).items()
        }
        # 音素切分规则别（sw 前鼻化/tʃ 等专属规则的开关在 phonemes.split_phonemes 里按 lang 读取）
        ph = d.get("phoneme_rules", {}) or {}
        self.phoneme_rules: dict = dict(ph)
        self.ph_ready: bool = bool(self.ph_vowels and self.ph_consonants)

        # ─ 能力缺口（诚实留痕）──
        self.capability_gaps: list[str] = []
        if not self._yaml_present:
            self.capability_gaps.append(
                f"缺少 data/lang/{self.lang}.yaml：语言级资源（虚词表/NSW/词源口径）不可用，"
                f"按脚本家族 {self.script} 的通用规则运行")
        if not self._script_present:
            self.capability_gaps.append(
                f"缺少 data/script/{self.script}.yaml：按 Unicode 属性兜底（generic），规则可能偏保守")
        if self.ipa_dict_path is None:
            self.capability_gaps.append(
                f"无发音词典（data/ipa/{self.lang}.txt 不存在）：音素维度只能靠 G2P 兜底或不可用")
        elif not self.ipa_dict_path.exists():
            self.capability_gaps.append(f"发音词典缺失：{self.ipa_dict_path}")
        if not self.epitran_lang:
            if self.g2p_fallback in ("none", "null", ""):
                self.capability_gaps.append(
                    "G2P 无规则兜底（该语言未配 epitran 映射或有意关闭）：词典未命中的词无 IPA")
            else:
                self.capability_gaps.append("未配置 G2P 兜底语言码（g2p.epitran_lang）：词典未命中的词无 IPA")
        if self.syllable_method == "na":
            self.capability_gaps.append("音节口径未定稿（syllable.method=na）：长度维度不含音节数")
        if self.syllable_method == "dict" and (self.syllable_dict_path is None
                                               or not self.syllable_dict_path.exists()):
            self.capability_gaps.append("音节词典缺失：音节数将按近似口径并披露覆盖率")
        if not self.function_words:
            self.capability_gaps.append("无虚词表：语言判定只依赖 langdetect（短文本不稳）")

        # 兼容旧字段（既有代码/测试引用的 degraded 语义）
        self.degraded: bool = bool(self.capability_gaps)
        self.degraded_reasons: list = list(self.capability_gaps)

    @property
    def resources_ok(self) -> bool:
        """语言资源是否**真的**就绪——本语言 yaml 在、且在的词典是**本语言**的。

        要点：词典按 `data/ipa/<lang>.txt` 约定查找，不再因为他语词典存在而误判就绪。
        """
        return self._yaml_present and self.ipa_dict_path is not None and self.ipa_dict_path.exists()

    def get(self, key: str, default=None):
        """取原始 yaml 值（语言层优先）——供既有代码的 `cfg.get("g2p")` 等调用。"""
        v = self._d(key, None)
        return default if v is None else v