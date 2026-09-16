---
name: profile-length
description: 语料长度分布画像（含切句）。当需要把整段回流文本切成单句、统计单句字符数/词数/音节数分布、生成 sentences.jsonl 中间态时使用。输入 records.jsonl，输出按句的中间态句子文件 + dims/length.json。
---

# profile_length — 长度分布（含切句）

## 触发
- `/profile-length` 或 `python skills/profile_length/run.py --records output/<run>/records.jsonl --out output/<run>/`

## 输入/输出
- 输入 `records.jsonl`（gate_validity 产物）
- 输出 `sentences.jsonl`（sent_id → row_id 可追溯，含 n_chars/n_words/n_syllables/tokens）+ `dims/length.json`

## 口径
- 切句：换行 + 句末 .!? + 引号闭合保护（对齐 31,561 句实测口径）
- 音节：数拼写元音 aeiou（斯语一元音=一音节核；实测 ipa-dict 4.8 万词拼写元音与 IPA 音位数 100% 一致），不做开/闭音节切分
- 词数：空白切词（斯语词边界天然是空格）
