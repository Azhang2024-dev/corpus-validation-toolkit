"""reconstruct —— 记录边界重建：把「整表 dump / 逐行 txt / 单列表」还原成一条一条记录。

工具集只认「一行一条」，但上游常给整段 dump（记录被引号包裹、内部引号双写转义、
记录内换行原样保留、记录之间没有稳定分隔符）。本模块负责把这类文件还原成逻辑记录，
**不做文本清洗**（清洗在 clean.py），只解决「哪些字节属于同一条记录」。

口径来源见 docs/语料清洗步骤调研_v1.md；实测：TTS_TEXT_SWAHILI.txt（2.5 MB）
按 dump 规则重建得 5038 条，其中 5037/5038 与 canonical 逐字相同。
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

# 新行归一：CRLF / CR / NEL / LS / PS → LF（\r\n 必须整体先替，否则会成为两个 LF）
_NEWLINE_RE = re.compile(r"\r\n|[\r\u0085\u2028\u2029]")
# 完整性核对用：剥掉引号与零宽字符，并把空白**连串折成一个空格**。
#
# 为什么这样定：
# - 引号是记录框架（包裹引号不是内容），零宽字符无内容语义 → 剥掉。
# - 空白只折「数量与形态」，不「丢弃」——因为重建会合法地改变边界空白的形态
#   （记录间的分隔换行 vs 拼接时的换行），但**丢失空白本身**正是边界重建最可能的
#   故障（记录拼错会粘词）。若把空白整个剥掉，断言就恰好瞎在它要防的风险上
#   （实测 `a b` 与 `ab` 会被误判为守恒）。
_STRIP_FOR_INTEGRITY_RE = re.compile(r"[\u200b\"]")
_WS_RUN_RE = re.compile(r"\s+")


def integrity_signature(text: str) -> str:
    """内容签名：剥引号/零宽 → 空白连串折成一个空格 → 去首尾。用于核对重建是否丢了内容。

    该签名对「空白的形态与数量」不敏感（重建会合法改变边界空白），
    但对「空白的有无」敏感——所以粘词/错切都能被发现。
    实测 TTS_TEXT_SWAHILI.txt：源与重建结果签名逐字符相等（2,078,263 字符）。
    """
    return _WS_RUN_RE.sub(" ", _STRIP_FOR_INTEGRITY_RE.sub("", text)).strip()

FORMATS = ("auto", "dump", "txt", "tsv", "csv")


@dataclass
class ReconstructResult:
    """records 为逻辑记录（已去包裹引号）；raw 保留原文片段备审。"""
    records: list[str] = field(default_factory=list)
    detected_format: str = ""
    n_physical_lines: int = 0
    n_records: int = 0
    separator: str = ""
    # 完整性核对：内容签名是否守恒（源 vs 重建）。
    #   True  = 守恒；
    #   False = 丢了内容（**防御性分支**：dump/txt 两条路径在构造上不会丢非引号内容——
    #           引号属框架、空白被签名归一，实测穷举 ~9000 组合均未触发；留此断言是为了
    #           兜住未来格式探测出错时「整段被错切/粘词」的回归，故宁可报错不可静默）；
    #   None  = 不适用（tsv/csv 是按列选取文本，少掉的列属于有意选择而非损失）。
    content_preserved: bool | None = True
    dropped_chars: int = 0

    def to_dict(self) -> dict:
        return {
            "detected_format": self.detected_format,
            "n_physical_lines": self.n_physical_lines,
            "n_records": self.n_records,
            "separator": self.separator,
            "content_preserved": self.content_preserved,
            "dropped_chars": self.dropped_chars,
        }


def normalize_newlines(text: str) -> str:
    return _NEWLINE_RE.sub("\n", text)


# ── 格式探测 ────────────────────────────────────────────────

def _looks_like_dump(text: str) -> bool:
    """整段 dump 特征：记录被引号包裹，故「引号层」会改变行结构。

    两个判据，满足其一即可（任一都只可能出现在引号包裹的 dump 上）：
      1. **跨行**：按引号解析出的记录数 < 非空物理行数（一条记录跨多个物理行）；
      2. **包裹**：多数非空行整行被引号包住（一条记录恰好一行，但内容带引号框架）。

    注意「以引号开头的行占比」不是好判据——多行 dump 里只有每条记录的**首行**以引号开头
    （实测 TTS_TEXT_SWAHILI.txt：21,140 非空行仅 7,187 行以引号开头，占 0.34），
    按占比判会漏检。
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return False
    try:
        parsed = [c for c in csv.reader(io.StringIO(text, newline=""), quotechar='"') if "".join(c).strip()]
    except Exception:
        return False
    if len(parsed) < len(lines):
        return True
    wrapped = sum(1 for l in lines if len(l) > 2 and l.startswith('"') and l.endswith('"'))
    return wrapped / len(lines) >= 0.5


