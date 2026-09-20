"""g2p_audit —— G2P 一致性抽验（V4.4）。

为什么验这个
------------
G2P 管线是「ipa-dict 查表 → epitran 兜底 → 补丁」。查表路径命中词典、结果必然一致，
**无验证价值**；要验的是**兜底路径可靠性**：词典未覆盖时 epitran 的转写是否与词典口径一致。
方法：随机抽 N 个**词典命中**词 → 绕过查表直接用 epitran 转写 → 与词典 IPA 比对。

三档口径（逐档放宽，把"表示层差异"和"真差异"分开）
  · rate_exact    ：字符串完全相同
  · rate_phoneme  ：归一（异写 g/ɡ、r/ɾ + 前鼻化拆分）后音素序列相同
  · rate_folded   ：再把**表示层约定差异**折合后相同（词典 `ŋg`/`ᵐɓ` vs epitran `ng`/`mb`）
判定用 rate_folded；三档都报，便于看清差异到底来自约定还是算法。阈值 0.95（框架口径）。
"""
from __future__ import annotations

import random

from corpus_kit.phonotactics import normalize_sequence


def _epitran_of(word: str, g2p) -> str | None:
    """绕过词典，直接走 epitran（复刻 G2P.phonemize 的兜底分支）。"""
    import unicodedata

    from corpus_kit.g2p import STRESS, word_pattern_for

    w = word.strip().lower()
    if not w or not word_pattern_for(g2p.cfg).fullmatch(w):
        return None
    try:
        out = g2p._get_epitran().transliterate(w).lower().translate(STRESS)
        if getattr(g2p.cfg, "g2p_strip_marks", True):
            out = "".join(c for c in out if unicodedata.category(c) != "Mn")
        for src, dst in g2p.cfg.g2p_patch:
            out = out.replace(src, dst)
        return out or None
    except Exception:
        return None


def fold_sequence(seq: list[str], fold_pairs) -> list[str]:
    """把等价写法折成同一标记。fold_pairs 元素为两个等价的音素序列（list）。"""
    pairs = [([str(x) for x in p[0].split()], [str(x) for x in p[1].split()])
             for p in fold_pairs if isinstance(p, (list, tuple)) and len(p) == 2]
    out: list[str] = []
    i = 0
    while i < len(seq):
        hit = None
        for a, b in pairs:
            for s in (a, b):
                if s and seq[i:i + len(s)] == s:
                    hit = "≪" + "|".join(["".join(x) for x in sorted((a, b))]) + "≫"
                    i += len(s)
                    break
            if hit:
                break
        if hit:
            out.append(hit)
        else:
            out.append(seq[i])
            i += 1
    return out


def audit(g2p, ipa_dict: dict, cfg, n: int = 200, seed: int = 0, fold: bool = True) -> dict:
    """抽 n 个词典命中词，比 epitran 与词典（三档口径）。"""
    words = sorted(w for w in ipa_dict if w and len(w) > 1)
    if not words:
        return {"n_sample": 0, "rate_folded": 0.0, "status": "no_dict", "mismatches": [],
                "note": "无发音词典或词典为空：无法抽验"}
    if not getattr(g2p, "use_epitran", False) or not getattr(cfg, "epitran_lang", None):
        return {"n_sample": 0, "rate_folded": 0.0, "status": "no_fallback", "mismatches": [],
                "note": "未配置 G2P 兜底（epitran_lang 缺失或 fallback=none）：无对照对象，抽验不适用"}
    rng = random.Random(seed)
    sample = rng.sample(words, min(n, len(words)))

    fold_pairs = (cfg.get("g2p", {}) or {}).get("audit_fold", []) if fold else []
    exact = phonemic = folded = 0
    mismatches: list[dict] = []
    for w in sample:
        dict_ipa = ipa_dict[w]
        et_ipa = _epitran_of(w, g2p)
        if et_ipa is None:
            mismatches.append({"word": w, "dict_ipa": dict_ipa, "epitran_ipa": "", "kind": "no_output"})
            continue
        if dict_ipa == et_ipa:
            exact += 1
        d_seq, e_seq = normalize_sequence(dict_ipa, cfg), normalize_sequence(et_ipa, cfg)
        if d_seq == e_seq:
            phonemic += 1
        if fold_sequence(d_seq, fold_pairs) == fold_sequence(e_seq, fold_pairs):
            folded += 1
        else:
            mismatches.append({"word": w, "dict_ipa": dict_ipa, "epitran_ipa": et_ipa, "kind": "diff"})

    ns = len(sample)
    rate_p = round(phonemic / ns, 4) if ns else 0.0
    rate_e = round(exact / ns, 4) if ns else 0.0
    rate_f = round(folded / ns, 4) if ns else 0.0
    thr = float((cfg.get("g2p", {}) or {}).get("audit_agreement_threshold", 0.95))
    return {
        "n_sample": ns,
        "n_match_exact": exact,
        "n_match_phoneme": phonemic,
        "n_match_folded": folded,
        "rate_exact": rate_e,
        "rate_phoneme": rate_p,
        "rate_folded": rate_f,
        "threshold": thr,
        "status": "pass" if rate_f >= thr else "warn",
        "n_mismatch": len(mismatches),
        "mismatches": mismatches,
    }