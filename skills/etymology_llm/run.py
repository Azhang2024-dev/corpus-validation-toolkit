"""etymology_llm —— 词源打标：外部模型服务（endpoint+API key，OpenAI 兼容接口）。

口径（2026-09-16 定稿）：**全局词级去重**。
  整批语料按 token 提取全部词 → 去重 → 仅对「尚未打标」的词分批送模型，一个词只判一次。
  （旧「按句逐词」口径对同一个词重复调用 N 次，故废弃：实测调用数由 31,561 句
   降到 ceil(unique_words / batch_size)，约数百次。）
产物：
  etymology.jsonl      词级：一行一个词 {word, origin, ts}
  dims/etymology.json  词级聚合（origin 按 token 加权 / origin_words 按型符）
断点续跑：已打标词跳过；JSON 容错：解析失败重试 1 次，仍失败计入 failed。
离线自测：--mock 本地规则服务；--verify 自检不变量（去重生效 / 全覆盖 / 续跑幂等）。"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.config import Config
from corpus_kit.g2p import load_ipa_dict
from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl

VALID_ORIGINS = ["bantu_native", "arabic_loan", "english_loan", "other_loan", "uncertain"]
CANDIDATE_HINT = "可能的词源：bantu_native / arabic_loan / english_loan / other_loan / uncertain"
WORD_HAS_LETTER = re.compile(r"[a-z]")
BULLET_RE = re.compile(r"^-\s+(.+)$")


def _ety_spec(cfg=None) -> tuple[str, list, str]:
    """词源口径（语言 yaml 提供）：(语言名, 候选词源, 提示语)。缺配置时用 sw 默认（历史口径）。"""
    if cfg is None:
        return "斯瓦希里语(sw)", VALID_ORIGINS, CANDIDATE_HINT
    name = getattr(cfg, "ety_prompt_name", None) or getattr(cfg, "label", "目标语言")
    origins = list(getattr(cfg, "ety_valid_origins", None) or VALID_ORIGINS)
    hint = getattr(cfg, "ety_candidate_hint", None) or (
        "可能的词源：" + " / ".join(origins))
    return name, origins, hint


def build_prompt(words: list[str], cfg=None) -> str:
    """词键 JSON：请求去重后的词表，要求逐词返回 {word, origin}。"""
    name, origins, hint = _ety_spec(cfg)
    return (
        f"你是{name}语言学家。下面是去重后的词表（每行一个词）。"
        "请逐词判定词源，只输出一个 JSON 数组，不要任何解释：\n"
        f"[{{\"word\": \"{words[0] if words else 'word'}\", \"origin\": \"{origins[0] if origins else 'uncertain'}\"}}, ...]\n"
        f"候选词源 {origins}；{hint}。\n"
        "词表：\n"
        + "\n".join(f"- {w}" for w in words)
    )


def parse_json_response(content: str):
    """剥离 markdown 围栏后取第一个 JSON 数组。"""
    if not content:
        return None
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.M)
    m = re.search(r"\[.*\]", content, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else None
    except Exception:
        return None


class MockHandler(BaseHTTPRequestHandler):
    origins = None
    valid_origins = None

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        content = body.get("messages", [{}])[-1].get("content", "") if body.get("messages") else ""
        words = [m.group(1).strip() for m in
                 (BULLET_RE.match(line.strip()) for line in content.splitlines()) if m]
        valid = list(self.valid_origins or VALID_ORIGINS)
        # mock 口径：词典命中 → 第一个候选（原生类）；未命中 → english_loan（若候选里有，
        # 保持 sw 历史 mock 行为以对齐既有测试），否则取第一个 *_loan，再退 uncertain
        native = valid[0] if valid else "uncertain"
        if "english_loan" in valid:
            loan = "english_loan"
        else:
            loan = next((o for o in valid if o.endswith("_loan")), "uncertain")
        items = [{"word": w,
                  "origin": native if w.lower() in (self.origins or {}) else loan}
                 for w in words]
        resp = json.dumps({"choices": [{"message": {"content": json.dumps(items, ensure_ascii=False)}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def call_llm(words, endpoint, model, api_key, timeout=120, retries=1, cfg=None):
    url = endpoint if endpoint.endswith("/chat/completions") else endpoint.rstrip("/") + "/chat/completions"
    origins = list(getattr(cfg, "ety_valid_origins", None) or VALID_ORIGINS) if cfg else VALID_ORIGINS
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_prompt(words, cfg)}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    for _ in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            items = parse_json_response(data["choices"][0]["message"]["content"])
            if validate(items, words, origins):
                return items
        except Exception:
            pass
        time.sleep(1)
    return None


def validate(items, words, origins=None) -> bool:
    """词键校验：返回词集必须与请求词集完全一致（忽略顺序），且 origin 合法。"""
    valid = list(origins or VALID_ORIGINS)
    if not isinstance(items, list) or len(items) != len(words):
        return False
    want = [str(w).strip().lower() for w in words]
    got: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            return False
        w = str(item.get("word", "")).strip().lower()
        if not w or item.get("origin") not in valid:
            return False
        got.append(w)
    return Counter(got) == Counter(want)


def token_has_letter(t: str) -> bool:
    """token 是否含字母（语言无关：isalpha 依 Unicode 属性，非拉丁脚本同样成立）。"""
    return any(c.isalpha() for c in (t or ""))


def candidate_counts(sents) -> Counter:
    """全批 token 词频：仅保留含字母的词（纯符号/数字不进词源）。"""
    c: Counter = Counter()
    for s in sents:
        for t in s.get("tokens") or []:
            if t and token_has_letter(t):
                c[t] += 1
    return c


def order_words(counts: Counter) -> list[str]:
    """确定性排序：频次降序，同频按字典序（保证断点续跑与 --limit 可复现）。"""
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def chunk(seq: list, size: int) -> list[list]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def load_done(ety_path) -> dict:
    """已打标词 → origin（断点续跑用）。"""
    done: dict[str, str] = {}
    p = Path(ety_path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done[rec["word"]] = rec["origin"]
            except Exception:
                continue
    return done


def tag_words(words, endpoint, model, api_key, batch_size, ety_path, audit_n=0, cfg=None):
    """按批打标（只传未打标词）；追加写 etymology.jsonl。

    返回 (n_calls, failed_words, audit_rows)。"""
    n_calls = 0
    failed: list[str] = []
    audit_rows: list[list] = []
    for batch in chunk(words, batch_size):
        items = call_llm(batch, endpoint, model, api_key, cfg=cfg)
        n_calls += 1
        if items is None:
            failed.extend(batch)
            continue
        got = {str(it["word"]).strip().lower(): it["origin"] for it in items}
        with ety_path.open("a", encoding="utf-8", newline="\n") as f:
            for w in batch:
                o = got.get(w, "uncertain")
                f.write(json.dumps({"word": w, "origin": o, "ts": time.time()}, ensure_ascii=False) + "\n")
                if audit_n and len(audit_rows) < audit_n:
                    audit_rows.append([w, o])
    return n_calls, failed, audit_rows


def run_tagging(sents, endpoint, model, api_key, outdir, batch_size, audit_n=0, cfg=None):
    """核心：全批去重 → 仅对未打标词分批调用 → 落 etymology.jsonl + dims + 回写句级状态。"""
    outdir = ensure_dir(outdir)
    counts = candidate_counts(sents)
    all_words = order_words(counts)
    ety_path = outdir / "etymology.jsonl"

    done = load_done(ety_path)
    todo = [w for w in all_words if w not in done]
    n_calls = 0
    failed: list[str] = []
    audit_rows: list[list] = []
    if todo:
        n_calls, failed, audit_rows = tag_words(todo, endpoint, model, api_key, batch_size, ety_path,
                                                audit_n, cfg=cfg)
        done = load_done(ety_path)

    # 统计只在**本批词集内**做：done 会载入 etymology.jsonl 的全部历史词，
    # 输出目录复用于另一批（或更小批）语料时会引入不在本批的旧词——
    # 旧词按 weight=1 计入 origin 会污染分布，且 untagged 可能算出负数。
    # 残留词单独记为 stale，不计入 tagged/untagged/origin。
    done_batch = {w: o for w, o in done.items() if w in counts}
    n_stale = len(done) - len(done_batch)

    if audit_n:
        with (outdir / "etymology_audit.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["word", "origin"])
            for word, o in audit_rows:
                w.writerow([word, o])

    origin_tokens: Counter = Counter()   # 按 token 加权
    origin_words: Counter = Counter()    # 按型符
    for w, o in done_batch.items():
        origin_words[o] += 1
        origin_tokens[o] += counts[w]

    for s in sents:
        toks = [t for t in (s.get("tokens") or []) if t and token_has_letter(t)]
        if not toks:
            s["etymology_status"] = "tagged" if done_batch else "untagged"
        else:
            hit = sum(1 for t in toks if t in done_batch)
            if hit == len(toks):
                s["etymology_status"] = "tagged"
            elif hit:
                s["etymology_status"] = "partial"
            else:
                s["etymology_status"] = "etym_fail" if failed else "untagged"
    write_jsonl(outdir / "sentences.jsonl", sents)

    dims = {
        "unique_words": len(all_words),
        "token_total": sum(counts.values()),
        "tagged": len(done_batch),
        "untagged": len(all_words) - len(done_batch),
        "failed": len(failed),
        "stale": n_stale,
        "calls": n_calls,
        "batch_size": batch_size,
        "origin": dict(sorted(origin_tokens.items(), key=lambda kv: -kv[1])),
        "origin_words": dict(sorted(origin_words.items(), key=lambda kv: -kv[1])),
    }
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "etymology.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    return dims


def _start_mock(cfg) -> str:
    MockHandler.origins = load_ipa_dict(cfg.ipa_dict_path)
    MockHandler.valid_origins = list(getattr(cfg, "ety_valid_origins", None) or VALID_ORIGINS)
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/v1"


def verify(sents, cfg, batch_size) -> tuple[bool, dict]:
    """自检不变量（单进程 mock，不需要真 LLM）：
    V1 去重生效：调用数 == ceil(unique_words / batch_size)
    V2 全覆盖 + origin 合法：每个 unique word 恰好一个合法标签
    V3 续跑幂等：复跑 0 次调用
    V4 词级形态：etymology.jsonl 行数 == unique_words"""
    endpoint = _start_mock(cfg)
    problems: list[str] = []
    stats2: dict = {}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        counts = candidate_counts(sents)
        all_words = order_words(counts)
        uniq = len(all_words)
        stats = run_tagging(sents, endpoint, "mock", "mock", td, batch_size, cfg=cfg)
        expect_calls = math.ceil(uniq / batch_size) if uniq else 0
        if uniq == 0:
            problems.append("V1: 无候选词，无法验证")
        elif stats["calls"] != expect_calls:
            problems.append(f"V1 去重未生效：calls={stats['calls']} 应为 {expect_calls}")
        if stats["tagged"] != uniq:
            problems.append(f"V2 覆盖不全：tagged={stats['tagged']} uniq={uniq}")
        if stats["failed"]:
            problems.append(f"V2 有失败词：failed={stats['failed']}")
        done = load_done(td / "etymology.jsonl")
        bad = [w for w in all_words if w not in done]
        if bad:
            problems.append(f"V2 缺词 {len(bad)} 个，如 {bad[:5]}")
        valid_origins = list(getattr(cfg, "ety_valid_origins", None) or VALID_ORIGINS)
        for o in set(done.values()):
            if o not in valid_origins:
                problems.append(f"V2 非法 origin: {o}")
                break
        lines = [l for l in (td / "etymology.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) != uniq:
            problems.append(f"V4 jsonl 行数 {len(lines)} != unique_words {uniq}")
        stats2 = run_tagging(read_jsonl(td / "sentences.jsonl"), endpoint, "mock", "mock", td, batch_size, cfg=cfg)
        if stats2["calls"] != 0:
            problems.append(f"V3 续跑非幂等：第二次 calls={stats2['calls']} 应为 0")
    verdict = {
        "verify": "pass" if not problems else "fail",
        "unique_words": uniq,
        "batch_size": batch_size,
        "expected_calls": math.ceil(uniq / batch_size) if uniq else 0,
        "rerun_calls": stats2.get("calls"),
        "problems": problems,
    }
    return (not problems), verdict


def main(argv=None):
    ap = argparse.ArgumentParser(description="词源打标（LLM，全局词级去重）")
    ap.add_argument("--sentences", required=True)
    ap.add_argument("--lang", required=True, help="language code or auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="只取前 N 句（开发用）")
    ap.add_argument("--batch-size", type=int, default=None, help="每批词数（默认 LLM_BATCH_SIZE 或 30）")
    ap.add_argument("--mock", action="store_true", help="本地 mock 服务（离线测试）")
    ap.add_argument("--verify", action="store_true", help="自检不变量：去重生效/全覆盖/续跑幂等（不需真 LLM）")
    ap.add_argument("--audit", type=int, default=0, help="额外输出前 N 个词的人工抽检 CSV")
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    batch_size = args.batch_size or int(os.environ.get("LLM_BATCH_SIZE", "30") or 30)
    sents = read_jsonl(args.sentences)
    if args.limit:
        sents = sents[: args.limit]
    outdir = ensure_dir(args.out)

    if args.verify:
        ok, verdict = verify(sents, cfg, batch_size)
        # 记录验证结论（真词源未跑，故 tagged=0）；报告据此显示链路已校验
        verdict_dims = {
            "unique_words": verdict["unique_words"],
            "token_total": sum(candidate_counts(sents).values()),
            "tagged": 0, "untagged": verdict["unique_words"], "failed": 0,
            "calls": 0, "batch_size": batch_size,
            "origin": {}, "origin_words": {},
            "verify": verdict["verify"],
            "verify_detail": verdict,
        }
        ensure_dir(outdir / "dims")
        (outdir / "dims" / "etymology.json").write_text(json.dumps(verdict_dims, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(verdict, ensure_ascii=False))
        return 0 if ok else 1

    endpoint = args.endpoint or os.environ.get("LLM_ENDPOINT", "")
    model = args.model or os.environ.get("LLM_MODEL", "qwen3.6")
    api_key = args.api_key or os.environ.get("LLM_API_KEY", "")
    if args.mock:
        endpoint = _start_mock(cfg)
        api_key = "mock"
        print(f"[mock] 本地词源服务已起: {endpoint}（命中 ipa-dict → bantu_native，其余 english_loan）", flush=True)
    if not endpoint:
        print(json.dumps({"error": "LLM_ENDPOINT 未配置：设置环境变量 LLM_ENDPOINT/LLM_MODEL/LLM_API_KEY，或 --mock 离线自测",
                          "tagged": 0, "untagged": 0, "failed": 0}, ensure_ascii=False))
        ensure_dir(outdir / "dims")
        (outdir / "dims" / "etymology.json").write_text(
            json.dumps({"unique_words": 0, "tagged": 0, "untagged": 0, "failed": 0,
                        "calls": 0, "origin": {}, "origin_words": {}, "error": "not_configured"},
                       ensure_ascii=False), encoding="utf-8")
        return 1

    dims = run_tagging(sents, endpoint, model, api_key, outdir, batch_size, args.audit, cfg=cfg)
    print(json.dumps(dims, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())