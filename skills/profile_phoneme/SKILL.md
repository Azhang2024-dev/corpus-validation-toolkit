---
name: profile-phoneme
description: 音素分布画像（G2P：ipa-dict 查表→epitran 兜底→补丁）。单字母/单音素/双音素 + 音素组合空间与缺失组合 + G2P 一致性抽验。当需要统计语料的音素覆盖、找缺失组合（选句补齐）、验证 G2P 可信度、或生成词→IPA 中间态时使用。输入 sentences.jsonl，输出 dims/phoneme.json + token_ipa.json + g2p_audit.csv。
---

# profile_phoneme — 音素分布（G2P）

## 触发
- `/profile-phoneme` 或 `python skills/profile_phoneme/run.py --sentences output/<run>/sentences.jsonl --out output/<run>/`
- 抽验样本数：`--audit-n 200`（默认 200，0=跳过）

## G2P 定稿管线（对应 wiki「音素分布」节）
1. ipa-dict 查表优先（命中 80.8% token，零误差）
2. 未命中走 epitran（swa-Latn）
3. 已知差异打补丁（lang/<code>.yaml g2p.patch）
- 数字/缩写等非纯字母词跳过（TN 在工具集外，准入制）
- IPA 统一小写，前鼻化（ⁿ ᵐ ᶮ ᵑ ᶬ+后字）合并单音位，tʃ/dʒ 双字母按单音素

## 两项口径修正（2026-09-16）
- **异写归并**：词典写 ASCII `g`/`r`、epitran 写 `ɡ`/`ɾ`，是同一音素 → 统计前归并
  （原始 46 单音素 → 归一 40）；前鼻化上标单音位拆回 N+C，与普通写法统一
- **组合空间按词内统计**：把整句音素拼起来会跨词边界造伪组合；缺失组合必须基于**词内**相邻音素对

## 产出
| 文件 | 内容 |
|---|---|
| `token_ipa.json` | `{词: IPA\|null}`（null=未覆盖） |
| `g2p_audit.csv` | G2P 抽验不一致清单：`word,dict_ipa,epitran_ipa,kind` |
| `dims/phoneme.json` | 原始分布（`single`/`bi`/…）+ 归一分布（`*_norm`）+ `phonotactics`（空间/缺失/越界/observed）+ `g2p_audit`（三档一致率/阈值/判定/不一致） |

## 音素组合与缺失组合（V4.3）
- 理论空间 = CV + VC + VV + 鼻音丛（同化：m 接唇音、n 接齿/软腭）+ C+滑音，由 `lang/<code>.yaml` 的 `phonotactics` 生成
- **缺失组合** = 空间内、语料未覆盖 → 选句阶段贪心补齐的目标
- **越界组合** = 语料出现但不在 native 空间（多为英语/阿拉伯借词丛），不计入缺失

## G2P 一致性抽验（V4.4）
- 抽词典命中词 → 绕过查表用 epitran 单独转写 → 与词典比
- 三档：`rate_exact`（全同）/ `rate_phoneme`（归一后同）/ `rate_folded`（**折合表示层差异**后同）；**判定用 rate_folded**，阈值 `g2p.audit_agreement_threshold`（默认 0.95）
- 折合表 `g2p.audit_fold` 记录等价写法（如 `n g` ≡ `ŋ g`）

## 依赖
- `requirements-g2p.txt`（epitran 必装）；重环境可复用 g2p_lab/venv