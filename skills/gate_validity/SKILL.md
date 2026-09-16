---
name: gate-validity
description: 语料合法性命中 gate（目标语言判定 + 字符检查）。当需要对 TTS 回流语料做准入、判断一行文本是否为目标语言/是否混入非拉丁脚本字符、或生成记录级 gate 标签（records.jsonl）时使用。输入只认 UTF-8 txt，输出 pass/warn/fail + 原因，标记不下车不删数据。
---

# gate_validity — 合法性 gate

## 触发
- 对话触发：`/gate-validity` （agent 挂载后可用）
- CLI 触发：`python skills/gate_validity/run.py --input input/INPUT.txt [--meta input/INPUT.meta.json] --out output/<run>/ --lang sw`

## 输入
- `INPUT.txt`：UTF-8，一行一条（需要保留原表字段时，由 ingest_xlsx.py 生成带列的 txt + meta.json）
- `INPUT.meta.json`：可选，声明列顺序/文本列/数值列

## 输出
- `records.jsonl`：行级 Row + `gate.lang` / `gate.charset`（每项 pass/warn/fail + reason）
- `dims/gate.json`：通过率统计

## 判定口径（对应 wiki「合法性」节）
- 语言：虚词表命中率 ≥0.15 优先，langdetect 1.0.9（seed=0）兜底 → 94.0% 行判斯语（可复现）
- 字符：regex `\p{Block=...}` 越界脚本分桶（<5% pass / 5–20% warn / ≥20% fail）；emoji 等噪声剥离不误杀，纯噪声行 warn
- fasttext 判斯语 64.2% 已弃用；不做 TN 格式转换（准入在工具集层）

## 边界
- 只负责判定与标记，不删行、不改文本内容
- 不读 xlsx/csv/json 直接入库——那属于 ingest/上游
