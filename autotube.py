"""TechPulse: trending tech news -> scripts -> voice -> video -> YouTube (long 16:9 + Shorts 9:16)."""
import argparse
import asyncio
import datetime
import html
import json
import os
import random
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import edge_tts
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HISTORY = ROOT / "history.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
UA = {"User-Agent": "Mozilla/5.0 (TechPulse trend fetcher)"}

FORMATS = {
    "long": dict(w=1920, h=1080, orientation="landscape", font=104, align=2, margin_v=90, per_line=5, clip_secs=8),
    "short": dict(w=1080, h=1920, orientation="portrait", font=150, align=5, margin_v=0, per_line=3, clip_secs=6),
}
FONT = "Anton"  # bundled in fonts/ (OFL) so captions look the same on Windows and the Linux cloud runner


def subs_filter(work, ass):
    fontsdir = os.path.relpath(ROOT / "fonts", work).replace("\\", "/")
    return f"subtitles={ass}:fontsdir={fontsdir}"
LENGTHS = {"long": (680, 820), "short": (110, 140)}


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


FFMPEG = shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()


def ff(args, cwd):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True, cwd=cwd)


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------- 1. Trends ----------
def rss_items(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return list(ET.fromstring(r.content).iter("item"))


def src_google_trends(geo):
    out = []
    for item in rss_items(f"https://trends.google.com/trending/rss?geo={geo}"):
        t = {"source": "Google Trends", "title": item.findtext("title"), "score": "", "context": []}
        for el in item:
            tag = el.tag.split("}")[-1]
            if tag == "approx_traffic":
                t["score"] = f"{el.text} searches"
            elif tag == "news_item":
                title = next((c.text for c in el if c.tag.endswith("news_item_title")), None)
                if title:
                    t["context"].append(title)
        out.append(t)
    return out


def src_google_news_tech(geo):
    url = f"https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-{geo}&gl={geo}&ceid={geo}:en"
    return [{"source": "Google News Tech", "title": i.findtext("title"), "score": "", "context": []}
            for i in rss_items(url)[:30]]


def src_hackernews(_geo):
    r = requests.get("https://hn.algolia.com/api/v1/search", params={"tags": "front_page", "hitsPerPage": 30},
                     headers=UA, timeout=30)
    r.raise_for_status()
    return [{"source": "Hacker News", "title": h["title"], "score": f"{h.get('points', 0)} points", "context": []}
            for h in r.json()["hits"]]


def src_reddit(_geo):
    out = []
    for sub in ("technology", "artificial", "gadgets"):
        r = requests.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "day", "limit": 10},
                         headers=UA, timeout=30)
        if r.ok:
            out += [{"source": f"r/{sub}", "title": c["data"]["title"], "score": f"{c['data']['score']} upvotes",
                     "context": []} for c in r.json()["data"]["children"]]
    return out


def src_youtube_trending(geo):
    r = youtube_client().videos().list(part="snippet,statistics", chart="mostPopular", regionCode=geo,
                                       videoCategoryId="28", maxResults=20).execute()
    return [{"source": "YouTube Trending Tech", "title": v["snippet"]["title"],
             "score": f"{v['statistics'].get('viewCount', '?')} views", "context": []} for v in r.get("items", [])]


def fetch_trends(geo):
    trends = []
    for fn in (src_google_trends, src_google_news_tech, src_hackernews, src_reddit, src_youtube_trending):
        try:
            items = fn(geo)
            trends += items
            log(f"  {fn.__name__}: {len(items)}")
        except Exception as e:
            log(f"  {fn.__name__} failed: {str(e)[:120]}")
    return trends


def trends_text(trends):
    lines = []
    for t in trends[:130]:
        ctx = f" | {'; '.join(t['context'][:3])}" if t["context"] else ""
        score = f" ({t['score']})" if t["score"] else ""
        lines.append(f"- [{t['source']}] {t['title']}{score}{ctx}")
    return "\n".join(lines)


# ---------- 2. Scripts (LLM with automatic provider fallback) ----------
LLM_TIMEOUT = 200


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    # raw_decode stops at the end of the first JSON object, so trailing text/objects are ignored.
    return json.JSONDecoder().raw_decode(text[text.find("{"):])[0]


def gemini(prompt, model):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}},
        timeout=LLM_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def openrouter(prompt, model):
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={"model": model, "temperature": 0.9,
              "messages": [{"role": "user", "content": prompt + "\n\nRespond with the JSON object only."}]},
        timeout=LLM_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["choices"][0]["message"]["content"]


_FREE_MODELS = None


