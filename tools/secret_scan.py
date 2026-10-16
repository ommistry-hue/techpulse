"""Block commits that contain secrets. Run by .git/hooks/pre-commit; exits 1 on any hit."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_NAMES = re.compile(r"(KEY|PASSWORD|SECRET|TOKEN)$")
PATTERNS = re.compile(r"sb_secret_[A-Za-z0-9]|sk-or-v1-[0-9a-f]{10}|AQ\.Ab8|GOCSPX-|ya29\.|\"refresh_token\"\s*:\s*\"1//")


def secret_values():
    vals = {}
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^(\w+)=(.+)$", line.strip())
            if m and SECRET_NAMES.search(m[1]) and len(m[2].strip()) >= 6:
                vals[m[1]] = m[2].strip()
    for name, path in (("client_secret", "client_secret.json"), ("refresh_token", "token.json")):
        p = ROOT / path
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            v = data.get("installed", {}).get("client_secret") or data.get("refresh_token")
            if v:
                vals[name] = v
    return vals


def main():
    files = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                           cwd=ROOT, capture_output=True, text=True).stdout.split()
    vals, hits = secret_values(), []
    for f in files:
        blocked = re.search(r"(^|/)(\.env(\..*)?|client_secret.*\.json|token\.json)$", f) and f != ".env.example"
        if blocked:
            hits.append(f"{f}: secret file must not be committed")
            continue
        try:
            text = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits += [f"{f}: contains {k}" for k, v in vals.items() if v in text]
        if f != "tools/secret_scan.py" and PATTERNS.search(text):  # this file holds the patterns themselves
            hits.append(f"{f}: contains key-like text")
    if hits:
        print("COMMIT BLOCKED - secrets found:\n  " + "\n  ".join(hits))
        sys.exit(1)
    print(f"secret scan OK ({len(files)} files, {len(vals)} secrets checked)")


if __name__ == "__main__":
    main()
