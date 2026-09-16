---
name: etymology-llm
description: 词源打标（外部模型服务 endpoint+API key，按句逐词判源，返回 word_id/word/origin JSON）。当需要给斯语语料的每个词打词源标签（bantu_native/arabic_loan/english_loan/other_loan/uncertain）或统计词源分布时使用。断点续跑，可 --mock 离线自测。
---

# etymology_llm — 词源打标（LLM）

## 触发
- `/etymology-llm` 或
  `python skills/etymology_llm/run.py --sentences output/<run>/sentences.jsonl --out output/<run>/`
- 离线自测：`--mock`（本地规则 mock，不依赖外网）
- 人工抽检：`--audit 100` 生成前 100 句 `etymology_audit.csv`

## 配置（2026-09-10 定稿：外部模型服务，非本地部署）
- 环境变量：`LLM_ENDPOINT`（base URL，OpenAI 兼容 `/chat/completions`）、`LLM_MODEL`（qwen3.6）、`LLM_API_KEY`
- key 只走环境变量，不入库；费用按 token 计，分批 + 断点续跑控制用量

## 质量保障
- word_id 与输入词序强校验（长度/顺序不一致 → 拒绝该批结果）
- 返回 JSON 容错：剥 markdown 围栏；解析失败重试 1 次 → 仍失败标 etym_fail 人工兜底
- 先 `--audit 100` 人工核对标签质量，再全量跑