def openrouter_free_models():
    """Free OpenRouter models change often (removed/blocked), so read the live list once per run."""
    global _FREE_MODELS
    if _FREE_MODELS is None:
        try:
            data = requests.get("https://openrouter.ai/api/v1/models", timeout=30).json()["data"]
            skip = ("safety", "guard", "code", "embed", "vision", "audio", "omni")
            free = [m for m in data if m["id"].endswith(":free") and (m.get("context_length") or 0) >= 32000
                    and not any(s in m["id"] for s in skip)]
            _FREE_MODELS = [m["id"] for m in sorted(free, key=lambda m: -(m.get("context_length") or 0))][:8]
        except Exception as e:
            log(f"OpenRouter model list failed: {e}")
            _FREE_MODELS = []
    return _FREE_MODELS


def llm_providers():
    split = lambda v: [m.strip() for m in os.environ.get(v, "").split(",") if m.strip()]
    providers = []
    if os.environ.get("GEMINI_API_KEY"):
        providers += [(gemini, m) for m in split("GEMINI_MODELS") or ["gemini-flash-latest"]]
    if os.environ.get("OPENROUTER_API_KEY"):
        preferred = split("OPENROUTER_MODELS")
        providers += [(openrouter, m) for m in preferred + [m for m in openrouter_free_models() if m not in preferred]]
    return providers


def llm_json(prompt, required=()):
    """Try each provider/model in order; move to the next on rate limit, timeout, error or bad JSON.
    Two full rounds with a pause, because Gemini 503 'overloaded' errors usually clear within a minute."""
    for attempt in range(2):
        for call, model in llm_providers():
            try:
                data = parse_json(call(prompt, model))
                missing = [k for k in required if k not in data]
                if missing:
                    raise ValueError(f"missing keys {missing}")
                log(f"LLM ok: {call.__name__}/{model}")
                return data
            except Exception as e:
                log(f"LLM failed {call.__name__}/{model}: {str(e)[:160]} -> switching")
        if attempt == 0:
            log("All LLM providers failed, waiting 90s and retrying")
            time.sleep(90)
    raise RuntimeError("All LLM providers failed")


RULES = """Rules:
- Only state facts supported by the trend titles/headlines given. Otherwise frame as context, opinion or open question.
- Never invent numbers, quotes, dates or specs.
- Natural spoken English, no headings read aloud, no stage directions, no emojis, no hashtags in the script.
- Image keywords (searched on Wikimedia Commons): 2-4 words each, unambiguous, in script order.
  Keyword 1 = the exact main subject (used for the thumbnail), e.g. 'iPhone Duo' or 'Nvidia Blackwell GPU'.
  Mostly specific names (company + product, full person name), e.g. 'Apple iPhone' not 'Apple',
  'smartphone heat pipe' not 'pipe', 'Sam Altman OpenAI'. A few generic visuals like 'data center servers'."""


def topic_rules(niche, used):
    return (f"Channel: {os.environ.get('CHANNEL_NAME', 'TechPulse')}, niche: {niche or 'tech'}.\n"
            f"Pick stories that fit the niche, are fresh today, and have the biggest audience (high searches,"
            f" points, upvotes, views; covered by several sources = bigger).\n"
            f"Do NOT pick these already-covered topics: {json.dumps(used, ensure_ascii=False)}")


def expand(text, lo, hi):
    return llm_json(f"""Expand this YouTube voiceover script to {lo}-{hi} words. Keep the same topic, facts, hook,
tone and ending. Add depth (context, implications, what it means for viewers) without inventing numbers,
quotes or dates. No headings, no stage directions, no emojis.

SCRIPT:
{text}

Return JSON only: {{"script": "..."}}""", required=("script",))["script"]


def plan_long(trends, niche, used):
    lo, hi = LENGTHS["long"]
    meta = llm_json(f"""You write a viral tech & AI news YouTube channel. Today's trending items:
{trends_text(trends)}

{topic_rules(niche, used)}

Pick ONE story for a {lo}-{hi} word (about 4 minute) video. Structure as 5-7 sections in this order:
hook (1-2 sentences that make people stay), why it is trending now, background, key details,
reactions / what people are saying, what happens next and what it means for viewers,
closing (ask a comment question + ask to subscribe to {os.environ.get('CHANNEL_NAME', 'TechPulse')}).
Count words carefully: total under {lo - 30} words is too short.
{RULES}

Return JSON only:
{{"topic": "short topic name",
 "title": "search-friendly curiosity title, main keyword first, max 70 chars, no clickbait lies",
 "description": "first sentence has the main keyword; 4-6 sentences total, natural related search terms",
 "tags": ["12-15 tags, mix broad and specific"],
 "thumbnail_text": "2-4 punchy words for the thumbnail",
 "pinned_comment": "one engaging question for viewers",
 "sections": [{{"heading": "chapter title, 2-5 words", "text": "spoken text"}}],
 "keywords": ["12 image search terms"]}}""", required=("topic", "title", "sections", "keywords"))
    for _ in range(2):
        n = sum(len(s["text"].split()) for s in meta["sections"])
        if n >= lo * 0.92:
            break
        log(f"[long] script only {n} words, expanding")
        fixed = llm_json(f"""Expand these video script sections to {lo}-{hi} words in total. Keep headings, order,
facts, hook and ending. Add depth without inventing numbers, quotes or dates.

{json.dumps(meta['sections'], ensure_ascii=False)}

Return JSON only: {{"sections": [{{"heading": "...", "text": "..."}}]}}""", required=("sections",))
        meta["sections"] = fixed["sections"]
    meta["script"] = " ".join(s["text"].strip() for s in meta["sections"])
    return meta


