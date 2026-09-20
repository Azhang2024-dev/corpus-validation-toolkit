"""回归测试：语料清洗（reconstruct 边界重建 + clean 归一/质检/去重）。
运行：python -m unittest discover -s tests -v

重点覆盖三件事：
1. 记录边界重建（dump / txt / tsv）与内容守恒断言；
2. **语言无关性**——非拉丁语料（阿/天城/西里尔/泰）不被误杀，且源码不含 Latin-only 字符类；
3. 不轻删——占比类 flag 只记录（soft），只有结构不成立（hard）才剔除。
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corpus_kit.clean import (clean_config, clean_records, dedup_key,
                             dedup_exact, has_hard_flag, normalize_text,
                             quality_flags, summarize)
from corpus_kit.reconstruct import (detect_format, reconstruct, split_dump,
                                    split_plain, split_tsv)

PY = sys.executable
FIXTURE = ROOT / "tests" / "fixtures" / "sample_dump.txt"
CFG = clean_config()


class TestReconstruct(unittest.TestCase):
    def test_detect_dump_vs_txt(self):
        dump = '"Habari za leo. Ni nzuri."\n"Tuna paka wawili."\n"Pili."\n'
        self.assertEqual(detect_format(dump), "dump")
        self.assertEqual(detect_format("Habari za leo\nNina paka wawili\nNi vizuri\n", "auto"), "txt")

    def test_detect_multiline_dump(self):
        """多行 dump：只有每条记录首行以引号开头，占比判据会漏检（回归）。

        实测 TTS_TEXT_SWAHILI.txt 21,140 非空行中仅 7,187 行以引号开头（0.34），
        故必须按「引号解析出的记录数 < 物理行数」判，而不是按开头占比。
        """
        text = '"Habari za leo.\nNi nzuri.\n\nSana."\n"Pili."\n"Tatu."\n'
        self.assertEqual(detect_format(text), "dump")

    def test_comma_prose_is_not_csv(self):
        """散文里逗号数量随机，不应被判成 csv（回归）。"""
        prose = ("Habari za leo, ni nzuri sana.\n"
                 "Nina paka, mbwa, na kuku wengi.\n"
                 "Ni vizuri, kweli, sana.\n")
        self.assertEqual(detect_format(prose), "txt")

    def test_stable_columns_are_csv(self):
        self.assertEqual(detect_format("a,b,c\n1,2,3\n4,5,6\n"), "csv")

    def test_multiline_quoted_csv_detected_and_column_selected(self):
        """回归：多列 csv、文本列含多行引号单元格——不得误判 dump（P3-10）。

        误判 dump 会按单列逗号拼串，丢掉选列语义（`--text-col` 对 csv 形同虚设）。
        注：工具集契约是「INPUT.txt 无表头」（ingest 已跳过 xlsx 表头），故此处不带表头行。
        """
        text = '1,"m",plain\n2,"m","line1\nline2"\n'
        self.assertEqual(detect_format(text), "csv")
        recs = reconstruct(text, text_col=-1).records
        self.assertEqual(recs, ["plain", "line1\nline2"])       # 取最后一列（文本列）
        recs0 = reconstruct(text, text_col=0).records
        self.assertEqual(recs0, ["1", "2"])                     # 指定列生效

    def test_dump_not_misdetected_as_csv(self):
        """回归：真 dump（记录被引号包裹、单列）不得被判成 csv（探测顺序改动的守约）。"""
        dump = '"Habari za leo.\n\nNi nzuri."\n"Pili."\n'
        self.assertEqual(detect_format(dump), "dump")
        self.assertEqual(len(reconstruct(dump).records), 2)

    def test_csv_json_cell_decoded(self):
        """csv 单元格 json 还原：与 tsv 同契约（`null`→空、数字→原样）。"""
        text = 'a,null\nb,"x"\n'
        recs = reconstruct(text, text_col=-1).records
        self.assertEqual(recs, ["", "x"])

    def test_dump_multiline_record(self):
        # 记录跨物理行：引号层必须把它们合成一条
        text = '"Habari za leo.\n\nNina paka."\n"Sentensi ya pili."\n'
        recs = split_dump(text)
        self.assertEqual(len(recs), 2)
        self.assertIn("Nina paka", recs[0])

    def test_dump_escaped_inner_quotes(self):
        # 内部引号双写转义：csv 还原为单个引号
        text = '"Alisema ""Habari"" halafu akaondoka."\n'
        recs = split_dump(text)
        self.assertEqual(recs[0], 'Alisema "Habari" halafu akaondoka.')

    def test_tsv_takes_last_column(self):
        text = "1\tmeta\tHabari za leo\n2\tmeta\tNina paka\n"
        recs = split_tsv(text)
        self.assertEqual(recs, ["Habari za leo", "Nina paka"])

    def test_tsv_json_cells_decoded(self):
        """ingest_xlsx 产出的每格都是 json 编码，须还原（与 io.read_input_rows 同契约）。"""
        text = '1\t"sw"\t"Habari za \\"leo\\""\n'
        self.assertEqual(split_tsv(text), ['Habari za "leo"'])

    def test_tsv_and_read_input_rows_same_contract(self):
        """回归：split_tsv 与 io.read_input_rows 的 json 还原契约必须一致（P3-12）。

        此前 split_tsv 只在以 `"`/`[`/`{` 开头时解析 → `null`/纯数字一路得字符串、
        read_input_rows 一路得 None/数字。
        """
        from corpus_kit.io import read_input_rows
        from corpus_kit.reconstruct import decode_cell, cell_text
        # 单元级：统一解码函数
        self.assertIsNone(decode_cell("null"))
        self.assertEqual(decode_cell("123"), 123)
        self.assertEqual(cell_text("null"), "")      # None → 空，不是字面量 "None"
        self.assertEqual(cell_text("123"), "123")

        text = "a\tnull\nb\t123\nc\tplain\n"
        self.assertEqual(split_tsv(text), ["", "123", "plain"])

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "INPUT.txt").write_text(text, encoding="utf-8")
            (td / "INPUT.meta.json").write_text(
                json.dumps({"columns": ["c1", "c2"], "text_column": "c2"}), encoding="utf-8")
            rows = read_input_rows(td / "INPUT.txt", td / "INPUT.meta.json")
        self.assertEqual([r.text for r in rows], ["", "123", "plain"])

    def test_short_row_warns(self):
        """回归：行尾列缺失要告警，不再把文本列静默读成空串（P3-11）。"""
        from corpus_kit.io import read_input_rows
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # 声明 3 列，实际 2 格 → 文本列（第 3 列）缺失
            (td / "INPUT.txt").write_text("a\tb\n", encoding="utf-8")
            (td / "INPUT.meta.json").write_text(
                json.dumps({"columns": ["c1", "c2", "c3"], "text_column": "c3"}), encoding="utf-8")
            import io as _io
            import contextlib
            buf = _io.StringIO()
            with contextlib.redirect_stderr(buf):
                rows = read_input_rows(td / "INPUT.txt", td / "INPUT.meta.json")
        self.assertEqual(rows[0].text, "")                 # 缺失列按空
        self.assertIn("列数少于", buf.getvalue())           # 且必须告警

    def test_multicol_tsv_not_misdetected_as_dump(self):
        """回归：带引号的多行单元格的多列 tsv 不得被判成 dump。

        判成 dump 会按单列拼回，整行变乱码（实测项目自己的 input/INPUT.txt 踩到）。
        """
        text = ('1\t"meta"\t"Habari za leo.\\nNi nzuri."\n'
                '2\t"meta"\t"Pili."\n')
        self.assertEqual(detect_format(text), "tsv")
        recs = reconstruct(text).records
        self.assertEqual(len(recs), 2)
        self.assertTrue(recs[0].startswith("Habari za leo"))

    def test_split_plain_skips_blank(self):
        self.assertEqual(split_plain("a\n\nb\n"), ["a", "b"])

    def test_crlf_normalized(self):
        r = reconstruct('"Habari za leo."\r\n"Nina paka."\r\n', fmt="dump")
        self.assertEqual(len(r.records), 2)

    def test_content_preserved_assertion(self):
        text = '"Habari za leo.\n\nNi nzuri."\n"Pili."\n'
        r = reconstruct(text, fmt="dump")
        self.assertTrue(r.content_preserved)
        self.assertEqual(r.dropped_chars, 0)

    def test_integrity_signature_is_whitespace_sensitive(self):
        """回归：签名必须对「空白的有无」敏感——否则看不见它要防的粘词故障。

        但要容忍空白的**形态/数量**差异（记录边界空白会合法变化）。
        """
        from corpus_kit.reconstruct import integrity_signature
        self.assertNotEqual(integrity_signature("a b"), integrity_signature("ab"))
        # 包裹引号不是内容 → 剥离后应相等
        self.assertEqual(integrity_signature('"habari za leo"'), integrity_signature("habari za leo"))
        # 空白形态不同（换行 vs 两空格）→ 折成一个空格后相等
        self.assertEqual(integrity_signature("a\nb"), integrity_signature("a  b"))

    def test_conserved_for_wrapped_and_bare_records(self):
        """内容守恒对「引号包裹」与「裸记录」都成立（引号属框架，不是内容）。"""
        for text in ('"Habari za leo."\n"Pili ni nzuri."\n',
                     '"Habari za leo.\n\nNi nzuri."\n"Pili."\n',
                     'Habari za leo.\nPili ni nzuri.\n'):
            with self.subTest(text=text[:30]):
                r = reconstruct(text, fmt="dump")
                self.assertTrue(r.content_preserved)
                self.assertEqual(r.dropped_chars, 0)

    def test_fixture_recovers_records(self):
        text = FIXTURE.read_text(encoding="utf-8")
        r = reconstruct(text, fmt="auto")
        self.assertEqual(r.detected_format, "dump")
        self.assertTrue(r.content_preserved)
        # 夹具有 2 条同文重复，应被识别为不同记录而非合并
        joined = [x for x in r.records if x.startswith("Picha zifuatazo")]
        self.assertEqual(len(joined), 2)


class TestNormalize(unittest.TestCase):
    def test_bom_and_crlf(self):
        self.assertEqual(normalize_text("\ufeffHabari za leo.\r\n", CFG), "Habari za leo.")

    def test_control_and_zero_width_stripped(self):
        # ZWSP / ZWJ / 软连字符 / C1 控制字符
        s = "Ha\u200bbari\u200d za\u00ad leo\u0085."
        self.assertEqual(normalize_text(s, CFG), "Habari za leo.")

    def test_wrapper_quotes_unwrapped(self):
        self.assertEqual(normalize_text('"Habari za leo."', CFG), "Habari za leo.")

    def test_wrapper_quotes_only_when_paired(self):
        """回归：正文首尾恰好是引号但内部有落单引号时，不得当包裹引号切掉（P3-9）。

        旧实现只看 startswith/endswith → `"hi" alisema "bye"` 会被切掉首尾引号、损坏内容。
        """
        s = '"hi" alisema "bye"'
        self.assertEqual(normalize_text(s, CFG), s)          # 原样保留

    def test_wrapper_quotes_escaped_pair_unwrapped_once(self):
        """回归：包裹引号内的双写转义只还原一次（P3-9）。

        旧实现无条件 `replace('""','"')`：dump 路径的 csv.reader 已还原过一次，
        这里再转一次会把正文里真实的相邻双引号也破坏。
        """
        self.assertEqual(normalize_text('"Alisema ""Habari"" halafu."', CFG),
                         'Alisema "Habari" halafu.')
        # 非包裹文本里的相邻双引号必须原样保留（不做二次转义）
        self.assertEqual(normalize_text('a "" b', CFG), 'a "" b')

    def test_newline_to_space(self):
        self.assertEqual(normalize_text("Habari\n\nza leo", CFG), "Habari za leo")

    def test_repeat_run_folded(self):
        self.assertEqual(normalize_text("Habari" + "-" * 200, CFG).count("-"), 100)

    def test_nfc_composes(self):
        # e + U+0301 → é（NFC 合成）
        out = normalize_text("cafe\u0301", CFG)
        self.assertEqual(out, "café")


class TestLanguageAgnostic(unittest.TestCase):
    """核心约束：非拉丁语料必须原样存活，不被 Latin-only 逻辑误杀。"""

    def test_nonlatin_survives_normalize(self):
        cases = {
            "ar": "أهلاً بك! كيف يمكنني مساعدتك اليوم؟",
            "hi": "नमस्ते, आप कैसे हैं?",
            "ru": "Привет, как дела?",
            "th": "สวัสดีครับ สบายดีไหม",
        }
        for lang, s in cases.items():
            with self.subTest(lang=lang):
                out = normalize_text(s, CFG)
                self.assertEqual(out, s.strip())
                self.assertFalse(has_hard_flag(quality_flags(out, CFG)),
                                 msg=f"{lang} 被硬规则误杀：{quality_flags(out, CFG)}")

    def test_dedup_key_works_for_nonlatin(self):
        # 去重键必须能对非拉丁文本归一（数字→0、去标点走 Unicode 属性）
        a = dedup_key("नमस्ते 123", CFG)
        b = dedup_key("नमस्ते 456", CFG)
        self.assertEqual(a, b)          # 数字归一后应相同
        self.assertTrue(a)              # 非空（不是被清成空串）

    def test_dedup_distinguishes_nonlatin(self):
        self.assertNotEqual(dedup_key("नमस्ते", CFG), dedup_key("स्वागत", CFG))

    def test_no_latin_only_charclass_in_source(self):
        """守卫：清洗模块的**代码**里不得出现 Latin-only 字符类字面量。

        这是本仓库已有三处缺陷（TOKEN_RE / CORE_RE / foreign_blocks）的同类风险，
        用测试钉住，防止后续维护无意退化。

        扫的是**字符串常量**（正则/字符类只可能写在字符串里）。docstring 是唯一例外
        ——它要能*提到* `[A-Za-z]` 作为反例说明，故显式排除 docstring 节点；
        `cur[k]` 这类下标不是字符串常量，天然不误报。
        """
        import ast

        latin_class = re.compile(r"\[[A-Za-z]|\b(?:a-z|A-Z|A-Za-z)\b")
        docstrings: set[int] = set()
        for name in ("corpus_kit/clean.py", "corpus_kit/reconstruct.py"):
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    body = getattr(node, "body", [])
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                        docstrings.add(id(body[0].value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and id(node) not in docstrings:
                    self.assertIsNone(
                        latin_class.search(node.value),
                        msg=f"{name} 字符串常量出现 Latin-only 字符类：{node.value!r}")


class TestQuality(unittest.TestCase):
    def test_empty_and_no_letters_are_hard(self):
        self.assertTrue(has_hard_flag(quality_flags("", CFG)))
        self.assertTrue(has_hard_flag(quality_flags("   ", CFG)))
        self.assertTrue(has_hard_flag(quality_flags("!!!...", CFG)))

    def test_normal_sentence_is_not_hard(self):
        flags = quality_flags("Habari za leo ni nzuri sana, ninaweza kukusaidia.", CFG)
        self.assertFalse(has_hard_flag(flags), msg=flags)

    def test_punctuation_dense_is_soft_not_hard(self):
        # 合法但标点密度高：业界阈值在短句上偏高 → 只记 soft，不剔除
        flags = quality_flags("Sawa..", CFG)
        self.assertTrue(flags)
        self.assertFalse(has_hard_flag(flags), msg=flags)

    def test_emoji_only_is_hard(self):
        self.assertTrue(has_hard_flag(quality_flags("😀😀", CFG)))

    def test_nonalnum_ratio_excludes_whitespace(self):
        # 带标点的正常句不该因空格被计入分母而越界
        flags = quality_flags("Samahani, inaonekana kuna mkanganyiko kuhusu neno.", CFG)
        self.assertFalse(any("nonalnum" in f for f in flags), msg=flags)

    def test_nonalnum_ratio_same_unit_for_conjuncts(self):
        """回归：分子分母必须同为字素簇，否则复合字符脚本会算出负数。

        天城文 क्ष = 1 字素簇 / 3 码点。若分子数码点、分母数字素簇，
        ratio = 1 - 3/1 = -1.0（实测踩到）。这是语言无关性的硬要求。
        """
        for text in ("क्ष", "क्षत्रिय", "নমস্কার", "ஸ்ீ"):
            with self.subTest(text=text):
                flags = quality_flags(text, CFG)
                ratios = [f for f in flags if "nonalnum" in f]
                for f in ratios:
                    self.assertGreaterEqual(float(f.rsplit(":", 1)[1]), 0.0,
                                            msg=f"负数比 {f} —— 分子分母不是同一单位")

    def test_words_with_alpha_uses_whitespace_denominator(self):
        """回归：Gopher 含字母词比的分母必须是空白切词，不是「以字母开头的词」。

        原实现用 WORD_RE 取词（每个 token 必以字母开头）→ frac 恒为 1.0，
        检查形同虚设。修复后数字词/符号词要进分母。
        """
        # 8 个 token，只有 2 个是字母词 → frac=0.25 < 0.8，应出 flag
        text = "123 456 789 !!! ??? 111 abc def"
        flags = quality_flags(text, CFG, raw=text)
        got = [f for f in flags if "words_with_alpha" in f]
        self.assertEqual(len(got), 1, msg=flags)
        self.assertAlmostEqual(float(got[0].rsplit(":", 1)[1]), 0.25, places=2)

    def test_words_with_alpha_all_alpha_clean(self):
        # 全字母词 → frac=1.0，不出 flag（正例，防过度触发）
        flags = quality_flags("habari za leo ni nzuri", CFG)
        self.assertFalse(any("words_with_alpha" in f for f in flags), msg=flags)

    def test_symbol_ratio_counts_hash_from_raw(self):
        """回归：`#` 在归一阶段被 NOISE_RE 剥掉，符比必须数原文，否则恒为 0。

        原实现数归一后的 text → text.count("#") 恒 0，Gopher 符号检查失效。
        """
        raw = "### jambo ### la ### muhimu ### sana"
        cleaned = normalize_text(raw, CFG)
        self.assertNotIn("#", cleaned)                     # 归一后确已剥掉
        flags = quality_flags(cleaned, CFG, raw=raw)
        got = [f for f in flags if "symbol_word_ratio" in f]
        self.assertEqual(len(got), 1, msg=flags)


class TestDedupModeSelection(unittest.TestCase):
    """回归：fuzzy 不得被 dedup.exact 门控（P2-8）。"""

    def test_fuzzy_runs_even_when_exact_disabled(self):
        # exact:false + fuzzy=true —— 原实现会静默变成「完全不去重」
        cfg = clean_config(dedup={"exact": False})
        texts = ["habari za leo sana", "habari za leo sana", "habari za leo sana"]
        res = clean_records(texts, cfg, fuzzy=True)
        self.assertEqual(len(res["dedup"]["drop"]), 2, msg=res["dedup"])

    def test_fuzzy_false_disables_fuzzy(self):
        cfg = clean_config(dedup={"exact": False})
        res = clean_records(["a b c", "a b c"], cfg, fuzzy=False)
        self.assertEqual(res["dedup"]["drop"], [])

    def test_no_dedup_and_fuzzy_mutually_exclusive_cli(self):
        """--no-dedup 与 --fuzzy 同时给 → 明确报错，不静默。"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.txt"
            src.write_text("habari za leo\nhabari za leo\n", encoding="utf-8")
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "prepare_input.py"),
                 "--lang", "sw",
                 "--input", str(src), "--out-dir", str(Path(td) / "c"),
                 "--no-dedup", "--fuzzy"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("互斥", r.stdout + r.stderr)


