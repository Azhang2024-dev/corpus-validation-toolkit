"""report —— 落盘：数据集_全字段.xlsx（原字段保留+维度列+多 sheet）+ csv + manifest.json。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import __version__
from .io import ensure_dir, read_jsonl

HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(color="FFFFFF", bold=True)
WARN_FONT = Font(color="9C6500")
FAIL_FONT = Font(color="C00000")

# 新增维度列说明（字段说明子表）
NEW_COLUMNS = [
    ("sent_id", "句级唯一 ID（1..N，贯穿全链路）", "行"),
    ("row_id", "原 INPUT.txt 行号（1..N），回溯原回流表", "行"),
    ("gate_lang", "目标语言判定：pass / warn / fail", "文本"),
    ("gate_charset", "字符检查：pass / warn / fail（越界脚本比例分桶）", "文本"),
    ("gate_reason", "gate 判定原因摘要（虚词命中率 / 越界比例等）", "文本"),
    ("n_chars", "单句字符数 len()", "整数"),
    ("n_words", "单句词数（空白切词）", "整数"),
    ("n_syllables", "单句音节数（拼写元音 aeiou 计数，与 IPA 100% 一致）", "整数"),
    ("sentence_type", "句式：疑问 / 感叹 / 陈述 / 短语", "文本"),
    ("nsw_types", "命中 NSW 类别（逗号分隔；无则空）", "文本"),
    ("n_phonemes", "句内可音素化词的音素总数（查表+epitran 兜底后）", "整数"),
    ("phoneme_types", "句内不同音素数", "整数"),
    ("etymology_status", "词源打标：tagged / untagged / etym_fail", "文本"),
]

# 回流原表头说明（已知 23 列；未知列自动兜底『原表字段』）
ORIGINAL_COLUMNS = {
    "text_query": "用户查询原文（JSON 数组字符串）",
    "tts_model_version": "模型版本",
    "tts_voice_type": "音色类型（如 sw-KE-ZuriNeural）",
    "tts_model_name": "语音合成模型/厂商",
    "tts_s3_key": "音频 S3 key",
    "p_date": "分区日期",
    "tts_bit_rate": "比特率",
    "tts_length": "原始字段-文本长度",
    "tts_sample_rate": "采样率",
    "tts_encoding": "编码格式（opus 等）",
    "tts_s3_key_duration": "S3 音频时长（ms）",
    "tts_answer": "助手回复文本（JSON 数组字符串）",
    "tts_speed_ratio": "语速比例",
    "tts_duration": "音频时长（ms）",
    "tts_vendor": "供应商",
    "tts_synthesis_method": "合成方式（online 等）",
    "tts_text": "实际合成文本（TTS 录音用，验证主体）",
    "tts_language": "语言码（sw）",
    "dm_asr_info_is_in_tts": "ASR 信息是否在 TTS 中",
    "tts_locale_language": "语言区域（sw_KE/sw_TZ）",
    "multimodal_query": "多模态查询 JSON",
    "request_id": "请求唯一 ID",
    "tts_user_interrupt_flag": "用户打断标记",
}


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _col_widths(ws, widths: dict):
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def _header(ws, headers: list[str]):
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT


def _tag(ws, r: int, col: int, status: str):
    cell = ws.cell(row=r, column=col)
    if status == "fail":
        cell.font = FAIL_FONT
    elif status == "warn":
        cell.font = WARN_FONT


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v


def build_report(outdir: Path, meta: dict, sentences: list[dict], records: list[dict],
                 dims: dict, run_params: dict) -> dict:
    outdir = ensure_dir(outdir)
    rec_by_id = {r["row_id"]: r for r in records}
    src_cols = [c for c in (meta.get("columns") or []) if c != meta.get("text_column")]
    numeric_cols = set(meta.get("numeric_columns") or [])

    wb = Workbook()

    # ---------- Sheet1 句子级明细 ----------
    ws = wb.active
    ws.title = "句子级明细"
    headers = ["sent_id", "row_id"] + src_cols + ["文本"] + [
        "gate_lang", "gate_charset", "gate_reason",
        "n_chars", "n_words", "n_syllables", "sentence_type", "nsw_types",
        "n_phonemes", "phoneme_types", "etymology_status",
    ]
    _header(ws, headers)
    gate_lang_col = headers.index("gate_lang") + 1
    gate_charset_col = headers.index("gate_charset") + 1
    r = 1
    for s in sentences:
        rec = rec_by_id.get(s.get("row_id"), {})
        gate = rec.get("gate", {}) or {}
        gl = gate.get("lang") or {}
        gc = gate.get("charset") or {}
        row = [
            s.get("sent_id"), s.get("row_id"),
        ]
        src_pos = {c: i for i, c in enumerate(src_cols)}
        for c in src_cols:
            fields = rec.get("fields") or []
            idx = src_pos[c]
            v = fields[idx] if idx < len(fields) else ""
            if c in numeric_cols:
                v = _num(v)
            row.append(v)
        row.append(s.get("text", ""))
        row += [
            gl.get("status", ""), gc.get("status", ""),
            "; ".join(x for x in [gl.get("reason"), gc.get("reason")] if x),
            s.get("n_chars"), s.get("n_words"), s.get("n_syllables"),
            s.get("sentence_type", ""),
            ",".join(s.get("nsw_types") or []),
            s.get("n_phonemes", 0), s.get("phoneme_types", 0),
            s.get("etymology_status", "untagged"),
        ]
        ws.append(row)
        r += 1
        _tag(ws, r, gate_lang_col, gl.get("status", ""))
        _tag(ws, r, gate_charset_col, gc.get("status", ""))
    _col_widths(ws, {"A": 10, "B": 10})
    ws.freeze_panes = "C2"

    # ---------- Sheet2 行级汇总 ----------
    ws2 = wb.create_sheet("行级汇总")
    h2 = ["row_id"] + src_cols + ["gate_lang", "gate_charset", "gate_reason",
                                   "n_sents", "中位句长", "max句长", "句式中疑问", "句式中感叹", "NSW句数"]
    _header(ws2, h2)
    gl_col2 = h2.index("gate_lang") + 1
    gc_col2 = h2.index("gate_charset") + 1
    rr = 1
    by_row: dict = {}
    for s in sentences:
        by_row.setdefault(s.get("row_id"), []).append(s)
    for r in records:
        sid = r["row_id"]
        sents = by_row.get(sid, [])
        gate = r.get("gate", {}) or {}
        gl = gate.get("lang") or {}
        gc = gate.get("charset") or {}
        row = [sid]
        fields = r.get("fields") or []
        for idx, c in enumerate(src_cols):
            v = fields[idx] if idx < len(fields) else ""
            if c in numeric_cols:
                v = _num(v)
            row.append(v)
        lens = sorted(s.get("n_chars", 0) for s in sents)
        med = lens[len(lens) // 2] if lens else 0
        row += [
            gl.get("status", ""), gc.get("status", ""),
            "; ".join(x for x in [gl.get("reason"), gc.get("reason")] if x),
            len(sents), med, max(lens) if lens else 0,
            sum(1 for s in sents if s.get("sentence_type") == "疑问"),
            sum(1 for s in sents if s.get("sentence_type") == "感叹"),
            sum(1 for s in sents if s.get("nsw_types")),
        ]
        ws2.append(row)
        rr += 1
        _tag(ws2, rr, gl_col2, gl.get("status", ""))
        _tag(ws2, rr, gc_col2, gc.get("status", ""))
    _col_widths(ws2, {"A": 10})

    # ---------- Sheet3 维度分布 ----------
    ws3 = wb.create_sheet("维度分布")

    def block(title, rows):
        ws3.append([title])
        ws3.cell(ws3.max_row, 1).font = Font(bold=True, size=12)
        for r in rows:
            ws3.append(r)

    gate = dims.get("gate", {}) or {}
    block("一、合法性 gate", [
        ["项", "值"],
        ["行数", gate.get("rows") or len(records)],
        ["语言判定 pass 行数", gate.get("lang_pass")],
        ["语言判定 pass 占比", gate.get("lang_pass_ratio")],
        ["字符检查 pass 行数", gate.get("charset_pass")],
        ["字符检查 pass 占比", gate.get("charset_pass_ratio")],
        ["带 emoji 行占比", gate.get("emoji_ratio")],
    ])
    ws3.append([])

    length = dims.get("length", {}) or {}
    block("二、长度分布（句级）", [
        ["指标", "值"],
        ["句子总数", length.get("n_sents")],
        ["单句字符 中位/P95/max", f"{length.get('char', {}).get('p50')} / {length.get('char', {}).get('p95')} / {length.get('char', {}).get('max')}"],
        ["单句词数 中位/P95/max", f"{length.get('word', {}).get('p50')} / {length.get('word', {}).get('p95')} / {length.get('word', {}).get('max')}"],
        ["单句音节 中位/P95/max", f"{length.get('syll', {}).get('p50')} / {length.get('syll', {}).get('p95')} / {length.get('syll', {}).get('max')}"],
        ["超 300 字符句数", length.get("over_300")],
        ["超 30 词句数", length.get("over_30w")],
        ["超 60 音节句数", length.get("over_60syll")],
    ])
    ws3.append([])

    st = dims.get("sentence", {}) or {}
    sents_n = st.get("n", 0) or (length.get("n_sents") or 0)
    block("三、句式分布", [
        ["句式", "句数", "占比"],
    ] + [
        [k, v, (f"{100*v/sents_n:.1f}%" if sents_n else "")]
        for k, v in (st.get("types") or {}).items()
    ])
    ws3.append([])

    voc = dims.get("vocab", {}) or {}
    block("四、词汇分布", [
        ["指标", "值"],
        ["词例 token 总数", voc.get("tokens")],
        ["型符 unique", voc.get("types")],
        ["型符/词例", voc.get("ttr")],
        ["H_norm", voc.get("h_norm")],
        ["Gini", voc.get("gini")],
        ["Top10% 型符 token 份额", voc.get("top10_share")],
        ["ipa-dict 命中 token 占比", voc.get("dict_hit_ratio")],
        ["虚词 token 占比", voc.get("sw_ratio")],
        ["英语功能词 token 占比（近似）", voc.get("en_ratio")],
        ["NSW 命中句占比", voc.get("nsw_sent_ratio")],
        ["高频词 Top20", "、".join(f"{w}:{c}" for w, c in (voc.get("top", []) or [])[:20])],
    ])
    ws3.append([])

    ph = dims.get("phoneme", {}) or {}
    block("五、音素分布", [
        ["指标", "值"],
        ["词级单音素集合数", ph.get("n_single")],
        ["双音素组合数", ph.get("n_bi")],
        ["双音素总出现", ph.get("total_bi")],
        ["长尾双音素(<3次)数", ph.get("n_longtail_bi")],
        ["字母总数", (ph.get("letters") or {}).get("total")],
        ["字母种类", (ph.get("letters") or {}).get("n_types")],
        ["G2P 未覆盖 token 数", ph.get("g2p_miss")],
    ])
    ws3.append([])

    ety = dims.get("etymology", {}) or {}
    block("六、词源分布（LLM）", [
        ["指标", "值"],
        ["已打标词数", ety.get("tagged")],
        ["待打标词数", ety.get("untagged")],
        ["打标失败词数", ety.get("failed")],
    ] + [
        [f"origin={k}", v] for k, v in sorted((ety.get("origin") or {}).items())
    ])

    # ---------- Sheet4 字段说明 ----------
    ws4 = wb.create_sheet("字段说明")
    _header(ws4, ["类别", "字段名", "说明"])
    for c in src_cols:
        ws4.append(["原表字段", c, ORIGINAL_COLUMNS.get(c, "原回流表字段（透传）")])
    for name, desc, dtype in NEW_COLUMNS:
        ws4.append(["新增字段", name, f"{desc}（{dtype}）"])

    # ---------- 落盘 CSV（句子级明细） ----------
    csv_path = outdir / "数据集_全字段.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for row in ws.iter_rows(values_only=True):
            w.writerow(row)

    # ---------- manifest ----------
    manifest = {
        "run_id": run_params.get("run_id"),
        "lang": run_params.get("lang"),
        "seed": 0,
        "version": {"corpus_kit": __version__, "python": sys.version.split()[0]},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "file": str(run_params.get("input")),
            "sha256": _hash_file(Path(run_params["input"])) if run_params.get("input") and Path(run_params["input"]).exists() else None,
            "meta_columns": src_cols,
            "rows": len(records),
            "sentences": len(sentences),
        },
        "params": {k: v for k, v in run_params.items() if k not in ("input",)},
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    xlsx_path = outdir / "数据集_全字段.xlsx"
    wb.save(xlsx_path)
    return {"xlsx": str(xlsx_path), "csv": str(csv_path), "manifest": str(outdir / "manifest.json")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="report —— 汇总中间态出全字段报告")
    ap.add_argument("--out", required=True, help="output 运行目录")
    ap.add_argument("--meta", default=None, help="INPUT.meta.json 路径")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--input", default="")
    args = ap.parse_args(argv)
    outdir = ensure_dir(args.out)
    meta = {}
    meta_src = args.meta if (args.meta and Path(args.meta).exists()) else (outdir / "input_meta.json")
    if Path(meta_src).exists():
        meta = json.loads(Path(meta_src).read_text(encoding="utf-8-sig"))
    sentences = read_jsonl(outdir / "sentences.jsonl")
    records = read_jsonl(outdir / "records.jsonl")
    dims = {}
    for name in ("gate", "length", "sentence", "vocab", "phoneme", "etymology"):
        p = outdir / "dims" / f"{name}.json"
        if p.exists():
            dims[name] = json.loads(p.read_text(encoding="utf-8-sig"))
    out = build_report(outdir, meta, sentences, records, dims, {
        "run_id": args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S"),
        "lang": args.lang, "input": args.input,
    })
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
