"""lang —— 目标语言判定：虚词表命中（>=阈值）优先 + langdetect 1.0.9（seed=0）双保险。"""
from __future__ import annotations

import re

from langdetect import DetectorFactory, detect_langs

from .tokenize import word_tokens

DetectorFactory.seed = 0  # 结果可复现（文档口径：seed 固定为 0）


def function_word_score(text: str, fw: set, token_pattern: str | None = None) -> tuple[float, int, int]:
    """虚词命中率 score = 命中虚词数 / 词法 token 数；返回 (score, hits, n_tokens)。"""
    toks = word_tokens(text, token_pattern)
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
    """返回 {status, score, hits, tokens, detected, detected_probs, reason, notes}。

    多语种口径（2026-09-18）：
    - token 正则取自 cfg（非拉丁语料才有 token）；
    - **虚词表为空**（缺 yaml 的语言）：不再把「fw_score=0」当失败（那对无虚词表的语言
      是假失败），改由 langdetect 独立判定，并在 notes 里如实标注「无虚词表，仅 LID」；
    - langdetect 无该语言 profile（ha/fil 等）：如实标注「LID 不覆盖」。
    """
    tp = getattr(cfg, "token_pattern", None)
    score, hits, ntok = function_word_score(text, cfg.function_words, tp)
    detected = detect_top_lang(text)
    top = detected[0][0] if detected else None
    notes: list[str] = []
    has_fw = bool(cfg.function_words)
    aliases = {a.lower() for a in (getattr(cfg, "langdetect_aliases", None) or [])}

    if ntok == 0:
        status, reason = "fail", "no_tokens"
    elif has_fw and score >= cfg.function_word_threshold:
        status = "pass"
        reason = f"fw_score={score:.2f}>={cfg.function_word_threshold}"
    elif top == cfg.langdetect_code or (detected and detected[0][0] in aliases):
        status = "pass"
        reason = f"langdetect={top}"
    elif not has_fw:
        # 无虚词表：LID 命中即 pass（已在上面处理），否则如实给 warn（不计为语言失败）
        if detected:
            status, reason = "warn", f"无虚词表，仅 LID（top={top}，非 {cfg.langdetect_code}）"
            notes.append(f"该语言无虚词表配置，判定仅依赖 langdetect（对 {top} 的把握 {detected[0][1]:.2f}）")
        else:
            status, reason = "warn", "无虚词表且 LID 不可用"
            notes.append("该语言既无虚词表、langdetect 也未能给出结论，无法判定语言")
    else:
        status = "fail"
        reason = f"fw_score={score:.2f}, langdetect={top or 'ERR'}"

    if top is None and ntok > 0:
        notes.append("langdetect 无输出（文本过短或不在其 55 语 profile 内），判定基于虚词表")
    return {
        "status": status,
        "score": round(score, 4),
        "hits": hits,
        "tokens": ntok,
        "detected": top or "ERR",
        "detected_probs": detected,
        "reason": reason,
        "has_fw": has_fw,
        "notes": notes,
    }
