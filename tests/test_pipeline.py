"""回归测试：核心模块单测 + 小型端到端（M1 gate 与 M2/M3 口径）。运行：python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corpus_kit.charset import check_charset
from corpus_kit.config import Config
from corpus_kit.g2p import G2P, load_ipa_dict
from corpus_kit.lang import check_lang
from corpus_kit.phonemes import letter_stats, phoneme_dist, split_phonemes
from corpus_kit.segment import split_sents
from corpus_kit.stats import entropy_norm, gini, summary, top_share
from corpus_kit.tokenize import whitespace_words, word_tokens

PY = sys.executable
CFG = Config("sw")


class TestConfig(unittest.TestCase):
    def test_load(self):
        self.assertGreaterEqual(len(CFG.function_words), 90)
        self.assertGreaterEqual(len(CFG.question_words), 9)
        self.assertTrue(CFG.ipa_dict_path.exists())
        self.assertEqual(len(load_ipa_dict(CFG.ipa_dict_path)), 48308)


class TestSegment(unittest.TestCase):
    def test_simple_split(self):
        s = split_sents("Habari za asubuhi! Leo ni siku nzuri.")
        # 句级两侧空白都剥掉：断点后的前导空格不是内容，留着会让 n_chars 系统性 +1
        self.assertEqual(s, ["Habari za asubuhi!", "Leo ni siku nzuri."])

    def test_split_strips_leading_whitespace(self):
        """回归：断点后的前导空格必须剥掉（P3-13）。

        旧口径 rstrip 只去尾 → 每句 n_chars（len()）系统性 +1。
        句数与断点位置不得因此改变。
        """
        s = split_sents("Habari za asubuhi!   Leo ni siku nzuri.\n\n  Pili.")
        self.assertEqual(s, ["Habari za asubuhi!", "Leo ni siku nzuri.", "Pili."])
        self.assertTrue(all(x == x.strip() for x in s))

    def test_decimal_not_split(self):
        s = split_sents("Bei ni 3.5% hapa.")
        self.assertEqual(len(s), 1)

    def test_ellipsis_and_quote(self):
        s = split_sents('Alisema "Ngoja niweke alama..." halafu akamaliza.')
        self.assertEqual(len(s), 1)


class TestTokenize(unittest.TestCase):
    def test_word_tokens(self):
        self.assertEqual(word_tokens("Habari za Leo!", r"[A-Za-z'\-]+"), ["habari", "za", "leo"])
        self.assertEqual(word_tokens("mzuri sana, ndio.", r"[A-Za-z'\-]+"), ["mzuri", "sana", "ndio"])
        self.assertEqual(word_tokens("ng'ombe wangu", r"[A-Za-z'\-]+"), ["ng'ombe", "wangu"])  # 撇号/连字符留在词内

    def test_whitespace(self):
        self.assertEqual(len(whitespace_words("a b c")), 3)


class TestLang(unittest.TestCase):
    def test_sw_pass(self):
        r = check_lang("Habari za leo ni nzuri sana, ninaweza kukusaidia lini?", CFG)
        self.assertIn(r["status"], ("pass",))

    def test_en_fail(self):
        r = check_lang("Red light therapy is genuinely interesting, and your description is on the right track.", CFG)
        self.assertEqual(r["status"], "fail")

    def test_arabic_fail(self):
        r = check_lang("أهلاً بك! كيف يمكنني مساعدتك اليوم؟", CFG)
        self.assertEqual(r["status"], "fail")


class TestCharset(unittest.TestCase):
    def test_arabic_fail(self):
        r = check_charset("أهلاً بك! كيف يمكنني مساعدتك اليوم؟", CFG)
        self.assertEqual(r["status"], "fail")

    def test_chinese_fail(self):
        r = check_charset("你好，世界！", CFG)
        self.assertEqual(r["status"], "fail")

    def test_emoji_pass(self):
        r = check_charset("Niko hapa tu! 😀 Labda kesho tutaonana.", CFG)
        self.assertEqual(r["status"], "pass")
        self.assertTrue(r["has_emoji"])
        self.assertGreaterEqual(r["core_after"], 5)


class TestG2P(unittest.TestCase):
    def test_dict_hit(self):
        g = G2P(CFG)
        ipa = g.phonemize("habari")
        self.assertTrue(ipa and "/" not in ipa)

    def test_miss_returns_none_or_ipa(self):
        g = G2P(CFG)
        # 数字/缩写不进 G2P
        self.assertIsNone(g.phonemize("12345"))
        # 词形变化词可能查不到 → epitran 兜底（装了就出 IPA，没装返回 None）
        ipa = g.phonemize("tutakapokutana")
        self.assertTrue(ipa is None or len(ipa) > 0)

    def test_has_letter_includes_hyphenated(self):
        """回归：词形判定须含连字符词，否则 g2p 未覆盖率系统性偏低（P2-7）。

        连字符词 `well-known`：isalpha()=False、WORD_RE 不匹配 → phonemize 返回 None，
        旧判据（isalpha 或含撇号）会漏计它。has_letter 必须认为它是「需要 IPA 的词」。
        """
        from corpus_kit.g2p import has_letter
        self.assertTrue(has_letter("well-known"))     # 连字符词
        self.assertTrue(has_letter("ng'ombe"))        # 撇号词
        self.assertTrue(has_letter("habari"))
        self.assertFalse(has_letter("12345"))         # 纯数字
        self.assertFalse(has_letter("!!!"))           # 纯符号
        self.assertFalse(has_letter(""))


class TestPhonemes(unittest.TestCase):
    def test_prenasalized(self):
        self.assertEqual(split_phonemes("aᵐɓo"), ["a", "ᵐɓ", "o"])
        self.assertEqual(split_phonemes("aⁿɗo"), ["a", "ⁿɗ", "o"])

    def test_digraph(self):
        self.assertEqual(split_phonemes("tʃaka"), ["tʃ", "a", "k", "a"])
        self.assertEqual(split_phonemes("dʒi"), ["dʒ", "i"])

    def test_dist(self):
        d = phoneme_dist(["habari", "chakula"])
        self.assertGreater(d["n_single"], 0)
        self.assertGreater(d["total_bi"], 0)


class TestStats(unittest.TestCase):
    def test_uniform(self):
        self.assertAlmostEqual(gini({"a": 1, "b": 1}), 0.0, places=4)
        self.assertAlmostEqual(entropy_norm({"a": 1, "b": 1}), 1.0, places=4)

    def test_concentrated(self):
        self.assertGreater(gini({"a": 100, "b": 1}), 0.4)
        self.assertLess(entropy_norm({"a": 100, "b": 1}), 0.5)

    def test_summary(self):
        s = summary([1, 2, 3, 100])
        self.assertEqual(s["min"], 1)
        self.assertEqual(s["max"], 100)
        self.assertEqual(s["n"], 4)


class TestEndToEnd(unittest.TestCase):
    def test_pipeline_fixture(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            fixture = ROOT / "tests" / "fixtures" / "sample_sw.txt"
            out = td / "run1"
            r = subprocess.run(
                [PY, str(ROOT / "run_pipeline.py"), "--input", str(fixture),
                 "--out", str(out), "--skip-g2p", "--skip-etymology"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertTrue((out / "records.jsonl").exists())
            self.assertTrue((out / "sentences.jsonl").exists())
            self.assertTrue((out / "数据集_全字段.xlsx").exists())
            self.assertTrue((out / "manifest.json").exists())
            sents = json.loads((out / "dims" / "length.json").read_text(encoding="utf-8-sig"))
            self.assertGreater(sents["n_sents"], 10)
            # 中文/阿拉伯行应被 gate fail
            recs = [json.loads(l) for l in (out / "records.jsonl").read_text(encoding="utf-8-sig").splitlines() if l.strip()]
            fails = [r_ for r_ in recs if r_["gate"]["charset"]["status"] == "fail"]
            self.assertGreaterEqual(len(fails), 2)


if __name__ == "__main__":
    unittest.main()