class TestDedup(unittest.TestCase):
    def test_exact_dedup_keeps_first(self):
        texts = ["Habari za leo.", "Text nyingine.", "Habari za leo.", "Habari  za leo."]
        r = dedup_exact(texts, CFG)
        # 空白折叠后前三条里 0 与 2 同键；第三条去重键与 0 相同 → 去掉 2
        self.assertIn(0, r["keep"])
        self.assertEqual(len([d for d in r["drop"] if d[0] == 2]), 1)

    def test_dedup_digits_normalized(self):
        texts = ["Bei ni 100 shilingi", "Bei ni 999 shilingi"]
        r = dedup_exact(texts, CFG)
        self.assertEqual(len(r["keep"]), 1)   # 数字归一后同键

    def test_keep_last_policy(self):
        cfg = clean_config(dedup={"keep_policy": "last"})
        texts = ["Picha zifuatazo..", "Text nyingine.", "Picha zifuatazo.."]
        r = dedup_exact(texts, cfg)
        self.assertIn(2, r["keep"])

    def test_clean_records_keeps_soft_flagged(self):
        rows = ["Habari za leo ni nzuri.", "Sawa..", "😀😀"]
        res = clean_records(rows, CFG)
        kept = [r for r in res["rows"] if r["kept"]]
        # "Sawa.." 是 soft → 保留；"😀" 无字母 → hard → 剔除
        texts = [r["text"] for r in kept]
        self.assertIn("Sawa..", texts)
        self.assertNotIn("😀😀", texts)

    def test_summarize_counts(self):
        res = clean_records(["Habari za leo.", "😀", "Habari za leo."], CFG)
        s = summarize(res["rows"], res["dedup"])
        self.assertEqual(s["n_in"], 3)
        self.assertEqual(s["n_dedup_dropped"], 1)
        self.assertGreaterEqual(len(s["hard_flag_counts"]), 1)


