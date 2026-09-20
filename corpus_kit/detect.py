"""detect —— 脚本/语言探测与指令校验（「诚实」原则的地基）。

三条口径（对应产品要求）：
1. **进来什么就检测什么**：不猜。脚本按 `\\p{scx=...}` 统计采样；语言用 langdetect 采 top-k。
2. **能力边界如实报**：探测不到就是 `unknown`，并给出候选与原因（供报告「能力与口径」块）。
3. **指令冲突要顶嘴**：用户 `--lang` 与数据检测强烈不符 → `conflict`，报告标出请人核，
   而不是按错的指令静默跑完。

脚本：拉丁 latin / 阿拉伯 arabic / 天城 devanagari / 孟加拉 bengali / 古吉拉特 gujarati /
古鲁穆奇 gurmukhi / 泰米尔 tamil / 西里尔 cyrillic / 汉字 han。这 9 个与 data/script/*.yaml 同名。
"""
from __future__ import annotations

import regex as re

from .lang import detect_top_lang

# 家族名 → 用于 `\p{scx=...}` 的脚本名
FAMILY_SCRIPT = {
    "latin": "Latin",
    "arabic": "Arabic",
    "devanagari": "Devanagari",
    "bengali": "Bengali",
    "gujarati": "Gujarati",
    "gurmukhi": "Gurmukhi",
    "tamil": "Tamil",
    "cyrillic": "Cyrillic",
    "han": "Han",
}

_SCRIPTS = {f: re.compile(r"\p{scx=%s}" % s) for f, s in FAMILY_SCRIPT.items()}

# langdetect 的返回码 → 我们的语言码（只收本的常见别名；语言 yaml 的
# `langdetect_aliases` 可再补。未列出的码原样返回，避免误并）
LANGDETECT_ALIAS = {
    "zh-cn": "zh", "zh-tw": "zh", "zh": "zh",
    "tl": "fil",
    "iw": "he",
    "in": "id",
}

SAMPLE_LIMIT = 200_000   # 采样上限（字符）：探测是「判大类」，不需要吃全量


def _norm_code(code: str) -> str:
    c = (code or "").strip().lower()
    return LANGDETECT_ALIAS.get(c, c)


def script_profile(text: str, limit: int = SAMPLE_LIMIT) -> dict:
    """采样文本 → {家族: 命中字符数}。空白不计。"""
    sample = (text or "")[:limit]
    out: dict = {}
    for fam, pat in _SCRIPTS.items():
        n = len(pat.findall(sample))
        if n:
            out[fam] = n
    return out


def detect_script(text: str, limit: int = SAMPLE_LIMIT) -> dict:
    """主脚本判定。

    返回 {script, profile, total, ratios}；探测不出（空文本/无脚本字符）时 script=unknown。
    判据只看**字符计数**（不猜语言）：这是「数据事实」，报告里以此与 --lang 对账。
    """
    prof = script_profile(text, limit)
    total = sum(prof.values())
    if not total:
        return {"script": "unknown", "profile": {}, "total": 0, "ratios": {}}
    top = max(prof, key=lambda k: prof[k])
    return {
        "script": top,
        "profile": prof,
        "total": total,
        "ratios": {k: round(v / total, 4) for k, v in sorted(prof.items(), key=lambda kv: -kv[1])},
    }


def detect_language(text: str) -> list:
    """langdetect top-k（seed=0 固定于 lang 模块，可复现）。返回 [(code, prob), ...]。"""
    return detect_top_lang(text)