def plan_shorts(trends, niche, used, n):
    lo, hi = LENGTHS["short"]
    data = llm_json(f"""You write viral tech & AI news YouTube Shorts. Today's trending items:
{trends_text(trends)}

{topic_rules(niche, used)}

Pick {n} DIFFERENT stories (one Short each). Each script {lo}-{hi} words (40-55 seconds):
first sentence is a scroll-stopping hook, short punchy sentences, end with a question for comments.
{RULES}

Return JSON only:
{{"shorts": [{{"topic": "short topic name",
  "title": "curiosity title, main keyword first, max 60 chars",
  "description": "2-3 sentences, first one has the main keyword",
  "tags": ["8-12 tags"],
  "pinned_comment": "one engaging question",
  "script": "...",
  "keywords": ["5 image search terms"]}}]}}""", required=("shorts",))
    shorts = data["shorts"][:n]
    for s in shorts:
        if len(s["script"].split()) < lo * 0.9:
            log(f"[short] '{s['topic']}' too short, expanding")
            s["script"] = expand(s["script"], lo, hi)
    return shorts


# ---------- 3. Voice + captions ----------
async def _tts(text, voice, rate, mp3):
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for c in comm.stream():
            if c["type"] == "audio":
                f.write(c["data"])
            elif c["type"] == "WordBoundary":
                words.append((c["offset"] / 1e7, (c["offset"] + c["duration"]) / 1e7, c["text"]))
    return words


def tts(text, mp3, kind):
    for attempt in range(4):
        try:
            return asyncio.run(_tts(text, os.environ.get("TTS_VOICE", "en-US-AndrewMultilingualNeural"),
                                    os.environ.get("TTS_RATE", "+10%"), mp3))
        except Exception as e:
            if attempt == 3:
                raise
            log(f"[{kind}] TTS failed ({e}), retrying")
            time.sleep(10 * (attempt + 1))


def ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(words, path, fmt):
    style = (f"Style: Default,{FONT},{fmt['font']},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
             f"1,0,0,0,100,100,0,0,1,6,3,{fmt['align']},70,70,{fmt['margin_v']},1")
    n = fmt["per_line"]
    lines = []
    for i in range(0, len(words), n):
        chunk = words[i:i + n]
        end = words[i + n][0] if i + n < len(words) else chunk[-1][1] + 0.3
        text = " ".join(w[2] for w in chunk).upper().replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{ass_time(chunk[0][0])},{ass_time(end)},Default,,0,0,0,,{text}")
    path.write_text(ASS_HEAD.format(w=fmt["w"], h=fmt["h"], styles=style) + "\n".join(lines) + "\n", encoding="utf-8")


