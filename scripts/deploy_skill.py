# -*- coding: utf-8 -*-
"""deploy_skill —— 把「发布版 SKILL.md」实例化成机器可用的 agent skill 副本。

设计约束（这就是我们要测的东西）
--------------------------------
1. **仓库根 `SKILL.md` 是唯一真源**，也是唯一发布物：不含任何人的本机路径，
   任何人 clone 后直接可用。它里面的 `<REPO>` 是占位符。
2. 装到 agent skills 目录（`~/.agents/skills/`、`~/.codex/skills/`）的副本 =
   发布版 + **一次确定性的 `<REPO>` → 本机 checkout 路径替换**。
   除此之外不允许有任何差异 —— 副本永远不该被人手工编辑。
3. 替换是**幂等**的：重复安装不会二次替换、不会破坏已有内容。

于是「测已发布的东西」和「测本机那份」是同一件事：模板由
`tests/test_skill_portable.py` 守，实例化由本脚本保证，两者之间只差一个可验证的替换。

用法
----
    python scripts/deploy_skill.py                    # 部署 ~/.agents 与 ~/.codex
    python scripts/deploy_skill.py --check            # 只校验是否与仓库版一致，不写盘
    python scripts/deploy_skill.py --target DIR ...   # 部署到指定目录（测试用）

退出码：0 成功/一致；1 检出不一致（--check 模式）；2 用法或环境错误。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "<REPO>"
SKILL_NAME = "corpus-validation-toolkit"
DEFAULT_PARENTS = (Path.home() / ".agents" / "skills",
                   Path.home() / ".codex" / "skills")

# ---------------------------------------------------------------- 本机路径扫描
# 单一真源：守卫测试也 import 这里，避免规则两处漂移。
# 匹配真实用户名；`<user>`、`<name>`、`{u}` 这类占位符形态天然不匹配，
# 所以文档/测试里可以安全地举反例。
MACHINE_PATH_PATTERNS = [
    (r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"'<>{}]+", "Windows 用户目录绝对路径（含具体用户名）"),
    (r"(?<![\w:.])/Users/[A-Za-z0-9._-]+/", "macOS 用户目录绝对路径"),
    (r"(?<![\w:.])/home/[A-Za-z0-9._-]+/", "Linux home 绝对路径"),
    (r"Desktop[\\/]My_Project", "本机项目落盘目录"),
]


def scan_machine_paths(text: str) -> list[tuple[int, str, str]]:
    """扫描文本里的本机绝对路径，返回 [(行号, 命中的规则说明, 该行内容)]。

    带尖括号/花括号的占位（如 D:/Users/<name>、{u}:/Users/{u}）不匹配，
    因此反例可安全地写在文档与测试里。
    """
    hits: list[tuple[int, str, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat, why in MACHINE_PATH_PATTERNS:
            if re.search(pat, line):
                hits.append((i, why, line.strip()))
    return hits


def template_path() -> Path:
    return ROOT / "SKILL.md"


def render_template(template: str, repo: Path | str) -> str:
    """发布版 → 本机副本：只做一次 <REPO> 替换，其余逐字节保留。"""
    return template.replace(PLACEHOLDER, str(repo))


def install(target_dir: Path | str, repo: Path | str | None = None) -> Path:
    """把发布版渲染进 target_dir/SKILL.md（幂等）。返回写入路径。"""
    repo = Path(repo) if repo is not None else ROOT
    target = Path(target_dir) / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_template(template_path().read_text(encoding="utf-8"), repo),
                      encoding="utf-8")
    return target


def check(target_dir: Path | str, repo: Path | str | None = None) -> tuple[bool, str]:
    """校验 target_dir/SKILL.md 是否恰好等于「发布版 + 本机路径替换」。

    返回 (是否一致, 说明)。不一致时说明里指出具体差在哪。
    """
    repo = Path(repo) if repo is not None else ROOT
    target = Path(target_dir) / "SKILL.md"
    if not target.exists():
        return False, "未安装"
    expected = render_template(template_path().read_text(encoding="utf-8"), repo)
    actual = target.read_text(encoding="utf-8")
    if actual == expected:
        return True, "一致"
    # 给出可定位的差异，而不是笼统的 False
    if PLACEHOLDER in actual:
        return False, f"仍是未实例化的模板（残留 {PLACEHOLDER}）"
    a, e = actual.splitlines(), expected.splitlines()
    for i, (la, le) in enumerate(zip(a, e), 1):
        if la != le:
            return False, f"第 {i} 行与发布版不一致（副本可能被手工改过）：\n      副本: {la[:100]}\n      应为: {le[:100]}"
    return False, f"行数不同（副本 {len(a)} 行 / 应为 {len(e)} 行）：副本可能过期，请重跑本脚本"


def default_targets() -> list[Path]:
    return [p / SKILL_NAME for p in DEFAULT_PARENTS]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="部署/校验 corpus-validation-toolkit 的 agent skill 副本")
    ap.add_argument("--target", action="append", default=None,
                    help="目标 skills 目录（可重复；默认 ~/.agents/skills/<name> 与 ~/.codex/skills/<name>）")
    ap.add_argument("--repo", default=None, help=f"仓库根路径（默认本脚本所在仓库 {ROOT}）")
    ap.add_argument("--check", action="store_true", help="只校验一致性，不写盘")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else ROOT
    if not (repo / "SKILL.md").exists():
        print(f"[FAIL] {repo} 下找不到 SKILL.md", file=sys.stderr)
        return 2
    targets = [Path(t) for t in args.target] if args.target else default_targets()

    bad = 0
    for t in targets:
        if args.check:
            ok, why = check(t, repo)
            print(f"[{'OK ' if ok else 'BAD'}] {t}  {why}")
            bad += 0 if ok else 1
        else:
            p = install(t, repo)
            print(f"[OK ] 已部署 {p}（<REPO> → {repo}）")

    if args.check and bad:
        print(f"\n{bad} 个副本与发布版不一致：副本不应手工编辑，重跑一次本脚本即可对齐。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
