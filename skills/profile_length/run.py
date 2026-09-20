"""profile_length —— 切句 + 四类长度分布（字符/词/音节）。records.jsonl → sentences.jsonl + dims/length.json

多语种口径（2026-09-18）：
- 字符数按**字素簇** `\\X` 计（不是码点）——合体字/组合符语言下 `len()` 会虚高；
  sw 保持历史 `len()`（其配置 `length.char_mode: codepoints`），基线不漂移。
- 音节按 `Config.syllable_method` 分派：`vowel_groups`（拼音法）/ `dict`（词典真值，
  未覆盖回退并披露）/ `from_ipa`（依 IPA 音素数）/ `na`（口径未定稿，出 N/A）。
- 阈值（超 300 字符 / 30 词 / 60 音节）是历史 sw 口径，非拉丁语言按字素簇对齐后
  同阈值，报告口径块里披露这一选择。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import regex as re

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.config import Config
from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl
from corpus_kit.segment import split_sents
from corpus_kit.stats import summary
from corpus_kit.tokenize import whitespace_words, word_tokens

GRAPHEME_RE = re.compile(r"\X")
SYLL_RE = re.compile(r"[aeiou]")   # 历史 sw 口径（vowel_groups 的缺省元音集）


def syll_vowel_groups(t: str, vowels: str | None = None) -> int:
    if vowels:
        return len(re.compile("[" + re.escape(vowels) + "]").findall(t.lower()))
    return len(SYLL_RE.findall(t.lower()))


def load_syll_dict(path) -> dict:
    """data/syll/<lang>.txt：`词\t音节数`。缺失返回空表（上层回退并披露）。"""
    d: dict = {}
    if path is None:
        return d
    p = Path(path)
    if not p.exists():
        return d
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                d[parts[0].strip().lower()] = int(float(parts[1].strip()))
            except ValueError:
                continue
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(description="长度分布（含切句）")
    ap.add_argument("--records", required=True, help="records.jsonl 路径")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 行（开发用）")
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    records = read_jsonl(args.records)
    if args.limit:
        records = records[: args.limit]
    outdir = ensure_dir(args.out)

    length_cfg = cfg.get("length", {}) or {}
    if not isinstance(length_cfg, dict):
        length_cfg = {}
    char_mode = length_cfg.get("char_mode", "codepoints")
    use_graphemes = char_mode == "graphemes"

    method = cfg.syllable_method
    syll_dict = load_syll_dict(cfg.syllable_dict_path) if method == "dict" else {}
    vowels = cfg.vowel_letters or None
    n_syll_dict_hit = n_syll_dict_miss = 0

    def count_chars(s: str) -> int:
        return len(GRAPHEME_RE.findall(s)) if use_graphemes else len(s)

    def count_syll(s: str) -> int | None:
        """返回 None 表示该语言音节口径为 N/A。"""
        nonlocal n_syll_dict_hit, n_syll_dict_miss
        if method == "na":
            return None
        if method == "dict":
            total = 0
            for w in whitespace_words(s):
                v = syll_dict.get(w.strip().lower().strip(".,;:!?…«»\"'()"))
                if v is None:
                    n_syll_dict_miss += 1
                    total += syll_vowel_groups(w, vowels)   # 未覆盖词回退（披露覆盖率）
                else:
                    n_syll_dict_hit += 1
                    total += v
            return total
        if method == "from_ipa":
            return None   # 由 profile_phoneme 后补（首版不出）
        return syll_vowel_groups(s, vowels)

    sentences = []
    sent_id = 0
    para_chars, para_words, para_sents = [], [], []
    for r in records:
        text = r.get("text", "")
        ss = [s for s in split_sents(text, cfg.sentence_enders, cfg.quote_pairs, cfg.enders_greedy) if s]
        para_chars.append(count_chars(text))
        para_words.append(len(whitespace_words(text)))
        para_sents.append(len(ss))
        for s in ss:
            sent_id += 1
            sentences.append({
                "sent_id": sent_id,
                "row_id": r["row_id"],
                "text": s,
                "n_chars": count_chars(s),
                "n_words": len(whitespace_words(s)),
                "n_syllables": count_syll(s),
                "tokens": word_tokens(s, cfg.token_pattern),
            })
    write_jsonl(outdir / "sentences.jsonl", sentences)

    cs = [x["n_chars"] for x in sentences]
    ws = [x["n_words"] for x in sentences]
    sy = [x["n_syllables"] for x in sentences if x["n_syllables"] is not None]
    dims = {
        "n_sents": len(sentences),
        "n_rows": len(records),
        "char": summary(cs),
        "char_unit": "grapheme" if use_graphemes else "codepoint",
        "word": summary(ws),
        "syll": summary(sy) if sy else None,
        "syll_method": method,
        "syll_coverage": ({"dict_hit_words": n_syll_dict_hit, "dict_miss_words": n_syll_dict_miss,
                           "dict_hit_ratio": round(n_syll_dict_hit / (n_syll_dict_hit + n_syll_dict_miss), 4)
                           if (n_syll_dict_hit + n_syll_dict_miss) else None}
                          if method == "dict" else None),
        "syll_note": ("N/A：音节口径未定稿（syllable.method=na）" if method == "na"
                      else ("词典未覆盖词按元音组近似（见 syll_coverage）" if method == "dict" else None)),
        "over_300": sum(1 for v in cs if v > 300),
        "over_30w": sum(1 for v in ws if v > 30),
        "over_60syll": (sum(1 for v in sy if v > 60) if sy else None),
        "para": {"char": summary(para_chars), "word": summary(para_words), "sents": summary(para_sents)},
    }
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "length.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_sents": len(sentences), "over_300": dims["over_300"],
                      "over_30w": dims["over_30w"], "over_60syll": dims["over_60syll"],
                      "syll_method": method}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())