def audio_duration(mp3):
    err = subprocess.run([FFMPEG, "-i", str(mp3)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def chapters(sections, words):
    """YouTube chapters: first at 0:00, at least 3, each at least 10s apart."""
    total = sum(len(s["text"].split()) for s in sections) or 1
    out, cum = [], 0
    for s in sections:
        t = 0.0 if not out else words[min(len(words) - 1, round(cum / total * len(words)))][0]
        if not out or t - out[-1][0] >= 10:
            out.append((t, s["heading"].strip()))
        cum += len(s["text"].split())
    return out if len(out) >= 3 else []


def ts(t):
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


# ---------- 4. Visuals ----------
def pixabay_search(query, key):
    r = requests.get("https://pixabay.com/api/videos/",
                     params={"key": key, "q": query[:100], "per_page": 30, "safesearch": "true"}, timeout=30)
    if not r.ok:
        return []
    return [{"id": f"pb{h['id']}",
             "files": [{"link": v["url"], "width": v["width"], "height": v["height"]}
                       for v in h["videos"].values() if v.get("url") and v.get("width")]}
            for h in r.json().get("hits", [])]


def pexels_search(query, fmt, key):
    r = requests.get("https://api.pexels.com/videos/search",
                     params={"query": query, "orientation": fmt["orientation"], "per_page": 15},
                     headers={"Authorization": key}, timeout=30)
    if not r.ok:
        return []
    return [{"id": f"px{v['id']}",
             "files": [{"link": f["link"], "width": f["width"], "height": f["height"]}
                       for f in v["video_files"] if f.get("width") and f.get("height")]}
            for v in r.json().get("videos", [])]


WIKI_UA = {"User-Agent": "TechPulseVideoBot/1.0 (personal YouTube automation; python-requests)"}


def wikimedia_search(query):
    """Free-licensed photos from Wikimedia Commons, no key needed. Credit required (collected per image)."""
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6, "gsrlimit": 15, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1920})
    if not r.ok:
        return []
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3}
    out = []
    for p in r.json().get("query", {}).get("pages", {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/webp") or min(ii.get("width", 0), ii.get("height", 0)) < 700:
            continue
        name = p["title"].removeprefix("File:")
        score = len(words & set(re.findall(r"[a-z0-9]+", name.lower())))
        if words and score == 0:  # file name shares no word with the query: usually off-topic
            continue
        md = ii.get("extmetadata", {})
        artist = html.unescape(re.sub(r"<[^>]+>", "", md.get("Artist", {}).get("value", "Unknown"))).strip()[:60]
        license_ = md.get("LicenseShortName", {}).get("value", "see source")
        out.append({"id": f"wm{p['pageid']}", "image": ii.get("thumburl") or ii["url"], "score": score,
                    "credit": f"{name} - {artist} ({license_}) {ii.get('descriptionurl', '')}"})
    return out


def search_footage(query, fmt):
    videos = []
    if os.environ.get("PIXABAY_API_KEY"):
        videos += pixabay_search(query, os.environ["PIXABAY_API_KEY"])
    if os.environ.get("PEXELS_API_KEY"):
        videos += pexels_search(query, fmt, os.environ["PEXELS_API_KEY"])
    random.shuffle(videos)
    portrait = fmt["h"] > fmt["w"]
    # list.pop() takes from the end: images first in list (used last), then videos, matching orientation last.
    videos.sort(key=lambda v: any((f["height"] > f["width"]) == portrait for f in v["files"]))
    images = wikimedia_search(query) if os.environ.get("USE_WIKIMEDIA", "1") == "1" else []
    random.shuffle(images)
    images.sort(key=lambda i: i["score"])  # best match popped first
    return images + videos


def best_file(video, fmt):
    portrait = fmt["h"] > fmt["w"]
    files = [f for f in video["files"] if max(f["width"], f["height"]) >= 1280]
    same = [f for f in files if (f["height"] > f["width"]) == portrait]
    return min(same or files, key=lambda f: abs(f["width"] - fmt["w"]) + abs(f["height"] - fmt["h"]), default=None)


def fetch_clips(keywords, folder, fmt, need):
    """Spread `need` clips across keywords in script order, distinct sources.
    Returns [{"path", "is_image", "credit"}]."""
    if not keywords:
        return []
    results = {kw: search_footage(kw, fmt) for kw in keywords}
    clips, used = [], set()
    while len(clips) < need and any(results.values()):
        for kw in keywords:
            if len(clips) >= need:
                break
            while results[kw]:
                v = results[kw].pop()
                if v["id"] in used:
                    continue
                if "image" in v:
                    ext = Path(urlparse(v["image"]).path).suffix.lower()
                    ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"  # browser renderer needs a real type
                    link, path = v["image"], folder / f"clip{len(clips):02d}{ext}"
                else:
                    f = best_file(v, fmt)
                    if not f:
                        continue
                    link, path = f["link"], folder / f"clip{len(clips):02d}.mp4"
                used.add(v["id"])
                try:
                    with requests.get(link, stream=True, timeout=180, headers=WIKI_UA) as d:
                        d.raise_for_status()
                        with open(path, "wb") as fh:
                            for b in d.iter_content(1 << 20):
                                fh.write(b)
                except requests.RequestException:
                    continue
                clips.append({"path": path, "is_image": "image" in v, "credit": v.get("credit")})
                break
    return clips


# ---------- 5. Assemble ----------
def build_video(work, clips, duration, fmt):
    w, h = fmt["w"], fmt["h"]
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,setsar=1"
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an"]
    total = duration + 0.5
    if clips:
        n = max(len(clips), round(total / fmt["clip_secs"]))
        seg = total / n
        parts = []
        frames = round(seg * 30)
        for i in range(n):
            clip, out = clips[i % len(clips)], f"part{i:03d}.mp4"
            if clip["is_image"]:
                # Blurred fill behind the fitted photo, then slow zoom in/out (Ken Burns).
                z = f"min(1+0.12*on/{frames},1.12)" if i % 2 == 0 else f"max(1.12-0.12*on/{frames},1)"
                if h > w:  # vertical: photo fills a large center band instead of a thin strip
                    bh = round(h * 0.62) // 2 * 2
                    fg = f"scale={w}:{bh}:force_original_aspect_ratio=increase,crop={w}:{bh}"
                else:
                    fg = f"scale={w}:{h}:force_original_aspect_ratio=decrease"
                fc = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=40:4[bg];"
                      f"[0:v]{fg}[fg];"
                      f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={w * 2}:{h * 2},"
                      f"zoompan=z='{z}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=30,setsar=1")
                ff(["-i", clip["path"].name, "-filter_complex", fc, "-frames:v", str(frames), *enc, out], work)
            else:
                ff(["-stream_loop", "-1", "-i", clip["path"].name, "-t", f"{seg:.3f}", "-vf", vf, *enc, out], work)
            parts.append(out)
        (work / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
        ff(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "bg.mp4"], work)
    else:
        ff(["-f", "lavfi", "-i", f"color=c=0x0f172a:s={w}x{h}:r=30", "-t", f"{total:.2f}", *enc, "bg.mp4"], work)
    ff(["-i", "bg.mp4", "-i", "voice.mp3", "-vf", subs_filter(work, "subs.ass"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", "final.mp4"], work)
    for p in work.glob("part*.mp4"):
        p.unlink()
    return work / "final.mp4"


def make_thumbnail(work, text, at, image=None):
    """1280x720 JPG: main-subject photo (or a video frame) darkened + big yellow headline + channel tag."""
    channel = os.environ.get("CHANNEL_NAME", "TechPulse").upper()
    styles = (f"Style: Head,{FONT},172,&H0000E5FF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,10,6,4,70,460,0,1\n"
              f"Style: Tag,{FONT},52,&H00FFFFFF,&H000000FF,&H00000000,&HC0E5A000,0,0,0,0,100,100,3,0,3,14,0,7,50,50,40,1")
    clean = re.sub(r"[{}\\]", "", text).upper()
    (work / "thumb.ass").write_text(ASS_HEAD.format(w=1280, h=720, styles=styles)
                                    + f"Dialogue: 0,0:00:00.00,9:00:00.00,Head,,0,0,0,,{clean}\n"
                                    + f"Dialogue: 0,0:00:00.00,9:00:00.00,Tag,,0,0,0,,{channel}\n", encoding="utf-8")
    look = f"eq=brightness=-0.12:saturation=1.4,{subs_filter(work, 'thumb.ass')}"
    if image:
        fc = ("[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,boxblur=30:3[bg];"
              "[0:v]scale=1280:720:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{look}")
        ff(["-i", image.name, "-frames:v", "1", "-filter_complex", fc, "-q:v", "3", "thumb.jpg"], work)
    else:
        src = "bg.mp4" if (work / "bg.mp4").exists() else "final.mp4"  # animated style has no bg.mp4
        ff(["-ss", f"{at:.2f}", "-i", src, "-frames:v", "1", "-vf", f"scale=1280:720,{look}",
            "-q:v", "3", "thumb.jpg"], work)
    return work / "thumb.jpg"


def render_motion(work, kind, words, duration, clips, title, sections):
    """Animated style (Remotion): mascot, kinetic captions, headline cards. Assets served from the work folder."""
    fmt = FORMATS[kind]
    fps, total = 30, duration + 0.8
    images = [c for c in clips if c["is_image"]]
    scenes = []
    if images:
        n = max(len(images), round(total / fmt["clip_secs"]))
        seg = total / n
        scenes = [{"start": round(i * seg, 3), "end": round((i + 1) * seg, 3), "src": images[i % len(images)]["path"].name}
                  for i in range(n)]
    shutil.copy(ROOT / "fonts" / "Anton-Regular.ttf", work / "Anton-Regular.ttf")
    props = {"kind": kind, "width": fmt["w"], "height": fmt["h"], "fps": fps, "durationInFrames": round(total * fps),
             "audio": "voice.mp3", "words": [[round(a, 3), round(b, 3), w] for a, b, w in words], "scenes": scenes,
             "sections": [{"start": round(t, 2), "heading": h} for t, h in sections], "title": title,
             "channel": os.environ.get("CHANNEL_NAME", "TechPulse").upper()}
    (work / "props.json").write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    npx = shutil.which("npx") or "npx"
    subprocess.run([npx, "remotion", "render", "src/index.jsx", "Long" if kind == "long" else "Short",
                    str(work / "final.mp4"), f"--props={work / 'props.json'}", f"--public-dir={work}",
                    "--log=error", "--crf=20"], cwd=ROOT / "motion", check=True)
    return work / "final.mp4"


def make_video(work, kind, script, keywords, title="", sections=()):
    fmt = FORMATS[kind]
    work.mkdir(parents=True, exist_ok=True)
    log(f"[{kind}] voice")
    words = tts(script, work / "voice.mp3", kind)
    write_ass(words, work / "subs.ass", fmt)
    duration = audio_duration(work / "voice.mp3")
    log(f"[{kind}] voice {duration:.0f}s, downloading visuals")
    clips = fetch_clips(keywords, work, fmt, need=min(30, round(duration / fmt["clip_secs"])))
    log(f"[{kind}] {len(clips)} clips ({sum(c['is_image'] for c in clips)} photos), rendering")
    credits = [c["credit"] for c in clips if c["credit"]]
    video = None
    if os.environ.get("RENDER_STYLE", "motion") == "motion":
        try:
            video = render_motion(work, kind, words, duration, clips, title, chapters(sections, words) if sections else [])
        except Exception as e:  # never lose a day's video: fall back to the classic slideshow
            log(f"[{kind}] animated render failed ({str(e)[:150]}), using classic style")
    if video is None:
        video = build_video(work, clips, duration, fmt)
    first_photo = next((c["path"] for c in clips if c["is_image"]), None)
    return {"video": video, "words": words, "duration": duration, "credits": credits, "first_photo": first_photo}


# ---------- 6. YouTube ----------
_YT = None


def youtube_client():
    global _YT
    if _YT:
        return _YT
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # user may untick optional scopes on consent screen
    tok = ROOT / "token.json"
    # Cloud runner: credentials come from encrypted GitHub Secrets, written to git-ignored files at runtime.
    for path, var in ((tok, "YT_TOKEN_JSON"), (ROOT / "client_secret.json", "YT_CLIENT_SECRET_JSON")):
        if not path.exists() and os.environ.get(var):
            path.write_text(os.environ[var].lstrip("﻿"), encoding="utf-8")  # PowerShell pipes add a BOM
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / "client_secret.json"), SCOPES)
            creds = flow.run_local_server(port=0)
        tok.write_text(creds.to_json())
    _YT = build("youtube", "v3", credentials=creds)
    return _YT


def description(meta, short, topic, credits, chapter_list=()):
    channel = os.environ.get("CHANNEL_NAME", "TechPulse")
    tag = re.sub(r"\W", "", topic.title())
    parts = [meta["description"].strip()]
    if chapter_list:
        parts.append("Chapters:\n" + "\n".join(f"{ts(t)} {h}" for t, h in chapter_list))
    parts.append(f"Subscribe to {channel} for daily tech & AI news.")
    tail = ("#Shorts " if short else "") + f"#TechNews #AI #{tag}"
    head = "\n\n".join(parts)
    if credits:
        block = "Image credits (Wikimedia Commons / stock):\n"
        budget = 4800 - len(head) - len(tail)
        for c in credits:
            if len(block) + len(c) + 1 > budget:
                break
            block += c + "\n"
        head += "\n\n" + block.strip()
    return f"{head}\n\n{tail}"


def upload(path, title, desc, tags, short):
    from googleapiclient.http import MediaFileUpload

    title = title.strip()
    if short and "#shorts" not in title.lower():
        title = title[:90] + " #Shorts"
    body = {
        "snippet": {"title": title[:100], "description": desc, "tags": tags[:15],
                    "categoryId": os.environ.get("YT_CATEGORY", "28"), "defaultLanguage": "en",
                    "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": os.environ.get("YT_PRIVACY", "public"), "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},
    }
    req = youtube_client().videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    tries = 0
    while resp is None:
        try:
            _, resp = req.next_chunk()  # resumable: a retry continues where the dropped chunk stopped
        except Exception as e:
            tries += 1
            if tries > 5:
                raise
            log(f"  upload interrupted ({str(e)[:80]}), retry {tries}/5")
            time.sleep(10 * tries)
    return resp["id"]


def after_upload(vid, thumb=None, comment=None):
    from googleapiclient.http import MediaFileUpload

    yt = youtube_client()
    if thumb:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
            log("  thumbnail set")
        except Exception as e:
            log(f"  thumbnail skipped: {str(e)[:150]}")
    if comment:
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {
                "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": comment}}}}).execute()
            log("  comment posted (pin it in YouTube Studio for best results)")
        except Exception as e:
            log(f"  comment skipped: {str(e)[:150]}")


