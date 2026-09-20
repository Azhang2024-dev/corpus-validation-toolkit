# 发音词典与语言资源来源（data/ipa/ · data/syll/）

> 本目录所有词典均由 `scripts/fetch_dicts.py` 拉取并规范化（可复现）。
> 规范格式：`词<TAB>IPA`（小写；无斜杠包裹；一词多发音取首条）。
> 逐条来源/条数/校验和见 `data/ipa/_sources.json`。

## 一、来源与许可

| 来源 | 许可 | 用途 | 说明 |
|---|---|---|---|
| [ipa-dict](https://github.com/open-dict-data/ipa-dict) | **MIT** | sw / fr / en / es / pt / zh | 格式与工具集原生一致（`词\t/IPA/`） |
| [WikiPron](https://github.com/CUNY-CL/wikipron) | 代码 **Apache-2.0**；数据按 Wiktionary 条款（**CC BY-SA 系**） | 其余 14 语种 | 需署名 + 相同方式共享（见下方声明） |
| [Lexique383](http://www.lexique.org/) | **CC BY-SA 4.0** | 法语音节数（`data/syll/fr.txt`） | 从 `Lexique383.tsv` 提取 `ortho → nbsyll` |

**CC BY-SA 声明**：`data/ipa/` 下由 WikiPron 生成的词表（ar/bn/gu/ha/hi/id/mr/ru/ta/te/tr/ur/fil）
与 `data/syll/fr.txt`（Lexique383）在 CC BY-SA 条款下提供，署名见上表；再分发需保持相同许可。
`data/ipa/sw.txt`（含 fr/en/es/pt/zh）为 ipa-dict（MIT），不受该义务约束。

## 二、逐语种清单（当前版本）

| 语种 | 文件 | 来源 / 远端名 | 条数 | 备注 |
|---|---|---|---:|---|
| sw | `sw.txt` | ipa-dict `sw` | 48,308 | 原有；g2p 命中率 80.8%（历史口径） |
| fr | `fr.txt` | ipa-dict `fr_FR` | 245,972 | 另有 `syll/fr.txt`（Lexique383，125,653 词形） |
| en | `en.txt` | ipa-dict `en_US` | 125,927 | 美式 |
| es | `es.txt` | ipa-dict `es_ES` | 595,896 | 卡斯蒂利亚 |
| pt | `pt.txt` | ipa-dict `pt_BR` | 95,933 | 巴西葡语（与语料口径一致） |
| zh | `zh.txt` | ipa-dict `zh_hans` | 44,780 | 汉-字/词级；**汉字→拼音→IPA 链路未内置**，G2P 只查表 |
| ar | `ar.txt` | WikiPron `ara_arab_broad` | 14,272 | 宽式；多发音/重复 3,291 次已取首条 |
| ur | `ur.txt` | WikiPron `urd_arab_broad` | 6,296 | 宽式；规模有限（无 ipa-dict 级词典） |
| hi | `hi.txt` | WikiPron `hin_deva_broad` | 30,379 | 宽式 |
| mr | `mr.txt` | WikiPron `mar_deva_broad` | 4,269 | 宽式 |
| bn | `bn.txt` | WikiPron `ben_beng_dhaka_broad` | 6,513 | **达卡方言**（与语料来源地区一致，口径已声明） |
| gu | `gu.txt` | WikiPron `guj_gujr_broad` | 4,086 | 宽式；**epitran 无 guj-Gujr map** → 无 G2P 兜底 |
| ta | `ta.txt` | WikiPron `tam_taml_broad` | 10,095 | 宽式 |
| te | `te.txt` | WikiPron `tel_telu_broad` | 5,110 | 备用（上游语料为空） |
| ru | `ru.txt` | WikiPron `rus_cyrl_narrow` | 403,873 | **仅窄式**（WikiPron 无宽式，口径限制） |
| tr | `tr.txt` | WikiPron `tur_latn_broad` | 11,582 | 宽式 |
| ha | `ha.txt` | WikiPron `hau_latn_broad` | 1,857 | 宽式；规模小 |
| fil | `fil.txt` | WikiPron `tgl_latn_broad` | 25,861 | **以塔加洛（tl）代理**（WikiPron 无 fil 条目） |

## 三、已知限制（逐条如实披露，不隐藏）

1. **ur/bn/hi/mr/ta/ar 无 ipa-dict 级词典**：WikiPron 规模 4k–30k，覆盖率有限；
   「查表 + epitran 兜底」在这几语会更多依赖兜底路径，报告 `dict_hit_ratio` 会体现。
2. **ru 仅窄式（narrow）转写**：与宽式口径不可直接比；如需宽式需换来源（当前无干净替代）。
3. **fil 用 tgl 代理**：塔加洛与菲律宾语互为标准语/变体，词形高度重合但非完全相同。
4. **zh 为字级词典**：仅覆盖词典条目；未内置汉字→拼音转换，未命中词无 IPA（报告披露）。
5. **gu 无 G2P 兜底**：epitran 缺失该 map（约 128 个 map 中无 guj-Gujr）→ 只查表。
6. **方言选择**：bn 用达卡（Dhaka）方言；WikiPron 另有 Rarh 变体，**已在语言配置声明选择**，
   两套不可混用。

## 四、复现方式

```bash
python scripts/fetch_dicts.py            # 拉取全部并规范化（网络可达时）
python scripts/fetch_dicts.py --check    # 只检查现状，不联网
python scripts/fetch_dicts.py --only fr ur   # 只拉指定语种
```

下载通道：`cdn.jsdelivr.net`（GitHub 仓库 CDN）；>20MB 文件（如 ru）自动改走
`raw.githubusercontent.com`（Windows schannel 需 `--ssl-no-revoke`，脚本已处理）。