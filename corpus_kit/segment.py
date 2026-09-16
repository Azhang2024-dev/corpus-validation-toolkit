"""segment —— 切句：换行 + 句末 .!? + 引号闭合保护（对齐 31,561 句实测口径）。"""
from __future__ import annotations


def split_sents(para: str) -> list[str]:
    """把整段/整行文本切成单句列表。规则与 _sent_probe.py 完全一致：
    换行（引号外）与句末标点（.!?）断句；『.』后紧跟字母/数字/『.』视为缩写/小数点不断；
    『.!?』后是空格/引号/右括号/又一句号等才断。"""
    out: list[str] = []
    buf = ""
    dq = sq = False
    i, n = 0, len(para)
    while i < n:
        ch = para[i]
        buf += ch
        if ch == '"':
            dq = not dq
        elif ch == "'":
            sq = not sq
        elif ch == "\n" and not dq and not sq:
            s = buf.rstrip(" \n")
            if s:
                out.append(s)
            buf = ""
        elif ch in ".!?" and not dq and not sq:
            nxt = para[i + 1 : i + 2] if i + 1 < n else ""
            nxt2 = para[i + 2 : i + 3] if i + 2 < n else ""
            if ch == "." and nxt and (nxt.isalnum() or nxt == "."):
                pass  # 缩写/小数点/省略号，不断
            elif nxt == "" or nxt in ' \n"\'「」“”)' or nxt2 == ".":
                s = buf.rstrip(" \n")
                if s:
                    out.append(s)
                buf = ""
        i += 1
    s = buf.rstrip(" \n")
    if s:
        out.append(s)
    return out
