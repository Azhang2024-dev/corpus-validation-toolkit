"""多语种通用化回归测试（2026-09-18）。

主题：从 sw 单语 → 18 语种通用（家族层 + 语言薄层 + 检测层 + 能力披露）。
要守的东西：
  1. 家族机制：9 族可加载、正则可编译、越界目录不含本族脚本（修掉「目标语被当外语」）；
  2. 非拉丁行为：token>0、charset pass、danda 切句、ZWNJ 保留；
  3. 检测层：脚本探测、--lang 冲突顶嘴、auto 判不出不瞎猜；
  4. 诚实降级：缺配置语言（generic）可跑且列明缺口；无词典/无兜底如实标注；
  5. sw 基线：pinned 口径与历史值一致（与 test_pipeline 的锁定数字互补）。

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = sys.executable

import regex as rx

from corpus_kit.charset import check_charset, foreign_pattern
from corpus_kit.config import Config
from corpus_kit.detect import detect_script, pick_language, verify_lang_command
from corpus_kit.io import write_jsonl
from corpus_kit.segment import split_sents
from corpus_kit.tokenize import word_tokens

ALL_LANGS = ["ar", "bn", "en", "es", "fil", "fr", "gu", "ha", "hi", "id", "mr", "pt",
             "ru", "sw", "ta", "tr", "ur", "zh"]


class TestScriptFamilies(unittest.TestCase):
    """家族层：配置齐全、模式可编译、越界目录结构性正确。"""

    def test_all_families_load_and_compile(self):
        for fam in ("latin", "arabic", "devanagari", "bengali", "gujarati", "tamil",
                    "cyrillic", "han", "generic"):
            c = Config("sw", script=fam)
            self.assertEqual(c.script, fam)
            for attr in ("token_pattern", "core_pattern", "letter_pattern", "word_pattern"):
                rx.compile(getattr(c, attr))   # 编译失败会抛异常

    def test_all_18_languages_configured(self):
        for code in ALL_LANGS:
            c = Config(code)
            self.assertNotIn("缺少 data/lang", " ".join(c.capability_gaps),
                             f"{code} 缺语言配置")

    def test_foreign_blocks_exclude_own_script(self):
        """核心修复：目标语脚本不得出现在自己的越界目录里。"""
        cases = {"ur": ["Arabic"], "ar": ["Arabic"], "hi": ["Devanagari"], "bn": ["Bengali"],
                 "ta": ["Tamil"], "ru": ["Cyrillic"], "zh": ["CJK Unified Ideographs"],
                 "fr": ["Latin-1 Supplement", "Latin Extended-A"], "gu": ["Gujarati"]}
        for code, own in cases.items():
            blocks = Config(code).charset_blocks
            for b in own:
                self.assertNotIn(b, blocks, f"{code} 的越界目录含本族块 {b}——会对目标语误杀")

    def test_foreign_pattern_ignores_whitespace_punct_digits(self):
        """回归：越界只按字母/组合符计（块含空格/标点/数字会污染比率）。"""
        c = Config("ur")
        pat = foreign_pattern(c.charset_blocks, bool(getattr(c, "foreign_letters_only", True)))
        self.assertEqual(pat.findall("  123.,;"), [], "空白/标点/数字不得计为越界字符")


class TestNonLatinBehaviors(unittest.TestCase):
    """非拉丁脚本的核心行为（此前三处致命缺陷的直接回归）。"""

    def test_tokenize_non_latin_nonzero(self):
        cases = [("ur", "یہی تناسب یوتھ کا بھی ہے", {"یہی", "تناسب"}),
                 ("hi", "नमस्ते दुनिया यह परीक्षण है", {"नमस्ते", "दुनिया"}),
                 ("ru", "привет мир это тест", {"привет", "мир"}),
                 ("bn", "সকালের সূর্য সবার জন্য", {"সকালের"})]
        for code, text, expect in cases:
            toks = word_tokens(text, Config(code).token_pattern)
            self.assertGreater(len(toks), 0, f"{code} token 数为 0（TOKEN_RE 类缺陷回归）")
            for w in expect:
                self.assertIn(w, toks, f"{code} token 切分错误：{toks}")

    def test_charset_passes_for_target_script(self):
        """目标语字符不得被判为外语（foreign_blocks 误杀的直接回归）。"""
        cases = [("ur", "یہی تناسب یوتھ کا بھی ہے"),
                 ("hi", "नमस्ते दुनिया यह परीक्षण है।"),
                 ("bn", "সকালের সূর্য সবার জন্য সমান আলো দেয়।"),
                 ("ru", "привет мир это тест"),
                 ("zh", "你好，世界。今天天气很好。")]
        for code, text in cases:
            r = check_charset(text, Config(code))
            self.assertNotEqual(r["status"], "fail", f"{code} 目标语字符被判越界：{r['reason']}")

    def test_latin_targets_not_falsely_flagged(self):
        for code, text in [("fr", "Bonjour le monde, ceci est un test."),
                           ("tr", "Merhaba dünya bu bir testtir."),
                           ("ha", "Sannu duniya wannan gwaji ne.")]:
            r = check_charset(text, Config(code))
            self.assertEqual(r["status"], "pass", f"{code}: {r['reason']}")

    def test_danda_and_greedy_endings(self):
        """bn/hi 的 danda 。与 ur 的问号 ؟ 必须能断句。"""
        c_hi = Config("hi")
        sents = split_sents("नमस्ते दुनिया। यह परीक्षण है।", c_hi.sentence_enders, c_hi.quote_pairs, c_hi.enders_greedy)
        self.assertEqual(len(sents), 2, f"danda 未断句：{sents}")
        c_ur = Config("ur")
        sents2 = split_sents("یہ کیا ہے؟ ٹھیک ہے۔", c_ur.sentence_enders, c_ur.quote_pairs, c_ur.enders_greedy)
        self.assertEqual(len(sents2), 2, f"؟/۔ 未断句：{sents2}")

    def test_zwj_not_stripped_for_devanagari(self):
        """bn/hi 的 ZWJ/ZWNJ 是正字法组成，不得被噪声剥离。"""
        c = Config("hi")
        text = "क्ष\u200dत्र"
        r = check_charset(text, c)
        self.assertIn("\u200d", r["cleaned"], "ZWJ 被剥离——合体字正字法会坏")

    def test_zh_tokenization_char_level(self):
        toks = word_tokens("你好，世界。", Config("zh").token_pattern)
        self.assertEqual(toks[:2], ["你", "好"])


class TestDetectLayer(unittest.TestCase):
    """检测层：脚本探测 / 指令顶嘴 / auto 不瞎猜。"""

    def test_script_detection(self):
        self.assertEqual(detect_script("नमस्ते दुनिया यह परीक्षण है")["script"], "devanagari")
        self.assertEqual(detect_script("مرحبا بكم في العالم")["script"], "arabic")
        self.assertEqual(detect_script("hello world this is english")["script"], "latin")
        self.assertEqual(detect_script("Привет мир")["script"], "cyrillic")

    def test_command_conflict_detected(self):
        """--lang=ur 但数据是拉丁文 → 必须 conflict（诚实性核心）。"""
        det = detect_script("Bonjour le monde, ceci est un test en français.")
        v = verify_lang_command("ur", "arabic", det, [("fr", 1.0)])
        self.assertEqual(v["status"], "conflict")
        self.assertTrue(any("不符" in n for n in v["notes"]))

    def test_command_match_ok(self):
        det = detect_script("habari za leo ni nzuri sana")
        v = verify_lang_command("sw", "latin", det, [("sw", 1.0)])
        self.assertEqual(v["status"], "ok")

    def test_auto_pick_by_langdetect(self):
        fam = {c: Config(c).script for c in ALL_LANGS}
        pick = pick_language("bonjour le monde ceci est un test de français",
                             ALL_LANGS, fam, {c: Config(c).langdetect_aliases for c in ALL_LANGS})
        self.assertEqual(pick["lang"], "fr")

    def test_auto_undetermined_reports_reason(self):
        """判不出必须报出来（candidates + reason），不瞎猜。"""
        fam = {c: Config(c).script for c in ALL_LANGS}
        pick = pick_language("!!! ### 12345", ALL_LANGS, fam)
        self.assertIsNone(pick["lang"])
        self.assertIn("reason", pick)

    def test_gate_auto_cli(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "run"
            src = Path(td) / "in.txt"
            src.write_text("Bonjour le monde. Ceci est un test.\n", encoding="utf-8")
            r = subprocess.run([PY, str(ROOT / "skills" / "gate_validity" / "run.py"),
                                "--input", str(src), "--lang", "auto", "--out", str(out)],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            g = json.loads((out / "dims" / "gate.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(g["lang"], "fr")
            self.assertEqual(g["lang_check"]["status"], "auto")


class TestHonestDegradation(unittest.TestCase):
    """诚实降级：缺什么标什么；不借他语资源。"""

    def test_unknown_language_no_silent_borrow(self):
        """未配置语言：不得回落 sw 词典/斯语 G2P。"""
        c = Config("zz")
        self.assertIsNone(c.ipa_dict_path, "未配置语言竟拿到了词典（静默回落他语）")
        self.assertIsNone(c.epitran_lang, "未配置语言竟拿到了 G2P 语言码")
        self.assertTrue(any("无发音词典" in g for g in c.capability_gaps))
        self.assertFalse(c.resources_ok)

    def test_known_language_gaps_empty_or_explicit(self):
        """已配置语言：缺口列表必须与实际一致（有词典/有兜底 → 无该类缺口）。"""
        for code in ALL_LANGS:
            c = Config(code)
            gaps = " ".join(c.capability_gaps)
            self.assertNotIn("无发音词典", gaps, f"{code} 有词典却报缺")
            self.assertNotIn("缺少 data/lang", gaps, f"{code} 有配置却报缺")

    def test_gu_no_fallback_is_disclosed(self):
        """gu 无 epitran map → 必须如实标注（不假装有兜底）。"""
        c = Config("gu")
        self.assertEqual(c.g2p_fallback, "none")
        self.assertIsNone(c.epitran_lang)

    def test_na_syllable_is_disclosed(self):
        c = Config("ur")
        self.assertEqual(c.syllable_method, "na")
        self.assertIn("音节", " ".join(c.capability_gaps))

    def test_capability_block_in_report(self):
        """报告必须含「能力与口径」块（含缺口/词典/口径）。"""
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "run"
            src = Path(td) / "in.txt"
            src.write_text("Bonjour le monde. Ceci est un test de français.\n", encoding="utf-8")
            r = subprocess.run([PY, str(ROOT / "run_pipeline.py"), "--input", str(src),
                                "--lang", "fr", "--out", str(out), "--skip-etymology"],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            wb = load_workbook(out / "数据集_全字段.xlsx", read_only=True)
            labels = [str(row[0]) for row in wb["维度分布"].iter_rows(values_only=True) if row and row[0]]
            wb.close()
            joined = " | ".join(labels)
            self.assertIn("能力与口径", joined)
            self.assertIn("发音词典", joined)
            self.assertIn("音节口径", joined)


class TestMultiLangPipeline(unittest.TestCase):
    """端到端：非拉丁语种跑完整管线并出报告。"""

    def _run(self, code: str, text: str, td: str):
        out = Path(td) / f"run_{code}"
        src = Path(td) / f"{code}.txt"
        src.write_text(text + "\n", encoding="utf-8")
        r = subprocess.run([PY, str(ROOT / "run_pipeline.py"), "--input", str(src),
                            "--lang", code, "--out", str(out), "--skip-etymology",
                            "--audit-n", "5"], capture_output=True, text=True, encoding="utf-8")
        return out, r

    def test_ur_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            out, r = self._run("ur", "یہی تناسب یوتھ کا بھی ہے\nاب اس کا حال تو یہی ہے کہ دعا کریں", td)
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            g = json.loads((out / "dims" / "gate.json").read_text(encoding="utf-8-sig"))
            self.assertGreater(g["lang_pass"], 0)
            l = json.loads((out / "dims" / "length.json").read_text(encoding="utf-8-sig"))
            self.assertIsNone(l["syll"], "ur 音节应为 N/A")
            self.assertIn("N/A", str(l["syll_note"]))

    def test_ru_pipeline_syllable_vowel_groups(self):
        with tempfile.TemporaryDirectory() as td:
            out, r = self._run("ru", "Привет мир. Это тест русского языка.", td)
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            l = json.loads((out / "dims" / "length.json").read_text(encoding="utf-8-sig"))
            self.assertIsNotNone(l["syll"], "ru 音节应按书写元音组给数")
            self.assertEqual(l["syll_method"], "vowel_groups")

    def test_zh_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            out, r = self._run("zh", "你好，世界。今天天气很好。", td)
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            l = json.loads((out / "dims" / "length.json").read_text(encoding="utf-8-sig"))
            # 「你好，世界。今天天气很好。」= 2 句（。是 greedy ender）
            self.assertEqual(l["n_sents"], 2)

    def test_generic_language_runs_and_discloses(self):
        """完全未配置的语言（如泰语样本走 generic）也要能跑，并列出缺口。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "run"
            src = Path(td) / "th.txt"
            src.write_text("สวัสดีชาวโลก นี่คือการทดสอบ\n", encoding="utf-8")
            r = subprocess.run([PY, str(ROOT / "run_pipeline.py"), "--input", str(src),
                                "--lang", "th", "--out", str(out), "--skip-etymology", "--skip-g2p"],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            g = json.loads((out / "dims" / "gate.json").read_text(encoding="utf-8-sig"))
            self.assertTrue(g["degraded"])
            self.assertTrue(any("缺少 data/lang/th.yaml" in x for x in g["capability_gaps"]))

    def test_batch_verify_single_file(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "sample.txt"
            src.write_text("Bonjour le monde. Ceci est un test.\n"
                           "Les données sont importantes pour l'analyse.\n", encoding="utf-8")
            out = Path(td) / "batch_out"
            r = subprocess.run([PY, str(ROOT / "scripts" / "batch_verify.py"),
                                "--input", str(src), "--out", str(out), "--lang", "fr",
                                "--skip-g2p"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertTrue((out / "INDEX.md").exists())
            self.assertTrue((out / "index.json").exists())


class TestSwBaselinePinned(unittest.TestCase):
    """sw 口径被显式 pin（防未来改动漂移历史基线）。"""

    def test_sw_pins_historical_patterns(self):
        c = Config("sw")
        self.assertEqual(c.token_pattern, r"[A-Za-z'\-]+")
        self.assertEqual(c.word_pattern, r"^[a-z']+$")
        self.assertEqual(c.sentence_enders, ".!?")
        self.assertEqual(c.phoneme_rules.get("mode"), "sw_legacy")
        self.assertFalse(getattr(c, "foreign_letters_only", True), "sw 应 pin 旧越界口径")
        self.assertEqual(c.syllable_method, "vowel_groups")

    def test_sw_split_phonemes_legacy(self):
        from corpus_kit.phonemes import split_phonemes
        c = Config("sw")
        # sw 历史口径：上标前鼻化 + 后随字符合并为**单音位**（ᵐɓ 不拆）
        self.assertEqual(split_phonemes("aᵐɓo", c), ["a", "ᵐɓ", "o"])
        self.assertEqual(split_phonemes("tʃaka", c), ["tʃ", "a", "k", "a"])



class TestWordTokensRequirePattern(unittest.TestCase):
    """bare word_tokens must not silently Latin-filter non-Latin text."""

    def test_missing_pattern_raises(self):
        with self.assertRaises(ValueError):
            word_tokens("你好")
        with self.assertRaises(ValueError):
            word_tokens("नमस्ते")

    def test_explicit_sw_still_latin(self):
        self.assertEqual(
            word_tokens("Habari za Leo!", Config("sw").token_pattern),
            ["habari", "za", "leo"],
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())