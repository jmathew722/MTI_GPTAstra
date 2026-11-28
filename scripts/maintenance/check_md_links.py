"""List broken relative links in tracked Markdown files (ignores http, anchors, and generated evidence folders).

Usage (repo root):  python scripts/maintenance/check_md_links.py [--all]
Exit code 1 when broken links exist outside the legacy evidence folders."""
import re, subprocess, sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
SKIP = ("FINAL_OUTPUTs/", "archive/", "docs/phase1-evidence/", "docs/phase2-evidence/", "graphify-out/", "reference-repos/")
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

def main():
    files = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    bad = []
    for f in files:
        if "--all" not in sys.argv and f.startswith(SKIP):
            continue
        p = ROOT / f
        if not p.exists():
            continue
        in_code = False
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
            if in_code:
                continue
            for m in LINK.finditer(line):
                t = m.group(1)
                if t.startswith(("http", "mailto:", "#", "<")):
                    continue
                t = unquote(t.split("#")[0])
                if t and not (p.parent / t).exists():
                    bad.append(f"{f}:{n}: {m.group(1)}")
    print("\n".join(bad) or "no broken links")
    print(f"{len(bad)} broken")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
