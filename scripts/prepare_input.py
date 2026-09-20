"""prepare_input —— 辅助（不在验证管线内）：文本语料 → 清洗后 INPUT.txt + meta + 清理报告。

上游给的东西格式不可预期（整段 dump / 逐行 txt / tsv / csv），行边界可能已丢。
本脚本负责「接入 + 清洗」，产出验证工具集唯一入口 INPUT.txt（一行一条）+ 审计产物：

  INPUT.txt / INPUT.meta.json     验证管线入口（契约同 ingest_xlsx.py）
  clean_report.json / .csv        干了什么：逐条 flag、阈值、计数、输入 sha256
  quarantine.jsonl                剔除了什么、为什么（含完整原文，可回滚）
  clean_manifest.json             本次跑的入参 / 阈值 / 版本 / seed → 可复现

边界：只做清洗，不做语言准入（那是 gate 的活）；不改验证管线任何代码。
**不吃 xlsx**（二进制，会读坏）——xlsx 请先走 scripts/ingest_xlsx.py。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus_kit.clean import GRAPHEME_RE, clean_config, clean_records, summarize
from corpus_kit.reconstruct import FORMATS, reconstruct

ROOT = Path(__file__).resolve().parents[1]


def read_source(path: Path) -> str:
    """读源文件：UTF-8 严格优先；BOM 容错；可选 chardet/ftfy 降级修复。

    降级时会在 stderr 如实说明用了什么编码/是否做了 mojibake 修复（不静默）。
    """
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # 非 UTF-8：探测编码 + mojibake 修复（未装依赖则降级，并**打印说明**）
    note = []
    try:
        import chardet  # type: ignore
        guess = chardet.detect(data[:65536]) or {}
        enc = guess.get("encoding") or "latin-1"
        text = data.decode(enc, errors="replace")
    except Exception:
        enc = "latin-1"
        text = data.decode(enc, errors="replace")
    note.append(f"非 UTF-8，按 {enc} 解码（errors=replace）")
    try:
        import ftfy  # type: ignore
        text = ftfy.fix_text(text)
        note.append("已做 ftfy mojibake 修复")
    except Exception:
        note.append("ftfy 未安装，跳过 mojibake 修复")
    print("[prepare_input] " + "；".join(note), file=sys.stderr)
    return text


def write_report(outdir: Path, src: Path, sha: str, fmt: str, recon: dict,
                 summary: dict, rows: list[dict], cfg) -> None:
    report = {
        "source": src.name,
        "input_sha256": sha,
        "detected_format": fmt,
        "reconstruct": recon,
        "thresholds": cfg.raw,
        "summary": summary,
        "rows": rows,
    }
    (outdir / "clean_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # CSV：逐条一行，便于透视
    import csv as _csv
    with (outdir / "clean_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["index", "kept", "hard_flags", "soft_flags", "n_graphemes", "text_preview"])
        for r in rows:
            hard = ";".join(x for x in r["flags"] if x.startswith("hard:"))
            soft = ";".join(x for x in r["flags"] if x.startswith("soft:"))
            # 列名是 n_graphemes，就必须是字素簇数（不是码点数）——本模块的硬口径
            w.writerow([r["index"], int(r["kept"]), hard, soft,
                        len(GRAPHEME_RE.findall(r["text"])), r["text"][:120]])


def main(argv=None):
    ap = argparse.ArgumentParser(description="任意格式语料 → 清洗后 INPUT.txt + 报告")
    ap.add_argument("--input", required=True, help="源文件（dump/txt/tsv/csv）")
    ap.add_argument("--format", default="auto", choices=FORMATS, help="格式；默认自动探测")
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--out-dir", default="input_clean", help="输出目录")
    ap.add_argument("--text-col", type=int, default=-1, help="tsv/csv 文本列下标（默认最后一列）")
    ap.add_argument("--dry-run", action="store_true", help="只分析出报告，不写 INPUT.txt")
    ap.add_argument("--fuzzy", action="store_true", help="启用模糊近重去重")
    ap.add_argument("--no-dedup", action="store_true", help="关闭去重")
    ap.add_argument("--keep-quarantined", action="store_true",
                    help="把质检不通过的行也写进 INPUT.txt（默认剔除）")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"源文件不存在：{src}")
    raw_text = read_source(src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()

    cfg = clean_config()
    recon = reconstruct(raw_text, args.format, quotechar=cfg.quotechar,
                        doublequote=cfg.doublequote, join_with=cfg.join_with,
                        text_col=args.text_col)
    # 内容守恒断言：重建丢了内容必须**当场报错**，不许静默出报告
    # （丢失意味着记录被错切/粘词，下游所有指标都是假的）。tsv/csv 取列时该检查为 None。
    if recon.content_preserved is False:
        raise SystemExit(
            f"重建丢内容：源与重建的内容签名不相等（差 {recon.dropped_chars} 字符）。"
            f"疑似格式判断错误或记录被错切，请人工核对后重跑（可加 --format 显式指定）。")
    if args.no_dedup and args.fuzzy:
        raise SystemExit("--no-dedup 与 --fuzzy 互斥：前者要求完全不去重，后者要求做模糊近重。")
    if args.no_dedup:
        cfg = clean_config(dedup={"exact": False, "fuzzy": False})
    res = clean_records(recon.records, cfg, fuzzy=(args.fuzzy or None))
    rows, dedup = res["rows"], res["dedup"]
    summary = summarize(rows, dedup)

    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    kept_rows = [r for r in rows if r["kept"]]
    if args.keep_quarantined:
        # 只放回「被硬规则剔除的」，重复项仍需去重（否则下游会拿到重复语料）
        kept_rows = [r for r in rows if r["index"] in set(dedup["keep"])]
    # summary.n_kept 是「默认剔除硬行」口径（clean.summarize 里排除了 hard）。
    # --keep-quarantined 把硬行放回了 INPUT.txt，实际保留数应以 kept_rows 为准，
    # 否则 manifest.counts 与 INPUT.txt/meta.rows 会互相打架。此处覆盖为同一口径。
    if args.keep_quarantined:
        summary = {**summary, "n_kept": len(kept_rows),
                   "n_quarantined": summary["n_in"] - len(kept_rows)}

    if not args.dry_run:
        with (outdir / "INPUT.txt").open("w", encoding="utf-8", newline="\n") as f:
            for r in kept_rows:
                f.write(json.dumps(r["text"], ensure_ascii=False) + "\n")

        meta = {
            "source": src.name, "lang": args.lang,
            "columns": ["__text__"], "text_column": "__text__",
            "rows": len(kept_rows),
            "sha256": sha,
            "clean": {
                "prepared_at": datetime.now().isoformat(timespec="seconds"),
                "detected_format": recon.detected_format,
                "n_records_in": recon.n_records,
                "n_kept": len(kept_rows),
                "n_quarantined": summary["n_quarantined"],
                "n_dedup_dropped": summary["n_dedup_dropped"],
            },
            "note": "由 scripts/prepare_input.py 清洗产出；一行一条；逐条审计见 clean_report.json",
        }
        (outdir / "INPUT.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # quarantine：剔除项逐条落盘（可回滚）
        drop_idx = {d[0]: d[1] for d in dedup["drop"]}
        with (outdir / "quarantine.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                if r["kept"]:
                    continue
                reason = [x for x in r["flags"] if x.startswith("hard:")]
                if r["index"] in drop_idx:
                    reason = ["duplicate_of:%d" % drop_idx[r["index"]]]
                # raw/cleaned 写全，不截断——本文件是「可回滚」的依据，
                # 截断会让长记录无法还原（实测 596 条里有 27 条超 400 字符）。
                f.write(json.dumps({
                    "index": r["index"], "reason": reason,
                    "soft_flags": [x for x in r["flags"] if x.startswith("soft:")],
                    "raw": r["raw"], "cleaned": r["text"],
                }, ensure_ascii=False) + "\n")

        (outdir / "clean_manifest.json").write_text(json.dumps({
            "input": src.name, "input_sha256": sha, "lang": args.lang,
            "format": recon.detected_format, "seed": 0,
            "params": {"dry_run": False, "fuzzy": bool(args.fuzzy),
                       "no_dedup": bool(args.no_dedup),
                       "keep_quarantined": bool(args.keep_quarantined)},
            "counts": summary,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    write_report(outdir, src, sha, recon.detected_format, recon.to_dict(),
                 summary, rows, cfg)

    print(json.dumps({
        "format": recon.detected_format,
        "n_physical_lines": recon.n_physical_lines,
        "n_records": recon.n_records,
        **summary,
        "out_dir": str(outdir),
        "dry_run": bool(args.dry_run),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())