def verify_lang_command(cmd_lang: str, cmd_family: str | None,
                        script_det: dict, lang_probs: list,
                        aliases: list | None = None,
                        *, min_script_ratio: float = 0.30) -> dict:
    """`--lang` 指令与数据检测的相符性判定（诚实性：不符就顶嘴）。

    判据分两层，都以**检测到的事实**为准：
    - 脚本层（硬证据）：检测主脚本与命令语言的脚本族不符，且主脚本占比 ≥ min_script_ratio
      → conflict（如 --lang=ur 但数据 99% 是拉丁字符）。
    - 语言层（软证据）：langdetect top-1 与命令语言不符，且命令语言不在 top-k 前列
      → 记 note（短文本上 langdetect 不稳，不单独升 conflict）。
    """
    notes: list[str] = []
    detected = script_det.get("script") or "unknown"
    top_ratio = (script_det.get("ratios") or {}).get(detected, 0.0)

    status = "ok"
    if not script_det.get("total"):
        status = "unverifiable"
        notes.append("数据中未发现可识别脚本字符（空文本或纯符号），无法核对 --lang")
        return {"status": status, "command": cmd_lang, "detected_script": detected,
                "detected_lang": (lang_probs[0][0] if lang_probs else None), "notes": notes}

    if cmd_family and detected != "unknown" and detected != cmd_family:
        if top_ratio >= min_script_ratio:
            status = "conflict"
            notes.append(
                f"--lang={cmd_lang}（脚本族 {cmd_family}）与数据主脚本 {detected}"
                f"（占比 {top_ratio:.1%}）不符：按当前指令跑出的数字不代表该语言，请核对")
        else:
            notes.append(f"数据含少量其他脚本（主脚本={detected} {top_ratio:.1%}），未达冲突阈值")

    # 语言层软提示
    aliases_set = {_norm_code(a) for a in (aliases or [])}
    cmd_alias = _norm_code(cmd_lang)
    top_codes = [_norm_code(c) for c, _ in (lang_probs or [])[:3]]
    if lang_probs and cmd_alias not in top_codes and (aliases_set & set(top_codes)) == set():
        d_top = lang_probs[0]
        if d_top[1] >= 0.80:
            notes.append(
                f"langdetect 倾向 {d_top[0]}({d_top[1]:.2f}) 而非 --lang={cmd_lang}；"
                f"若语料确为 {cmd_lang}，可能是短文本或混排所致，供参考")
        else:
            notes.append(f"langdetect 未给出高置信结论（top={d_top[0]} {d_top[1]:.2f}），以 --lang 为准")
    return {
        "status": status,
        "command": cmd_lang,
        "detected_script": detected,
        "detected_lang": (lang_probs[0][0] if lang_probs else None),
        "notes": notes,
    }


def pick_language(text: str, available: list[str], families: dict[str, str],
                  aliases: dict[str, list] | None = None) -> dict:
    """`--lang auto`：从候选语言里选一个；**选不出就说选不出**（不瞎猜）。

    families: {lang_code: script_family}（来自各语言 yaml）。
    aliases:  {lang_code: [langdetect 别名]}。

    策略：① langdetect top-k 命中候选 → 选它；
         ② 否则按检测脚本筛候选：唯一 → 选它；多个 → 无法确定（回候选清单）。
    """
    script_det = detect_script(text)
    probs = detect_language(text)
    det_script = script_det.get("script")
    alias_map = {c: {_norm_code(a) for a in (aliases or {}).get(c, [])} for c in available}

    for code, prob in probs[:3]:
        nc = _norm_code(code)
        for cand in available:
            if nc == _norm_code(cand) or nc in alias_map.get(cand, set()):
                return {"lang": cand, "method": "langdetect", "confidence": prob,
                        "detected_script": det_script, "detected_lang": code,
                        "candidates": [cand]}
    if det_script and det_script != "unknown":
        cands = [c for c in available if families.get(c) == det_script]
        if len(cands) == 1:
            return {"lang": cands[0], "method": "script-unique", "confidence": None,
                    "detected_script": det_script,
                    "detected_lang": (probs[0][0] if probs else None), "candidates": cands}
        return {"lang": None, "method": "undetermined", "confidence": None,
                "detected_script": det_script,
                "detected_lang": (probs[0][0] if probs else None), "candidates": cands,
                "reason": f"主脚本 {det_script} 下候选 {cands} 不唯一，langdetect 也未命中候选；"
                          f"请显式 --lang 指定"}
    return {"lang": None, "method": "undetermined", "confidence": None,
            "detected_script": det_script, "detected_lang": (probs[0][0] if probs else None),
            "candidates": list(available), "reason": "无法从数据中识别脚本/语言，请显式 --lang"}