"""phonotactics —— 音位级组合空间与缺失组合（V4.3）。

背景
----
`profile_phoneme` 从 IPA 串切出音素后，词典与 epitran 存在两处**内部不一致**，
直接统计会污染音素清单与组合空间：
  · 同音素异写：ipa-dict 写 ASCII `g`/`r`，epitran 写 `ɡ`/`ɾ` → 统计成两个音素；
  · 前鼻化写法不一：词典既用上标单音位 `ᵐɓ`/`ⁿ`/`v`/`ⁿz`，又用普通 `mb`/`nd`。
本模块在统计前先归一（`normalize_sequence`），再按 config 的 native 音类生成
**理论组合空间**（CV / VC / VV / 鼻音+N+C / C+Glide），与观测组合做差 → 缺失清单。

缺失组合的用途：**选句阶段贪心补齐的目标**（哪些音素组合语料还没覆盖，需要补录哪些句子）。
"""
from __future__ import annotations

from corpus_kit.phonemes import split_phonemes


def normalize_phoneme(p: str, cfg) -> str:
    """单个音素归一：异写归并（ɡ→g、r→ɾ）。"""
    return cfg.ph_equivalences.get(p, p) if cfg.ph_ready else p


def normalize_sequence(ipa: str, cfg) -> list[str]:
    """IPA 串 → 归一后的音素序列。

    两步：① 切音素 + 异写归并；② 前鼻化上标单音位拆回 N+C（与普通写法统一）。
    cfg 无音位学配置时退化为纯切分（不归并、不拆分）——切片规则仍按 cfg 的语种口径。
    """
    out: list[str] = []
    for p in split_phonemes(ipa, cfg):
        p = cfg.ph_equivalences.get(p, p) if cfg.ph_ready else p
        decomp = cfg.ph_prenasal_decompose.get(p) if cfg.ph_ready else None
        if decomp:
            out.extend(decomp)
        else:
            out.append(p)
    return out


def combo_space(cfg) -> set[tuple[str, str]]:
    """理论组合空间（相邻音素对）。仅 native 音类，不含外来借词音。"""
    if not cfg.ph_ready:
        return set()
    V, C, G = cfg.ph_vowels, cfg.ph_consonants, cfg.ph_glides
    space: set[tuple[str, str]] = set()
    for c in C:
        for v in V:
            space.add((c, v))          # CV
    for v in V:
        for c in C:
            space.add((v, c))          # VC
    for a in V:
        for b in V:
            space.add((a, b))          # VV
    for n, seconds in cfg.ph_prenasal.items():
        for c in seconds:
            space.add((n, c))          # 前鼻化/鼻音丛（同化规则）
    for c in C:
        for g in G:
            space.add((c, g))          # C + Glide（唇化/颚化）
    return space


def phonotactics_report(pairs: dict, cfg) -> dict:
    """观测 bigram → {missing, out_of_space, n_*}。

    pairs：{音素对(元组或串): 次数}，应为**已归一**的音素对。
    缺失 = 理论空间内、语料未出现；越界 = 语料出现但不在理论空间（多为外来借词丛）。
    """
    obs = set(pairs)
    space = combo_space(cfg)
    missing = sorted(space - obs)
    out = sorted(obs - space, key=lambda k: -pairs.get(k, 0))
    total = sum(pairs.values())
    return {
        "n_space": len(space),
        "n_observed": len(obs),
        "n_missing": len(missing),
        "n_out_of_space": len(out),
        "missing": [{"combo": "".join(k), "from": k[0], "to": k[1]} for k in missing],
        # 越界丛**全量**落盘（原 out[:120] 把 536→120，丢弃 416 个组合/1984 次出现且无痕迹）。
        # 越界丛多为外来借词/native 音类缺口，是判断借词渗透的依据，截断即失去该依据。
        "out_of_space": [{"combo": "".join(k), "count": pairs[k]} for k in out],
        "out_of_space_total": sum(pairs[k] for k in out),
        "observed_total": total,
        # 词内观测组合（供报告「音素组合」sheet 用；按次数降序）
        "observed": [{"combo": "".join(k), "count": pairs[k]}
                     for k in sorted(pairs, key=lambda k: -pairs[k])],
    }