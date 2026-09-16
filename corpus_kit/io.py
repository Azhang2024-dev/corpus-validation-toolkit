"""io —— INPUT.txt + meta.json 读取，标准中间态 jsonl 读写。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable


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


def read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
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
    否则整行视为待验证文本。"""
    p = Path(input_txt)
    if not p.exists():
        return []
    meta = read_meta(meta_path) if meta_path else {}
    columns = meta.get("columns") or []
    text_col = meta.get("text_column")
    rows: list[Row] = []
    raw = p.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    for i, line in enumerate(raw.split("\n"), start=1):
        line = line.strip()
        if not line:
            continue
        if columns:
            cells = line.split("\t")
            fields: list[Any] = []
            text = ""
            for j, col in enumerate(columns):
                val = cells[j] if j < len(cells) else ""
                try:
                    val = json.loads(val) if val != "" else ""
                except json.JSONDecodeError:
                    pass
                if col == text_col or (text_col is None and j == len(columns) - 1):
                    text = str(val)
                else:
                    fields.append(val)
            rows.append(Row(row_id=i, text=text, fields=fields, meta=meta))
        else:
            rows.append(Row(row_id=i, text=line, fields=[], meta=meta))
        if limit and len(rows) >= limit:
            break
    return rows
