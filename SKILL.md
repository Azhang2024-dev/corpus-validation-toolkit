---
name: corpus-validation-toolkit
description: "TTS 回流语料「前置清洗 + 准入 gate + 维度画像 + 报告」工具集（corpus_kit 核心库 + 可编排 skills）。当需要对 TTS 回流语料做清洗（整段 dump 行边界重建/归一/去重，语言无关）、合法性 gate（语言+字符检查）、长度/句式/词汇/音素/词源分布画像，或生成保留原表字段的全字段 Excel/CSV + manifest 报告时使用；斯瓦西里语先行、多语种可扩展。输入只认 UTF-8 txt 一行一条；产物进 output/<run>/。命令须在本仓库根目录执行（clone 后即为 cwd），本文件是发布版、不含任何人的本机路径。"
---

# Corpus Validation Toolkit（语料验证工具集）

## 是什么
对 TTS 回流语料做「**前置清洗 → 准入 gate → 维度画像 → 报告**」：先把任意格式的上游数据（含行边界丢失的整段 dump）清洗成规范 txt，再判定语言/字符是否合格（**标记不下车，不删数据**），统计长度/句式/词汇/音素分布，词源用 LLM 批量打标，最后出保留原表字段的全字段报告（Excel+CSV+manifest.json，seed=0 可复现）。

