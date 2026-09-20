r"""发布面守卫：以「发布版」为标准，测模板 + 实例化。

设计前提（与 `scripts/deploy_skill.py` 一致）
-------------------------------------------
- 仓库根 `SKILL.md` 是**唯一真源 + 唯一发布物**，不含任何人的本机路径，clone 即可用。
- 装到 agent skills 目录的副本 = 发布版 + 一次确定性 `<REPO>` → 本机 checkout 替换。
- 因此本文件测三件事：**模板可移植**、**实例化是纯替换**、**线上副本没漂移**。
  三者合起来等价于「按发布标准测试本机那份」：副本不允许出现模板之外的内容。

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = sys.executable

from scripts import deploy_skill as ds

# 只扫入 git 的文本文件（-z 模式下 git 才能正确解析中文路径）
TEXT_SUFFIXES = {".md", ".py", ".txt", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".ps1"}

# 扫描规则来自 scripts/deploy_skill.py（单一真源，别在这里再抄一份）
MACHINE_PATH_PATTERNS = ds.MACHINE_PATH_PATTERNS
scan_machine_paths = ds.scan_machine_paths

# 发布版 SKILL.md 的 description 里不允许出现盘符或绝对路径
DESC_FORBIDDEN = [
    (r"[A-Za-z]:[\\/]", "盘符路径"),
    (r"(?<![\w<])/(?:Users|home|mnt|opt|srv)/", "Unix 绝对路径"),
]


def tracked_files() -> list[Path]:
    """git ls-files（-z 避免中文路径被转义）；非 git 环境退回 rglob。"""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT,
            capture_output=True, check=True,
        ).stdout.decode("utf-8")
        names = [n for n in out.split("\0") if n]
        return [ROOT / n for n in names]
    except Exception:
        return [p for p in ROOT.rglob("*") if p.is_file()
                and ".venv" not in p.parts and ".git" not in p.parts]


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


class TestNoMachinePaths(unittest.TestCase):
    def test_repo_files_compile_into_no_machine_paths(self):
        hits: list[str] = []
        for p in tracked_files():
            if p.suffix.lower() not in TEXT_SUFFIXES or not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            for i, why, line in scan_machine_paths(read_text(p)):
                hits.append(f"{rel}:{i}  [{why}]  {line[:110]}")
        self.assertEqual(
            hits, [],
            "发布面写死了本机绝对路径，别人 clone 后跑不通；请改用 <REPO> 占位或 $HOME 相对写法：\n  "
            + "\n  ".join(hits),
        )

    def test_scanner_catches_machine_paths(self):
        """扫描器自身的行为：真实路径必须抓，占位符形态必须放过。

        反例里的用户段用占位符写（<user> / {u}）—— 正则不匹配占位符形态，
        所以本文件不会被自己的守卫扫到（避免守卫扫自己的死循环）。
        """
        bad = [
            "cd D:/Users/<user>/Desktop/proj".replace("<user>", "someone"),
            "cd D:\\Users\\{u}\\proj".replace("{u}", "someone"),
            "cd /Users/{u}/src/tool".replace("{u}", "someone"),
            "cd /home/{u}/src/tool".replace("{u}", "someone"),
        ]
        for line in bad:
            with self.subTest(line=line):
                self.assertTrue(scan_machine_paths(line), f"应抓到这个本机路径：{line}")
        ok = [
            "cd <REPO>",
            "cd $HOME\\src\\corpus-validation-toolkit",
            "cd D:/Users/<user>/Desktop/proj",   # 占位符形态
            "cd D:/Users/<name>/Desktop/proj",
            "cd {u}:/Users/{u}/Desktop/proj",
        ]
        for line in ok:
            with self.subTest(line=line):
                self.assertFalse(scan_machine_paths(line), f"不该误报：{line}")


class TestSkillTemplate(unittest.TestCase):
    """发布版模板本身：可移植、自足、能被任何人直接用。"""

    def setUp(self):
        self.text = read_text(ROOT / "SKILL.md")
        self.assertTrue(self.text, "仓库根缺少 SKILL.md")

    def test_frontmatter_parseable(self):
        self.assertTrue(self.text.startswith("---\n"), "SKILL.md 必须以 YAML frontmatter 开头")
        end = self.text.find("\n---", 4)
        self.assertGreater(end, 0, "SKILL.md frontmatter 未闭合")
        fm = self.text[4:end]
        self.assertIn("name: corpus-validation-toolkit", fm)
        self.assertIn("description:", fm)

    def test_description_has_no_local_path(self):
        fm = self.text[4:self.text.find("\n---", 4)]
        desc = next((l for l in fm.splitlines() if l.startswith("description:")), "")
        self.assertTrue(desc, "frontmatter 缺 description")
        for pat, why in DESC_FORBIDDEN:
            self.assertIsNone(
                re.search(pat, desc),
                f"description 里出现{why}，会随仓库发给别人：{desc[:160]}",
            )

    def test_commands_use_repo_placeholder(self):
        self.assertIn("cd <REPO>", self.text, "快速命令应使用 `cd <REPO>` 占位")
        self.assertNotIn("cd D:", self.text)
        self.assertNotIn("cd C:", self.text)

    def test_template_selfsufficient_in_fresh_clone(self):
        """发布版单独拷到别处（模拟别人 clone）也必须可移植、不需要实例化就能读。"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            p.write_text(self.text, encoding="utf-8")
            body = p.read_text(encoding="utf-8")
            self.assertFalse(scan_machine_paths(body), "fresh-clone 场景不该出现本机路径")
            self.assertIn("cd <REPO>", body)
            # 关键：模板不依赖「必须先安装到 skills 目录」才有意义
            self.assertIn("本仓库根目录", body)


