"""segment —— 切句：换行 + 句末标点 + 引号闭合保护（标点集由配置提供）。

sw 口径（冻结）：句末 `. ! ?`，`『.』后紧跟字母/数字/『.』视为缩写/小数点不断`，
`『.!?』后是空格/引号/右括号/又一句号等才断`。

多语种扩展（2026-09-18）：句末标点集从 `Config.sentence_enders` 读
（ur 加 `؟۔`、bn/hi 加 `।॥`、zh 加 `。！？`）；`Config.enders_greedy` 里的字符
**无需后随空格**也断句（东亚/印度标点常直接跟下一句）；引号对从 `Config.quote_pairs` 读。
不传 cfg 时保持历史 sw 行为（既有测试依赖）。
"""
from __future__ import annotations


def split_sents(para: str, enders: str = ".!?", quote_pairs=None,
                greedy: str = "") -> list[str]:
    """把整段/整行文本切成单句列表。

    规则：换行（引号外）与句末标点断句；`. `.后紧跟字母/数字/`.`视为缩写/小数点不断；
    `.!?` 后是空格/引号/右括号/又一句号等才断。

    每句两侧空白都剥掉（`strip` 而非只 `rstrip`）：断点后的前导空格不是内容，
    留着会让句级 `n_chars`（`len()`）系统性 +1。句数与断点位置一律不变。
    """
    out: list[str] = []
    buf = ""
    dq = sq = False
    pairs = [str(p) for p in (quote_pairs or ['""', "''"])]
    openers = {p[0] for p in pairs if p}
    closers = {p[-1] for p in pairs if len(p) > 1}
    i, n = 0, len(para)
    while i < n:
        ch = para[i]
        buf += ch
        if ch in openers and ch in closers:
            # 同形引号（" 与 '）：奇偶翻转
            if ch == '"':
                dq = not dq
            elif ch == "'":
                sq = not sq
        elif ch in openers:
            dq = True
        elif ch in closers:
            dq = False
        elif ch == "\n" and not dq and not sq:
            s = buf.strip(" \n\t")
            if s:
                out.append(s)
            buf = ""
        elif (ch in enders or ch in greedy) and not dq and not sq:
            nxt = para[i + 1 : i + 2] if i + 1 < n else ""
            nxt2 = para[i + 2 : i + 3] if i + 2 < n else ""
            if ch == "." and nxt and (nxt.isalnum() or nxt == "."):
                pass  # 缩写/小数点/省略号，不断
            elif ch in greedy:
                # 贪婪标点（。！？।॥ 等）：直接断，不要求后随空格
                s = buf.strip(" \n\t")
                if s:
                    out.append(s)
                buf = ""
            elif nxt == "" or nxt in ' \n"\'「」“”)' or nxt2 == ".":
                s = buf.strip(" \n\t")
                if s:
                    out.append(s)
                buf = ""
        i += 1
    s = buf.strip(" \n\t")
    if s:
        out.append(s)
    return out