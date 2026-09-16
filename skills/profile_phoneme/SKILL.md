---
name: profile-phoneme
description: 音素分布画像（G2P：ipa-dict 查表→epitran 兜底→补丁，单字母/单音素/双音素）。当需要统计语料的音素覆盖、双音素长尾、或生成词→IPA 中间态时使用。输入 sentences.jsonl，输出 dims/phoneme.json + token_ipa.json。
---

# profile_phoneme — 音素分布（G2P）

## 触发
- `/profile-phoneme` 或 `python skills/profile_phoneme/run.py --sentences output/<run>/sentences.jsonl --out output/<run>/`

## G2P 定稿管线（对应 wiki「音素分布」节）
1. ipa-dict 查表优先（命中 80.8% token，零误差）
2. 未命中走 epitran（swa-Latn）
3. ng'/dh 已知差异打补丁（lang/<code>.yaml g2p.patch）
- 数字/缩写等非纯字母词跳过（TN 在工具集外，准入制）
- IPA 统一小写，前鼻化（ⁿ ᵐ ᶮ ᵑ ᶬ+后字）合并单音位，tʃ/dʒ 双字母按单音素

## 依赖
- `requirements-g2p.txt`（epitran 必装）；重环境可复用 g2p_lab/venv
