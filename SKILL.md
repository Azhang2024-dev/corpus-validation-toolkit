---
name: corpus-validation-toolkit
description: "TTS 回流语料「准入 gate + 维度画像 + 报告」工具集（corpus_kit 核心库 + 可编排 skills）。当需要对 TTS 回流语料做合法性 gate（语言+字符检查）、长度/句式/词汇/音素/词源分布画像，或生成保留原表字段的全字段 Excel/CSV + manifest 报告时使用；斯瓦西里语先行、多语种可扩展。输入只认 UTF-8 txt 一行一条；产物进 output/<run>/。项目即 GitLab 仓库 user/corpus-validation-toolkit，本地 checkout：D:/Users/admin/Desktop/My_Project/斯瓦西里语助手tts回流数据不含音频/语料验证工具集。"
---

# Corpus Validation Toolkit（语料验证工具集）

## 是什么
对 TTS 回流语料做「准入 gate → 维度画像 → 报告」：判定语言/字符是否合格（**标记不下车，不删数据**），统计长度/句式/词汇/音素分布，词源用 LLM 批量打标，最后出保留原表字段的全字段报告（Excel+CSV+manifest.json，seed=0 可复现）。

## 什么时候用
- 拿到回流 xlsx/csv，要判断这批语料「分布合不合理、能不能拿去录音」
- 要按句切分、统计句式/词频/音素覆盖、筛查 NSW 非标词、标词源
- 要一份**带原表字段 + 全部验证维度**的 Excel 报告

## 快速命令（在工具集目录下跑）
```powershell
cd D:/Users/admin/Desktop/My_Project/斯瓦西里语助手tts回流数据不含音频/语料验证工具集

# 0) 环境（一次性）：python -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements-all.txt

# 1) 回流表 → INPUT.txt + meta（只认 txt，转换在工具集外）
.\.venv\Scripts\python scripts\ingest_xlsx.py --xlsx 回流表.xlsx --text-col tts_text --out-dir input

# 2) 一键全流程
.\.venv\Scripts\python run_pipeline.py --input input\INPUT.txt --meta input\INPUT.meta.json --lang sw --out output\run1
#   可选：--skip-g2p / --skip-etymology / --etymology-mock（离线自测） / --limit N（开发）

# 3) 分步（每个 skill 可独立跑、可编排）
.\.venv\Scripts\python skills\gate_validity\run.py    --input input\INPUT.txt --meta input\INPUT.meta.json --out output\run1
.\.venv\Scripts\python skills\profile_length\run.py   --records output\run1\records.jsonl   --out output\run1
.\.venv\Scripts\python skills\profile_sentence\run.py --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_vocab\run.py    --records output\run1\records.jsonl --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_phoneme\run.py  --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\etymology_llm\run.py    --sentences output\run1\sentences.jsonl --out output\run1   # 需 LLM_ENDPOINT/KEY，或 --mock
```

## 词源 LLM（M5，唯一需外部配置的环节）
- 环境变量：`LLM_ENDPOINT` / `LLM_MODEL`（qwen3.6）/ `LLM_API_KEY`；key 不入库
- 断点续跑、按句逐词判源（word_id/word/origin 强校验）、先 `--audit 100` 人工抽检再全量

## 口径速记（详见仓库 docs/，此处不重复维护）
- gate：虚词表命中 ≥0.15 + langdetect(seed=0)；字符 Unicode Block 越界分桶（<5% pass / ≥20% fail）
- 长度：切句（31,561 句口径）；音节=拼写元音 aeiou（与 IPA 100% 一致）
- G2P：ipa-dict 查表(80.8%) → epitran(swa-Latn) → 补丁（requirements-g2p.txt，setuptools<81 必装）
- 26 行脚本越界零漏检、94%+ 判斯语、全量 5038 行实测数字对齐（详见 README「关键口径」）

## 边界
- 只收 UTF-8 txt；xlsx/csv/json 转换由 ingest_xlsx.py 或上游完成（**不做 TN 格式转换**）
- gate 只标记 pass/warn/fail + 原因，不自动删行
- 多语种：data/lang/<code>.yaml 缺失时逐项降级（口径标 degraded）

## 参考
- README.md（安装/使用/触发第一入口）
- docs\语料验证工具集_架构设计_v1.md（架构/里程碑）
- GitLab: internal-gitlab/corpus-validation-toolkit
