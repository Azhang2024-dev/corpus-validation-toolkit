"""词级口径回归：词源全局去重 / 词级明细 join / verify 自检不变量。

对应 2026-09-16 三项定稿：
  (1) etymology 改全局词级去重（一个词只调用一次）
  (2) etymology 可只做验证、不出真结果（--verify）
  (3) 交付物披露词级明细（Excel 列 + 词级 sheet + csv/jsonl）

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = sys.executable

from corpus_kit.config import Config
from corpus_kit.report import build_word_rows, fmt_word_detail, load_etymology, load_word_ipa
from corpus_kit.tokenize import word_tokens
from skills.etymology_llm import run as ety

CFG = Config("sw")


class TestEtymologyWordLevelDedup(unittest.TestCase):
    """(1) 去重：calls == ceil(unique_words / batch_size)，而非句数。"""

    def _sents(self):
        # 反复出现同样 4 个词、跨 5 句：去重后 unique=4，按句口径则 5 次调用
        words = ["habari", "yako", "leo", "sana"]
        return [{"sent_id": i + 1, "row_id": 1, "text": " ".join(words), "tokens": list(words)}
                for i in range(5)]

    def test_candidate_counts_dedup_and_filter(self):
        sents = self._sents()
        c = ety.candidate_counts(sents)
        self.assertEqual(len(c), 4)
        self.assertEqual(c["habari"], 5)  # token 频次累加，型符去重
        # 纯符号/数字不进词源
        c2 = ety.candidate_counts([{"tokens": ["123", "--", "kwa"]}])
        self.assertEqual(list(c2), ["kwa"])

    def test_order_words_deterministic(self):
        c = Counter({"b": 3, "a": 2, "c": 2})
        self.assertEqual(ety.order_words(c), ["b", "a", "c"])  # 频次降序，同频字典序

    def test_run_tagging_call_count_is_dedup(self):
        sents = self._sents()
        endpoint = ety._start_mock(CFG)
        with tempfile.TemporaryDirectory() as td:
            stats = ety.run_tagging(sents, endpoint, "mock", "mock", Path(td), batch_size=2)
        self.assertEqual(stats["unique_words"], 4)
        self.assertEqual(stats["calls"], 2)            # ceil(4/2)，与 5 句无关
        self.assertEqual(stats["tagged"], 4)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(sum(stats["origin"].values()), 4 * 5)  # token 加权 = 4 词 × 5 句

    def test_resume_is_idempotent(self):
        endpoint = ety._start_mock(CFG)
        sents = self._sents()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            s1 = ety.run_tagging(sents, endpoint, "mock", "mock", td, batch_size=2)
            s2 = ety.run_tagging(sents, endpoint, "mock", "mock", td, batch_size=2)
        self.assertEqual(s1["calls"], 2)
        self.assertEqual(s2["calls"], 0)   # 续跑不重复调用

    def test_validate_rejects_mismatch(self):
        words = ["a", "b", "c"]
        good = [{"word": w, "origin": "bantu_native"} for w in words]
        self.assertTrue(ety.validate(good, words))
        self.assertTrue(ety.validate(list(reversed(good)), words))  # 顺序无关
        self.assertFalse(ety.validate(good[:2], words))            # 缺词
        self.assertFalse(ety.validate(good + [{"word": "d", "origin": "bantu_native"}], words))
        self.assertFalse(ety.validate([{"word": "a", "origin": "nope"}, {"word": "b", "origin": "bantu_native"}, {"word": "c", "origin": "bantu_native"}], words))

    def test_stale_words_do_not_pollute_stats(self):
        """回归：输出目录复用时，jsonl 里的历史词不得污染统计（P1-3）。

        原实现用 done（含所有历史词）算 tagged/untagged/origin：
        旧词按 weight=1 计入 origin、untagged 可能为负。
        """
        import tempfile as _tf
        from pathlib import Path as _P
        endpoint = ety._start_mock(CFG)
        with _tf.TemporaryDirectory() as td:
            td = _P(td)
            # 预置一批「旧语料」的词（不在本批 counts 里）
            (td / "etymology.jsonl").write_text(
                "\n".join(__import__("json").dumps({"word": w, "origin": "arabic_loan"})
                          for w in ("oldaa", "oldbb", "oldcc")) + "\n", encoding="utf-8")
            sents = [{"sent_id": 1, "row_id": 1, "text": "habari leo",
                      "tokens": ["habari", "leo"]}]
            stats = ety.run_tagging(sents, endpoint, "mock", "mock", td, batch_size=8)
        self.assertEqual(stats["unique_words"], 2)
        self.assertEqual(stats["tagged"], 2)          # 只算本批
        self.assertEqual(stats["untagged"], 0)        # 不再为负
        self.assertEqual(stats["stale"], 3)           # 旧词单独计数
        # origin 加权只含本批 token（habari:1 + leo:1 = 2），旧词不得计入
        self.assertEqual(sum(stats["origin"].values()), 2)
        self.assertNotIn("arabic_loan", stats["origin"])


class TestEtymologyVerify(unittest.TestCase):
    """(2) --verify 不出真结果，但证明链路正确。"""

    def test_verify_passes_on_real_fixture(self):
        rows = [l for l in (ROOT / "tests" / "fixtures" / "sample_sw.txt")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        from corpus_kit.segment import split_sents
        sents = []
        sid = 0
        for r in rows:
            for s in split_sents(r):
                if s:
                    sid += 1
                    sents.append({"sent_id": sid, "row_id": 1, "text": s, "tokens": word_tokens(s, r"[A-Za-z'\-]+")})
        ok, verdict = ety.verify(sents, CFG, batch_size=8)
        self.assertTrue(ok, msg=str(verdict))
        self.assertEqual(verdict["verify"], "pass")
        self.assertEqual(verdict["problems"], [])

    def test_verify_cli_writes_dims_and_exit0(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            sents_path = td / "sentences.jsonl"
            rows = ["Habari za asubuhi! Leo ni siku nzuri sana.", "Ninaweza kukusaidia leo?"]
            sents = []
            sid = 0
            for r in rows:
                from corpus_kit.segment import split_sents
                for s in split_sents(r):
                    sid += 1
                    sents.append({"sent_id": sid, "row_id": 1, "text": s, "tokens": word_tokens(s, r"[A-Za-z'\-]+")})
            sents_path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in sents) + "\n", encoding="utf-8")
            r = subprocess.run(
                [PY, str(ROOT / "skills" / "etymology_llm" / "run.py"),
                 "--sentences", str(sents_path), "--out", str(td), "--verify", "--batch-size", "8"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            dims = json.loads((td / "dims" / "etymology.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(dims["verify"], "pass")
            self.assertEqual(dims["tagged"], 0)          # 不出真结果
            self.assertGreater(dims["unique_words"], 0)


class TestReportWordDetail(unittest.TestCase):
    """(3) 交付物披露词级明细：inline 列 + 词级 sheet + csv/jsonl。"""

    def test_fmt_word_detail_shape(self):
        s = fmt_word_detail(["kwa", "sasa"], {"kwa": "kwa", "sasa": "sasa"},
                            {"kwa": "bantu_native"}, {}, sent_id=1)
        self.assertEqual(s, "kwa[kwa|bantu_native] sasa[sasa|-]")
        # 全缺失时用 '-' 占位，不留空
        self.assertEqual(fmt_word_detail(["zzz"], {}, {}, {}, 1), "zzz[-|-]")

    def test_load_etymology_supports_word_and_sentence_rows(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "etymology.jsonl").write_text(
                json.dumps({"word": "kwa", "origin": "bantu_native"}) + "\n"
                + json.dumps({"sent_id": 1, "word_id": 2, "word": "sasa", "origin": "arabic_loan"}) + "\n",
                encoding="utf-8")
            by_word, by_sw = load_etymology(td)
        self.assertEqual(by_word, {"kwa": "bantu_native"})       # 词级行
        self.assertEqual(by_sw, {(1, 2): "arabic_loan"})          # 旧句级行兜底

    def test_build_word_rows_joins_ipa_and_origin(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "token_ipa.json").write_text(json.dumps({"kwa": "kwa", "sasa": "sasa", "zzz": None}),
                                               encoding="utf-8")
            (td / "etymology.jsonl").write_text(
                json.dumps({"word": "kwa", "origin": "bantu_native"}) + "\n", encoding="utf-8")
            sents = [{"tokens": ["kwa", "sasa", "zzz", "kwa"]}]
            rows = build_word_rows(td, sents)
        by = {r["word"]: r for r in rows}
        self.assertEqual(by["kwa"]["count"], 2)
        self.assertEqual(by["kwa"]["origin"], "bantu_native")
        self.assertEqual(by["sasa"]["ipa"], "sasa")
        self.assertEqual(by["sasa"]["origin"], "")
        self.assertEqual(by["zzz"]["ipa"], "")            # null → 空串
        self.assertEqual(by["zzz"]["n_phonemes"], 0)
        self.assertEqual(rows[0]["word"], "kwa")          # 频次降序

    def test_pipeline_xlsx_has_word_columns_and_sheet(self):
        """端到端：跳过词源也应出词级明细列/sheet/csv（词源留空）。"""
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "run"
            r = subprocess.run(
                [PY, str(ROOT / "run_pipeline.py"),
                 "--input", str(ROOT / "tests" / "fixtures" / "sample_sw.txt"),
                 "--out", str(out), "--skip-etymology"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertTrue((out / "数据集_词级明细.csv").exists())
            self.assertTrue((out / "词级明细.jsonl").exists())
            wb = load_workbook(out / "数据集_全字段.xlsx", read_only=True)
            self.assertIn("词级明细", wb.sheetnames)
            headers = [c.value for c in next(wb["句子级明细"].iter_rows(max_row=1))]
            self.assertIn("词级明细", headers)
            # 句子级明细里 inline 词级串确实带上了 IPA（token_ipa 已算）
            wrow = [c.value for c in next(wb["词级明细"].iter_rows(min_row=2, max_row=2))]
            self.assertTrue(wrow[0])                       # 有词
            self.assertTrue(wrow[1])                       # 有 IPA
            wb.close()
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8-sig"))
            self.assertIn("unique_words", manifest["input"])
            self.assertGreater(manifest["input"]["unique_words"], 0)


class TestNswHitsDetail(unittest.TestCase):
    """NSW 不只给类别，还要给命中的具体串（否则规则误报无从复核）。"""

    def test_fmt_nsw_hits_shape(self):
        from corpus_kit.report import fmt_nsw_hits
        self.assertEqual(fmt_nsw_hits({"纯数字": ["17", "2026"]}), "纯数字:17,2026")
        self.assertEqual(fmt_nsw_hits({"纯数字": ["1"], "全大写缩写": ["KH", "NU"]}),
                         "纯数字:1; 全大写缩写:KH,NU")
        self.assertEqual(fmt_nsw_hits({}), "")
        self.assertEqual(fmt_nsw_hits(None), "")

    def test_run_records_matched_strings(self):
        """profile_vocab 写到 sentences.jsonl 的 nsw_hits 必须含具体串，不能只有类别。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            sents = [
                {"sent_id": 1, "text": "Amethibitishwa kuwa Rais Aam wa PBNU kwa kipindi cha 2026-2031 ."},
                {"sent_id": 2, "text": "habari za asubuhi tu ."},
            ]
            (out / "records.jsonl").write_text(
                json.dumps({"row_id": 1, "text": sents[0]["text"], "fields": []}) + "\n"
                + json.dumps({"row_id": 2, "text": sents[1]["text"], "fields": []}) + "\n", encoding="utf-8")
            (out / "sentences.jsonl").write_text(
                "\n".join(json.dumps(s, ensure_ascii=False) for s in sents) + "\n", encoding="utf-8")
            r = subprocess.run(
                [PY, str(ROOT / "skills" / "profile_vocab" / "run.py"),
                 "--records", str(out / "records.jsonl"), "--sentences", str(out / "sentences.jsonl"),
                 "--lang", "sw", "--out", str(out)],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            got = [json.loads(x) for x in (out / "sentences.jsonl").read_text(encoding="utf-8-sig").splitlines()]
            s1 = got[0]
            self.assertEqual(s1["nsw_types"], ["纯数字", "号码(+254等)", "全大写缩写"])
            self.assertIn("PBNU", s1["nsw_hits"]["全大写缩写"])      # 具体串，不是只有类别
            self.assertTrue(any(h.startswith("2026") for h in s1["nsw_hits"]["纯数字"]))
            self.assertEqual(got[1]["nsw_hits"], {})                 # 无命中 → 空 dict
            dims = json.loads((out / "dims" / "vocab.json").read_text(encoding="utf-8-sig"))
            cats = {c["category"]: c for c in dims["nsw_by_category"]}
            self.assertEqual(cats["全大写缩写"]["sentences"], 1)
            self.assertGreaterEqual(cats["全大写缩写"]["hits"], 1)

    def test_report_xlsx_has_nsw_hits_column(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "run"
            r = subprocess.run(
                [PY, str(ROOT / "run_pipeline.py"), "--input", str(ROOT / "tests" / "fixtures" / "sample_sw.txt"),
                 "--out", str(out), "--skip-etymology", "--skip-g2p"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            wb = load_workbook(out / "数据集_全字段.xlsx", read_only=True)
            headers = [c.value for c in next(wb["句子级明细"].iter_rows(max_row=1))]
            self.assertIn("nsw_hits", headers)
            wb.close()


class TestWordLevelDeliverableScale(unittest.TestCase):
    """规模体检：词级明细行数 == 去重型符数（不与 token 总数混淆）。"""

    def test_word_rows_unique(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "token_ipa.json").write_text(json.dumps({"a": "a", "b": "b"}), encoding="utf-8")
            sents = [{"tokens": ["a", "b", "a", "a"]}, {"tokens": ["b", "a"]}]
            rows = build_word_rows(td, sents)
        self.assertEqual(len(rows), 2)                     # 去重
        self.assertEqual(sum(r["count"] for r in rows), 6)  # token 总数守恒


if __name__ == "__main__":
    unittest.main()