def upload_existing(work):
    """Upload an already-rendered video folder (used by the dashboard's Upload button)."""
    work = Path(work).resolve()
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    short = "_short_" in work.name
    desc = (work / "description.txt").read_text(encoding="utf-8")
    vid = upload(work / "final.mp4", meta["title"], desc, meta.get("tags", []), short)
    log(f"uploaded https://youtu.be/{vid}")
    thumb = work / "thumb.jpg"
    after_upload(vid, thumb if thumb.exists() else None, meta.get("pinned_comment"))
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    video = str(work / "final.mp4")
    entry = next((h for h in history if h.get("video") == video), None)
    if entry is None:
        entry = {"date": str(datetime.date.today()), "kind": "short" if short else "long",
                 "topic": meta["topic"], "title": meta["title"], "video": video}
        history.append(entry)
    entry["youtube_id"] = vid
    HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------- 7. Supabase (records, previews, publish queue, stats, cleanup) ----------
BUCKET = "videos"
KEEP_DAYS = 7


def sb_on():
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"))


def sb_headers(extra=None):
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return {"apikey": key, "Authorization": f"Bearer {key}", **(extra or {})}


def sb_rest(method, path, **kw):
    r = requests.request(method, f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path}",
                         headers=sb_headers({"Content-Type": "application/json", "Prefer": "return=representation"}),
                         timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.text else []


