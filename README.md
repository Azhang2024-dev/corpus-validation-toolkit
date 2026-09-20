# 语料验证工具集（corpus_validation_toolkit）

TTS 回流语料「准入 gate + 维度画像 + 报告」工具集：斯瓦西里语（sw）先行，多语种可扩展。
形态：**一个共享核心库 corpus_kit + 可编排 skills（薄壳）**，可被 agent 按需调用，也可命令行一键跑通。
本仓库为可移植 tip 快照；clone 本仓库即可使用。

## 它解决什么
回流数据不能直接用：先过「合法性 gate」（语言 + 字符），再做长度/句式/词汇/音素/词源维度画像，
最后出**保留原表字段**的全字段报告（Excel/CSV + manifest.json），判断这批语料分布是否合理、能不能拿去录音。

## 用法 A：Agent 会话（推荐，对话即用）

1) **先把仓库 clone 到本机**（安装脚本要在这里跑；示例目录可自行替换）：

```powershell
git clone <this-repo-url> "$HOME\src\corpus-validation-toolkit"
cd "$HOME\src\corpus-validation-toolkit"
```

2) **装到 agent 的 skills 目录**（脚本会把 checkout 路径填进副本）：

> 仓库里的 `SKILL.md` 是**唯一真源，也是唯一发布物**——命令用 `<REPO>` 占位，**不含任何人的本机绝对路径**，clone 到哪都能直接读、直接用。
> 装到 `$HOME\.agents\skills\` / `$HOME\.codex\skills\` 的副本 = 发布版 + **一次确定性的 `<REPO>` → 本机 checkout 路径替换**，除此之外不允许有任何差异。**副本不要手工编辑**（改了就会和发布版漂移）。

```powershell
python scripts\deploy_skill.py            # 部署到 ~/.agents/skills 与 ~/.codex/skills
python scripts\deploy_skill.py --check     # 只校验：不一致返回非 0，并指出差在哪一行
```

改了仓库里的 `SKILL.md` 后重跑一次即可对齐；`tests/test_skill_portable.py` 会像 CI 一样把三件事钉住：**模板可移植**（无本机路径、fresh clone 可用）、**实例化只做一次替换**（幂等、除占位行外逐字符相同）、**本机副本没漂移**。

3) 新会话里说人话即触发：

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

### 2. 接数据（先清洗，再验证；工具集只认 UTF-8 txt）

上游格式不可预期。两种入口，都在验证管线之外：

```powershell
# A) 回流表 xlsx → INPUT.txt（原表字段透传）
.\.venv\Scripts\python scripts\ingest_xlsx.py --xlsx 回流表.xlsx --text-col tts_text --out-dir input