class TestInstantiationContract(unittest.TestCase):
    """实例化契约：副本 = 发布版 + 一次 <REPO> 替换，多一个字符都不允许。"""

    REPO = Path(r"D:\some\path\to\checkout")   # 假路径，避免测试依赖真实位置

    def test_placeholder_is_idempotent_and_single(self):
        tpl = read_text(ROOT / "SKILL.md")
        self.assertGreaterEqual(tpl.count(ds.PLACEHOLDER), 1, "模板应含 <REPO> 占位符")
        once = ds.render_template(tpl, self.REPO)
        twice = ds.render_template(once, self.REPO)
        self.assertEqual(once, twice, "重复渲染必须幂等，不能二次替换")

    def test_rendered_differs_only_on_placeholder_lines(self):
        tpl = read_text(ROOT / "SKILL.md")
        out = ds.render_template(tpl, self.REPO)
        self.assertNotIn(ds.PLACEHOLDER, out, "渲染后不得残留占位符")
        t, o = tpl.splitlines(), out.splitlines()
        self.assertEqual(len(t), len(o), "渲染不得增删行")
        diff = [i for i, (a, b) in enumerate(zip(t, o)) if a != b]
        self.assertEqual(len(diff), tpl.count(ds.PLACEHOLDER),
                         f"只有含占位符的行才允许有差异，实际差 {len(diff)} 行")
        for i in diff:
            self.assertIn(ds.PLACEHOLDER, t[i])
            self.assertEqual(t[i].replace(ds.PLACEHOLDER, str(self.REPO)), o[i])

    def test_install_then_check_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ds.SKILL_NAME
            ok, why = ds.check(target, self.REPO)
            self.assertFalse(ok, "未安装时 check 应为不一致")
            self.assertIn("未安装", why)
            written = ds.install(target, self.REPO)
            self.assertTrue(written.exists())
            ok, why = ds.check(target, self.REPO)
            self.assertTrue(ok, f"安装后应一致，实际：{why}")

    def test_check_detects_manual_edit(self):
        """副本被手工改过必须被检出（这正是之前两份副本静默过期的教训）。"""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ds.SKILL_NAME
            ds.install(target, self.REPO)
            f = target / "SKILL.md"
            f.write_text(f.read_text(encoding="utf-8") + "\n手工加的一行\n", encoding="utf-8")
            ok, why = ds.check(target, self.REPO)
            self.assertFalse(ok, "手工改动必须被检出")
            self.assertTrue("不一致" in why or "行数" in why, why)

    def test_check_detects_stale_unrendered_copy(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ds.SKILL_NAME
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(read_text(ROOT / "SKILL.md"), encoding="utf-8")
            ok, why = ds.check(target, self.REPO)
            self.assertFalse(ok, "未实例化的模板副本应被检出")
            self.assertIn(ds.PLACEHOLDER, why)

    def test_cli_check_and_deploy_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ds.SKILL_NAME
            script = str(ROOT / "scripts" / "deploy_skill.py")
            base = [PY, script, "--target", str(target), "--repo", str(ROOT)]

            r = subprocess.run([*base, "--check"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1, "未安装时 --check 应返回 1")
            self.assertIn("BAD", r.stdout)

            r = subprocess.run(base, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, f"部署应成功：{r.stdout}{r.stderr}")

            r = subprocess.run([*base, "--check"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, f"部署后 --check 应返回 0：{r.stdout}{r.stderr}")
            self.assertIn("OK", r.stdout)


class TestInstalledCopiesInSync(unittest.TestCase):
    """本机真实副本（~/.agents、~/.codex）不得漂移；不存在则跳过。"""

    def test_live_copies_match_published_template(self):
        seen = 0
        for target in ds.default_targets():
            if not (target / "SKILL.md").exists():
                continue
            seen += 1
            if target.resolve() == ROOT.resolve():
                continue
            ok, why = ds.check(target, ROOT)
            self.assertTrue(ok, f"{target} 与发布版不一致：{why}\n  → 重跑 python scripts/deploy_skill.py")
        if not seen:
            self.skipTest("本机未安装 skill 副本（非开发者机器，正常）")


class TestDocsDescribeInstall(unittest.TestCase):
    def test_readme_documents_placeholder_and_script(self):
        readme = read_text(ROOT / "README.md")
        self.assertIn(ds.PLACEHOLDER, readme, "README 应说明 <REPO> 占位符")
        self.assertIn("deploy_skill.py", readme, "README 应指向部署脚本而不是散装 snippet")
        self.assertIn("--check", readme, "README 应说明一致性校验方式")


if __name__ == "__main__":
    sys.exit(unittest.main())
