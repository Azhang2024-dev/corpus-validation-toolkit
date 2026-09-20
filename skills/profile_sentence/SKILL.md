---
name: profile-sentence
description: 语料句式分布画像（疑问/感叹/陈述/短语）+ 目标配比偏差告警。当需要统计回流语料的句式构成、对切句后的句子打句式标签、或核对句式配比是否达标时使用。输入 sentences.jsonl，回写句子类型字段并输出 dims/sentence.json。
---

# profile_sentence — 句式分布

## 触发
- `/profile-sentence` 或 `python skills/profile_sentence/run.py --sentences output/<run>/sentences.jsonl --out output/<run>/`

## 口径（对应 wiki「句式分布」节）
- 疑问：句尾带 ?（含 ?. 拼接残留），或句首斯语疑问词（je/nani/nini/lini/wapi/gani/ngapi/vipi/mbona/kwani）
- 感叹：句尾带 !
- 陈述：两类标点句挑走后的剩余（句尾 . 或无标点）
- 短语：无句末标点且 <5 词
- 60 句人工抽检已通过（句式识别准）

## 目标配比与偏差告警（2026-09-16 新增）
- 目标区间来自 `data/lang/<code>.yaml` 的 `sentence_targets`（sw：陈述 70–80% / 短语 5–15% / 疑问 10–20% / 感叹 10–20%）
- 每类算「占比 − 目标区间」的差距；越界即 `偏低`/`偏高` 告警
- `dims/sentence.json` 增 `targets`/`distribution`（含每类差距与告警）/`n_warn`/`status`；报告 `维度分布` sheet 的句式块据此渲染