"""lang —— 目标语言判定：虚词表命中（>=阈值）优先 + langdetect 1.0.9（seed=0）双保险。"""
from __future__ import annotations

import re

from langdetect import DetectorFactory, detect_langs

from .tokenize import word_tokens

DetectorFactory.seed = 0  # 结果可复现（文档口径：seed 固定为 0）


def function_word_score(text: str, fw: set) -> tuple[float, int, int]:
    """虚词命中率 score = 命中虚词数 / 词法 token 数；返回 (score, hits, n_tokens)。"""
    toks = word_tokens(text)
    if not toks:
        return 0.0, 0, 0
    hits = sum(1 for t in toks if t in fw)
    return hits / len(toks), hits, len(toks)


def detect_top_lang(text: str, max_len: int = 600, k: int = 3) -> list:
    flat = re.sub(r"\s+", " ", text).strip()[:max_len]
    if not flat:
        return []
    try:
        return [(d.lang, round(d.prob, 4)) for d in detect_langs(flat)[:k]]
    except Exception:
        return []


def check_lang(text: str, cfg) -> dict:
    """返回 {status, score, hits, tokens, detected, detected_probs, reason}。"""
    score, hits, ntok = function_word_score(text, cfg.function_words)
    detected = detect_top_lang(text)
    top = detected[0][0] if detected else None
    if ntok == 0:
        status, reason = "fail", "no_tokens"
    elif score >= cfg.function_word_threshold or top == cfg.langdetect_code:
        status = "pass"
        reason = f"fw_score={score:.2f}>={cfg.function_word_threshold}" if score >= cfg.function_word_threshold else f"langdetect={top}"
    else:
        status = "fail"
        reason = f"fw_score={score:.2f}, langdetect={top or 'ERR'}"
    return {
        "status": status,
        "score": round(score, 4),
        "hits": hits,
        "tokens": ntok,
        "detected": top or "ERR",
        "detected_probs": detected,
        "reason": reason,
    }