def _stable_columns(text: str, delim: str, min_cols: int = 2) -> bool:
    """分隔符是否构成「稳定多列」：**所有**非空行的列数一致且 ≥ min_cols。

    要求完全一致是刻意的保守选择：散文里逗号数量随机起伏，多半行行不同，
    故不会被误判成 csv——而误判 csv 会静默取错列（危险），
    误判 txt 只是退化成「整行一条」（安全）。故一律偏向 txt。
    真实表格（ingest 产出的 tsv / 标准 csv）列数天然一致。
    """
    counts = [len(l.split(delim)) for l in text.split("\n") if l.strip()]
    if len(counts) < 2 or min(counts) < min_cols:
        return False
    return len(set(counts)) == 1


def _stable_reader_columns(text: str, delim: str, quotechar: str = '"',
                           min_cols: int = 2) -> bool:
    """把 text 交给 csv.reader（让引号层处理跨行/转义）后，所有记录列数是否稳定且 ≥ min_cols。

    这是 `_stable_columns` 的**引号感知**版本，专为「多列 csv、文本列含多行引号单元格」而设：
    这种文件按物理行数 `split(delim)` 得不到稳定列（引号内的换行会打断行），
    只能先过引号层。dump 文件（单列、记录被引号包裹）经此解析列数不稳定 → 不会误判成 csv。
    """
    try:
        recs = [r for r in csv.reader(io.StringIO(text, newline=""), quotechar=quotechar)
                if any(c.strip() for c in r)]
    except Exception:
        return False
    if len(recs) < 2:
        return False
    counts = {len(r) for r in recs}
    return len(counts) == 1 and min(counts) >= min_cols


def detect_format(text: str, hint: str = "auto") -> str:
    """探测格式。顺序有意如此：

    1. **先判 tsv 的稳定列结构**（按物理行）——稳定的多列是表格的铁证，且必须先于 dump 判：
       带引号的多行单元格（如项目自己的固有多列 tsv `input/INPUT.txt`）会被引号层
       看成「记录跨行」，误判成 dump 后按单列拼回，会把整行搞成乱码（实测踩到）。
    2. 再判 **csv 的引号感知稳定列**——多列 csv 且文本列含多行引号单元格时，
       物理行上得不到稳定列，必须先过引号层才能识别（否则会误判 dump、按单列拼串丢列）。
    3. 再判 dump（引号包裹、记录跨行）。
    4. 都不像 → txt（逐行整条，最安全）。
    """
    if hint and hint != "auto":
        return hint
    if _stable_columns(text, "\t"):
        return "tsv"
    if _stable_reader_columns(text, ",", min_cols=2):
        return "csv"
    if _looks_like_dump(text):
        return "dump"
    if _stable_columns(text, ","):
        return "csv"
    return "txt"


# ── 各格式的切分 ────────────────────────────────────────────

def _strip_wrapper(s: str) -> str:
    s = s.strip()
    if len(s) > 1 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s.strip()


def split_dump(text: str, quotechar: str = '"', doublequote: bool = True,
               join_with: str = ",") -> list[str]:
    """按 CSV 引号规则切整段 dump。

    用 csv.reader 让引号层负责「记录跨行 + 双写转义」，再把同一条记录被切开的 cell
    用字段分隔符拼回。这是实测口径：合成过 5037/5038 行的逐字一致。
    """
    buf = io.StringIO(text, newline="")
    reader = csv.reader(buf, quotechar=quotechar, doublequote=doublequote)
    recs: list[str] = []
    for cells in reader:
        joined = join_with.join(cells).strip()
        if joined:
            recs.append(joined)
    return recs


def split_tsv(text: str, text_col: int = -1) -> list[str]:
    """逐行 tsv：按 \\t 分列，取文本列（默认最后一列）。

    单元格若是 json 编码则还原——与 corpus_kit.io.read_input_rows 同契约
    （ingest_xlsx.py 产出的 INPUT.txt 每格都是 json.dumps 过的）。
    """
    out = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        cells = line.split("\t")
        idx = text_col if text_col >= 0 else len(cells) - 1
        val = cells[idx] if idx < len(cells) else ""
        out.append(cell_text(val))
    return out


