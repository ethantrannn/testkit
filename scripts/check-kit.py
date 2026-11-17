"""Static checks for the testkit repository (used by CI and before releases).

    python3 scripts/check-kit.py

Checks:
  - every skills/<name>/SKILL.md follows the Agent Skills spec (name = folder, charset, lengths)
  - every agents/*.md has name + description frontmatter
  - kit-owned SKILL.md files avoid tool-specific wording (portability across coding agents)
  - Python files compile; shell scripts pass `bash -n`
  - bin/testkit_sync.py installs into a temp project for every coding agent; generated Codex TOML parses
  - every README.*.md links back to the other languages
"""
import py_compile
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDORED = {"docx", "pdf", "xlsx", "pptx"}  # third-party, kept unmodified
NON_PORTABLE = [r"\bSkill tool\b", r"\bRead tool\b", r"\bAgent tool\b", r"\bsubagent_type\b(?!: \"test-lead\")"]
errors = []


def err(msg):
    errors.append(msg)
    print(f"  FAIL {msg}")


def frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if mm:
            meta[mm.group(1)] = mm.group(2).strip().strip('"')
    return meta


def check_skills():
    print("skills")
    for skill in sorted((ROOT / "skills").iterdir()):
        if not skill.is_dir():
            continue
        f = skill / "SKILL.md"
        if not f.exists():
            err(f"{skill.name}: missing SKILL.md")
            continue
        meta = frontmatter(f) or {}
        name, desc = meta.get("name", ""), meta.get("description", "")
        if name != skill.name:
            err(f"{skill.name}: name '{name}' must equal the folder name")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
            err(f"{skill.name}: invalid name")
        if not 0 < len(desc) <= 1024:
            err(f"{skill.name}: description length {len(desc)} (1..1024)")
        if skill.name not in VENDORED:
            text = f.read_text(encoding="utf-8")
            for pat in NON_PORTABLE:
                if re.search(pat, text):
                    err(f"{skill.name}: tool-specific wording /{pat}/ (keep skills portable)")
            lines = text.count("\n")
            if lines > 500:
                err(f"{skill.name}: SKILL.md has {lines} lines (keep under 500)")
    print(f"  checked {sum(1 for s in (ROOT / 'skills').iterdir() if s.is_dir())} skills")


def check_agents():
    print("agents")
    for f in sorted((ROOT / "agents").glob("*.md")):
        meta = frontmatter(f) or {}
        if meta.get("name") != f.stem or not meta.get("description"):
            err(f"agents/{f.name}: needs name == file name and a description")


def check_code():
    print("code")
    for f in sorted(ROOT.rglob("*.py")):
        if any(p in f.parts for p in ("node_modules", "public")):
            continue
        try:
            py_compile.compile(str(f), doraise=True, cfile=str(Path(tempfile.gettempdir()) / "testkit-check.pyc"))
        except py_compile.PyCompileError as e:
            err(f"{f.relative_to(ROOT)}: {e.msg.strip()}")
    for f in [ROOT / "install.sh", ROOT / "bin/testkit", *sorted(ROOT.rglob("*.sh"))]:
        if "node_modules" in f.parts:
            continue
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        if r.returncode:
            err(f"{f.relative_to(ROOT)}: {r.stderr.strip()}")


def check_sync():
    print("install for every coding agent")
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(ROOT / "bin/testkit_sync.py"), "--kit", str(ROOT),
                            "--project", tmp, "--agents", "all"], capture_output=True, text=True)
        if r.returncode:
            err(f"testkit_sync.py --agents all failed:\n{r.stdout}\n{r.stderr}")
            return
        p = Path(tmp)
        for d in (".claude/skills", ".agents/skills", ".claude/agents", ".codex/agents", ".gemini/agents", ".github/agents"):
            if not (p / d).is_dir():
                err(f"sync: {d} not created")
        for t in (p / ".codex/agents").glob("*.toml"):
            try:
                data = tomllib.loads(t.read_text(encoding="utf-8"))
                assert data["name"] and data["description"] and data["developer_instructions"]
            except Exception as e:  # noqa: BLE001
                err(f"sync: {t.name}: {e}")


def check_readmes():
    print("readmes")
    readmes = sorted(ROOT.glob("README*.md"))
    names = {f.name for f in readmes}
    for f in readmes:
        text = f.read_text(encoding="utf-8")
        for other in names - {f.name}:
            if f"]({other})" not in text:
                err(f"{f.name}: missing language link to {other}")


if __name__ == "__main__":
    check_skills()
    check_agents()
    check_code()
    check_sync()
    check_readmes()
    print("OK" if not errors else f"{len(errors)} problem(s)")
    sys.exit(1 if errors else 0)
