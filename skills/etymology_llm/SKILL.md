---
name: etymology-llm
description: 词源打标（外部模型服务 endpoint+API key，全局词级去重后按批判源，返回 word/origin JSON）。当需要给斯语语料的每个词打词源标签（bantu_native/arabic_loan/english_loan/other_loan/uncertain）或统计词源分布时使用。断点续跑，可 --mock 离线自测、--verify 免 LLM 自检链路。
---

# etymology_llm — 词源打标（LLM，全局词级去重）

## 触发
- `/etymology-llm` 或
  `python skills/etymology_llm/run.py --sentences output/<run>/sentences.jsonl --out output/<run>/`
- 离线自测：`--mock`（本地规则 mock，不依赖外网）
- **链路自检：`--verify`**（不需真 LLM：验证去重生效 / 全覆盖 / 续跑幂等，写 `dims/etymology.json`）
- 人工抽检：`--audit 100` 生成前 100 个词的 `etymology_audit.csv`

## 口径（2026-09-16 定稿：全局词级去重）
- 先把全批 `sentences.jsonl` 的 token 汇总、**去重**成词表（仅保留含字母的词），只对**未打标**的词分批调用。
- 一个词只判一次（旧「按句逐词」口径对同词重复调用，已废弃）。
- 调用数 = `ceil(unique_words / batch_size)`，而非句数；实测全量 unique≈2.4 万，
  按 `--batch-size 50` 约 500 次，而不是 3.1 万次。
- 确定性顺序（频次降序、同频字典序）+ 断点续跑（已打标词跳过），保证 `--limit` 可复现。

## 产物
| 文件 | 内容 |
|---|---|
| `etymology.jsonl` | 词级，一行一个词：`{word, origin, ts}` |
| `dims/etymology.json` | 聚合：`unique_words`/`tagged`/`untagged`/`failed`/`calls`/`batch_size`，`origin`（token 加权）+ `origin_words`（型符）；`--verify` 时含 `verify`/`verify_detail` |

## 配置（外部模型服务，非本地部署）
- 环境变量：`LLM_ENDPOINT`（base URL，OpenAI 兼容 `/chat/completions`）、`LLM_MODEL`（qwen3.6）、`LLM_API_KEY`、`LLM_BATCH_SIZE`（默认 30）
- key 只走环境变量，不入库；费用按 token 计，分批 + 断点续跑控制用量

## 质量保障
- 词键校验：返回词集必须与请求词集完全一致（忽略顺序）+ origin 合法，否则拒绝该批
- 返回 JSON 容错：剥 markdown 围栏；解析失败重试 1 次 → 仍失败计入 `failed`
- 先 `--verify` 确认链路，再 `--audit 100` 人工核对标签质量，最后全量跑

## 与报告的关系
报告层（`corpus_kit/report.py`）会把 `etymology.jsonl`（词→词源）与 `token_ipa.json`（词→IPA）
join 进交付物：句子级明细的 `词级明细` 列、`词级明细` sheet、`数据集_词级明细.csv` / `词级明细.jsonl`。
因此**即便 `--skip-etymology`，词级明细表仍会出**（词源列留空），IPA 与音素不受影响。