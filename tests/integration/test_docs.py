"""Documentation checks: links resolve, generated tables are current, wording rules for current documents."""
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
    assert "none built, energised or tested" in text.lower()
    assert "not built" in text                                     # the diagram labels proposed hardware
    assert "Implemented host software" in text
    assert "TELEMETRY_EMBEDDED_PORT.md" in text                     # embedded firmware is listed as remaining work
