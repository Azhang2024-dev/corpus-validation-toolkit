"""etymology_llm —— 词源打标：外部模型服务（endpoint+API key，OpenAI 兼容接口），按句逐词判源。
断点续跑：已打标 sent_id 跳过；JSON 容错：解析失败重试 1 次，仍失败标 etym_fail。
可用于测试的 --mock：本地起一个返回规则词源的 mock 服务（不依赖外网）。"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from corpus_kit.config import Config
from corpus_kit.g2p import load_ipa_dict
from corpus_kit.io import ensure_dir, read_jsonl, write_jsonl

VALID_ORIGINS = ["bantu_native", "arabic_loan", "english_loan", "other_loan", "uncertain"]
CANDIDATE_HINT = "可能的词源：bantu_native / arabic_loan / english_loan / other_loan / uncertain"


def build_prompt(words: list[str]) -> str:
    return (
        "你是斯瓦希里语(sw)语言学家。下面是一个句子里的词表（按出现顺序，word_id 从 0 开始）。"
        "请逐词判定词源，只输出一个 JSON 数组，不要任何解释：\n"
        f"[{{\"word_id\": 0, \"word\": \"{words[0]}\", \"origin\": \"bantu_native\"}}, ...]\n"
        f"候选词源 {VALID_ORIGINS}；{CANDIDATE_HINT}。\n"
        + "\n".join(f'{i}: {w}' for i, w in enumerate(words))
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

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        words = []
        content = body.get("messages", [{}])[-1].get("content", "") if body.get("messages") else ""
        for line in content.splitlines():
            m = re.match(r"(\d+): (.+)$", line.strip())
            if m:
                words.append((int(m.group(1)), m.group(2)))
        items = []
        for i, w in words:
            items.append({"word_id": i, "word": w,
                          "origin": "bantu_native" if w.lower() in (self.origins or {}) else "english_loan"})
        resp = json.dumps({"choices": [{"message": {"content": json.dumps(items, ensure_ascii=False)}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def call_llm(words, endpoint, model, api_key, timeout=120, retries=1):
    url = endpoint if endpoint.endswith("/chat/completions") else endpoint.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_prompt(words)}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            items = parse_json_response(content)
            if validate(items, words):
                return items
            last = f"validate_fail"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(1)
    return None


def validate(items, words) -> bool:
    if not isinstance(items, list) or len(items) != len(words):
        return False
    for idx, (item, w) in enumerate(zip(items, words)):
        if not isinstance(item, dict):
            return False
        if str(item.get("word_id")) != str(idx):
            return False
        if str(item.get("word", "")).strip().lower() != str(w).strip().lower():
            return False
        if item.get("origin") not in VALID_ORIGINS:
            return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="词源打标（LLM）")
    ap.add_argument("--sentences", required=True)
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 句（开发用）")
    ap.add_argument("--mock", action="store_true", help="本地 mock 服务（离线测试）")
    ap.add_argument("--audit", type=int, default=0, help="额外输出前 N 句人工抽检 CSV")
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args(argv)

    cfg = Config(args.lang)
    sents = read_jsonl(args.sentences)
    if args.limit:
        sents = sents[: args.limit]
    outdir = ensure_dir(args.out)

    daemon = None
    endpoint = args.endpoint or os.environ.get("LLM_ENDPOINT", "")
    model = args.model or os.environ.get("LLM_MODEL", "qwen3.6")
    api_key = args.api_key or os.environ.get("LLM_API_KEY", "")
    if args.mock:
        dict_words = load_ipa_dict(cfg.ipa_dict_path)
        MockHandler.origins = dict_words
        server = HTTPServer(("127.0.0.1", 0), MockHandler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{port}/v1"
        api_key = "mock"
        print(f"[mock] 本地词源服务已起: {endpoint}（命中 ipa-dict → bantu_native，其余 english_loan）", flush=True)
    if not endpoint:
        print(json.dumps({"error": "LLM_ENDPOINT 未配置：设置环境变量 LLM_ENDPOINT/LLM_MODEL/LLM_API_KEY，或 --mock 离线自测",
                          "tagged": 0, "untagged": len(sents), "failed": 0}, ensure_ascii=False))
        (outdir / "dims" / "etymology.json").write_text(
            json.dumps({"tagged": 0, "untagged": len(sents), "failed": 0, "origin": {}, "error": "not_configured"}, ensure_ascii=False), encoding="utf-8")
        return 1

    done_ids = set()
    ety_path = outdir / "etymology.jsonl"
    done_ids = {json.loads(l)["sent_id"] for l in ety_path.read_text(encoding="utf-8").splitlines() if l.strip()} if ety_path.exists() else set()

    tagged = failed = 0
    origin_cnt: dict = {}
    audit_rows: list[list] = []
    for s in sents:
        sid = s["sent_id"]
        text = s.get("text", "")
        words = list(dict.fromkeys(s.get("tokens") or []))
        if not words:
            tagged += 1
            s["etymology_status"] = "tagged"
            continue
        if sid in done_ids:
            tagged += 1
            s["etymology_status"] = "tagged"
            continue
        items = call_llm(words, endpoint, model, api_key)
        if items is None:
            failed += 1
            s["etymology_status"] = "etym_fail"
            continue
        for it in items:
            rec = {"sent_id": sid, "word_id": it["word_id"], "word": it["word"],
                   "origin": it["origin"], "ts": time.time()}
            with ety_path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            origin_cnt[it["origin"]] = origin_cnt.get(it["origin"], 0) + 1
            if args.audit and sid <= args.audit:
                audit_rows.append([sid, it["word_id"], it["word"], it["origin"]])
        tagged += 1
        s["etymology_status"] = "tagged"
    write_jsonl(outdir / "sentences.jsonl", sents)

    if args.audit and audit_rows:
        import csv
        with (outdir / "etymology_audit.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sent_id", "word_id", "word", "origin"])
            w.writerows(audit_rows)

    dims = {"tagged": tagged, "untagged": len(sents) - tagged - failed, "failed": failed, "origin": origin_cnt}
    ensure_dir(outdir / "dims")
    (outdir / "dims" / "etymology.json").write_text(json.dumps(dims, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(dims, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
