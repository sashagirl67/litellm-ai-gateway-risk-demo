"""Pre-publish safety check: fail if anything that looks like a real AWS credential, or the .env
file, is tracked by git. Run before every push to the public repository.

Usage: python scripts/check_no_aws_keys.py
"""
import re
import subprocess
import sys

from _util import ROOT

PATTERNS = {
    "AWS access key id": re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    "AWS secret key assignment": re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+]{40}"),
}


def main():
    try:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except Exception:
        sys.exit("Run this inside the git repository (after git init / git add).")
    problems = []
    if any(f == ".env" or f.endswith("/.env") for f in files):
        problems.append(".env is tracked by git: run  git rm --cached .env")
    for f in files:
        path = ROOT / f
        if path.suffix in {".png", ".jpg", ".docx", ".pdf"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, rx in PATTERNS.items():
            for m in rx.finditer(text):
                problems.append(f"{f}: possible {label}: {m.group(0)[:12]}…")
    if problems:
        print("NOT SAFE TO PUBLISH:")
        print("\n".join("  " + p for p in problems))
        sys.exit(1)
    print(f"OK: checked {len(files)} tracked files, no AWS credentials and no .env.")
    print("Note: the committed LiteLLM master key and Postgres password are intentional local-only demo values.")


if __name__ == "__main__":
    main()