# B) 任意格式 → 清洗 → INPUT.txt（整段 dump / txt / tsv / csv）
.\.venv\Scripts\python scripts\prepare_input.py --input 原始文件 --lang sw --out-dir input_clean
# 先看效果再落盘：加 --dry-run（只出报告，不写 INPUT.txt）
# 关掉去重：--no-dedup；启用模糊近重：--fuzzy
# 产物：INPUT.txt + INPUT.meta.json + clean_report.{json,csv} + quarantine.jsonl + clean_manifest.json
```

`prepare_input` 做五步：**记录边界重建**（整段 dump 按 CSV 引号规则还原成一行一条）→ 文本归一 → 质检 → 去重 → 落盘。
语言无关（`\p{L}`/`\p{Nd}`/字素簇，零词表），阈值在 `data/clean.yaml`，来源见 `docs/语料清洗步骤调研_v1.md`。
**只标记不轻删**：占比类异常记为 soft（保留并记录），只有结构不成立（无字母/无词/空）才剔除；剔除项逐条写 `quarantine.jsonl` 可回滚。

### 3. 一键全流程

```powershell
.\.venv\Scripts\python run_pipeline.py --input input\INPUT.txt --meta input\INPUT.meta.json --lang sw --out output\run1
# 可选：--skip-g2p / --skip-etymology / --etymology-mock（词源离线自测）
#       --etymology-verify（只验证词源链路不变量，不出真结果）/ --etymology-batch-size N / --limit N（先跑前 N 行调试）
# 产物：output\run1\数据集_全字段.xlsx（含词级明细 sheet）+ .csv + 数据集_词级明细.csv + 词级明细.jsonl + manifest.json + 中间态 jsonl
```

### 4. 分步执行（可编排，供 agent / MCP 按需组合）

```powershell
.\.venv\Scripts\python skills\pipeline\run.py --input input\INPUT.txt --meta input\INPUT.meta.json --out output\run1   # 编排入口，等价一键
.\.venv\Scripts\python skills\gate_validity\run.py    --input input\INPUT.txt --meta input\INPUT.meta.json --out output\run1
.\.venv\Scripts\python skills\profile_length\run.py   --records output\run1\records.jsonl   --out output\run1
.\.venv\Scripts\python skills\profile_sentence\run.py --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_vocab\run.py    --records output\run1\records.jsonl --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\profile_phoneme\run.py  --sentences output\run1\sentences.jsonl --out output\run1
.\.venv\Scripts\python skills\etymology_llm\run.py    --sentences output\run1\sentences.jsonl --out output\run1   # 需 LLM_ENDPOINT/KEY，或 --mock；--verify 免 LLM 自检
.\.venv\Scripts\python -m corpus_kit.report            --out output\run1   # meta 自动回退 input_meta.json
```

## 词源 LLM（唯一需外部配置的环节）

- 环境变量：`LLM_ENDPOINT` / `LLM_MODEL`（qwen3.6）/ `LLM_API_KEY` / `LLM_BATCH_SIZE`（默认 30）（key 不入库，模板见 `.env.example`）
- **全局词级去重**：整批词去重后按批判源，一个词只调用一次；调用数 = `ceil(unique_words / batch_size)`（旧「按句逐词」已废弃）
- 断点续跑（已打标词跳过）、返回 JSON 强校验（word/origin）；先 `--verify` 验链路、`--audit N` 人工抽检，再全量

## 目录

```
README.md / SKILL.md            README 人看；SKILL.md 是 agent 入口安装源
run_pipeline.py                 一键全流程编排
requirements-{core,g2p,all}.txt 依赖分级
.env.example                    LLM 环境变量模板（真 key 不入库）
corpus_kit/                     核心库（config[两级]/detect[探测]/io/segment/tokenize/lang/charset/g2p/phonemes/stats/report/reconstruct/clean）
skills/                         7 个 skill（SKILL.md + run.py）：pipeline/gate_validity/profile_length/profile_sentence/profile_vocab/profile_phoneme/etymology_llm
data/                           script/<家族>.yaml（9 个脚本族）+ lang/<code>.yaml（18 语）+ ipa/<code>.txt（19 语词典，见 ipa/SOURCES.md）+ syll/fr.txt + clean.yaml
scripts/                        ingest_xlsx.py（xlsx→txt）+ prepare_input.py（清洗）+ batch_verify.py（批量逐文件）+ fetch_dicts.py（词典获取）+ deploy_skill.py
tests/                          回归测试（168 条：词级口径/清洗/静默丢失/多语种 test_multilang.py）
docs/                           架构设计 + 维度框架 + 清洁步骤调研 + 交付物呈现 / 多语种扩展调研
input/  output/                 输入 / 产物（不入库）
g2p_lab/                        G2P 对照实验室脚本（重环境 venv/espeak-ng 不入库）
```

## 关键口径（详见在线文档《TTS文本设计指南》+ docs/）

- **前置清洗**（`prepare_input.py`，语言无关）：记录边界重建（整段 dump 按 CSV 引号规则）→ 归一 → 质检 → 去重；实测 `TTS_TEXT_SWAHILI.txt` 物理行 21,140 → 逻辑记录 5,038，**内容签名守恒**（2,078,263 字符逐字节相等），清洗后字母数零丢失；去重 596、硬剔除 0
- 输入只认 UTF-8 txt，一行一条；xlsx→txt 由 ingest 或上游完成（TN 前置已否决，验证层做准入）
- gate：虚词表命中率 ≥0.15 + langdetect(seed=0) 双保险 → 判斯语 94%+（全量 5038 行实测 94.8%）；字符 Unicode Block 越界分桶（<5% pass / 5–20% warn / ≥20% fail）
- 长度：切句（31,561 句口径）后统计单句字符/词/音节；音节=拼写元音 aeiou（与 IPA 100% 一致），不做开/闭音节切分
- 句式：疑问（? 或疑问词开头）/ 感叹（!）/ 陈述 / 短语（无标点且 <5 词）；60 句人工抽检已通过；**与目标配比（陈述 70–80% 等）差距自动告警**
- 词汇：37.2 万 token / 2.48 万型符；H_norm 0.72、Gini 0.87、Top10% 占 85.2%；ipa-dict 命中 80.8%、虚词 28.9%、英语 ≈1.7%
- G2P：ipa-dict 查表（80.8%）→ epitran(swa-Latn) 兜底 → 补丁；词级基线 40 个音素（归一后；异写 g/ɡ、r/ɾ 归并 + 前鼻化拆分）
- 音素组合：理论空间（CV/VC/VV/鼻音丛/C+滑音）345 个，**缺失组合清单**供选句贪心补齐；语料外的外来丛单列（越界）
- G2P 抽验：随机抽词典命中词，比 epitran 兜底三档一致率（完全/归一/折合表示层），阈值 0.95；实测折合后 97.5%（差异主要来自 `ŋg` vs `ng` 等书写约定）
- 词源：外部模型服务（qwen3.6），**全局词级去重**后逐词判源，断点续跑；`--verify` 免 LLM 自检链路
- 报告保留回流表头字段，新增字段有「字段说明」子表；**词级明细**（每词 IPA/音素/词源/频次）在 `词级明细` sheet + `数据集_词级明细.csv` + `词级明细.jsonl`，句子级明细另加 inline `词级明细` 列
- 另附专题 sheet：`音素组合` / `缺失组合`（选句补齐候选）/ `G2P抽验`（音素数字可信度门槛）
- `manifest.json` 记录输入哈希与**本次实际参数**（`run_args`：`--limit` / `--skip-g2p` / `--skip-etymology` / `--audit-n` 等），seed=0 可复现——没记参数时 `--limit` 批次与全量跑在产物上无法区分

## 多语言（通用架构：家族层 + 语言薄层 + 检测层）

**设计目标：给什么处理什么；处理不了、或指令与数据不符，就诚实报出来。**

- **两级配置**：
  - `data/script/<family>.yaml` —— **脚本家族层**（语言无关）：token 正则、核心字符、越界块目录、
    句末标点、引号对、G2P 词形判据等。9 个家族：`latin / arabic / devanagari / bengali / gujarati /
    tamil / cyrillic / han / generic`（generic 兜底任意未建家族的文字）。
  - `data/lang/<code>.yaml` —— **语言薄层**：虚词表、疑问词、NSW 正则、词典路径、G2P 兜底码、
    音节口径、词源候选。**18 个语种已内置**：`ar bn en es fil fr gu ha hi id mr pt ru sw ta tr ur zh`。
- **新语言上线 = 零代码**：家族已有 → 只加语言 yaml；新文字体系 → 加一个家族 yaml。
- **检测层**（`corpus_kit/detect.py`）：脚本探测 + langdetect + **`--lang auto`**；
  若你指定的 `--lang` 与数据主脚本强烈不符（如给 ur 指令却喂了拉丁文本），
  报告会标 **`⚠ 指令与数据不符`** 请你核对，不按错的指令静默跑完。
- **能力与口径块**：每份报告的「维度分布」sheet 第一块就写明——本次用了什么家族/词典/G2P、
  各维度口径、**哪些没算和为什么、怎么才能算**（如「无发音词典」「音节口径未定稿」「无虚词表仅 LID」）。
- **绝不静默借他语资源**：缺词典/缺配置时不再回落 sw 词典与 `swa-Latn`；`resources_ok` 只认本语言资源。

### 发音词典与音节数据

`data/ipa/<lang>.txt`（19 语）+ `data/syll/fr.txt`（法语音节，Lexique383）。
来源与许可逐条见 **`data/ipa/SOURCES.md`**（ipa-dict = MIT；WikiPron = 数据按 CC BY-SA 系；
Lexique383 = CC BY-SA 4.0）。可复现下载：`python scripts/fetch_dicts.py`（`--check` 只查不联网）。

### 批量验证（不合并，逐文件报告）

```powershell
# 一个文件 → 一份报告；一个目录 → 每文件一份报告 + INDEX.md
.\.venv\Scripts\python scripts\batch_verify.py --input <文件或目录> --out output\testset_all
# --lang auto（默认）/ --only fr ur bn / --skip-g2p / --audit-n N
```

索引包含逐文件的行数/句数/gate/词典命中/G2P 未覆盖/音节口径/能力缺口，
并自动检测**跨文件同源**（如某测试集的三份文件共用同一文本池、kathbath 类复刻结构）。

### 已知限制（逐条披露，不隐藏）

| 语种/项 | 限制 |
|---|---|
| ur/bn/hi/mr/ta/ar | 无 ipa-dict 级词典（WikiPron 4k–30k，覆盖率有限） |
| ru | 词典仅窄式（narrow）转写 |
| fil | 以塔加洛（tl）代理 |
| zh | 字级词典 + 无空格分词（token=单字）；无汉字→拼音链路 |
| gu | epitran 无该 map → G2P 只查表无兜底 |
| ur/bn/hi/mr/ta/ar/zh | 音节置 N/A（正字法/合体字使字符层算不准，口径待定稿） |
| sw | **全部历史口径已 pin**（token/核心字符/句末标点/音素切分），保证历史报告可逐项复现 |

sw 为第一优先语种（历史基线零漂移，已与改造前逐项对照验证）。
