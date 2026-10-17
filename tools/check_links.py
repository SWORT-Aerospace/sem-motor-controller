#!/usr/bin/env python3
"""Check that documentation links resolve.

    python3 tools/check_links.py            # exit 1 on any broken link

Checks every tracked Markdown file:
  * Markdown links [text](target) to files or directories in the repository,
    including #anchors against the target's headings (GitHub-style slugs);
  * file paths written in backticks (`docs/ICD.md`, `tools/x.py`) in the
    current documents (CURRENT below): such a path must exist. Records of
    earlier releases may name files that were renamed later; they are not
    rewritten, so backtick paths are checked only in the current documents.
External links (http, https, mailto) are not fetched.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CURRENT = {"README.md", "CONTRIBUTING.md", "docs/STATUS.md", "docs/ICD.md", "docs/INPUT_SHEET.md", "docs/TELEMETRY_INTEGRATION.md",
           "docs/TELEMETRY_CANDIDATES.md", "docs/TELEMETRY_EMBEDDED_PORT.md", "docs/PROCUREMENT.md", "docs/BATTERY.md",
           "docs/MQTT_SETUP.md", "docs/ENERGY_METHODS.md", "docs/VERIFICATION_REPORT.md", "docs/RULES_COMPLIANCE.md",
           "docs/generated/mqtt_demo/summary.md", "docs/generated/wheel_sensor_check.md",
           "docs/generated/host_demo/summary.md", "docs/generated/coastdown_sensitivity.md",
           "docs/README.md", "docs/FILE_INDEX.md", "docs/INTEGRATION_GUIDE.md", "docs/IMPLEMENTATION_PLAN.md",
           "docs/DESIGN_DECISIONS.md", "docs/DEVELOPMENT.md", "docs/MATH_SPEC.md",
           "config/README.md", "firmware/README.md", "protocol/README.md", "host/README.md", "models/README.md",
           "hardware/README.md", "tools/README.md", "tests/README.md"}
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
EXT = r"(?:md|py|yaml|yml|json|csv|c|h|txt|sh|toml|cmake|kicad_sch|net)"
TICK = re.compile(r"`([A-Za-z0-9_./-]+\." + EXT + r")`")
PLAIN = re.compile(r"(?<![\w`/.-])((?:docs|tools|host|firmware|hardware|config|protocol|tests|models)/[A-Za-z0-9_./-]+\."
                   + EXT + r")\b")
# Outputs that tools write but that are deliberately not committed (CI artifacts, smoke runs): a current
# document may name them although they are absent from a clean checkout.
UNTRACKED_OUTPUTS = {"hardware/kicad/ERC_REPORT.json", "hardware/kicad/ERC_REPORT.rpt",
                     "docs/generated/csia_evaluation_smoke.md", "docs/generated/csia_evaluation_smoke.json"}
ROOTS = ("docs/", "tools/", "host/", "firmware/", "hardware/", "config/", "protocol/", "tests/", "models/",
         ".github/", "README.md")


def slug(heading: str) -> str:
    h = re.sub(r"`|\*\*|\*|_(?=\w)", "", heading.strip().lower())
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(path: pathlib.Path) -> set[str]:
    out, seen, fence = set(), {}, False
    for line in path.read_text(errors="replace").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        if fence:
            continue
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            out.add(s if n == 0 else f"{s}-{n}")
            seen[s] = n + 1
    return out


def strip_code(text: str) -> str:
    """Remove fenced code blocks (their contents are commands, not links)."""
    return re.sub(r"```.*?```", "", text, flags=re.S)


def check() -> list[str]:
    files = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    errors = []
    for rel in files:
        p = ROOT / rel
        if not p.exists():
            continue
        text = strip_code(p.read_text(errors="replace"))
        for target in LINK.findall(text):
            if re.match(r"^[a-z]+:", target):
                continue
            path, _, frag = target.partition("#")
            dest = p if not path else (p.parent / path).resolve()
            if path and not dest.exists():
                errors.append(f"{rel}: link to missing {target}")
                continue
            if frag and dest.is_file() and dest.suffix == ".md" and frag not in anchors(dest):
                errors.append(f"{rel}: link to missing anchor {target}")
        if rel in CURRENT:
            bare = re.sub(r"\[[^\]]*\]\([^)]*\)", "", text)
            for ref in set(TICK.findall(bare)) | set(PLAIN.findall(bare)):
                if not ref.startswith(ROOTS) or "<" in ref or "*" in ref or ref in UNTRACKED_OUTPUTS:
                    continue
                if not (ROOT / ref).exists():
                    errors.append(f"{rel}: path `{ref}` does not exist")
    return errors


def main() -> int:
    errors = check()
    for e in errors:
        print("BROKEN " + e)
    n = len(subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True).stdout.split())
    print(f"links: {n} Markdown files checked, {len(errors)} broken")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