## 什么时候用
- 拿到回流 xlsx/csv/**整段 dump txt**，要判断这批语料「分布合不合理、能不能拿去录音」
- 要先把格式不规范/有重复/行边界丢失的数据清洗成规范 txt
- 要按句切分、统计句式/词频/音素覆盖、筛查 NSW 非标词、标词源
- 要一份**带原表字段 + 全部验证维度**的 Excel 报告

## 快速命令（在工具集目录下跑）
```powershell
# 先确认当前目录 = 本仓库根目录（clone 出来的地方；下文以 <REPO> 代指）
# 若 agent 的 cwd 不在仓库里，先 cd 到仓库（例：cd $HOME\src\corpus-validation-toolkit）
cd <REPO>

# 0) 环境（一次性）：python -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements-all.txt

# 1) 接数据（二选一，都在验证管线之外）
#    A) 回流表 → INPUT.txt + meta
.\.venv\Scripts\python scripts\ingest_xlsx.py --xlsx 回流表.xlsx --text-col tts_text --out-dir input
#    B) 任意格式（整段 dump / txt / tsv / csv）→ 清洗 → INPUT.txt + 报告
.\.venv\Scripts\python scripts\prepare_input.py --input 原始文件 --lang sw --out-dir input_clean
#       先看效果：--dry-run（只出报告不写 INPUT.txt）；--no-dedup / --fuzzy 按需

# 2) 一键全流程（产物含词级明细：xlsx 词级明细 sheet + 数据集_词级明细.csv + 词级明细.jsonl）
.\.venv\Scripts\python run_pipeline.py --input input\INPUT.txt --meta input\INPUT.meta.json --lang sw --out output\run1
#   可选：--skip-g2p / --skip-etymology / --etymology-mock（离线自测）
#         --etymology-verify（只验证词源链路，不出真结果）/ --etymology-batch-size N / --limit N（开发）

# 3) 分步（每个 skill 可独立跑、可编排）
.\.venv\Scripts\python skills\gate_validity\run.py    --input input\INPUT.txt --meta input\INPUT.meta.json --out output\run1
.\.venv\Scripts\python skills\profile_length\run.py   --records output\run1\records.jsonl   --out output\run1
.\.venv\Scripts\python skills\profile_sentence\run.py --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_vocab\run.py    --records output\run1\records.jsonl --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_phoneme\run.py  --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\etymology_llm\run.py    --sentences output\run1\sentences.jsonl --out output\run1   # 需 LLM_ENDPOINT/KEY，或 --mock
```

## 前置清洗（prepare_input.py，语言无关）
- 五步：**记录边界重建**（整段 dump 按 CSV 引号规则还原成一行一条 + 内容守恒断言）→ 归一 → 质检 → 去重 → 落盘
- 产物：`INPUT.txt` + `INPUT.meta.json` + `clean_report.{json,csv}` + `quarantine.jsonl`（剔除项可回滚）+ `clean_manifest.json`
- **语言无关硬约束**：零词表，字符判定走 Unicode 属性（`\p{L}`/`\p{Nd}`），长度按字素簇 `\X`；由测试守卫防止退化成 Latin-only
- **只标记不轻删**：占比类异常记 soft（保留并记录），只有结构不成立（无字母/无词/空）才剔除
- 阈值在 `data/clean.yaml`（业界口径，出处见 `docs/语料清洗步骤调研_v1.md`）

## 词源 LLM（M5，唯一需外部配置的环节）
- 环境变量：`LLM_ENDPOINT` / `LLM_MODEL`（qwen3.6）/ `LLM_API_KEY` / `LLM_BATCH_SIZE`（默认 30）；key 不入库
- **全局词级去重**：整批词去重后按批判源，一个词只调用一次（调用数 = `ceil(unique_words / batch_size)`）
- 断点续跑（已打标词跳过）、word/origin 强校验；`--verify` 免 LLM 自检链路，`--audit N` 人工抽检

## 口径速记（详见仓库 docs/，此处不重复维护）
- 前置清洗：整段 dump 重建后内容签名守恒（实测 5,038 条 / 2,078,263 字符逐字节相等）；清洗后字母数零丢失
- gate：虚词表命中 ≥0.15 + langdetect(seed=0)；字符 Unicode Block 越界分桶（<5% pass / ≥20% fail）
- 长度：切句（31,561 句口径）；音节=拼写元音 aeiou（与 IPA 100% 一致）
- G2P：ipa-dict 查表(80.8%) → epitran(swa-Latn) → 补丁（requirements-g2p.txt，setuptools<81 必装）
- 音素：原始 46 / 归一 40 单音素（异写 g/ɡ、r/ɾ 归并 + 前鼻化拆分）；理论组合空间 345，**缺失组合清单**供选句补齐
- G2P 抽验：抽词典命中词比 epitran 兜底，折合表示层差异后一致率，阈值 0.95（实测 97.5%）
- 句式：四类占比 + 与目标配比差距告警
- 26 行脚本越界零漏检、94%+ 判斯语、全量 5038 行实测数字对齐（详见 README「关键口径」）

## 边界
- 只收 UTF-8 txt；xlsx→txt 走 `scripts/ingest_xlsx.py`，txt/dump/tsv/csv 的清洗走 `scripts/prepare_input.py`（**不做 TN 格式转换**），二者都在验证管线之外；`prepare_input.py` 不吃 xlsx（二进制）
- gate 只标记 pass/warn/fail + 原因，不自动删行；清洗层同样「只标记不轻删」（仅剔除结构上不成立的行，且逐条落 quarantine 可回滚）
- **多语种（通用架构，18 语内置）**：`data/script/<家族>.yaml`（9 族：latin/arabic/devanagari/bengali/gujarati/tamil/cyrillic/han/generic，语言无关的脚本级规则）+ `data/lang/<code>.yaml`（语言薄层：虚词/NSW/词典/G2P/音节/词源）。**新语言 = 只加 yaml，零代码**。
  `--lang auto` 按数据检测（判不出就报判不出）；`--lang` 与数据脚本强烈不符时报告标「⚠ 指令与数据不符」。
  每份报告含**「能力与口径」块**（用了什么资源 / 哪些没算 / 为什么 / 怎么才能算）；缺资源不静默借他语词典与 G2P。
- **批量**：`scripts/batch_verify.py --input <文件或目录> --out <dir>`——一文件一报告（**不合并**，保留测试集身份）+ `INDEX.md`（逐文件数字 + **跨文件同源检测**）。
- **已知限制**（逐条披露）：ur/bn/hi/mr/ta/ar 无 ipa-dict 级词典；ru 仅窄式；fil 用 tgl 代理；zh 字级 + 无空格分词；gu 无 epitran map（只查表）；ur/bn/hi/mr/ta/ar/zh 音节 N/A；**sw 全部历史口径已 pin（与改造前逐项对照 0 漂移）**。

## 参考
- README.md（安装/使用/触发第一入口）
- docs\语料验证工具集_架构设计_v1.md（架构/里程碑/§14 清洗模块）
- docs\语料清洗步骤调研_v1.md（七套业界管线 + KEEP/DROP 判定 + 出处）
- GitLab: internal-gitlab/corpus-validation-toolkit
