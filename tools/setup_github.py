"""One-time: push secrets/variables from local .env + JSON files into the GitHub repo. Values never printed."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = sys.argv[1]  # owner/name

SECRETS = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
VARIABLES = ["GEMINI_MODELS", "OPENROUTER_MODELS", "GEO", "NICHE", "CHANNEL_NAME", "TTS_VOICE", "TTS_RATE",
             "YT_PRIVACY", "YT_CATEGORY", "USE_WIKIMEDIA", "SUPABASE_URL", "SUPABASE_ANON_KEY"]

env = {}
for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
    m = re.match(r"^(\w+)=(.*)$", line.strip())
    if m:
        env[m[1]] = m[2].strip()


def gh(kind, name, value):
    r = subprocess.run(["gh", kind, "set", name, "--repo", REPO], input=value, text=True, capture_output=True)
    print(f"{kind} {name}: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()[:120]}")


for name in SECRETS:
    if env.get(name):
        gh("secret", name, env[name])
gh("secret", "YT_TOKEN_JSON", (ROOT / "token.json").read_text(encoding="utf-8"))
gh("secret", "YT_CLIENT_SECRET_JSON", (ROOT / "client_secret.json").read_text(encoding="utf-8"))
for name in VARIABLES:
    if env.get(name):
        gh("variable", name, env[name])
print(json.dumps({"repo": REPO}))
