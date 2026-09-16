---
name: corpus-pipeline
description: 语料验证工具集编排（一键全流程）。当需要对回流语料一次性跑完整链路（gate→length→sentence→vocab→[phoneme]→[etymology]→report）或按需跳过 G2P/词源时使用。
---

# pipeline — 编排（一键全流程）

## 触发
- 对话：`/corpus-pipeline --input input/INPUT.txt [--skip-g2p] [--skip-etymology]`
- CLI：`python skills/pipeline/run.py --input input/INPUT.txt --out output/<run>/`
- 等价于根目录 `python run_pipeline.py ...`

## 链路
```
INPUT.txt + meta.json
  → gate_validity  行级 gate（语言+字符，标记不下车）       records.jsonl
  → profile_length 切句 + 长度分布                          sentences.jsonl
  → profile_sentence 句式分布
  → profile_vocab 词频/外来/实虚/NSW
  → profile_phoneme G2P(查表→epitran→补丁)（可选）
  → etymology_llm 词源打标（可选，需 LLM_ENDPOINT/KEY 或 --mock）
  → report 数据集_全字段.xlsx + csv + manifest.json
```
- 断点续跑：每个 stage 幂等，重跑只补增量；manifest.json 记录输入哈希/参数/seed=0
