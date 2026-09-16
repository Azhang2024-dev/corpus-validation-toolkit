# 语料验证工具集（corpus_validation_toolkit）

TTS 回流语料「准入 gate + 维度画像 + 报告」工具集：斯瓦西里语（sw）先行，多语种可扩展。
形态：**一个共享核心库 corpus_kit + 可编排 skills（薄壳）**，可被 agent 按需调用，也可命令行一键跑通。
GitLab：<internal-gitlab/corpus-validation-toolkit>

## 它解决什么
回流数据不能直接用：先过「合法性 gate」（语言 + 字符），再做长度/句式/词汇/音素/词源维度画像，
最后出**保留原表字段**的全字段报告（Excel/CSV + manifest.json），判断这批语料分布是否合理、能不能拿去录音。

## 用法 A：Agent 会话（推荐，对话即用）

1) 安装一次（复制仓库根 `SKILL.md` 到 agent skills 目录）：

```powershell
New-Item -ItemType Directory -Force "$HOME\.agents\skills\corpus-validation-toolkit" | Out-Null
Copy-Item SKILL.md "$HOME\.agents\skills\corpus-validation-toolkit\SKILL.md"
Copy-Item SKILL.md "$HOME\.codex\skills\corpus-validation-toolkit\SKILL.md"
```

2) 新会话里说人话即触发：

- 「用语料验证工具集跑一下 `input/INPUT.txt`，出全字段报告（跳过词源）」
- 或直接 `/corpus-validation-toolkit`

agent 会按 SKILL.md 里的命令自动完成「接数据 → 一键/分步 → 报告」；分步跑也是同一条链路，按需组合即可。

## 用法 B：命令行（不依赖 agent）

### 1. 环境安装（Python 3.12+）

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-all.txt   # 核心 + G2P(epitran)
# 只跑纯规则部分：requirements-core.txt
# 注意：G2P 需 epitran，见 requirements-g2p.txt（epitran 依赖 setuptools>=68,<81，新环境必装）
```

### 2. 接数据（回流表 xlsx → INPUT.txt；工具集只认 UTF-8 txt）

```powershell
.\.venv\Scripts\python scripts\ingest_xlsx.py --xlsx 回流表.xlsx --text-col tts_text --out-dir input
# 产物：input\INPUT.txt + input\INPUT.meta.json
```

### 3. 一键全流程

```powershell
.\.venv\Scripts\python run_pipeline.py --input input\INPUT.txt --meta input\INPUT.meta.json --lang sw --out output\run1
# 可选：--skip-g2p / --skip-etymology / --etymology-mock（词源离线自测）/ --limit N（先跑前 N 行调试）
# 产物：output\run1\数据集_全字段.xlsx + .csv + manifest.json + 中间态 jsonl
```

### 4. 分步执行（可编排，供 agent / MCP 按需组合）

```powershell
.\.venv\Scripts\python skills\pipeline\run.py --input input\INPUT.txt --meta input\INPUT.meta.json --out output\run1   # 编排入口，等价一键
.\.venv\Scripts\python skills\gate_validity\run.py    --input input\INPUT.txt --meta input\INPUT.meta.json --out output\run1
.\.venv\Scripts\python skills\profile_length\run.py   --records output\run1\records.jsonl   --out output\run1
.\.venv\Scripts\python skills\profile_sentence\run.py --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_vocab\run.py    --records output\run1\records.jsonl --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_phoneme\run.py  --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\etymology_llm\run.py    --sentences output\run1\sentences.jsonl --out output\run1   # 需 LLM_ENDPOINT/KEY，或 --mock
.\.venv\Scripts\python -m corpus_kit.report            --out output\run1   # meta 自动回退 input_meta.json
```

## 词源 LLM（唯一需外部配置的环节）

- 环境变量：`LLM_ENDPOINT` / `LLM_MODEL`（qwen3.6）/ `LLM_API_KEY`（key 不入库，模板见 `.env.example`）
- 断点续跑、返回 JSON 强校验（word_id/word/origin）；先 `--audit 100` 人工抽检再全量

## 目录

```
README.md / SKILL.md            README 人看；SKILL.md 是 agent 入口安装源
run_pipeline.py                 一键全流程编排
requirements-{core,g2p,all}.txt 依赖分级
.env.example                    LLM 环境变量模板（真 key 不入库）
corpus_kit/                     核心库（纯逻辑：config/io/segment/tokenize/lang/charset/g2p/phonemes/stats/report）
skills/                         7 个 skill（SKILL.md + run.py）：pipeline/gate_validity/profile_length/profile_sentence/profile_vocab/profile_phoneme/etymology_llm
data/                           lang/sw.yaml（虚词表/NSW/疑问词/字符块/G2P 配置）+ ipa/sw.txt（ipa-dict 48,308 条）
scripts/                        ingest_xlsx.py（回流表→txt，不在验证管线内）
tests/                          回归测试（21 条）
docs/                           《语料验证工具集_架构设计_v1》+《语料合理性验证维度框架_v1》
input/  output/                 输入 / 产物（不入库）
g2p_lab/                        G2P 对照实验室脚本（重环境 venv/espeak-ng 不入库）
```

## 关键口径（详见在线文档《TTS文本设计指南》+ docs/）

- 输入只认 UTF-8 txt，一行一条；xlsx→txt 由 ingest 或上游完成（TN 前置已否决，验证层做准入）
- gate：虚词表命中率 ≥0.15 + langdetect(seed=0) 双保险 → 判斯语 94%+（全量 5038 行实测 94.8%）；字符 Unicode Block 越界分桶（<5% pass / 5–20% warn / ≥20% fail）
- 长度：切句（31,561 句口径）后统计单句字符/词/音节；音节=拼写元音 aeiou（与 IPA 100% 一致），不做开/闭音节切分
- 句式：疑问（? 或疑问词开头）/ 感叹（!）/ 陈述 / 短语（无标点且 <5 词）；60 句人工抽检已通过
- 词汇：37.2 万 token / 2.48 万型符；H_norm 0.72、Gini 0.87、Top10% 占 85.2%；ipa-dict 命中 80.8%、虚词 28.9%、英语 ≈1.7%
- G2P：ipa-dict 查表（80.8%）→ epitran(swa-Latn) 兜底 → 补丁；词级基线 40 个音素
- 词源：外部模型服务（qwen3.6），逐词判源，断点续跑
- 报告保留回流表头字段，新增字段有「字段说明」子表；manifest.json 记录输入哈希与参数，seed=0 可复现

## 多语言

`data/lang/<code>.yaml` 缺失时逐项降级（字符通用检查 / langdetect 无虚词表 / epitran 兜底），
降级语种报告会标注口径=degraded。sw 为第一优先语种。
