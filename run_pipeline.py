"""run_pipeline —— 一键全流程：gate → length → sentence → vocab → [phoneme] → [etymology] → report。
每个 stage 是独立子进程（与 agent 分步调用同路径），幂等、可断点续跑、可跳过重环节。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS = ROOT / "skills"


def run(cmd: list[str], desc: str, verbose: bool = True) -> None:
    t0 = time.time()
    print(f"\n==> [{desc}] {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit(f"[{desc}] 失败 exit={proc.returncode}")
    print(f"    [{desc}] ok ({time.time() - t0:.1f}s)", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="语料验证工具集 · 一键全流程")
    ap.add_argument("--input", required=True, help="INPUT.txt 路径")
    ap.add_argument("--meta", default=None, help="INPUT.meta.json 路径（可选）")
    ap.add_argument("--lang", default="sw")
    ap.add_argument("--out", default=None, help="output 运行目录（默认 output/run_<ts>）")
    ap.add_argument("--skip-g2p", action="store_true", help="跳过音素（G2P）stage")
    ap.add_argument("--skip-etymology", action="store_true", help="跳过词源（LLM）stage")
    ap.add_argument("--etymology-mock", action="store_true", help="词源用本地 mock（离线自测）")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 行（开发用）")
    args = ap.parse_args(argv)

    outdir = Path(args.out) if args.out else ROOT / "output" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    outdir.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    meta_arg = ["--meta", args.meta] if args.meta else []
    limit_arg = ["--limit", str(args.limit)] if args.limit else []

    run([py, str(SKILLS / "gate_validity" / "run.py"), "--input", args.input, *meta_arg,
         "--lang", args.lang, "--out", str(outdir), *limit_arg], "gate_validity")
    run([py, str(SKILLS / "profile_length" / "run.py"), "--records", str(outdir / "records.jsonl"),
         "--out", str(outdir)], "profile_length (切句+长度)")
    run([py, str(SKILLS / "profile_sentence" / "run.py"), "--sentences", str(outdir / "sentences.jsonl"),
         "--lang", args.lang, "--out", str(outdir)], "profile_sentence (句式)")
    run([py, str(SKILLS / "profile_vocab" / "run.py"), "--records", str(outdir / "records.jsonl"),
         "--sentences", str(outdir / "sentences.jsonl"), "--lang", args.lang, "--out", str(outdir)], "profile_vocab (词汇)")
    if not args.skip_g2p:
        run([py, str(SKILLS / "profile_phoneme" / "run.py"), "--sentences", str(outdir / "sentences.jsonl"),
             "--lang", args.lang, "--out", str(outdir)], "profile_phoneme (G2P+音素)")
    if not args.skip_etymology:
        ety = [py, str(SKILLS / "etymology_llm" / "run.py"), "--sentences", str(outdir / "sentences.jsonl"),
               "--lang", args.lang, "--out", str(outdir)]
        if args.etymology_mock:
            ety.append("--mock")
        run(ety, "etymology_llm (词源)")
    run([py, "-m", "corpus_kit.report", "--out", str(outdir), "--lang", args.lang,
         "--input", args.input, *meta_arg], "report")

    # ---- 汇总 ----
    summary = {"outdir": str(outdir)}
    for name in ("gate", "length", "sentence", "vocab", "phoneme", "etymology"):
        p = outdir / "dims" / f"{name}.json"
        if p.exists():
            summary[name] = json.loads(p.read_text(encoding="utf-8-sig"))
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8-sig")) if (outdir / "manifest.json").exists() else {}
    print("\n================ 运行完成 ================")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("产物: ", manifest.get("input", {}).get("sentences"), "句 /", manifest.get("input", {}).get("rows"), "行")
    print("输出目录: ", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
