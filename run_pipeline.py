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


def _run_args(args) -> dict:
    """把本次实际入参记进 manifest——没有它，--limit 批次与全量跑在产物上无法区分
    （output/README.md 记录的 run_full 混合批次事故正是因此事后才发现）。"""
    return {
        "limit": args.limit,
        "skip_g2p": bool(args.skip_g2p),
        "skip_etymology": bool(args.skip_etymology),
        "etymology_mock": bool(args.etymology_mock),
        "etymology_verify": bool(args.etymology_verify),
        "etymology_batch_size": args.etymology_batch_size,
        "audit_n": args.audit_n,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="语料验证工具集 · 一键全流程")
    ap.add_argument("--input", required=True, help="INPUT.txt 路径")
    ap.add_argument("--meta", default=None, help="INPUT.meta.json 路径（可选）")
    ap.add_argument("--lang", required=True, help="language code or auto")
    ap.add_argument("--out", default=None, help="output 运行目录（默认 output/run_<ts>）")
    ap.add_argument("--skip-g2p", action="store_true", help="跳过音素（G2P）stage")
    ap.add_argument("--skip-etymology", action="store_true", help="跳过词源（LLM）stage")
    ap.add_argument("--etymology-mock", action="store_true", help="词源用本地 mock（离线自测）")
    ap.add_argument("--etymology-verify", action="store_true",
                    help="只验证词源链路（去重/覆盖/续跑不变量），不写真 LLM 结果，不阻塞出报告")
    ap.add_argument("--etymology-batch-size", type=int, default=None, help="词源每批词数（默认 LLM_BATCH_SIZE 或 30）")
    ap.add_argument("--audit-n", type=int, default=200, help="G2P 一致性抽验样本数（0=跳过）")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 行（开发用）")
    args = ap.parse_args(argv)

    outdir = Path(args.out) if args.out else ROOT / "output" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    outdir.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    meta_arg = ["--meta", args.meta] if args.meta else []
    limit_arg = ["--limit", str(args.limit)] if args.limit else []

    run([py, str(SKILLS / "gate_validity" / "run.py"), "--input", args.input, *meta_arg,
         "--lang", args.lang, "--out", str(outdir), *limit_arg], "gate_validity")
    # gate 可能把 auto 解析为具体语言：后续 stage 用 gate.json 里的实际语言，保持全链一致
    lang = args.lang
    if lang == "auto":
        g = outdir / "dims" / "gate.json"
        if g.exists():
            lang = json.loads(g.read_text(encoding="utf-8-sig")).get("lang")
            if not lang:
                raise SystemExit(
                    "gate.json missing lang after --lang auto; pass --lang explicitly"
                )
    run([py, str(SKILLS / "profile_length" / "run.py"), "--records", str(outdir / "records.jsonl"),
         "--lang", lang, "--out", str(outdir), *limit_arg], "profile_length (切句+长度)")
    run([py, str(SKILLS / "profile_sentence" / "run.py"), "--sentences", str(outdir / "sentences.jsonl"),
         "--lang", lang, "--out", str(outdir)], "profile_sentence (句式)")
    run([py, str(SKILLS / "profile_vocab" / "run.py"), "--records", str(outdir / "records.jsonl"),
         "--sentences", str(outdir / "sentences.jsonl"), "--lang", lang, "--out", str(outdir)], "profile_vocab (词汇)")
    if not args.skip_g2p:
        run([py, str(SKILLS / "profile_phoneme" / "run.py"), "--sentences", str(outdir / "sentences.jsonl"),
             "--lang", lang, "--out", str(outdir), "--audit-n", str(args.audit_n)], "profile_phoneme (G2P+音素+抽验)")
    if args.etymology_verify:
        # 只验证链路不变量（去重/覆盖/续跑），不写真 LLM 结果、不阻塞报告
        ety = [py, str(SKILLS / "etymology_llm" / "run.py"), "--sentences", str(outdir / "sentences.jsonl"),
               "--lang", lang, "--out", str(outdir), "--verify"]
        if args.etymology_batch_size:
            ety += ["--batch-size", str(args.etymology_batch_size)]
        print(f"\n==> [etymology_llm (verify)] {' '.join(ety)}", flush=True)
        proc = subprocess.run(ety, cwd=ROOT)
        if proc.returncode != 0:
            print("    [etymology_llm (verify)] 不变量校验未通过（不阻塞报告，见上方 problems）", flush=True)
        else:
            print("    [etymology_llm (verify)] ok", flush=True)
    elif not args.skip_etymology:
        ety = [py, str(SKILLS / "etymology_llm" / "run.py"), "--sentences", str(outdir / "sentences.jsonl"),
               "--lang", lang, "--out", str(outdir)]
        if args.etymology_mock:
            ety.append("--mock")
        if args.etymology_batch_size:
            ety += ["--batch-size", str(args.etymology_batch_size)]
        run(ety, "etymology_llm (词源)")
    run([py, "-m", "corpus_kit.report", "--out", str(outdir), "--lang", lang,
         "--input", args.input, *meta_arg,
         "--params", json.dumps(_run_args(args), ensure_ascii=False)], "report")

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