def sb_upload(local, remote, ctype):
    with open(local, "rb") as f:
        r = requests.post(f"{os.environ['SUPABASE_URL'].rstrip('/')}/storage/v1/object/{BUCKET}/{remote}",
                          headers=sb_headers({"Content-Type": ctype, "x-upsert": "true"}), data=f, timeout=900)
    r.raise_for_status()
    return remote


def sb_remove(paths):
    if paths:
        requests.delete(f"{os.environ['SUPABASE_URL'].rstrip('/')}/storage/v1/object/{BUCKET}",
                        headers=sb_headers({"Content-Type": "application/json"}),
                        json={"prefixes": paths}, timeout=60).raise_for_status()


def days_ago(n):
    # 'Z' form: a '+00:00' offset would turn into a space inside the query string.
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def used_topics():
    if sb_on():
        since = days_ago(14)
        return [r["topic"] for r in sb_rest("GET", f"videos?select=topic&created_at=gte.{since}") if r.get("topic")]
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    return [h["topic"] for h in history[-80:] if h.get("topic")]


def make_preview(work, kind):
    """Small 720p copy for the phone app (keeps Supabase free storage/bandwidth low)."""
    scale = "1280:-2" if kind == "long" else "-2:1280"
    ff(["-i", "final.mp4", "-vf", f"scale={scale}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
        "-maxrate", "800k", "-bufsize", "1600k", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
        "preview.mp4"], work)
    return work / "preview.mp4"


