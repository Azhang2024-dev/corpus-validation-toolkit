"""io —— INPUT.txt + meta.json 读取，标准中间态 jsonl 读写。"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

from .reconstruct import cell_text, decode_cell


@dataclass
class Row:
    """行级记录：row_id 全局唯一；fields 透传原表字段；text 是待验证文本。"""
    row_id: int
    text: str
    fields: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"row_id": self.row_id, "text": self.text, "fields": self.fields, "meta": self.meta}


def ensure_dir(path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_meta(meta_path) -> dict:
    p = Path(meta_path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def read_jsonl(path, name: str | None = None) -> list[dict]:
    """读 jsonl → list[dict]。坏行**不静默丢**：计数并在 stderr 告警（可定位首行）。

    原实现 `except JSONDecodeError: continue` 会让损坏/截断的中间态文件悄悄缩小语料量，
    而报告上的所有数字都跟着变小、却看不出原因。这里把丢弃如实报出来。
    """
    p = Path(path)
    if not p.exists():
        return []
    out = []
    n_bad = 0
    first_bad = None
    for i, line in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            n_bad += 1
            if first_bad is None:
                first_bad = i
            continue
    if n_bad:
        print(f"[io] 警告：{name or p.name} 有 {n_bad} 行无法解析为 JSON，已丢弃"
              f"（首个：第 {first_bad} 行）。若文件被截断/损坏，下游计数会随之偏小，请核对。",
              file=sys.stderr)
    return out


def write_jsonl(path, items: Iterable[dict]) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def append_jsonl(path, item: dict) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_input_rows(input_txt, meta_path=None, limit: int | None = None) -> list[Row]:
    """读 INPUT.txt（UTF-8，一行一条）→ Row。\n
    带 meta 且含 columns 时按 \\t 分列、json 还原，兼容原表字段透传；\n
    否则整行视为待验证文本。

    单元格解码统一走 reconstruct.decode_cell/cell_text（与 split_tsv/split_csv 同契约）。
    行尾列缺失会**告警**（stderr），不再把文本列静默读成空串——那会让整批 gate 全 fail
    而看不出原因（原实现 `cells[j] if j < len(cells) else ""` 静默兜底）。
    """
    p = Path(input_txt)
    if not p.exists():
        return []
    meta = read_meta(meta_path) if meta_path else {}
    columns = meta.get("columns") or []
    text_col = meta.get("text_column")
    rows: list[Row] = []
    n_short = 0            # 列数不足的行数
    first_short = None     # 首个不足的行号（用于告警定位）
    raw = p.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    for i, line in enumerate(raw.split("\n"), start=1):
        line = line.strip()
        if not line:
            continue
        if columns:
            cells = line.split("\t")
            if len(cells) < len(columns):
                n_short += 1
                if first_short is None:
                    first_short = (i, len(cells), len(columns))
            fields: list[Any] = []
            text = ""
            for j, col in enumerate(columns):
                val = cells[j] if j < len(cells) else ""
                if col == text_col or (text_col is None and j == len(columns) - 1):
                    # 文本列：还原后强制成字符串；None（json null / 缺失列）视作空，
                    # 不能变成字面量 "None"（与 split_tsv/split_csv 同一契约）
                    text = cell_text(val)
                else:
                    fields.append(decode_cell(val))
            rows.append(Row(row_id=i, text=text, fields=fields, meta=meta))
        else:
            rows.append(Row(row_id=i, text=line, fields=[], meta=meta))
        if limit and len(rows) >= limit:
            break
    if n_short:
        line_no, got, want = first_short
        print(f"[io] 警告：{n_short} 行的列数少于 meta 声明的 {want} 列"
              f"（首个：第 {line_no} 行仅 {got} 列）。缺失列按空处理，"
              f"文本列因此可能为空——请核对 INPUT.txt 与 meta 是否同源。", file=sys.stderr)
    return rows