class TestPrepareInputCLI(unittest.TestCase):
    def test_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            out = td / "clean"
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "prepare_input.py"),
                 "--input", str(FIXTURE), "--lang", "sw", "--out-dir", str(out)],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            for f in ("INPUT.txt", "INPUT.meta.json", "clean_report.json",
                      "clean_report.csv", "quarantine.jsonl", "clean_manifest.json"):
                self.assertTrue((out / f).exists(), msg=f"缺产物 {f}")

            meta = json.loads((out / "INPUT.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["clean"]["detected_format"], "dump")
            self.assertTrue(meta["clean"]["n_records_in"] >= 10)

            # 清洗后 INPUT.txt 一行一条，且能被 io.read_input_rows 读回
            sys.path.insert(0, str(ROOT))
            from corpus_kit.io import read_input_rows
            rows = read_input_rows(out / "INPUT.txt", out / "INPUT.meta.json")
            self.assertEqual(len(rows), meta["rows"])
            self.assertTrue(all(r.text.strip() for r in rows))
            # 包裹引号已被剥掉
            self.assertFalse(any(r.text.startswith('"') for r in rows))

    def test_quarantine_keeps_full_text(self):
        """quarantine 是「可回滚」的依据，raw/cleaned 不能截断。"""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            out = td / "c"
            # 造一条 > 400 字符的记录，确认落盘未被截断
            long_text = "Habari za leo. " * 40
            src = td / "in.txt"
            src.write_text('"' + long_text + '"\n', encoding="utf-8")
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "prepare_input.py"),
                 "--lang", "sw",
                 "--input", str(src), "--out-dir", str(out)],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            recs = [json.loads(l) for l in (out / "quarantine.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            for rec in recs:
                self.assertLess(len(rec["raw"]), len(long_text) + 10)   # 未被 400 截断
                self.assertGreater(len(rec["cleaned"]), 400)

    def test_content_loss_guard_exists(self):
        """丢内容必须当场报错（spec §4 R4）。

        说明：dump/txt 两条路径在构造上不丢非引号内容（引号属框架、空白被签名归一），
        实测穷举 ~9000 组合均未触发；故这里只断言**守卫存在且生效于合理输入**——
        正常输入不报错，且 `content_preserved` 字段确实被 CLI 消费（防回归）。
        """
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "in.txt"
            src.write_text('"Habari za leo."\n"Pili ni nzuri."\n', encoding="utf-8")
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "prepare_input.py"),
                 "--lang", "sw",
                 "--input", str(src), "--format", "dump", "--out-dir", str(td / "c")],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            # 报告里要能看到守恒结论（可审计）
            rep = json.loads((td / "c" / "clean_report.json").read_text(encoding="utf-8"))
            self.assertTrue(rep["reconstruct"]["content_preserved"])

    def test_dry_run_writes_no_input(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "prepare_input.py"),
                 "--lang", "sw",
                 "--input", str(FIXTURE), "--out-dir", str(td / "c"), "--dry-run"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertFalse((td / "c" / "INPUT.txt").exists())
            self.assertTrue((td / "c" / "clean_report.json").exists())

    def test_cleaned_output_runs_pipeline(self):
        """清洗产物能直接喂给验证管线（跳过 G2P/词源，离线确定性）。"""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clean = td / "clean"
            subprocess.run(
                [PY, str(ROOT / "scripts" / "prepare_input.py"),
                 "--lang", "sw",
                 "--input", str(FIXTURE), "--out-dir", str(clean)],
                capture_output=True, text=True, encoding="utf-8")
            run = td / "run"
            r = subprocess.run(
                [PY, str(ROOT / "run_pipeline.py"),
                 "--lang", "sw", "--input", str(clean / "INPUT.txt"),
                 "--meta", str(clean / "INPUT.meta.json"),
                 "--out", str(run), "--skip-g2p", "--skip-etymology"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertTrue((run / "数据集_全字段.xlsx").exists())


class TestIngestXlsxSheet(unittest.TestCase):
    """回归：--sheet 拼错必须报错，不能静默回退第一个 sheet（P3-14）。"""

    def _make_xlsx(self, path: Path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["tts_text", "other"])
        ws.append(["habari za leo", "x"])
        wb.create_sheet("Second")
        wb.save(path)

    def test_wrong_sheet_name_errors(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            xlsx = td / "t.xlsx"
            self._make_xlsx(xlsx)
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "ingest_xlsx.py"),
                 "--lang", "sw",
                 "--xlsx", str(xlsx), "--sheet", "NoSuchSheet", "--out-dir", str(td / "o")],
                capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("不存在", r.stdout + r.stderr)

    def test_default_sheet_is_first(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            xlsx = td / "t.xlsx"
            self._make_xlsx(xlsx)
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "ingest_xlsx.py"),
                 "--lang", "sw",
                 "--xlsx", str(xlsx), "--out-dir", str(td / "o")],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()