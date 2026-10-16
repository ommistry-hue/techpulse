# AutoTube — daily trending YouTube videos (free)

Each run: Google Trends → Gemini writes scripts → edge-tts voice + captions → Pexels footage → ffmpeg render → YouTube upload.
Produces one **long video (3–5 min, 16:9)** and one **Short (~50 s, 9:16)** on the same trending topic.

| Step | Tool | Cost |
|---|---|---|
| Trends | Google Trends RSS | free, no key |
| Script | Gemini API, auto-fallback to OpenRouter `:free` models on rate limit/timeout/error (`GEMINI_MODELS`, `OPENROUTER_MODELS`) | free tier |
| Voice + word captions | edge-tts | free, no key |
| Visuals | Wikimedia Commons real photos + Ken Burns zoom (credits auto-added); optional Pixabay/Pexels video clips | free, no key |
| Render | ffmpeg (bundled via imageio-ffmpeg) | free |
| Upload | YouTube Data API v3 | free, 10,000 units/day (1 upload = 1,600) |

## Setup (once)

1. `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in:
   - `GEMINI_API_KEY` from https://aistudio.google.com/apikey
   - `PEXELS_API_KEY` from https://www.pexels.com/api/
   - `NICHE` (optional, e.g. `tech`), `GEO` (country code)
3. YouTube API credentials:
   1. https://console.cloud.google.com → new project → enable **YouTube Data API v3**.
   2. OAuth consent screen → External → add your Gmail as test user → then **Publish app** (set to "In production").
      Apps left in "Testing" get refresh tokens that expire after 7 days, breaking the daily job.
   3. Credentials → Create OAuth client ID → **Desktop app** → download JSON → save as `client_secret.json` here.
   4. Run `.venv\Scripts\python.exe autotube.py --auth`, log in with the channel's account, accept the "unverified app" warning. Creates `token.json`.
4. Test without uploading: `.venv\Scripts\python.exe autotube.py --no-upload` → check `output\`.
5. Full run: `.venv\Scripts\python.exe autotube.py`

## Schedule daily (Windows Task Scheduler)

```
schtasks /create /tn "AutoTube Daily" /tr "\"C:\Om-Umaraliya\My\video-automation\run_daily.bat\"" /sc daily /st 09:00
```
PC must be on at that time. Logs: `logs\run.log`.

## Important limits

- **Private-only uploads until audit**: videos uploaded via an unverified API project are locked to private.
  Submit the YouTube API audit form (free) to allow public uploads: https://support.google.com/youtube/contact/yt_api_form
- YouTube may demonetize mass-produced, repetitive AI content ("inauthentic content" policy). Review scripts, vary topics, add your own commentary where possible.
- Uploads are marked `containsSyntheticMedia` (AI voice).
- `history.json` stores used topics so the same trend is not repeated.

## Files

- `autotube.py` — whole pipeline. Flags: `--auth`, `--no-upload`
- `output\<date>_<topic>\` — `meta.json`, `long\final.mp4`, `short\final.mp4`
