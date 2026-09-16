"""config —— 按语言加载 data/lang/<code>.yaml，缺失项逐项降级。"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


class Config:
    def __init__(self, lang: str = "sw", data_dir: Path | None = None):
        self.lang = (lang or "sw").strip().lower()
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._raw: dict = {}
        self._load()
        self._apply()

    def _load(self):
        p = self.data_dir / "lang" / f"{self.lang}.yaml"
        if p.exists():
            loaded = yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
            self._raw = loaded if isinstance(loaded, dict) else {}

    def _apply(self):
        d = self._raw
        self.code = str(d.get("code") or self.lang)
        self.label = str(d.get("name") or self.code)
        self.langdetect_code = str(d.get("langdetect_code") or self.code)
        self.function_words: set = set(d.get("function_words", []) or [])
        self.function_word_threshold: float = float(d.get("function_word_threshold", 0.15))
        self.question_words: list = list(d.get("question_words", []) or [])
        self.en_function_words: set = set(d.get("en_function_words", []) or [])
        nsw = d.get("nsw_patterns", {}) or {}
        self.nsw_patterns: list = [(str(k), str(v)) for k, v in nsw.items()]
        ch = d.get("charset", {}) or {}
        self.charset_pass_ratio = float(ch.get("pass_ratio", 0.05))
        self.charset_warn_ratio = float(ch.get("warn_ratio", 0.20))
        self.charset_blocks: list = list(ch.get("foreign_blocks", []) or [])
        self.ipa_dict_path = self.data_dir / str(d.get("ipa_dict", "ipa/sw.txt"))
        g = d.get("g2p", {}) or {}
        self.g2p_fallback = str(g.get("fallback", "epitran"))
        self.epitran_lang = str(g.get("epitran_lang", "swa-Latn"))
        patch = g.get("patch", {}) or {}
        self.g2p_patch: list = [(str(k), str(v)) for k, v in patch.items()]

    @property
    def resources_ok(self) -> bool:
        return self.ipa_dict_path.exists()

    def get(self, key: str, default=None):
        return self._raw.get(key, default)