def record(work, kind, meta, desc, duration, vid, thumb):
    if not sb_on():
        return
    prefix = f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%d}/{work.parent.name}_{work.name}"
    preview = sb_upload(make_preview(work, kind), f"{prefix}/preview.mp4", "video/mp4")
    thumb_path = sb_upload(thumb, f"{prefix}/thumb.jpg", "image/jpeg") if thumb else None
    sb_rest("POST", "videos", json={
        "kind": kind, "topic": meta["topic"], "title": meta["title"], "description": desc,
        "tags": meta.get("tags", [])[:15], "status": "uploaded" if vid else "rendered", "youtube_id": vid,
        "privacy": os.environ.get("YT_PRIVACY", "private") if vid else None,
        "preview_path": preview, "thumb_path": thumb_path, "duration_s": round(duration, 1),
        "meta": {k: meta.get(k) for k in ("pinned_comment", "keywords", "thumbnail_text")}})
    log(f"[{kind}] saved to Supabase")


def publish_pending():
    rows = sb_rest("GET", "videos?select=id,youtube_id,title,meta&publish_requested=is.true&status=neq.published"
                          "&youtube_id=not.is.null")
    for row in rows:
        try:
            youtube_client().videos().update(part="status", body={"id": row["youtube_id"], "status": {
                "privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}).execute()
            sb_rest("PATCH", f"videos?id=eq.{row['id']}", json={
                "status": "published", "privacy": "public",
                "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            log(f"published https://youtu.be/{row['youtube_id']} | {row['title']}")
            after_upload(row["youtube_id"], comment=(row.get("meta") or {}).get("pinned_comment"))
        except Exception as e:
            log(f"publish failed {row['youtube_id']}: {str(e)[:200]}")
    if not rows:
        log("nothing to publish")


def update_stats():
    rows = sb_rest("GET", "videos?select=id,youtube_id&youtube_id=not.is.null")
    for i in range(0, len(rows), 50):
        chunk = {r["youtube_id"]: r["id"] for r in rows[i:i + 50]}
        resp = youtube_client().videos().list(part="statistics,status", id=",".join(chunk)).execute()
        for v in resp.get("items", []):
            s = v.get("statistics", {})
            sb_rest("PATCH", f"videos?id=eq.{chunk[v['id']]}", json={
                "privacy": v["status"]["privacyStatus"],
                "stats": {k: int(s.get(k, 0)) for k in ("viewCount", "likeCount", "commentCount")}})
    log(f"stats updated for {len(rows)} videos")


def cleanup():
    cutoff = days_ago(KEEP_DAYS)
    old = sb_rest("GET", f"videos?select=id,preview_path,thumb_path&created_at=lt.{cutoff}")
    sb_remove([p for r in old for p in (r["preview_path"], r["thumb_path"]) if p])
    if old:
        sb_rest("DELETE", f"videos?created_at=lt.{cutoff}")
    log(f"cleanup: removed {len(old)} records older than {KEEP_DAYS} days (YouTube videos are kept)")


# ---------- main ----------
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "video"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--long", type=int, help="number of long videos (0 or 1, default 1)")
    ap.add_argument("--shorts", type=int, help="number of Shorts (default 1)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--upload-dir", help="upload an already-rendered video folder")
    ap.add_argument("--publish-pending", action="store_true", help="make app-approved videos public")
    ap.add_argument("--stats", action="store_true", help="refresh YouTube stats in Supabase")
    ap.add_argument("--cleanup", action="store_true", help=f"delete Supabase records/files older than {KEEP_DAYS} days")
    args = ap.parse_args()
    load_env()
    if args.auth:
        youtube_client()
        log("YouTube auth OK, token.json saved")
        return
    if args.upload_dir:
        upload_existing(args.upload_dir)
        return
    maintenance = [f for flag, f in ((args.publish_pending, publish_pending), (args.stats, update_stats),
                                     (args.cleanup, cleanup)) if flag]
    for f in maintenance:
        f()
    if maintenance and args.long is None and args.shorts is None:
        return
    args.long = 1 if args.long is None else args.long
    args.shorts = 1 if args.shorts is None else args.shorts

    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    used = used_topics()
    niche = os.environ.get("NICHE", "technology and AI")
    run_dir = OUT / f"{datetime.datetime.now():%Y-%m-%d_%H%M}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log("Fetching trends")
    trends = fetch_trends(os.environ.get("GEO", "US"))
    if not trends:
        raise RuntimeError("No trends from any source")

    jobs = []
    if args.long:
        log("Writing long script")
        m = plan_long(trends, niche, used)
        jobs.append(("long", m))
        used.append(m["topic"])
    if args.shorts:
        log(f"Writing {args.shorts} Short script(s)")
        jobs += [("short", m) for m in plan_shorts(trends, niche, used, args.shorts)]

    failures = 0
    for i, (kind, meta) in enumerate(jobs):
        try:
            work = run_dir / f"{i}_{kind}_{slugify(meta['topic'])}"
            work.mkdir(parents=True, exist_ok=True)
            (work / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            log(f"=== {kind}: {meta['topic']} | {meta['title']}")
            r = make_video(work, kind, meta["script"], meta.get("keywords", []), meta["title"],
                           meta.get("sections", []))
            chap = chapters(meta["sections"], r["words"]) if kind == "long" else []
            desc = description(meta, kind == "short", meta["topic"], r["credits"], chap)
            (work / "description.txt").write_text(desc, encoding="utf-8")
            thumb = make_thumbnail(work, meta.get("thumbnail_text") or meta["topic"], r["duration"] * 0.25,
                                   r["first_photo"]) if kind == "long" else None
            log(f"[{kind}] rendered {r['video']}")
            entry = {"date": str(datetime.date.today()), "kind": kind, "topic": meta["topic"],
                     "title": meta["title"], "video": str(r["video"])}
            vid = None
            if not args.no_upload:
                vid = upload(r["video"], meta["title"], desc, meta.get("tags", []), kind == "short")
                log(f"[{kind}] uploaded https://youtu.be/{vid}")
                # YouTube rejects comments on private videos; publish_pending() posts it once public.
                public_now = os.environ.get("YT_PRIVACY", "private") == "public"
                after_upload(vid, thumb, meta.get("pinned_comment") if public_now else None)
                entry["youtube_id"] = vid
            record(work, kind, meta, desc, r["duration"], vid, thumb)
            history.append(entry)
            HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:  # one bad video must not stop the rest of the run
            failures += 1
            log(f"[{kind}] FAILED: {e}")
    if failures:
        raise SystemExit(f"{failures} video(s) failed")


if __name__ == "__main__":
    main()