# ── 单元格解码（split_tsv / split_csv 与 io.read_input_rows 共用同一契约）──
# 放在本模块是因为它是「解析外部文件」的口径来源；io 反过来 import 它，
# 避免同一条规则在两地各写一遍后漂移（此前正是如此：`null`/纯数字在两条路径上结果不同）。

def decode_cell(val: str):
    """单元格文本 → Python 值：空串保持空串；能 json 解析则解析，否则原样返回字符串。

    统一契约：`null`→None、`123`→123、`"x"`→x、纯文本→原文本。
    此前 split_tsv 只在以 `"`/`[`/`{` 开头时才解析，导致 `null`/数字一路得字符串、
    read_input_rows 一路得 None/数字。
    """
    if val == "":
        return ""
    try:
        return json.loads(val)
    except (json.JSONDecodeError, ValueError):
        return val


def cell_text(val: str) -> str:
    """单元格文本 → 文本列取值：json 还原后强制成字符串，None 视作空（不是字面量 "None"）。"""
    v = decode_cell(val)
    return "" if v is None else str(v)


def split_csv(text: str, text_col: int = -1, quotechar: str = '"',
              doublequote: bool = True) -> list[str]:
    """逐记录 csv：过引号层（跨行/转义），取文本列（默认最后一列）。

    与 split_tsv 同契约：`--text-col` 对 csv 同样生效（此前只对 tsv 生效，
    帮助文本却承诺「tsv/csv」——多列 csv 会被整行逗号拼串、丢掉选列语义）。
    单元格若是 json 编码则还原。
    """
    out: list[str] = []
    buf = io.StringIO(text, newline="")
    for cells in csv.reader(buf, quotechar=quotechar, doublequote=doublequote):
        if not any(c.strip() for c in cells):
            continue
        idx = text_col if text_col >= 0 else len(cells) - 1
        val = cells[idx] if idx < len(cells) else ""
        out.append(cell_text(val))
    return out


def split_plain(text: str) -> list[str]:
    """逐行 txt：一行一条（去包裹引号）。"""
    return [r for r in (_strip_wrapper(l) for l in text.split("\n")) if r]


def reconstruct(text: str, fmt: str = "auto", *, quotechar: str = '"',
                doublequote: bool = True, join_with: str = ",",
                text_col: int = -1, normalize_nl: bool = True) -> ReconstructResult:
    """把原文还原成逻辑记录列表。fmt='auto' 时按特征探测。

    重建后做**内容守恒核对**：源与重建结果的内容签名（剥空白与引号）必须相等，
    否则 `content_preserved=False`、`dropped_chars>0`——这是「重建有没有丢东西」的
    可验证断言，不靠猜（引号奇偶之类的启发式判不准，已弃用）。
    tsv/csv 按列取文本，少掉的列属有意选择，故该项为 None（不适用）。
    """
    if normalize_nl:
        text = normalize_newlines(text)
    detected = detect_format(text, fmt)

    if detected == "dump":
        recs = split_dump(text, quotechar, doublequote, join_with)
        sep = "quote-wrapped / newline-preserving"
    elif detected == "csv":
        recs = split_csv(text, text_col, quotechar, doublequote)
        sep = ","
    elif detected == "tsv":
        recs = split_tsv(text, text_col)
        sep = "\\t"
    else:
        recs = split_plain(text)
        sep = "\\n"

    if detected in ("dump", "txt"):
        src_sig = integrity_signature(text)
        # 记录之间用**一个空格**拼接：记录分隔符（换行/引号）是框架不是内容，
        # 用 "" 拼会把合法的记录边界当成「丢了空白」而误报。
        rec_sig = integrity_signature(" ".join(recs))
        preserved: bool | None = src_sig == rec_sig
        dropped = abs(len(src_sig) - len(rec_sig))
    else:
        preserved, dropped = None, 0

    return ReconstructResult(
        records=recs,
        detected_format=detected,
        n_physical_lines=len([l for l in text.split("\n") if l.strip()]),
        n_records=len(recs),
        separator=sep,
        content_preserved=preserved,
        dropped_chars=dropped,
    )