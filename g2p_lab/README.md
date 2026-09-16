# g2p_lab — G2P 对照实验室（仓库内：脚本 + requirements 入库；重环境不入库）

> 用途：G2P 定稿的依据（ipa-dict 查表 → epitran 兜底 → 补丁）。
> 本文档对应在线文档《TTS文本设计指南》G2P 调研与实测：四工具对照 epitran 编辑距离 0.50 最优
> （phonemizer 1.29 / transphone 1.00 / espeak 5.50），故工具集 profile_phoneme 只用 epitran 兜底。

## 仓库内包含
```
g2p_lab/
├── _g2p_compare.py      # 四工具对照（ipa-dict 为金标准，算平均编辑距离）
├── g2p_live_test.py     # 五工具实测（espeak-ng/phonemizer/epitran/g2p_en/gruut）
├── transphone_test.py   # transphone 三语（swa/eng/hau）实测
└── requirements.txt     # 全量对照环境（含 torch/transphone ≈600MB，仅复现实验时装）
```

## 不随仓库走（体积 1.3GB+，在 .gitignore 语义之外由 git 排除）
- `venv/`（Python 3.13 + 全部依赖）
- `espeak-ng/`（便携 exe + dll + 语音数据）
- `nltk_data/`
需要复现对照实验时：从共享目录 `..\g2p_lab\`（项目根的同名旧环境）拷 venv/espeak-ng/nltk_data 过来，
或在本目录用 requirements.txt 重建环境（espeak-ng 用便携版）。

## 与工具集的关系
- 词典：`_g2p_compare.py` 读 `../data/ipa/sw.txt`（ipa-dict 48,308 条）
- 工具集正式管线只依赖 `requirements-g2p.txt` 的必装部分（epitran + setuptools<81）
