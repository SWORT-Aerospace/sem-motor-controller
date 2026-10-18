"""Documentation checks: links resolve, generated tables are current, wording rules for current documents."""
import pathlib
import re
import subprocess
import sys

from tools import check_links

ROOT = check_links.ROOT


def test_every_documentation_link_resolves():
    assert check_links.check() == []


def test_github_heading_slugs():
    assert check_links.slug("NUCLEO-U575ZI-Q") == "nucleo-u575zi-q"
    assert check_links.slug("GNSS: NEO-M9N") == "gnss-neo-m9n"
    assert check_links.slug("LTE: A7672") == "lte-a7672"
    assert check_links.slug("2. Signals") == "2-signals"


def test_generated_check_files_are_current():
    for cmd in (["tools/wheel_sensor_check.py", "--check"], ["tools/gen_procurement.py", "--check"],
                ["tools/coastdown_sensitivity.py", "--check"]):
        r = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


def test_current_documents_have_no_em_dash_or_assistant_branding():
    brand = re.compile(r"\b(Claude|ChatGPT|Codex|Copilot|GPT-\d|AI assistant|language model)\b")
    for rel in sorted(check_links.CURRENT):
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text()
        assert "\u2014" not in text, f"{rel} contains an em dash"
        assert not brand.search(text), f"{rel}: {brand.search(text).group(0)}"


def test_readme_keeps_the_scope_honest():
    text = (ROOT / "README.md").read_text()
    assert "**Physically tested** is still nothing: nothing has been energised" in text
    assert "**Not started.** No board exists." in text                 # milestone 3 is not claimed
    assert "hardware is not fabrication-ready" in text and "the release gate fails" in text
    assert "a reviewed design is not a tested board" in text
    assert "**Proposed** means designed or specified but not built" in text
    assert "**Host** means implemented and tested on a computer" in text
    assert "CONTRIBUTING.md" in text
    assert "They are not wiring diagrams" in text                  # block diagrams, not construction-ready wiring
    assert "TELEMETRY_EMBEDDED_PORT.md" in text                     # embedded firmware is listed as remaining work
    assert "Estimates are not quotes" in text and "not established" in text
    assert text.count("```mermaid") == 3


def _mentioned(path: str, texts: dict) -> bool:
    """A tracked file is indexed if FILE_INDEX.md or docs/README.md names it (or a glob or sibling that covers it),
    or if a folder index named there lists it."""
    import fnmatch
    p = pathlib.PurePosixPath(path)
    for where, text in texts.items():
        base = "" if where == "docs/FILE_INDEX.md" else "docs/"
        refs = {base + r if base and not r.startswith("../") else r.replace("../", "")
                for r in re.findall(r"`([^`\s]+)`", text) + re.findall(r"\]\(([^)#\s]+)", text)}
        if path in refs or any("*" in r and fnmatch.fnmatch(path, r) for r in refs):
            return True
        if any(pathlib.PurePosixPath(r).parent == p.parent and pathlib.PurePosixPath(r).stem == p.stem for r in refs):
            return True                                             # "(and `.json`)": same stem, other extension
    for folder in p.parents:                                        # a folder guide named in the index lists it
        guide = folder / "README.md"
        if str(folder) == "." or str(guide) == path or not (ROOT / guide).exists():
            continue
        named = any(str(guide) in t or str(guide).replace("docs/", "", 1) in t for t in texts.values())
        if named and p.name in (ROOT / guide).read_text():
            return True
    return False


def test_file_index_covers_every_tracked_file():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    texts = {rel: (ROOT / rel).read_text() for rel in ("docs/FILE_INDEX.md", "docs/README.md")}
    missing = [f for f in files if not f.endswith("__init__.py") and f not in texts and not _mentioned(f, texts)]
    assert missing == [], f"not in docs/FILE_INDEX.md or docs/README.md: {missing}"
