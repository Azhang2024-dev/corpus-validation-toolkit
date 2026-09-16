"""g2p —— 定稿管线：ipa-dict 查表(80.8%) → epitran(swa-Latn) 兜底 → 补丁。
数字/缩写等非纯字母词跳过（TN 在工具集之外，此处不展开）。"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

WORD_RE = re.compile(r"^[a-z']+$")
STRESS = str.maketrans({"ˈ": "", "ˌ": "", " ": ""})


def load_ipa_dict(path) -> dict:
    """data/ipa/<lang>.txt：每行『词\\tIPA』，词小写作 key，IPA 去斜杠、小写。"""
    d: dict = {}
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
        self.dict = load_ipa_dict(cfg.ipa_dict_path)
        self._epitran = None

    def _get_epitran(self):
        if self._epitran is None:
            import epitran

            self._epitran = epitran.Epitran(self.cfg.epitran_lang)
        return self._epitran

    def phonemize(self, word: str) -> str | None:
        """单词 → IPA 字符串；查不到又非纯字母（数字/缩写/符号）或 epitran 不可用则返回 None。"""
        w = word.strip().lower()
        if not w:
            return None
        if w in self.dict:
            return self.dict[w]
        if not WORD_RE.fullmatch(w):
            return None
        try:
            out = self._get_epitran().transliterate(w).lower().translate(STRESS)
            # 剥掉组合/附加符号（如 t͡ʃ 的连字线 U+0361）：斯语无鼻化元音等合法组合符，安全
            out = "".join(c for c in out if unicodedata.category(c) != "Mn")
        except Exception:
            return None
        for src, dst in self.cfg.g2p_patch:
            out = out.replace(src, dst)
        return out or None

    def phonemize_many(self, words) -> dict:
        """批量：唯一次数缓存后回填，返回 {word: ipa|None}。"""
        uniq = sorted({w.strip().lower() for w in words if w and w.strip().lower()})
        cache = {w: self.phonemize(w) for w in uniq}
        return cache
