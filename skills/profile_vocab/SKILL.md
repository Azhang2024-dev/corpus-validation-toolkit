---
name: profile-vocab
description: 语料词汇分布画像（词频表/外来词/实词虚词/NSW 非标词）。当需要统计回流语料的词例型符、均匀性（H_norm/Gini/Top10%）、词典命中率、虚词/英语占比、或按句标记 NSW 类别时使用。输入 records.jsonl+sentences.jsonl，输出 dims/vocab.json 并回写句子 nsw_types。
---

# profile_vocab — 词汇分布

## 触发
- `/profile-vocab` 或 `python skills/profile_vocab/run.py --records output/<run>/records.jsonl --sentences output/<run>/sentences.jsonl --out output/<run>/`

## 口径（对应 wiki「词汇分布」节）
- 词频：全语料小写 + 正则分词（保留 ' 与 -），按型符计数 + H_norm/Gini/Top10% 份额
- 外来词三层判定：① ipa-dict 命中锚定斯语 → ② 词形归并（v1 直查，归并放版本演进）→ ③ 英语高频词（code-switch）
- 虚词：lang/<code>.yaml 的 function_words 表；实义占比 = 1 - 虚词占比
- NSW：纯数字 / 时间版本 / 币种 KSh·TSh / 号码 +254 / 全大写缩写 / 网址邮箱，按句扫描
