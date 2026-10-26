"""TechPulse: trending tech news -> scripts -> voice -> video -> YouTube (long 16:9 + Shorts 9:16)."""
import argparse
import asyncio
import datetime
import html
import json
import math
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
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
UA = {"User-Agent": "Mozilla/5.0 (TechPulse trend fetcher)"}

FORMATS = {
    "long": dict(w=1920, h=1080, orientation="landscape", font=104, align=2, margin_v=90, per_line=5, clip_secs=6),
    "short": dict(w=1080, h=1920, orientation="portrait", font=150, align=5, margin_v=0, per_line=3, clip_secs=2),  # visual change every ~2s holds Shorts viewers
}
FONT = "Anton"  # bundled in fonts/ (OFL) so captions look the same on Windows and the Linux cloud runner


def subs_filter(work, ass):
    fontsdir = os.path.relpath(ROOT / "fonts", work).replace("\\", "/")
    return f"subtitles={ass}:fontsdir={fontsdir}"
LENGTHS = {"long": (680, 820), "short": (110, 140), "weekly": (1500, 1900)}

# Each language = its own audience: trends region, news edition, voices, lip-sync mode, YouTube language, UI text.
LANGS = {
    "en": {"name": "English", "geo": "US", "news": "hl=en-US&gl=US&ceid=US:en", "suggest_hl": "en",
           "voices": {"male": "en-US-AndrewMultilingualNeural", "female": "en-US-AvaMultilingualNeural"},
           "lipsync": "pocketSphinx",
           "ui": {"news": "TECH NEWS", "fact": "FACT", "subscribe": "SUBSCRIBE", "like": "LIKE", "comment": "COMMENT",
                  "share": "SHARE"},
           "follow_line": "Subscribe for daily AI and tech news in 30 seconds.",
           "show_intro": "This is TechPulse Daily.", "signoff": "Stay curious, stay ahead.",
           "text": {"in_video": "In this video:", "sources": "Sources",
                    "subscribe": "Subscribe to {c} for daily tech & AI news in minutes.",
                    "more_short": "Watch the full stories on our channel.", "more_long": "Quick versions in our Shorts.",
                    "ai": "Voice and visuals are AI-assisted. Facts are based on the sources listed above.",
                    "credits": "Image credits (Wikimedia Commons / stock):", "full_story": "▶ Full story:",
                    "topics": "Topics in this video:"},
           "wait": "WAIT FOR IT 👀",
           "style": "Natural spoken American English."},
    "hi": {"name": "Hindi", "geo": "IN", "news": "hl=en-IN&gl=IN&ceid=IN:en", "suggest_hl": "hi",
           "voices": {"male": "hi-IN-MadhurNeural", "female": "hi-IN-SwaraNeural"},
           "lipsync": "phonetic",  # Rhubarb's English recognizer does not know Hindi; phonetic mode is language-neutral
           "ui": {"news": "टेक न्यूज़", "fact": "तथ्य", "subscribe": "SUBSCRIBE", "like": "लाइक", "comment": "कमेंट",
                  "share": "शेयर"},
           "follow_line": "रोज़ की AI और tech news 30 seconds में - Subscribe करें।",
           "show_intro": "आप देख रहे हैं TechPulse Daily.", "signoff": "Curious रहिए, आगे रहिए।",
           "text": {"in_video": "इस वीडियो में:", "sources": "Sources",
                    "subscribe": "रोज़ की Tech और AI news के लिए {c} को Subscribe करें।",
                    "more_short": "पूरी कहानी हमारे channel पर देखें।", "more_long": "छोटे updates हमारे Shorts में देखें।",
                    "ai": "Voice और visuals AI की मदद से बनाए गए हैं। Facts ऊपर दिए गए sources पर आधारित हैं।",
                    "credits": "Image credits (Wikimedia Commons / stock):", "full_story": "▶ पूरी कहानी देखें:",
                    "topics": "इस वीडियो के topics:"},
           "wait": "अंत तक देखें 👀",
           "style": ("Conversational Hindi in Devanagari script, the way popular Indian tech YouTubers speak: keep product"
                     " names and everyday tech words (AI, app, phone, launch, update, chip, feature, price) in English"
                     " using Latin letters. Simple words, friendly tone, like talking to a friend. Mention what it means"
                     " for Indian users when the sources support it.")},
}
LANG = "en"  # set from --lang in main()


def L():
    return LANGS[LANG]


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
LLM_TIMEOUT = 120


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    # raw_decode stops at the end of the first JSON object, so trailing text/objects are ignored.
    return json.JSONDecoder().raw_decode(text[text.find("{"):])[0]


def gemini(prompt, model, timeout=None):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}},
        timeout=timeout or LLM_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def openrouter(prompt, model, timeout=None):
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={"model": model, "temperature": 0.9,
              "messages": [{"role": "user", "content": prompt + "\n\nRespond with the JSON object only."}]},
        timeout=timeout or LLM_TIMEOUT,
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


_LLM_BENCH = {}  # model -> time until which it is skipped (rate-limited, overloaded, or gone for this run)


def llm_json(prompt, required=(), timeout=None):
    """Try each provider/model in order; move to the next on rate limit, timeout, error or bad JSON.
    Three full rounds with growing pauses: Gemini 503 'overloaded' and per-minute 429 limits clear within minutes.
    Models that just failed with 429/503 sit out 2 minutes, and 401/403/404 ones the whole run, so calls don't
    waste time on them."""
    for attempt in range(3):
        for call, model in llm_providers():
            if _LLM_BENCH.get(model, 0) > time.time() and attempt == 0:
                continue
            try:
                data = parse_json(call(prompt, model, timeout))
                missing = [k for k in required if k not in data]
                if missing:
                    raise ValueError(f"missing keys {missing}")
                log(f"LLM ok: {call.__name__}/{model}")
                return data
            except Exception as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (429, 503):
                    _LLM_BENCH[model] = time.time() + 120
                elif code in (401, 403, 404):
                    _LLM_BENCH[model] = time.time() + 86400
                log(f"LLM failed {call.__name__}/{model}: {str(e)[:160]} -> switching")
        if attempt < 2:
            wait = (90, 240)[attempt]
            log(f"All LLM providers failed, waiting {wait}s and retrying")
            time.sleep(wait)
    raise RuntimeError("All LLM providers failed")


CHANNEL = lambda: os.environ.get("CHANNEL_NAME", "TechPulse")

RULES = """Accuracy rules (most important):
- Use ONLY facts found in the SOURCE HEADLINES below. If a detail is not there, do not state it as fact:
  frame it as context, opinion or an open question ("reports suggest", "it is not confirmed yet").
- Never invent numbers, prices, dates, quotes, specs or names. Attribute claims to their outlet ("according to The Verge").
- Natural spoken English, no headings read aloud, no stage directions, no emojis, no hashtags in the script.

Retention rules (what the YouTube algorithm rewards):
- First sentence = hook in under 2 seconds: a surprising fact, stakes, or a question. No greetings, no channel intro.
- Open a curiosity loop early ("but the real story is what happens next") and pay it off later.
- Short punchy sentences; a new idea every 2-3 sentences; say "you" - tell viewers why it matters to THEM.

Image keywords (searched on Wikimedia Commons): 2-4 words each, unambiguous, in script order.
  Keyword 1 = the exact main subject (used for the thumbnail), e.g. 'iPhone Duo' or 'Nvidia Blackwell GPU'.
  Mostly specific names, e.g. 'Apple iPhone' not 'Apple', 'Sam Altman OpenAI'. A few generic visuals like 'data center servers'."""

SEO_RULES = """SEO rules:
- primary_keyword: the phrase people actually search (prefer one from YOUTUBE SEARCH SUGGESTIONS).
- title: primary keyword in the first 40 characters, specific + curiosity, honest (no clickbait lies), no hashtags,
  no ALL CAPS sentences, no quotes around it.
- description_hook: ONE sentence that starts with the primary keyword and says what viewers learn.
- summary: 4-6 natural sentences (a real mini-article, not a keyword list) that work in 8-12 related search phrases
  people type (product + feature, product + price, "vs" comparisons, "explained", "news today", year).
- topics: 5-8 short phrases that describe what the video covers (shown as a bullet list), each a real search phrase.
- tags: 30-40 tags, ALL relevant to this exact video: exact search phrases from the suggestions, product/company
  names, model numbers, common misspellings people type, "vs" phrases, and broad tags like 'tech news', 'ai news',
  'technology'. No '#', no '<' or '>'. Never add unrelated trending tags (YouTube treats that as spam).
- hashtags: 10-12 relevant hashtags, CamelCase, no spaces, the 3 most important first (YouTube shows those above
  the title; more than 15 makes YouTube ignore all of them)."""


def lang_rules():
    if LANG == "hi":
        return ("LANGUAGE: Write the spoken script, description_hook, summary, key_points, facts, pinned_comment and section"
                f" headings in Hindi. {L()['style']}\n"
                "Title: Hinglish - start with the English search keyword Indians actually type (e.g. 'iPhone 17 Launch:'),"
                " then a short Hindi hook in Devanagari. thumbnail_text and hook_text: short, English letters or Hinglish.\n"
                "Tags: mix English search phrases, Hinglish phrases and Hindi words (e.g. 'tech news hindi', 'AI news in hindi').\n"
                "INDIA ANGLE: when the sources give it, lead with what it means in India - the India price in rupees (₹),"
                " India launch date, Jio/Airtel, UPI, Flipkart/Amazon India. Never convert or invent a rupee price the"
                " sources do not state.")
    return f"LANGUAGE: {L()['style']}"


# Channel safety: topics that commonly lead to YouTube Community Guidelines strikes, age limits or demonetization.
SAFE_TOPICS = ("NEVER pick stories about: deaths, shootings, violence, disasters or tragedies; elections, politicians or"
               " political fights; health, medical or vaccine claims; sexual content; children or minors; hate or"
               " religion; drugs or weapons; how-to hacking, piracy or cheating; investment, crypto or money advice;"
               " crimes or accusations against named private people. Tech business, products, AI, apps, outages and"
               " company security breaches are fine.")

# Tie-breaker focus that rotates daily (see the 1-year plan doc); trends and performance still come first.
DAY_FOCUS = {
    "en": ["AI tools and AI drama", "phone launches and leaks", "hacks, outages and data leaks",
           "big tech business (Apple, Google, Nvidia)", "apps changing their rules (Spotify, WhatsApp, X)",
           "gadgets and gaming", "the week's biggest tech story, explained"],
    "hi": ["AI in India (jobs, apps, government rules)", "phone prices and launches in India",
           "bank and UPI security, data leaks", "Jio, Airtel and Indian startups", "app rules and bans in India",
           "budget gadgets in India", "the week's biggest tech story, explained in Hindi"],
}


# What our own winners have in common (Oct 2026: "Switch 2 Hacked!", Xbox price, "DeepInfer" vs ~40-130 views for
# abstract stories) plus Shorts research: concrete brand + conflict/money beats abstract AI-research news.
TOPIC_SCORE = ("TOPIC SCORE - rate each candidate story and pick the highest:\n"
               "+3 a famous named product/brand people own or want (iPhone, Galaxy, Pixel, PlayStation, Xbox, Switch,"
               " ChatGPT, Gemini, WhatsApp, Instagram, Windows, Tesla)\n"
               "+2 money: a price, price hike, fee, 'free', deal or cost\n"
               "+2 conflict or stakes: hacked, leaked, banned, killed, broken, lawsuit, outage, 'vs'\n"
               "+2 for Hindi: an India angle in the sources (India price in rupees, India launch date, Jio/Airtel, UPI,"
               " Flipkart/Amazon India)\n"
               "+1 something the viewer can do or check today\n"
               "-3 abstract research, academic papers, enterprise/B2B tools, funding rounds or company reorganisations"
               " with no product people use")


def requests_block():
    """Topics viewers asked for in comments (last 7 days, this language): preferred when fresh news covers them."""
    week_ago = str(datetime.date.today() - datetime.timedelta(days=7))
    reqs = [r["topic"] for r in (get_setting("topic_requests", []) or []) if r.get("lang") == LANG
            and r.get("at", "") >= week_ago] if sb_on() else []
    return ("VIEWER REQUESTS (asked for in our comments - +3 if fresh news covers it): " + "; ".join(reqs[-10:]) + "\n"
            ) if reqs else ""


def topic_rules(niche, used):
    audience = ("Audience: Indian viewers. Prefer stories Indians care about (India launches, prices in India, Jio/Airtel,"
                " Indian startups, global big-tech news that affects India)." if LANG == "hi" else "Audience: US/global English viewers.")
    focus = DAY_FOCUS[LANG][datetime.date.today().toordinal() % 7]
    return (f"Channel: {CHANNEL()}, niche: {niche or 'tech'}. {audience}\n"
            f"Today's preferred theme when stories are otherwise equal: {focus}.\n"
            f"{SAFE_TOPICS}\n"
            f"{TOPIC_SCORE}\n"
            f"{requests_block()}"
            f"{goal_focus()}\n"
            f"{learned_block()}\n"
            f"Pick stories that fit the niche, are fresh today, and have the biggest audience (high searches,"
            f" points, upvotes, views; covered by several sources = bigger). Prefer stories viewers will have strong"
            f" feelings about (big brands, money, privacy, jobs, AI, new gadgets).\n"
            f"Do NOT pick these already-covered topics: {json.dumps(used, ensure_ascii=False)}")


STORY_COOLDOWN_H, STORY_MAX = 48, 2  # one product/event: max 2 videos per 48 h (14 iPhone Duo videos in 3 days hurt)
MIN_OUTLETS = 2  # never make a video about something fewer than 2 different news outlets report


def recent_stories(hours=STORY_COOLDOWN_H):
    """Videos of the last `hours` on the channel (both languages: viewers see one channel)."""
    if not sb_on():
        return []
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return sb_rest("GET", f"insights?select=story,topic,title&created_at=gte.{since}")
    except Exception:
        return []


def story_slug(pick):
    return slugify(pick.get("story") or pick.get("topic") or "")


def story_count(pick, rows):
    """How many recent videos are about the same product/event: same story tag, or (for older untagged videos)
    a near-identical topic."""
    slug = story_slug(pick)
    return sum(1 for r in rows if (r.get("story") and r["story"] == slug)
               or (not r.get("story") and repeats(pick.get("topic", ""), [r.get("topic") or ""])))


def stories_block(rows=None):
    """Tells the topic picker what the channel already covered and which stories are on cooldown."""
    rows = recent_stories() if rows is None else rows
    if not rows:
        return ""
    counts = {}
    for r in rows:
        key = r.get("story") or slugify(r.get("topic") or "")
        counts[key] = counts.get(key, 0) + 1
    blocked = [s for s, n in counts.items() if n >= STORY_MAX]
    return ("RECENT STORIES on this channel (last 48 h) and their number of videos:\n"
            + "\n".join(f"- {s}: {n}" for s, n in sorted(counts.items(), key=lambda x: -x[1])[:30])
            + f"\nBLOCKED (already {STORY_MAX}+ videos - do not pick ANY story about the same product or event, not even"
              f" a new angle): {', '.join(blocked) or 'none'}\n"
              'Give every pick a "story" field: a short lowercase slug of its main product or event. Reuse the exact slug'
              ' above when it is the same product/event (every iPhone Duo durability, price or launch story = "iphone-duo").')


def pick_topics(trends, niche, used, n_long, n_shorts, _retry=True):
    """Topics for the run. The model sometimes returns fewer than asked (an empty 'long' list once silently cost a
    long video): ask once more, then take what is missing from the other list's extras."""
    data = _pick_topics(trends, niche, used, n_long, n_shorts)
    longs = [p for p in data.get("long") or [] if isinstance(p, dict) and p.get("topic")][:n_long]
    shorts = [p for p in data.get("shorts") or [] if isinstance(p, dict) and p.get("topic")]
    if (len(longs) < n_long or len(shorts) < n_shorts) and _retry:
        log(f"topic picker returned {len(longs)} long / {len(shorts)} Shorts, asking again")
        return pick_topics(trends, niche, used, n_long, n_shorts, _retry=False)
    while len(longs) < n_long and len(shorts) > n_shorts:
        longs.append(shorts.pop())
    return longs, shorts  # may include the backup Short: plan_videos stops once it has n_shorts


def _pick_topics(trends, niche, used, n_long, n_shorts):
    return llm_json(f"""You run a viral tech & AI news YouTube channel. Today's trending items:
{trends_text(trends)}

{topic_rules(niche, used)}

{performance_block()}

{stories_block()}

Pick exactly {n_long} story for a long video and exactly {n_shorts + 1} DIFFERENT stories for Shorts (all different
from each other and about different products/events; the last Short is a backup). Never leave a list empty.
Return JSON only:
{{"long": [{{"topic": "short topic name", "story": "product-or-event-slug", "search_query": "3-6 word news search query", "angle": "why viewers care"}}],
 "shorts": [{{"topic": "...", "story": "...", "search_query": "...", "angle": "..."}}]}}""", required=("long", "shorts"))


def story_context(query, n=10, days=3):
    """Recent headlines from several outlets: the fact base for the script and the 'Sources' list."""
    try:
        items = rss_items("https://news.google.com/rss/search?q=" + requests.utils.quote(f"{query} when:{days}d")
                          + "&" + L()["news"])[:n]
    except Exception as e:
        log(f"  news search failed: {e}")
        return []
    out = []
    for i in items:
        src = (i.findtext("source") or "").strip()
        title = (i.findtext("title") or "").strip()
        if src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]
        src = re.sub(r"\.com$", "", src.split(" - ")[0].split(" | ")[0]).strip()  # "ABC News - Breaking News..." -> "ABC News"
        out.append({"headline": title, "source": src, "date": (i.findtext("pubDate") or "")[:16]})
    return out


def yt_suggestions(q, hl=None):
    try:
        r = requests.get("https://suggestqueries.google.com/complete/search",
                         params={"client": "firefox", "ds": "yt", "q": q, "hl": hl or L()["suggest_hl"]}, headers=UA, timeout=20)
        return r.json()[1] if r.ok else []
    except Exception:
        return []


def keyword_research(query):
    """Real YouTube search phrases for the topic (free autocomplete endpoint)."""
    words = query.split()
    seen, out = set(), []
    seeds = [query, " ".join(words[:2]), " ".join(words[:3]) + " news"]
    if LANG == "hi":
        seeds += [" ".join(words[:2]) + " hindi"]
    for seed in seeds:
        for s in yt_suggestions(seed) or yt_suggestions(seed, "en"):  # Indians mostly type tech searches in English
            if s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
    return out[:25]


def facts_block(ctx, kw):
    heads = "\n".join(f"- {c['headline']} ({c['source']}, {c['date']})" for c in ctx) or "- (no extra headlines found)"
    return f"SOURCE HEADLINES:\n{heads}\n\nYOUTUBE SEARCH SUGGESTIONS:\n{', '.join(kw) or '(none)'}"


def expand(text, lo, hi):
    return llm_json(f"""Expand this YouTube voiceover script to {lo}-{hi} words. Keep the same topic, facts, hook,
tone and ending. Add depth (context, implications, what it means for viewers) without inventing numbers,
quotes or dates. No headings, no stage directions, no emojis. Keep the same language and style.
{lang_rules()}

SCRIPT:
{text}

Return JSON only: {{"script": "..."}}""", required=("script",))["script"]


HOSTS_RULES = """TWO HOSTS (a conversation, not a lecture): Max (male) and Nova (female) co-host the show.
- Every section is a back-and-forth: alternate speakers, 1-3 sentences per turn, 3-8 turns per section.
- They react to each other ("Wait, really?", "Here's the part that surprised me"), ask each other the questions viewers
  would ask, and each brings different facts. Friendly, curious, a little playful; never fake or over-the-top.
- Max speaks first (the hook). Facts still come ONLY from the source headlines."""

CARD_RULES = """On-screen cards (optional, 0 or 1 per section, only sourced facts):
 {"type": "stat", "value": "$1,800", "label": "projected price"}  - one big number
 {"type": "quote", "text": "short exact quote from a headline", "source": "Reuters"}
 {"type": "versus", "left": "Old: 8GB", "right": "New: 16GB", "label": "RAM"}  - a comparison
Use null when no sourced number, quote or comparison fits."""

SECTION_SHAPE = ('{"heading": "chapter title, 2-5 words", "fact": "max 7 words sourced fact or empty string", '
                 '"card": null, "lines": [{"speaker": "max", "text": "..."}, {"speaker": "nova", "text": "..."}]}')


def finalize_sections(meta):
    """Derive the spoken text from the dialogue lines (sections keep 'text' for chapters/word counts)."""
    for s in meta["sections"]:
        lines = [l for l in s.get("lines") or [] if l.get("text", "").strip()]
        for l in lines:
            l["speaker"] = "nova" if str(l.get("speaker", "")).lower().startswith("n") else "max"
        s["lines"] = lines
        s["text"] = " ".join(l["text"].strip() for l in lines) or s.get("text", "")
    meta["script"] = " ".join(s["text"].strip() for s in meta["sections"])
    meta["dialogue"] = [l for s in meta["sections"] for l in s["lines"]]
    return meta


def write_dialogue(prompt_head, lo, hi, n_sections, structure, timeout=None):
    show = L()
    meta = llm_json(f"""{prompt_head}

Write a {lo}-{hi} word YouTube video script as a two-host conversation, in {n_sections} sections: {structure}
Right after the hook, one host says exactly: "{show['show_intro']}"
The very last line of the video (Nova) ends with exactly: "{show['signoff']}"
The closing section asks one question for the comments and asks viewers to subscribe to {CHANNEL()}.
Count words carefully: total under {lo - 30} words is too short.
{HOSTS_RULES}
{CARD_RULES}
{RULES}
{retention_block()}
{learned_block()}
{SEO_RULES}
{market_block()}
{lang_rules()}

Return JSON only:
{{"topic": "short topic name",
 "primary_keyword": "...",
 "title": "max 70 chars",
 "description_hook": "...",
 "summary": "...",
 "key_points": ["3-5 short bullet points of what the video covers"],
 "tags": ["..."],
 "hashtags": ["10-12 hashtags"],
 "topics": ["5-8 search phrases"],
 "thumbnail_text": "2-4 punchy words for the thumbnail",
 "pinned_comment": "one engaging question for viewers",
 "products": ["0-3 products from the story people can buy now (phones, laptops, gadgets, consoles), as {{\"name\", \"search\"}} objects with the exact product name from the sources and amazon search words; empty list otherwise"],
 "sections": [{SECTION_SHAPE}],
 "keywords": ["{n_sections * 2} image search terms: concrete visible things (exact product, device, company, app, place), 2-4 words, never news outlet names or abstract words"]}}""", required=("topic", "title", "sections", "keywords"), timeout=timeout)
    finalize_sections(meta)
    for _ in range(2):
        n = len(meta["script"].split())
        if n >= lo * 0.92:
            break
        log(f"[long] script only {n} words, expanding")
        fixed = llm_json(f"""Expand this two-host video script to {lo}-{hi} words in total by adding more conversation turns
(reactions, follow-up questions, what it means for viewers). Keep headings, facts, cards, order, hook, show intro line
and sign-off. Never invent numbers, quotes or dates. Keep the same language and style.
{lang_rules()}

{json.dumps(meta['sections'], ensure_ascii=False)}

Return JSON only: {{"sections": [{SECTION_SHAPE}]}}""", required=("sections",), timeout=timeout)
        meta["sections"] = fixed["sections"]
        finalize_sections(meta)
    return meta


def write_long(pick, ctx, kw):
    lo, hi = LENGTHS["long"]
    tease = ("\nWAIT-FOR-IT: right after the hook, a host teases the biggest surprise for later in the video (\"stick "
             "around - the most surprising part is coming up\"), and that sourced surprise is revealed in the second half. "
             "Never tease anything the video does not deliver.\n") if random.random() < WAIT_SHARE else ""
    return write_dialogue(
        f"STORY for {CHANNEL()}, a tech & AI news channel: {pick['topic']} - angle: {pick.get('angle', '')}\n{tease}\n"
        f"{facts_block(ctx, kw)}", lo, hi, "6-8",
        "hook, why it is trending now, background, key details, reactions (attribute to outlets), what happens next, "
        "what it means for YOU the viewer, closing.")


def write_weekly(stories):
    """'Top 10 tech stories of the week' long video (10-12 minutes): one section per story, countdown 10 -> 1."""
    lo, hi = LENGTHS["weekly"]
    blocks = "\n\n".join(f"STORY {i + 1}: {s['topic']}\n" + "\n".join(
        f"- {c['headline']} ({c['source']}, {c['date']})" for c in s["ctx"]) for i, s in enumerate(stories))
    meta = write_dialogue(
        f"WEEKLY SPECIAL for {CHANNEL()}: the top {len(stories)} tech stories of the week, counted down from "
        f"#{len(stories)} to #1 (#1 = biggest).\nSOURCE HEADLINES per story (only allowed facts):\n{blocks}",
        lo, hi, f"{len(stories) + 2}",
        f"hook (tease #1 without naming it), then one section per story counting down from #{len(stories)} to #1 "
        "(heading like '#7 Apple's new chip'), then closing.", timeout=240)
    meta["weekly"] = True
    return meta


SHORT_VARIANTS = {"fast": (45, 60, "16-22 seconds"), "core": (70, 85, "25-30 seconds")}

# Rotating Short formats: each story gets a real take, and the channel never looks like one repeated template
# (YouTube's "inauthentic / mass-produced content" rules target identical templated videos).
SHORT_FORMATS = {
    "hot_take": "Open with what just happened in one punchy line, then give a clear opinion (labelled as our take) on "
                "whether it is good or bad for normal people, backed by the sourced facts.",
    "versus": "Frame the story as a face-off (new vs old, company vs company, price vs price) and end with a verdict.",
    "three_things": "Three quick things to know, counted 3-2-1, the most surprising one last.",
    "myth_fact": "Start with what most people think, then the sourced fact that flips it.",
    "number_shock": "Open on the single most shocking sourced number or price, then explain why it matters to you.",
    "what_it_means": "Explain in plain words what this changes for the viewer's phone, money, job or daily life.",
    # Viral-format track (formats that took new tech channels to millions of Shorts views in 2026)
    "versus_test": "A face-off between two phones/gadgets/AI tools on ONE thing people care about (speed, battery, "
                   "camera, price, durability) using only sourced specs; fast back-and-forth, a clear winner named in "
                   "the line before the loop. Put the comparison on screen as a versus card.",
    "top3_unique": "Top 3 most unique or unbelievable gadgets / tech from the sources, counted 3-2-1, one punchy line "
                   "each, the wildest one last.",
    "budget_list": "Best phones or gadgets under one price (for example under Rs 15,000 or Rs 20,000) from the source "
                   "articles: 3 picks, one sourced reason each, then a verdict.",
    "hidden_trick": "One hidden setting or trick the viewer can try right now on their phone, app or AI tool, in 2-3 "
                    "short steps - only a trick the sources describe.",
    "what_if": "A curious 'what happens if...' question about real tech from the sources, answered with sourced "
               "facts, ending on a twist.",
    "money_risk": "Why this matters for the viewer's job or money (India for Hindi, US for English): the money or risk "
                  "angle, strictly factual, no fear beyond what the sources say.",
}
VIRAL_FORMATS = {"en": ["versus_test", "top3_unique", "what_if", "hidden_trick"],
                 "hi": ["versus_test", "budget_list", "hidden_trick", "top3_unique", "money_risk"]}
FAST_FORMATS = {"versus_test", "hidden_trick"}  # 16-22 s; the rest 25-30 s


NEWS_FORMATS = ["hot_take", "versus", "three_things", "myth_fact", "number_shock", "what_it_means"]


def formats_today():
    """Formats of this language's Shorts made today (UTC)."""
    if not sb_on():
        return []
    try:
        return [r.get("format") for r in sb_rest("GET", f"insights?select=format&kind=eq.short&lang=eq.{LANG}"
                f"&created_at=gte.{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d}T00:00:00Z")]
    except Exception:
        return []


def choose_format(names, taken=()):
    """Thompson sampling: each format's score is drawn from what its Shorts earned (log views/hour, last 21 days),
    pulled towards the channel average while it has few videos. Winners get picked more often, the rest keep being
    tested. A format already used twice today is skipped, so the channel never looks like one repeated template."""
    today = formats_today() + list(taken)
    pool = [f for f in names if today.count(f) < 2] or list(names)
    try:
        rows = [r for r in scored_videos(LANG, days=21) if r["kind"] == "short" and r.get("format")] if sb_on() else []
    except Exception:
        rows = []
    # views/hour, weighted by how much of the Short people watch when YouTube Analytics has it (~2 days later):
    # retention is what the Shorts feed rewards, so a format that holds viewers counts for more
    value = lambda r: math.log1p(r["vph"] * (r.get("avg_view_pct") or 40) / 40)  # 40% = our typical Short
    vals = [value(r) for r in rows]
    mean = sum(vals) / len(vals) if vals else 1.0
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 if len(vals) > 1 else 0.6
    draw = {}
    for f in pool:
        own = [value(r) for r in rows if r["format"] == f]
        k = 2  # prior strength: a new format counts as 2 average videos
        draw[f] = random.gauss((sum(own) + k * mean) / (len(own) + k), max(sd, 0.3) / math.sqrt(len(own) + k))
    return max(draw, key=draw.get)


def pick_short_format(i, taken=()):
    """Format for a news Short (see choose_format)."""
    return choose_format(NEWS_FORMATS, taken)


def pick_short_variant(i):
    """A/B test of Short length. Alternates until each length has 4+ videos online for 6+ hours, then uses the winner
    (views per hour, weighted by % watched when known) 70% of the time and keeps testing with the rest."""
    try:
        rows = [r for r in scored_videos(LANG) if r["kind"] == "short" and r.get("variant")] if sb_on() else []
    except Exception:
        rows = []
    score = {}
    for v in SHORT_VARIANTS:
        g = [r for r in rows if r["variant"] == v]
        if len(g) >= 4:
            score[v] = sum(r["vph"] * ((r.get("avg_view_pct") or 50) / 50) for r in g) / len(g)
    if len(score) == len(SHORT_VARIANTS):
        best = max(score, key=score.get)
        return best if random.random() < 0.7 else min(score, key=score.get)
    return list(SHORT_VARIANTS)[(datetime.date.today().toordinal() + i) % len(SHORT_VARIANTS)]


WAIT_SHARE = 0.35  # share of Shorts that tease a surprise ("wait for it") and save it for the end


def write_short(pick, ctx, kw, variant="core", fmt_name=None, _retry=True, wait=None):
    lo, hi, secs = SHORT_VARIANTS[variant]
    wait = random.random() < WAIT_SHARE if wait is None else wait
    wait_rule = ("\nWAIT-FOR-IT Short: in the first two sentences, tease that the best part comes at the end (e.g. "
                 "\"wait for the last one\", \"wait till you see the price\"; in Hindi: \"आख़िर तक देखिए\"). Keep the single "
                 "most surprising SOURCED fact for the end and really deliver it - never tease something the video does not "
                 "show. ORDER: hook + tease, facts and take, the subscribe line, THEN the surprise stated clearly with "
                 "its number/fact, THEN the short loop lead-in line.") if wait else ""
    if LANG == "hi":  # Hindi words are longer when spoken: same seconds need ~25% fewer words
        lo, hi = round(lo * 0.75), round(hi * 0.75)
    fmt_name = fmt_name or random.choice(list(SHORT_FORMATS))
    meta = llm_json(f"""Write a YouTube Short script ({lo}-{hi} words, {secs}) for {CHANNEL()}, a tech & AI news channel.
STORY: {pick['topic']} - angle: {pick.get('angle', '')}

{facts_block(ctx, kw)}

FORMAT for this Short: {SHORT_FORMATS[fmt_name]}{wait_rule}
Shorts rules (viewers decide in the first second whether to swipe away):
- First sentence: max 10 words, names the product/company and the stakes. Never start with "So", "Hey guys",
  "Did you know" or the channel name.
- One fast idea per sentence; build to the most surprising fact; include one clear take or verdict.
- Right after the most surprising fact (about 60% in), say exactly this line: "{L()['follow_line']}"
- No spoken comment question (it goes in the pinned comment).
- The LAST sentence is a COMPLETE short lead-in line (3-6 words, ending with ":" or "-") that sets up the first
  sentence, so the Short loops seamlessly but never sounds cut off for viewers who stop there (example: last
  "Here's the deal:" -> first "Apple just killed the iPhone mini."; Hindi: "और ये है असली बात:"). Never end on
  a dangling word like "because", "why", "क्योंकि" or "...".
{RULES}
{retention_block()}
{learned_block()}
{SEO_RULES}
{market_block()}
{lang_rules()}
For Shorts the title must be max 40 characters: curiosity line plus the main keyword (the feed cuts longer titles); one emoji at the end is allowed.
{CARD_RULES} (For a Short: "card" = at most one card, or null.)

Return JSON only:
{{"topic": "short topic name",
 "primary_keyword": "...",
 "title": "max 40 chars",
 "hook_text": "the key 3-5 words of the spoken first sentence, shown on screen from frame 1",
 "description_hook": "...",
 "summary": "...",
 "tags": ["..."],
 "hashtags": ["10-12 hashtags"],
 "topics": ["5-8 search phrases"],
 "pinned_comment": "one engaging question",
 "products": ["0-3 products from the story people can buy now (phones, laptops, gadgets, consoles), as {{\"name\", \"search\"}} objects with the exact product name from the sources and amazon search words; empty list otherwise"],
 "facts": ["2-3 on-screen fact cards, max 7 words each, only sourced facts"],
 "card": null,
 "script": "...",
 "keywords": ["6 image search terms: concrete visible things from the story (exact product, device, company logo, app, place), 2-4 words each; never news outlet names, never abstract words"]}}""", required=("topic", "title", "script", "keywords"))
    meta["script"] = clean_script(meta["script"]).get("script") or ""
    if not meta["script"]:
        raise ValueError("script came back malformed")
    if LANG == "hi" and devanagari_share(meta["script"]) < 0.4 and _retry:
        log("[short] Hindi script came back in Latin letters, rewriting")  # the Hindi voice needs Devanagari
        return write_short(pick, ctx, kw, variant, fmt_name, _retry=False, wait=wait)
    if len(meta["script"].split()) < lo * 0.75:  # only when clearly too short: padding hurts Shorts
        log(f"[short] '{meta['topic']}' too short, expanding")
        meta["script"] = expand(meta["script"], lo, hi)
    meta["script"] = fix_dangling_end(meta["script"])
    meta["format"] = fmt_name
    meta["wait_for_it"] = wait
    return meta


LOOP_LINE = {"en": "Here's the deal:", "hi": "और ये है असली बात:"}
DANGLING = re.compile(r"(\.\.\.|…|\b(because|why|that is why|that's why|and|so)|क्योंकि|इसलिए|और|तो)[\s.…]*$", re.I)


def fix_dangling_end(script):
    """The loop ending must never sound cut off ("...because", "क्योंकि..."): swap a dangling last fragment for a
    complete lead-in line that still flows back into the first sentence."""
    if not DANGLING.search(script.strip()):
        return script
    parts = re.split(r"(?<=[.!?।])\s+", script.strip())
    keep = parts[:-1] if len(parts) > 1 else parts
    last = parts[-1] if len(parts) > 1 else ""
    # the fragment may carry a real clause before the dangling word: keep it as a sentence
    clause = last
    while DANGLING.search(clause):  # "...assistant and that is why" -> strip "that is why", then "and"
        clause = DANGLING.sub("", clause).strip(" ,-")
    if len(clause.split()) >= 4:
        keep.append(clause + ("।" if LANG == "hi" else "."))
    return " ".join(keep + [LOOP_LINE[LANG]])


def clean_script(value):
    """Models sometimes return the script as a JSON string ('{"script": "...", "facts": [...]}'). Unwrap it so the
    voice never reads code aloud."""
    out, text = {}, value if isinstance(value, str) else ""
    for _ in range(2):
        t = text.strip().strip("`").strip()
        if not t.startswith("{"):
            break
        try:
            data = parse_json(t)
        except ValueError:
            return {}  # half-JSON: unusable
        out.update({k: data[k] for k in ("facts", "card") if k in data})
        text = data.get("script", "") if isinstance(data.get("script"), str) else ""
    if "{" in text or '"script"' in text:
        return {}
    out["script"] = text.strip()
    return out


def devanagari_share(s):
    """Share of letters that are Devanagari (Hinglish scripts keep English product names, so ~0.5-0.9 is normal)."""
    letters = [ch for ch in s if ch.isalpha()]
    return sum("\u0900" <= ch <= "\u097f" for ch in letters) / max(1, len(letters))


def same_writing(before, after):
    """Hindi stays Hindi: a rewrite must not switch Devanagari to Latin letters (the Hindi voice can't read that)."""
    dev = lambda s: sum("ऀ" <= ch <= "ॿ" for ch in s) / max(1, len(s))
    return dev(after) >= dev(before) * 0.6


def fact_check(meta, ctx, kind, _retry=True):
    """Second, strict pass: every claim must be backed by the source headlines. Unsupported sentences are softened or
    removed; if the story itself is unsupported the video is held private (auto-publish skips it)."""
    body = (json.dumps(meta["sections"], ensure_ascii=False) if kind == "long"
            else json.dumps({"script": meta["script"], "facts": meta.get("facts", []), "card": meta.get("card")},
                            ensure_ascii=False))
    heads = "\n".join(f"- {c['headline']} ({c['source']}, {c['date']})" for c in ctx) or "- (none)"
    shape = f'"sections": [{SECTION_SHAPE}]' if kind == "long" else '"script": "...", "facts": [...], "card": null'
    res = llm_json(f"""You are a strict news fact-checker for a YouTube channel.
SOURCE HEADLINES (the only allowed facts):
{heads}

TITLE: {meta['title']}
SCRIPT:
{body}

Check every factual claim (numbers, prices, dates, names, quotes, events, specs) in the script, title, on-screen facts
and cards (a card that is not sourced becomes null).
- Supported by the headlines: keep.
- Not supported: rewrite that sentence as hedged context ("reports suggest", "not confirmed yet") or remove it.
Keep everything else (language, tone, hook, length, structure) the same. When hedging, name the outlet
("The Verge reports...") instead of vague phrases. For a Short: keep the first sentence under 10 words and punchy,
and keep the last sentence leading back into the first. If the script teases something for later ("wait for...",
"stick around..."), check that it is clearly delivered with a sourced fact; if not, add the sourced payoff or
remove the tease (a tease that is never paid off is misleading).
verdict = "pass" (nothing changed), "fixed" (you corrected some sentences), or "fail" (the main story or title is not
supported by the headlines at all, or is misleading).
Also YouTube safety: safe = false if the video touches any of these: {SAFE_TOPICS}
Also unsafe if the title or thumbnail text promises something the video does not deliver (misleading clickbait).
Return JSON only: {{"verdict": "...", "safe": true, "safety_reason": "", "issues": ["short description of each problem"],
 "title": "corrected title", {shape}}}""", required=("verdict",))
    v = res.get("verdict", "fail")
    if res.get("safe") is False:
        v = "fail"
        res.setdefault("issues", []).insert(0, "SAFETY: " + str(res.get("safety_reason", "unsafe topic")))
    if v == "fixed":
        if kind == "long" and res.get("sections"):
            meta["sections"] = res["sections"]
            finalize_sections(meta)
        elif kind == "short" and res.get("script"):
            fixed = clean_script(res["script"])
            if fixed.get("script") and same_writing(meta["script"], fixed["script"]):
                meta["script"] = fixed["script"]
                meta["facts"] = fixed.get("facts") or res.get("facts", meta.get("facts", []))
                meta["card"] = fixed.get("card", res.get("card"))
            elif _retry:  # the rewrite came back malformed or in another script: ask once more
                log(f"[{kind}] fact-check rewrite malformed, checking again")
                return fact_check(meta, ctx, kind, _retry=False)
            else:  # still malformed: keep the original, hold it for review
                log(f"[{kind}] fact-check rewrite rejected (malformed or wrong script)")
                v = "fail"
        if res.get("title"):
            meta["title"] = res["title"]
    meta["fact_check"] = {"verdict": v, "issues": res.get("issues", [])[:8]}
    meta["hold"] = v == "fail"
    log(f"[{kind}] fact-check: {v}" + (f" ({len(res.get('issues', []))} issues)" if res.get("issues") else ""))
    return meta


SCRIPT_RUBRIC = """Score this YouTube Short script 0-100 for keeping viewers watching:
- hook (25): first sentence max 10 words, names the product/company and the stakes, no warm-up
- curiosity (15): an open question or tension that makes people wait for the answer
- pace (15): one idea per sentence, no filler words, no repetition
- specifics (15): concrete names, numbers, prices, dates from the facts
- payoff (15): the most surprising fact is delivered clearly, plus a verdict
- why it matters (10): one line on what it means for the viewer (their phone, money, job, daily life)
- loop (5): the last line is a complete short lead-in (e.g. "Here's the deal:") that flows back into the first
  sentence; a dangling ending ("because...", "क्योंकि...") scores 0 here"""


def title_doctor(meta):
    """Shorts titles get the same treatment as scripts: score the current title and 3 alternatives on what makes people
    stop scrolling, keep the best one that is honest to the script and fits the feed (max 40 characters)."""
    try:
        res = llm_json(f"""You choose the title for a YouTube Short ({L()['name']}).
SCRIPT: {meta['script']}
CURRENT TITLE: {meta['title']}
{lang_rules() if LANG == 'hi' else ''}
Write 3 alternative titles, then score the current title and each alternative 0-100:
- names the product/brand first (the search keyword) (30)
- clear stakes or curiosity: price, hack, ban, leak, vs, 'free', a surprising number (30)
- honest: every word supported by the script, no claim the script does not make (a dishonest title scores 0) (25)
- short and readable: max 40 characters, plain words, at most one emoji at the end (15)
Return JSON only: {{"titles": [{{"title": "...", "score": 0}}]}} with the CURRENT title first.""", required=("titles",))
        options = [t for t in res.get("titles") or [] if isinstance(t, dict) and isinstance(t.get("title"), str)
                   and 8 <= len(t["title"].strip()) <= 42]
        if options:
            score = lambda t: int(t.get("score") or 0)
            best = max(options, key=score)
            current = next((score(t) for t in options if t["title"].strip() == meta["title"].strip()), -1)
            if best["title"].strip() != meta["title"].strip() and score(best) > current:
                log(f"[short] title '{meta['title']}' -> '{best['title'].strip()}' (score {current} -> {score(best)})")
                meta["title"] = best["title"].strip()
    except Exception as e:
        log(f"[short] title doctor skipped ({str(e)[:120]})")
    return meta


def script_doctor(meta):
    """Retention pass for Shorts: grade the script, rewrite it to fix its weakest points, and keep the rewrite only if
    it grades higher. Same facts only; the fact-check still runs afterwards. Never loses the original script."""
    original = meta["script"]
    try:
        res = llm_json(f"""{SCRIPT_RUBRIC}

SCRIPT ({L()['name']}):
{original}

Then write an improved version that fixes the 2-3 weakest points by reordering, cutting filler and sharpening
wording ONLY. Strict rules for the rewrite:
- Every fact must keep its exact meaning: same who, what, which product/version, when, and the same numbers. Never
  move a detail from one fact to another (e.g. "hackers attacked OLD versions" must not become "...the NEW update").
- Never add a claim, name, number or question whose answer the script does not give.
- Same language and writing as the original, about the same length (within 10%).
- Keep this exact sentence unchanged: "{L()['follow_line']}". Keep the loop ending.
Return JSON only: {{"score": 0, "weakest": ["..."], "improved_script": "..."}}""", required=("score", "improved_script"))
        before = int(res.get("score") or 0)
        better = clean_script(res.get("improved_script") or "").get("script") or ""
        words, new_words = len(original.split()), len(better.split())
        if (not better or L()["follow_line"] not in better or not same_writing(original, better)
                or not 0.8 * words <= new_words <= 1.2 * words):
            meta["script_score"] = before
            log(f"[short] script score {before}; rewrite not usable, keeping the original")
            return meta
        check = llm_json(f"""{SCRIPT_RUBRIC}

ORIGINAL SCRIPT:
{original}

REWRITE ({L()['name']}):
{better}

1) Score the REWRITE with the rubric. 2) Strictly compare meanings: does the rewrite change ANY fact of the original
(who, what, which product or version, when, any number) or add any claim the original does not make?
Return JSON only: {{"score": 0, "same_facts": true, "changed": "what changed, or empty"}}""",
                         required=("score", "same_facts"))
        after = int(check.get("score") or 0)
        if check.get("same_facts") is not True:
            meta["script_score"] = before
            log(f"[short] script score {before}; rewrite changed a fact ({str(check.get('changed'))[:100]}), "
                "keeping the original")
            return meta
        if after > before:
            meta["script"] = better
        meta["script_score"] = max(before, after)
        log(f"[short] script score {before} -> {after}: {'rewrite kept' if after > before else 'original kept'}"
            f" (weakest: {'; '.join(str(w) for w in (res.get('weakest') or [])[:3])[:160]})")
    except Exception as e:  # the doctor is a bonus: never lose a video over it
        log(f"[short] script doctor skipped ({str(e)[:120]})")
    return meta


def write_checked(write, ctx, kind):
    """Fully automatic fact-checking: a script that fails the check is rewritten once from scratch with the problems
    listed; if it still fails it is dropped (never uploaded), so no video ever waits private for a human review.
    `write(note)` returns a script; `note` is extra instruction text for the rewrite. Shorts get the retention pass
    (script_doctor) before the fact-check, so the fact-check always sees the final words."""
    polish = (lambda m: title_doctor(script_doctor(m))) if kind == "short" else (lambda m: m)
    meta = fact_check(polish(write("")), ctx, kind)
    if not meta.get("hold"):
        return meta
    issues = meta["fact_check"]["issues"]
    if any(str(i).startswith("SAFETY") for i in issues):
        raise RuntimeError(f"dropped: unsafe topic ({str(issues[0])[:120]})")
    log(f"[{kind}] fact-check failed, rewriting from scratch")
    meta = fact_check(polish(write(". REWRITE - an earlier draft had these problems, avoid them and state only facts "
                                   "the sources support: " + "; ".join(str(i) for i in issues)[:800])), ctx, kind)
    if meta.get("hold"):
        raise RuntimeError("dropped: script failed the fact-check twice")
    return meta


def plan_weekly(trends, niche):
    """Pick the week's 10 biggest stories (this channel's last 7 days + today's trends) and write the countdown."""
    recent = []
    if sb_on():
        recent = [r["topic"] for r in sb_rest("GET", f"insights?select=topic,views&lang=eq.{LANG}"
                                                   f"&created_at=gte.{days_ago(7)}&order=views.desc&limit=30")]
    picks = llm_json(f"""Pick the 10 biggest tech & AI stories of this week for a "Top 10 of the week" video ({niche}).
{SAFE_TOPICS}
Stories this channel covered this week (most viewed first): {json.dumps(recent, ensure_ascii=False)}
Today's trending items:
{trends_text(trends)}

Order them 10 (smallest) to 1 (biggest). Return JSON only:
{{"stories": [{{"topic": "short name", "search_query": "3-6 word news search query"}}]}}""", required=("stories",))
    stories = []
    for s in picks["stories"][:10]:
        ctx = story_context(s.get("search_query") or s["topic"], n=6)
        if ctx:
            stories.append({"topic": s["topic"], "ctx": ctx})
    log(f"[weekly] {len(stories)} stories with sources")
    all_ctx = [c for s in stories for c in s["ctx"]]
    meta = fact_check(write_weekly(stories), all_ctx, "long")
    if meta.get("hold"):
        raise RuntimeError("weekly countdown failed the fact-check")  # caller makes a normal long video instead
    meta["sources"] = sorted({c["source"] for c in all_ctx if c["source"]})[:12]
    meta["search_suggestions"] = keyword_research("tech news this week")
    return meta


def plan_videos(trends, niche, used, n_long, n_shorts, weekly=False):
    jobs = []
    if weekly and n_long:
        try:
            jobs.append(("long", plan_weekly(trends, niche)))
        except Exception as e:
            log(f"[weekly] failed ({e}); making a normal long video instead")
            weekly = False
    longs, shorts = pick_topics(trends, niche, used, 0 if weekly else n_long, n_shorts)
    if longs and shorts:  # funnel: the first Short teases the long video's story and sends viewers to it
        shorts[0] = {**longs[0], "teaser": True, "angle": (longs[0].get("angle", "") + ". TEASER: give the single most "
                     "surprising fact; around the middle say the full story is on our channel today. Keep the loop ending.")}
    chosen = []  # formats picked in this run (choose_format avoids a third use of one format today)
    recent = recent_stories()
    want = {"long": len(longs), "short": n_shorts}
    for kind, picks, writer in (("long", longs, write_long), ("short", shorts, write_short)):
        made = 0
        for i, p in enumerate(picks):
            if made >= want[kind]:
                break
            try:
                if story_count(p, recent) >= STORY_MAX:
                    log(f"[{kind}] '{p['topic']}' skipped: story '{story_slug(p)}' already has {STORY_MAX}+ videos in 48 h")
                    continue
                n_story = len(sb_rest("GET", f"insights?select=youtube_id&story=eq.{story_slug(p)}")) if sb_on() else 0
                p = {**p, "angle": p.get("angle", "") + series_note(n_story + 1)}
                query = p.get("search_query") or p["topic"]
                ctx, kw = story_context(query), keyword_research(query)
                log(f"[{kind}] '{p['topic']}': {len(ctx)} source headlines, {len(kw)} search suggestions")
                outlets = {c["source"] for c in ctx if c["source"]}
                if len(outlets) < MIN_OUTLETS:  # never a video on something only one outlet (or none) reports
                    log(f"[{kind}] '{p['topic']}' skipped: only {len(outlets)} news outlet(s) report it")
                    continue
                if kind == "short":
                    variant = pick_short_variant(i)
                    fmt = pick_short_format(i, chosen)
                    chosen.append(fmt)
                    meta = write_checked(lambda note: writer({**p, "angle": p.get("angle", "") + note}, ctx, kw,
                                                             variant, fmt), ctx, kind)
                    meta["variant"] = variant
                else:
                    meta = write_checked(lambda note: writer({**p, "angle": p.get("angle", "") + note}, ctx, kw),
                                         ctx, kind)
                meta["sources"] = sorted({c["source"] for c in ctx if c["source"]})[:8]
                meta["search_suggestions"] = kw
                meta["story"] = story_slug(p)
                recent.append({"story": meta["story"], "topic": p["topic"]})  # counts for the next pick of this run
                jobs.append((kind, meta))
                made += 1
            except Exception as e:
                log(f"[{kind}] script failed for '{p.get('topic')}': {e}")
                if str(e).startswith("dropped"):
                    remember_dropped(p.get("topic", ""))
    return jobs


# ---------- 3. Voice + captions ----------
async def _tts(text, voice, rate, mp3, pitch="+0Hz", volume="+0%"):
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume, boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for c in comm.stream():
            if c["type"] == "audio":
                f.write(c["data"])
            elif c["type"] == "WordBoundary":
                words.append((c["offset"] / 1e7, (c["offset"] + c["duration"]) / 1e7, c["text"]))
    return words


VOICES = {"male": "en-US-AndrewMultilingualNeural", "female": "en-US-AvaMultilingualNeural"}
CHARACTERS = {"male": "max", "female": "nova"}


def pick_voice(i):
    """Alternate male/female across videos and days, so the channel has two recurring hosts."""
    genders = [g.strip() for g in os.environ.get("HOSTS", "male,female").split(",") if g.strip() in VOICES]
    g = genders[(datetime.date.today().toordinal() + i + (1 if LANG == "hi" else 0)) % len(genders)]
    return {"gender": g, "voice": L()["voices"][g], "character": CHARACTERS[g]}


# Emotion -> voice delivery (rate %, pitch Hz, volume %), applied per sentence on top of the base pace.
EMOTION_PROSODY = {"excited": (8, 8, 10), "surprised": (3, 14, 10), "serious": (-7, -6, 0), "curious": (0, 6, 0),
                   "calm": (-4, -3, -5), "neutral": (0, 0, 0)}
SURPRISE_WORDS = re.compile(r"\b(wait|shock\w*|insane|crazy|unbelievable|surpris\w*|whoa|wow|just|finally|record|"
                            r"biggest|first ever|never)\b|हैरान|चौंक|गज़ब|कमाल|पहली बार", re.I)
SERIOUS_WORDS = re.compile(r"\b(risk\w*|danger\w*|warn\w*|ban\w*|leak\w*|hack\w*|scam\w*|fraud|lawsuit|fine[ds]?|"
                           r"crisis|layoffs?|jobs?|privacy|breach|attack|careful)\b|खतरा|धोखा|सावधान|नुकसान|हैक", re.I)


def sentence_emotion(s, first=False):
    """Cheap, free emotion tag per sentence (no extra AI call): hook = excited; shock/number lines = surprised;
    risk lines = serious; questions = curious; exclamations = excited."""
    t = s.strip()
    if first:
        return "excited"
    if SERIOUS_WORDS.search(t):
        return "serious"
    if SURPRISE_WORDS.search(t) or re.search(r"[$₹€]\s?\d|\d+\s?(%|percent|crore|lakh|million|billion)", t, re.I):
        return "surprised"
    if t.endswith("?"):
        return "curious"
    if t.endswith("!"):
        return "excited"
    return "neutral"


def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?।])\s+", text.strip()) if s.strip()]


# Per-video look and delivery (see pick_style): varied so the channel never looks like one repeated template
# (YouTube's July 2025 "inauthentic / mass-produced content" rule), while the host and channel name stay the brand.
STYLES = {"accent": ["#2be4ff", "#a3ff3c", "#ff4fa3", "#ff8a1f"],  # cyan, lime, pink, orange
          "captions": ["mid", "low"],
          "pace": [-4, 0, 4]}  # % on top of the base voice speed
PACE_SHIFT = 0  # set per video by make_video


def pick_style(meta):
    """A look for this video: accent colour, caption height and voice pace, spread so back-to-back videos differ."""
    seed = sum(map(ord, meta.get("topic", ""))) + datetime.datetime.now().hour
    return {k: v[(seed // (i + 1)) % len(v)] for i, (k, v) in enumerate(STYLES.items())}


def tts(text, mp3, kind, voice=None, emotion="neutral"):
    for attempt in range(4):
        try:
            # English a little brisk for energy; Hindi at natural pace so it stays easy to follow.
            rate = os.environ.get("TTS_RATE") or (("+8%" if LANG == "hi" else "+12%") if kind == "short"
                                                  else ("+0%" if LANG == "hi" else "+6%"))
            dr, dp, dv = EMOTION_PROSODY.get(emotion, (0, 0, 0))
            rate = f"{int(rate.strip('%')) + dr + PACE_SHIFT:+d}%"
            return asyncio.run(_tts(text, voice or VOICES["male"], rate, mp3, f"{dp:+d}Hz", f"{dv:+d}%"))
        except Exception as e:
            if attempt == 3:
                raise
            log(f"[{kind}] TTS failed ({e}), retrying")
            time.sleep(10 * (attempt + 1))


def tts_emotional(text, work, kind, voice):
    """Single host: each sentence voiced with its own emotion (pace, pitch, energy), trimmed to the spoken words and
    joined with short natural pauses. Returns (words, emotion spans [[start, end, emotion]]); writes voice.mp3."""
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return tts(text, work / "voice.mp3", kind, voice, "excited"), [[0, 99, "excited"]]
    rate, gap = 24000, 0.12
    ff(["-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=mono", "-t", str(gap), "gap.wav"], work)
    words, spans, parts, t = [], [], [], 0.0
    for i, s in enumerate(sentences):
        emo = sentence_emotion(s, first=i == 0)
        mp3 = work / f"sent_{i:03d}.mp3"
        w = tts(s, mp3, kind, voice, emo)
        if not w:
            continue
        a, b = max(0.0, w[0][0] - 0.05), w[-1][1] + 0.15  # cut edge-tts's lead-in/trailing silence
        ff(["-i", mp3.name, "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-ar", str(rate), "-ac", "1", f"sent_{i:03d}.wav"], work)
        dur = audio_duration(work / f"sent_{i:03d}.wav")
        words += [(x0 - a + t, x1 - a + t, x) for x0, x1, x in w]
        spans.append([round(t, 3), round(t + dur, 3), emo])
        parts += [f"sent_{i:03d}.wav"] + (["gap.wav"] if i < len(sentences) - 1 else [])
        t += dur + (gap if i < len(sentences) - 1 else 0)
    (work / "voice_list.txt").write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    ff(["-f", "concat", "-safe", "0", "-i", "voice_list.txt", "-c:a", "libmp3lame", "-b:a", "96k", "-y", "voice.mp3"], work)
    for p in list(work.glob("sent_*")) + [work / "gap.wav"]:
        p.unlink(missing_ok=True)
    return words, spans


def tts_dialogue(lines, work, kind):
    """Two-host audio: each line in its host's voice, joined with short natural pauses.
    Returns (words with global timings, turns [[start, end, speaker]])."""
    voices = {"max": L()["voices"]["male"], "nova": L()["voices"]["female"]}
    gap, rate = 0.28, 24000
    ff(["-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=mono", "-t", str(gap), "gap.wav"], work)
    words, turns, parts, t = [], [], [], 0.0
    emotions = []
    for i, line in enumerate(lines):
        mp3 = work / f"line_{i:03d}.mp3"
        emo = sentence_emotion(line["text"], first=i == 0)
        w = tts(line["text"], mp3, kind, voices[line["speaker"]], emo)
        ff(["-i", mp3.name, "-ar", str(rate), "-ac", "1", f"line_{i:03d}.wav"], work)
        dur = audio_duration(work / f"line_{i:03d}.wav")
        words += [(a + t, b + t, x) for a, b, x in w]
        turns.append([round(t, 3), round(t + dur, 3), line["speaker"]])
        emotions.append([round(t, 3), round(t + dur, 3), emo])
        parts += [f"line_{i:03d}.wav", "gap.wav"]
        t += dur + gap
    (work / "voice_list.txt").write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    ff(["-f", "concat", "-safe", "0", "-i", "voice_list.txt", "-c:a", "libmp3lame", "-b:a", "96k", "voice.mp3"], work)
    for p in list(work.glob("line_*")) + [work / "gap.wav"]:
        p.unlink(missing_ok=True)
    TTS_EMOTIONS[str(work)] = emotions
    return words, turns


TTS_EMOTIONS = {}  # work folder -> emotion spans of the last dialogue voice (read by make_video)


def card_times(meta, kind, duration, section_list):
    """When each data/quote/comparison card shows: long = 7s into its section; short = about 38% in."""
    out = []
    if kind == "long":
        starts = {h: t for t, h in section_list}
        for s in meta.get("sections", []):
            c = s.get("card")
            if isinstance(c, dict) and c.get("type") in ("stat", "quote", "versus") and s["heading"].strip() in starts:
                out.append({**c, "t": round(starts[s["heading"].strip()] + 7.0, 2)})
    elif isinstance(meta.get("card"), dict) and meta["card"].get("type") in ("stat", "quote", "versus"):
        out.append({**meta["card"], "t": round(duration * 0.38, 2)})
    return out


def rhubarb_exe():
    if os.environ.get("RHUBARB"):
        return os.environ["RHUBARB"]
    found = sorted((ROOT / "tools" / "bin").glob("Rhubarb-Lip-Sync-*/rhubarb*"))
    return str(found[0]) if found else None


def lipsync(work, script):
    """Mouth shapes (A-H, X) timed to the voice, via Rhubarb Lip Sync. Empty list = fall back to loudness."""
    exe = rhubarb_exe()
    if not exe:
        return []
    try:
        ff(["-i", "voice.mp3", "-ac", "1", "-ar", "16000", "voice.wav"], work)
        (work / "dialog.txt").write_text(script, encoding="utf-8")
        rec = L()["lipsync"]
        dialog = ["--dialogFile", str(work / "dialog.txt")] if rec == "pocketSphinx" else []
        out = subprocess.run([exe, "-f", "json", "-r", rec, "--extendedShapes", "GHX", *dialog, str(work / "voice.wav")],
                             capture_output=True, text=True, timeout=900, check=True)
        return [[c["start"], c["end"], c["value"]] for c in json.loads(out.stdout)["mouthCues"]]
    except Exception as e:
        log(f"  lip sync skipped: {str(e)[:120]}")
        return []


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


def section_times(sections, words):
    """Start time of every script section, mapped through the voice's word timings."""
    total = sum(len(s["text"].split()) for s in sections) or 1
    out, cum = [], 0
    for s in sections:
        t = 0.0 if not out else words[min(len(words) - 1, round(cum / total * len(words)))][0]
        out.append((t, s["heading"].strip()))
        cum += len(s["text"].split())
    return out


def chapters(sections, words):
    """YouTube chapters: first at 0:00, at least 3, each at least 10s apart."""
    out = []
    for t, h in section_times(sections, words):
        if not out or t - out[-1][0] >= 10:
            out.append((t, h))
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


# Wikimedia requires a contact URL in the User-Agent (without it the media servers answer 429).
WIKI_UA = {"User-Agent": "TechPulseBot/1.0 (https://ommistry-hue.github.io/techpulse/about.html) python-requests"}


# Media titles with these words are skipped (sensitive imagery is a YouTube policy risk and off-brand).
SENSITIVE_MEDIA = re.compile(r"\b(accident|death|dead|killed|kill|crash|war|weapon|gun|blood|injur\w*|victim|corpse|"
                             r"nude|naked|protest|riot|terror\w*|bomb|explosion|fire|disaster|funeral)\b", re.I)
# Media that matches the words but shows something else (and trailers/music can trigger Content ID claims).
OFF_TOPIC_MEDIA = re.compile(r"\b(trailer|gameplay|game|film|movie|poster|album|music|song|concert|episode|"
                             r"cosplay|defective|broken|cracked|damaged|repair|teardown|parody|meme|advert\w*|"
                             r"commercial|lancement|bande|pyramid\w*|camel|temple|church|statue)\b", re.I)


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
        if SENSITIVE_MEDIA.search(name) or OFF_TOPIC_MEDIA.search(name):
            continue
        # Too few shared words = usually off-topic (and showing the wrong real person is misleading).
        if words and score < min(2, len(words), max(1, len(words) - 1)):
            continue
        md = ii.get("extmetadata", {})
        artist = html.unescape(re.sub(r"<[^>]+>", "", md.get("Artist", {}).get("value", "Unknown"))).strip()[:60]
        license_ = md.get("LicenseShortName", {}).get("value", "see source")
        out.append({"id": f"wm{p['pageid']}", "image": ii.get("thumburl") or ii["url"], "score": score,
                    "credit": f"{name} - {artist} ({license_}) {ii.get('descriptionurl', '')}"})
    return out


def wikimedia_video_search(query):
    """Free-licensed VIDEO clips from Wikimedia Commons (credited like photos). Uses Commons' own 480p/720p copies."""
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:video",
        "gsrnamespace": 6, "gsrlimit": 10, "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|derivatives"})
    if not r.ok:
        return []
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3}
    out = []
    for p in r.json().get("query", {}).get("pages", {}).values():
        vi = (p.get("videoinfo") or [{}])[0]
        name = p["title"].removeprefix("File:")
        score = len(words & set(re.findall(r"[a-z0-9]+", name.lower())))
        if SENSITIVE_MEDIA.search(name) or OFF_TOPIC_MEDIA.search(name):
            continue
        # video titles are vaguer than photo titles: every query word must match
        if (words and score < len(words)) or not 6 <= (vi.get("duration") or 0) <= 180:  # short files only
            continue
        ders = [d for d in vi.get("derivatives", []) if "webm" in d.get("type", "") and 360 <= (d.get("height") or 0) <= 480]
        if not ders:
            continue
        src = max(ders, key=lambda d: d["height"])["src"]  # 480p when available: small and sharp enough
        md = vi.get("extmetadata", {})
        artist = html.unescape(re.sub(r"<[^>]+>", "", md.get("Artist", {}).get("value", "Unknown"))).strip()[:60]
        license_ = md.get("LicenseShortName", {}).get("value", "see source")
        out.append({"id": f"wv{p['pageid']}", "wikivideo": src, "duration": vi["duration"], "score": score,
                    "credit": f"{name} - {artist} ({license_}) {vi.get('descriptionurl', '')}"})
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
    clips = []
    if os.environ.get("USE_WIKIMEDIA", "1") == "1" and os.environ.get("USE_WIKIMEDIA_VIDEO", "1") == "1":
        try:
            clips = sorted(wikimedia_video_search(query), key=lambda c: c["score"])
        except Exception:
            clips = []
    return images + videos + clips  # popped from the end: real video clips first (capped in fetch_clips)


def best_file(video, fmt):
    portrait = fmt["h"] > fmt["w"]
    files = [f for f in video["files"] if max(f["width"], f["height"]) >= 1280]
    same = [f for f in files if (f["height"] > f["width"]) == portrait]
    return min(same or files, key=lambda f: abs(f["width"] - fmt["w"]) + abs(f["height"] - fmt["h"]), default=None)


def has_video(path, min_s=3.0):
    """True if the file really contains a video stream of at least `min_s` seconds."""
    err = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return "Video:" in err and bool(m) and int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) >= min_s


def fetch_wiki_clip(v, path, folder):
    """Download a Commons clip in ONE request (seeking over HTTP triggers 429 rate limits), cut 10 s locally, verify."""
    raw = folder / (path.stem + "_src.webm")
    for attempt in range(3):
        try:
            with requests.get(v["wikivideo"], headers=WIKI_UA, stream=True, timeout=(15, 120)) as r:
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", "10") or 10) * (attempt + 1))
                    continue
                r.raise_for_status()
                size = 0
                with open(raw, "wb") as fh:
                    for b in r.iter_content(1 << 20):
                        size += len(b)
                        if size > 60 * 1024 * 1024:
                            raise ValueError("clip too large")
                        fh.write(b)
            break
        except Exception:
            raw.unlink(missing_ok=True)
            return False
    if not raw.exists():
        return False
    try:
        start = min(5.0, v["duration"] * 0.2)
        ff(["-ss", f"{start:.1f}", "-t", "10", "-i", raw.name, "-an", "-vf", "scale=-2:720", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "26", path.name], folder)
    except Exception:
        pass
    raw.unlink(missing_ok=True)
    if path.exists() and has_video(path):
        return True
    path.unlink(missing_ok=True)
    return False


NEWS_OUTLETS = re.compile(r"\b(ars technica|the verge|techcrunch|engadget|wired|reuters|bloomberg|cnbc|cnet|"
                          r"gizmodo|zdnet|windows central|macrumors|9to5\w+|tweaktown|android (?:authority|police|central)|"
                          r"tom's (?:guide|hardware)|times of india|ndtv|hindustan times|gadgets 360|news)\b", re.I)


def fetch_clips(keywords, folder, fmt, need):
    """Spread `need` clips across keywords in script order, distinct sources.
    Returns [{"path", "is_image", "credit"}]."""
    keywords = [k for k in keywords if isinstance(k, str) and k.strip() and not NEWS_OUTLETS.search(k)]
    if not keywords:
        return []
    results = {kw: search_footage(kw, fmt) for kw in keywords}
    clips, used = [], set()
    max_video = max(1, need // 3)  # real motion in about a third of the scenes keeps renders fast
    while len(clips) < need and any(results.values()):
        for kw in keywords:
            if len(clips) >= need:
                break
            while results[kw]:
                v = results[kw].pop()
                if v["id"] in used:
                    continue
                if "wikivideo" in v:
                    if sum(not c["is_image"] for c in clips) >= max_video:
                        continue
                    path = folder / f"clip{len(clips):02d}.mp4"
                    used.add(v["id"])
                    if fetch_wiki_clip(v, path, folder):
                        clips.append({"path": path, "is_image": False, "credit": v.get("credit")})
                        break
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
                if "image" not in v and not has_video(path):
                    path.unlink(missing_ok=True)
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
    normalize_loudness(work)
    return work / "final.mp4"


def make_thumbnail(work, text, at, image=None, character=None):
    """Host-face thumbnail (Remotion still); falls back to the plain text-on-photo version."""
    if os.environ.get("RENDER_STYLE", "motion") == "motion":
        try:
            props = {"image": image.name if image else None, "text": text,
                     "character": character or ("nova" if datetime.date.today().toordinal() % 2 else "max"),
                     "channel": os.environ.get("CHANNEL_NAME", "TechPulse").upper()}
            (work / "thumb_props.json").write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
            npx = shutil.which("npx") or "npx"
            subprocess.run([npx, "remotion", "still", "src/index.jsx", "Thumb", str(work / "thumb.png"),
                            f"--props={work / 'thumb_props.json'}", f"--public-dir={work}", "--log=error"],
                           cwd=ROOT / "motion", check=True, timeout=300)
            ff(["-i", "thumb.png", "-q:v", "3", "thumb.jpg"], work)  # JPG keeps it under YouTube's 2 MB limit
            return work / "thumb.jpg"
        except Exception as e:
            log(f"  host thumbnail failed ({str(e)[:100]}), using plain thumbnail")
    return make_plain_thumbnail(work, text, at, image)


def make_plain_thumbnail(work, text, at, image=None):
    """1280x720 JPG: main-subject photo (or a video frame) darkened + big yellow headline + channel tag."""
    channel = os.environ.get("CHANNEL_NAME", "TechPulse").upper()
    # Brand colors (ASS is &HAABBGGRR): neon cyan #2BE4FF headline, navy #070D1A tag box.
    styles = (f"Style: Head,{FONT},172,&H00FFE42B,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,10,6,4,70,460,0,1\n"
              f"Style: Tag,{FONT},52,&H00FFFFFF,&H000000FF,&H001A0D07,&H001A0D07,0,0,0,0,100,100,3,0,3,14,0,7,50,50,40,1")
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


VS_GENERIC = {"old", "new", "before", "after", "now", "then", "this", "that", "today", "last year", "next year"}
VS_WIN = re.compile(r"^(wins?|winner|winning|won|beats?|beat|crushes|takes|clear|better|faster|stronger|longer|cheaper|"
                    r"जीत\w*|विजेता|बेहतर|आगे)$", re.I)


def _norm_word(w):
    return re.sub(r"[^\w#]", "", w.lower())


def versus_props(meta, work, fmt, words):
    """versus_test Shorts: one photo per side of the versus card + who wins (None if the script is unclear).
    Returns (props or None, credits)."""
    c = meta.get("card")
    if meta.get("format") != "versus_test" or not isinstance(c, dict) or c.get("type") != "versus":
        return None, []
    sides, credits = {}, []
    for side in ("left", "right"):
        name = str(c.get(side) or "").strip()
        head = re.split(r"\s*[:=(|]\s*", name)[0].strip()
        query = head if len(re.findall(r"[^\W\d_]", head)) >= 3 else re.sub(r"\d[\d.,]*\s*[a-zA-Z%]{0,4}", "", name).strip(" :-")
        if not query or query.lower() in VS_GENERIC:
            return None, []
        src, credit, video = None, None, False
        try:
            imgs = sorted(wikimedia_search(query), key=lambda i: i["score"], reverse=True)
            for v in imgs[:3]:
                ext = Path(urlparse(v["image"]).path).suffix.lower()
                path = work / f"vs_{side}{ext if ext in ('.jpg', '.jpeg', '.png', '.webp') else '.jpg'}"
                try:
                    r = requests.get(v["image"], timeout=60, headers=WIKI_UA)
                    r.raise_for_status()
                    path.write_bytes(r.content)
                    src, credit, video = path.name, v.get("credit"), False
                    break
                except requests.RequestException:
                    continue
            if not src:  # any other source (stock video/photo) for that name
                (work / f"vs_{side}").mkdir(exist_ok=True)
                got = fetch_clips([query], work / f"vs_{side}", fmt, 1)
                if got:
                    src, credit, video = f"vs_{side}/{got[0]['path'].name}", got[0]["credit"], not got[0]["is_image"]
        except Exception as e:
            log(f"  versus image for '{query}' failed: {str(e)[:100]}")
        if not src:
            return None, []
        if credit:
            credits.append(credit)
        sides[side] = {"name": name, "src": src, "video": video, "query": query}
    # Which words name each side (only the ones the other side does not share, e.g. "s26" vs "iphone")
    toks = {s: {w for w in re.findall(r"\w+", sides[s]["query"].lower()) if len(w) >= 2} for s in sides}
    own = {"left": toks["left"] - toks["right"], "right": toks["right"] - toks["left"]}
    ws = [(a, _norm_word(w)) for a, _, w in words]
    for s in sides:
        sides[s]["hits"] = [round(a, 2) for a, w in ws if w in own[s]]
        del sides[s]["query"]
    winner, win_at = None, None
    last = ws[-1][0] if ws else 0
    for i in range(len(ws) - 1, -1, -1):  # the winner line is near the end, just before the loop line
        a, w = ws[i]
        if a < last * 0.5:
            break
        if not VS_WIN.match(w):
            continue
        before = [s for j in range(max(0, i - 6), i) for s in own if ws[j][1] in own[s]]
        after = [s for j in range(i + 1, min(len(ws), i + 7)) for s in own if ws[j][1] in own[s]]
        near = set(before + after)
        if len(near) == 1:
            winner = near.pop()
        elif near and w.startswith("winner") and after:
            winner = after[0]
        elif near and before:
            winner = before[-1]
        if winner:
            named = [j for j in range(max(0, i - 6), i) if ws[j][1] in own[winner]]
            win_at = round(ws[named[-1] if named else i][0], 2)  # "Galaxy wins": light up as the name is said
            break
    return {"left": sides["left"], "right": sides["right"], "label": c.get("label") or "",
            "winner": winner, "winAt": win_at}, credits


COUNT_WORDS = {3: {"3", "#3", "three", "third", "तीन", "तीसरा", "तीसरे", "तीसरी", "३"},
               2: {"2", "#2", "two", "second", "दो", "दूसरा", "दूसरे", "दूसरी", "२"},
               1: {"1", "#1", "one", "first", "एक", "पहला", "पहले", "पहली", "१"}}


def countdown_times(meta, words, duration):
    """top3_unique Shorts: when the #3, #2, #1 badges pop in (spoken markers, else 3 equal parts after the hook)."""
    if meta.get("format") != "top3_unique":
        return []
    ws = [(a, _norm_word(w)) for a, _, w in words]
    for strict in (True, False):  # strict = "number 3" / "#3" / a digit; loose = also the word "three"/"तीन"
        out, start = [], 0
        for n in (3, 2, 1):
            for i in range(start, len(ws)):
                a, w = ws[i]
                prev = ws[i - 1][1] if i else ""
                hit = (w in COUNT_WORDS[n] and (w[0].isdigit() or w.startswith("#") or prev in ("number", "नंबर", "no"))
                       if strict else w in COUNT_WORDS[n])
                if hit and a >= 1.0 and prev not in ("top", "टॉप") and (not out or a - out[-1]["t"] >= 2.0):
                    t = ws[i - 1][0] if prev in ("number", "नंबर", "no") else a
                    out.append({"n": n, "t": round(t, 2)})
                    start = i + 1
                    break
            else:
                break
        if len(out) == 3:
            return out
    hook = next((a for a, _ in ws if a >= 2.5), 2.5)
    hook = min(hook, duration * 0.25)
    step = (duration * 0.95 - hook) / 3
    return [{"n": n, "t": round(hook + k * step, 2)} for k, n in enumerate((3, 2, 1))]


def caption_highlights(title):
    """Caption words to colour gold: the product/brand words of the title (numbers and prices are coloured in the
    renderer itself). Keeps the eye on the names and numbers that carry the story."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9+]+", title or "")
    return sorted({w.lower() for w in words if w.lower() in BRANDS  # Xbox, Switch, Oppo
                   or (len(w) > 2 and any(c.isupper() for c in w[1:]))  # iPhone, ChatGPT (not "AI": in every video)
                   or any(c.isdigit() for c in w)})  # X10


BRANDS = {"apple", "iphone", "ipad", "mac", "macbook", "airpods", "samsung", "galaxy", "google", "pixel", "android",
          "gemini", "chatgpt", "openai", "microsoft", "windows", "xbox", "sony", "playstation", "nintendo", "switch",
          "meta", "instagram", "whatsapp", "facebook", "youtube", "tesla", "nvidia", "amd", "intel", "qualcomm",
          "snapdragon", "oneplus", "xiaomi", "redmi", "oppo", "vivo", "realme", "motorola", "moto", "nothing", "jio",
          "airtel", "upi", "amazon", "flipkart", "netflix", "spotify", "chrome", "deepseek", "claude", "anthropic",
          "grok", "kindle", "steam", "gta"}


def render_motion(work, kind, words, duration, clips, title, sections, host=None, mouth=(), facts=(), turns=(),
                  cards=(), versus=None, countdown=(), wait=None, emotions=(), style=None):
    """Animated style (Remotion): presenter character, kinetic captions, headline/fact cards.
    Assets are served from the work folder."""
    fmt = FORMATS[kind]
    fps, total = 30, duration + (0.1 if kind == "short" else 0.8)
    media = clips  # photos and real video clips, in script order
    scenes = []
    if media:
        n = max(len(media), round(total / fmt["clip_secs"]))
        seg = total / n
        scenes = [{"start": round(i * seg, 3), "end": round((i + 1) * seg, 3), "src": media[i % len(media)]["path"].name,
                   "video": not media[i % len(media)]["is_image"]} for i in range(n)]
    for font in ("Anton-Regular.ttf", "Mukta-ExtraBold.ttf"):  # Mukta covers Devanagari (Hindi)
        shutil.copy(ROOT / "fonts" / font, work / font)
    shutil.copy(ROOT / "assets" / "logo.jpg", work / "logo.jpg")
    for sfx in ("whoosh.wav", "pop.wav", "ding.wav", "hit.wav"):
        shutil.copy(ROOT / "assets" / "sfx" / sfx, work / sfx)
    tracks = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    music = None
    if tracks:  # rotate background tracks so videos don't all sound the same
        pick = tracks[(datetime.date.today().toordinal() + len(words)) % len(tracks)]
        shutil.copy(pick, work / "music.mp3")
        music = "music.mp3"
        name = pick.stem.replace("_", " ")
        (work / "music_credit.txt").write_text(
            f'Music: "{name}" Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 '
            f"http://creativecommons.org/licenses/by/4.0/", encoding="utf-8")
    props = {"kind": kind, "width": fmt["w"], "height": fmt["h"], "fps": fps, "durationInFrames": round(total * fps),
             "audio": "voice.mp3", "words": [[round(a, 3), round(b, 3), w] for a, b, w in words], "scenes": scenes,
             "sections": [{"start": round(t, 2), "heading": h} for t, h in sections], "title": title,
             "channel": os.environ.get("CHANNEL_NAME", "TechPulse").upper(),
             "character": (host or {}).get("character", "max"), "mouth": list(mouth), "ui": L()["ui"], "lang": LANG,
             "music": music, "turns": list(turns), "cards": list(cards), "versus": versus, "countdown": list(countdown), "wait": wait, "emotions": list(emotions),
             "facts": [{"t": round(t, 2), "text": x} for t, x in facts], "style": style or {},
             "highlights": caption_highlights(" ".join([title, *(w for *_, w in words)]))}
    (work / "props.json").write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    npx = shutil.which("npx") or "npx"
    subprocess.run([npx, "remotion", "render", "src/index.jsx", "Long" if kind == "long" else "Short",
                    str(work / "final.mp4"), f"--props={work / 'props.json'}", f"--public-dir={work}",
                    "--log=error", "--crf=20", "--concurrency=100%"], cwd=ROOT / "motion", check=True)  # all cores
    normalize_loudness(work)
    return work / "final.mp4"


def normalize_loudness(work):
    """Every video at YouTube's playback loudness (-14 LUFS, peaks under -1.5 dB), so no upload sounds quieter or
    harsher than the one before it in the feed. Video stream copied untouched; on any error the render is kept."""
    try:
        ff(["-i", "final.mp4", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "final_ln.mp4"], work)
        (work / "final_ln.mp4").replace(work / "final.mp4")
    except Exception as e:
        log(f"loudness normalisation skipped ({str(e)[:100]})")
        (work / "final_ln.mp4").unlink(missing_ok=True)


def fact_times(meta, kind, words, duration, chapter_list):
    """When each on-screen fact card appears: long = 2s into its section, short = spread through the video."""
    if kind == "long":
        heads = {h: t for t, h in chapter_list}
        return [(heads[s["heading"].strip()] + 2.0, s["fact"].strip()) for s in meta.get("sections", [])
                if s.get("fact", "").strip() and s["heading"].strip() in heads]
    facts = [f.strip() for f in meta.get("facts", []) if f.strip()][:3]
    return [(duration * (i + 1) / (len(facts) + 1), f) for i, f in enumerate(facts)]


def make_video(work, kind, meta, host=None):
    global PACE_SHIFT
    fmt = FORMATS[kind]
    meta["style"] = meta.get("style") or pick_style(meta)
    PACE_SHIFT = meta["style"]["pace"] if kind == "short" else 0
    log(f"[{kind}] style: {meta['style']}")
    work.mkdir(parents=True, exist_ok=True)
    host = host or pick_voice(0)
    turns, emotions = [], []
    if meta.get("dialogue"):
        log(f"[{kind}] voice (two hosts, {len(meta['dialogue'])} lines)")
        words, turns = tts_dialogue(meta["dialogue"], work, kind)
        emotions = TTS_EMOTIONS.pop(str(work), [])
    else:
        log(f"[{kind}] voice ({host['gender']} host, with emotion per sentence)")
        try:
            words, emotions = tts_emotional(meta["script"], work, kind, host["voice"])
        except Exception as e:  # never lose the video over the emotional voice: plain voice instead
            log(f"[{kind}] emotional voice failed ({str(e)[:120]}), plain voice")
            words = tts(meta["script"], work / "voice.mp3", kind, host["voice"])
    write_ass(words, work / "subs.ass", fmt)
    duration = audio_duration(work / "voice.mp3")
    log(f"[{kind}] voice {duration:.0f}s, downloading visuals")
    clips = fetch_clips(meta.get("keywords", []), work, fmt, need=min(40, round(duration / fmt["clip_secs"])))
    log(f"[{kind}] {len(clips)} clips ({sum(c['is_image'] for c in clips)} photos), rendering")
    credits = [c["credit"] for c in clips if c["credit"]]
    sections = meta.get("sections") or []
    chapter_list = chapters(sections, words) if sections else []      # for the description (YouTube rules)
    section_list = section_times(sections, words) if sections else []  # for on-screen cards
    video = None
    if os.environ.get("RENDER_STYLE", "motion") == "motion":
        try:
            mouth = lipsync(work, meta["script"])
            log(f"[{kind}] lip sync: {len(mouth)} mouth shapes")
            title = meta.get("hook_text") or meta["title"]
            versus, vs_credits = versus_props(meta, work, fmt, words) if kind == "short" else (None, [])
            credits += vs_credits
            countdown = countdown_times(meta, words, duration) if kind == "short" else []
            video = render_motion(work, kind, words, duration, clips, title, section_list, host, mouth,
                                  fact_times(meta, kind, words, duration, section_list), turns,
                                  card_times(meta, kind, duration, section_list), versus, countdown,
                                  L()["wait"] if kind == "short" and meta.get("wait_for_it") else None, emotions,
                                  meta["style"])
        except Exception as e:  # never lose a day's video: fall back to the classic slideshow
            log(f"[{kind}] animated render failed ({str(e)[:150]}), using classic style")
    if video is None:
        video = build_video(work, clips, duration, fmt)
    first_photo = next((c["path"] for c in clips if c["is_image"]), None)
    mc = work / "music_credit.txt"
    return {"video": video, "words": words, "duration": duration, "credits": credits, "first_photo": first_photo,
            "chapters": chapter_list, "music_credit": mc.read_text(encoding="utf-8") if mc.exists() else ""}


# ---------- 6. YouTube ----------
_YT = {}


# Two Google Cloud projects = two daily API quotas (~6 uploads each) for the SAME channel.
# Project 1 handles English uploads and all channel-wide work; project 2 handles Hindi uploads when connected.
PROJECT = 1


def project_files(p=None):
    p = p or PROJECT
    if p == 2:
        return ROOT / "token_2.json", "YT_TOKEN_JSON_2", ROOT / "client_secret_2.json", "YT_CLIENT_SECRET_JSON_2"
    return ROOT / "token.json", "YT_TOKEN_JSON", ROOT / "client_secret.json", "YT_CLIENT_SECRET_JSON"


def project2_available():
    return (ROOT / "token_2.json").exists() or bool(os.environ.get("YT_TOKEN_JSON_2"))


def token_file():
    tok, var, _, _ = project_files()
    return tok, var


def youtube_client():
    tok, tok_var, secret, secret_var = project_files()
    if tok.name in _YT:
        return _YT[tok.name]
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # user may untick optional scopes on consent screen
    # Cloud runner: the newest login made with the phone app's "Log in to YouTube" button wins (kept in Supabase,
    # service key only); otherwise credentials come from encrypted GitHub Secrets, written to git-ignored files.
    if os.environ.get("GITHUB_ACTIONS") and sb_on():
        try:
            row = sb_rest("GET", f"yt_logins?select=token&project=eq.{PROJECT}")
            if row:
                tok.write_text(json.dumps(row[0]["token"]), encoding="utf-8")
        except Exception as e:
            log(f"app login not read ({str(e)[:100]}), using the saved one")
    for path, var in ((tok, tok_var), (secret, secret_var)):
        if not path.exists() and os.environ.get(var):
            path.write_text(os.environ[var].lstrip("\ufeff"), encoding="utf-8")  # PowerShell pipes add a BOM
    # Load with the scopes the saved login was actually granted: asking for more on refresh fails (invalid_scope).
    creds = Credentials.from_authorized_user_file(str(tok)) if tok.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:  # revoked/expired login: tell the phone app, then use the other project's login
                if "invalid_grant" not in str(e):
                    raise
                if sb_on():
                    sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates", json={
                        "key": f"login_expired_{PROJECT}", "value": {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "lang": LANG}})
                return failover_client(e)
            if sb_on() and get_setting(f"login_expired_{PROJECT}", None):
                sb_rest("DELETE", f"settings?key=eq.login_expired_{PROJECT}")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
            creds = flow.run_local_server(port=0)
        tok.write_text(creds.to_json())
    _YT[tok.name] = build("youtube", "v3", credentials=creds)
    _YT[tok.name + ":creds"] = creds
    return _YT[tok.name]


def failover_client(err):
    """Both Google Cloud projects are logged in to the SAME channel, so when one login is revoked the other carries
    every upload (each project has quota for ~100 uploads a day) until the broken one is logged in again."""
    global PROJECT
    other = 2 if PROJECT == 1 else 1
    tok, var, _, _ = project_files(other)
    if _YT.get(f"failed:{other}") or not (tok.exists() or os.environ.get(var)):
        raise err
    _YT[f"failed:{PROJECT}"] = True
    log(f"YouTube login for project {PROJECT} expired; using project {other}'s login instead")
    PROJECT = other
    return youtube_client()


def push_login_to_github(p):
    """After --auth: copy the new login into GitHub Secrets so the cloud uses it at once (no manual step)."""
    tok, var, _, _ = project_files(p)
    r = subprocess.run(["gh", "secret", "set", var], input=tok.read_text(encoding="utf-8"), text=True,
                       capture_output=True, cwd=ROOT)
    log(f"GitHub secret {var}: {'updated' if r.returncode == 0 else 'NOT updated - ' + r.stderr.strip()[:150]}")
    if sb_on():
        try:  # an older app-button login would otherwise win over this one in the cloud
            sb_rest("POST", "yt_logins?on_conflict=project", prefer="resolution=merge-duplicates", json={
                "project": p, "token": json.loads(tok.read_text(encoding="utf-8")),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        except Exception as e:
            log(f"login not saved to Supabase ({str(e)[:100]})")
        sb_rest("DELETE", f"settings?key=eq.login_expired_{p}")  # clears the red banner in the app


def analytics_client():
    """YouTube Analytics (watch time, retention). Needs the yt-analytics.readonly scope from the login."""
    from googleapiclient.discovery import build
    youtube_client()
    creds = _YT[token_file()[0].name + ":creds"]
    if "https://www.googleapis.com/auth/yt-analytics.readonly" not in (creds.scopes or []):
        return None
    return build("youtubeAnalytics", "v2", credentials=creds)


BASE_HASHTAGS = {"en": ["TechNews", "Technology", "Tech"], "hi": ["TechNewsHindi", "TechNews", "Technology"]}


def hashtags(meta, short, topic):
    """Up to 15 hashtags (more makes YouTube ignore all of them); the first 3 show above the title."""
    tags = [re.sub(r"[^\w]", "", h.lstrip("#")) for h in meta.get("hashtags", [])]
    tags = [t for t in tags if t] + [re.sub(r"\W", "", topic.title())] + BASE_HASHTAGS.get(LANG, [])
    tags = [t for t in dict.fromkeys(tags) if t.lower() != "shorts" and len(t) <= 30]
    return " ".join(f"#{t}" for t in ((["Shorts"] + tags[:13]) if short else tags[:14]))


def clean_tags(meta, limit=480):
    """YouTube allows 500 characters of tags in total; '<' '>' are rejected."""
    out, seen, used = [], set(), 0
    for t in [meta.get("primary_keyword", "")] + meta.get("tags", []):  # raw suggestions are often off-topic
        t = re.sub(r"[<>#]", "", str(t)).strip()
        if not t or t.lower() in seen or len(t) > 60:
            continue
        cost = len(t) + (2 if " " in t else 0) + 1
        if used + cost > limit:
            break
        seen.add(t.lower())
        out.append(t)
        used += cost
    return out


AFFILIATE = {"en": ("AMAZON_TAG_US", "https://www.amazon.com/s"), "hi": ("AMAZON_TAG_IN", "https://www.amazon.in/s")}


def affiliate_block(meta):
    """Amazon search links for products in the story (only when an Associates tag is configured), with disclosure."""
    var, base = AFFILIATE[LANG]
    # Tracking ID from the app (More > Amazon affiliate), else the cloud setting. Only safe characters allowed.
    app_tags = get_setting("affiliate", {}) or {}
    tag = (app_tags.get("us" if LANG == "en" else "in") or os.environ.get(var, "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{3,40}", tag or ""):
        return ""
    items = [p for p in meta.get("products") or [] if isinstance(p, dict) and p.get("name") and p.get("search")][:3]
    if not tag or not items:
        return ""
    lines = [f"- {p['name']}: {base}?k={requests.utils.quote(p['search'])}&tag={tag}" for p in items]
    return ("Products mentioned (affiliate links):\n" + "\n".join(lines)
            + "\nAs an Amazon Associate I earn from qualifying purchases.")


LATEST_LONG = {}


def latest_long_url():
    """Newest public long video in this language (this run's, else the last 3 days) for the Shorts -> long funnel."""
    if LATEST_LONG.get(LANG):
        return LATEST_LONG[LANG]
    if not sb_on():
        return None
    rows = sb_rest("GET", f"videos?select=youtube_id&kind=eq.long&lang=eq.{LANG}&privacy=eq.public"
                          f"&created_at=gte.{days_ago(3)}&order=created_at.desc&limit=1")
    return f"https://youtu.be/{rows[0]['youtube_id']}" if rows else None


def description(meta, short, topic, credits, chapter_list=()):
    """Search-friendly layout: keyword sentence first (shown in search), summary, chapters, sources, hashtags."""
    channel = os.environ.get("CHANNEL_NAME", "TechPulse")
    tx = L()["text"]
    first = meta.get("description_hook") or meta.get("description", "")
    parts = [first.strip()]
    if meta.get("related_url"):
        parts.append(f"{tx['full_story']} {meta['related_url']}")
    if meta.get("summary"):
        parts.append(meta["summary"].strip())
    if meta.get("key_points") and not short:
        parts.append(tx["in_video"] + "\n" + "\n".join(f"- {p}" for p in meta["key_points"][:5]))
    if meta.get("topics"):
        parts.append(tx["topics"] + "\n" + "\n".join(f"- {t}" for t in meta["topics"][:8] if isinstance(t, str)))
    if chapter_list:
        parts.append("Chapters:\n" + "\n".join(f"{ts(t)} {h}" for t, h in chapter_list))
    if meta.get("sources"):
        parts.append(f"{tx['sources']}: " + ", ".join(meta["sources"]))
    parts.append(tx["subscribe"].format(c=channel) + "\n" + (tx["more_short"] if short else tx["more_long"]))
    aff = affiliate_block(meta)
    if aff:
        parts.append(aff)
    parts.append(tx["ai"])
    if meta.get("music_credit"):
        parts.append(meta["music_credit"])
    tail = hashtags(meta, short, topic)
    head = "\n\n".join(p for p in parts if p)
    if credits:
        block = tx["credits"] + "\n"
        budget = 4800 - len(head.encode()) - len(tail.encode())  # YouTube counts bytes, not characters
        for c in credits:
            if len(block.encode()) + len(c.encode()) + 1 > budget:
                break
            block += c + "\n"
        head += "\n\n" + block.strip()
    return f"{head}\n\n{tail}"


def refresh_seo(vid, dry=False):
    """Bring an older video's metadata up to the current SEO standard: 30-40 relevant tags, a topics list, the news
    outlets covering the story and 10-12 hashtags. Title and existing description text stay; no new claims."""
    global LANG
    yt = youtube_client()
    snip = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"]
    row = (sb_rest("GET", f"insights?select=topic,lang,kind&youtube_id=eq.{vid}") or [{}])[0] if sb_on() else {}
    LANG = row.get("lang") or ("hi" if (snip.get("defaultLanguage") or "").startswith("hi") else "en")
    topic = row.get("topic") or snip["title"]
    short = row.get("kind", "short") == "short"
    old = snip.get("description", "")
    body_text = re.sub(r"(\n\s*#\w+(\s+#\w+)*\s*)+$", "", old).rstrip()  # drop the old hashtag line at the end
    kw = keyword_research(topic)
    outlets = sorted({c["source"] for c in story_context(topic, n=10) if c["source"]})[:8]
    res = llm_json(f"""Improve the search metadata of this existing YouTube {'Short' if short else 'video'}.
TITLE: {snip['title']}
DESCRIPTION (what the video says): {old[:1500]}
YOUTUBE SEARCH SUGGESTIONS: {', '.join(kw) or '(none)'}
{SEO_RULES}
{lang_rules()}
Only describe what the title and description already say - never add new facts or claims.
Tags and topics must be about THIS exact story: drop any search suggestion about something else (other tools,
other languages/regions like "tamil", gift cards, makers/generators, tutorials). 20-35 strictly relevant tags beat
40 loose ones (unrelated tags count as spam).
Return JSON only: {{"topics": ["5-8 search phrases"], "tags": ["20-35 tags"], "hashtags": ["10-12 hashtags"]}}""",
                   required=("tags", "hashtags"))
    tx = L()["text"]
    extra = []
    if res.get("topics") and tx["topics"] not in old:
        extra.append(tx["topics"] + "\n" + "\n".join(f"- {t}" for t in res["topics"][:8] if isinstance(t, str)))
    if outlets and "Sources" not in old and "More coverage" not in old:
        extra.append("More coverage: " + ", ".join(outlets))  # outlets reporting the story (not claimed as our sources)
    # new blocks go before the image credits (credits stay last, just above the hashtags)
    cut = body_text.find(tx["credits"])
    head, credits = (body_text[:cut].rstrip(), body_text[cut:]) if cut > 0 else (body_text, "")
    build = lambda: "\n\n".join(p for p in [head, *extra, credits, hashtags(res, short, topic)] if p)
    desc = build()
    while len(desc.encode()) > 4900 and extra:  # YouTube's 5,000-byte limit
        extra.pop()
        desc = build()
    tags = clean_tags({"tags": res["tags"]})
    if dry:
        return {"old_tags": snip.get("tags", []), "new_tags": tags, "old_desc": old, "new_desc": desc}
    body = {k: snip[k] for k in ("title", "categoryId", "defaultLanguage", "defaultAudioLanguage") if k in snip}
    yt.videos().update(part="snippet", body={"id": vid, "snippet": {**body, "description": desc, "tags": tags}}).execute()
    log(f"SEO refreshed: {snip['title'][:50]} ({len(snip.get('tags', []))} -> {len(tags)} tags)")
    return {"new_tags": tags}


SAFETY_PAUSE = False  # set by channel_health(): YouTube rejected/removed something recently


def get_setting(key, default):
    """App-controlled switch (Studio app > Controls). Falls back to `default` when Supabase is off or unreachable."""
    if not sb_on():
        return default
    try:
        rows = sb_rest("GET", f"settings?select=value&key=eq.{key}")
        return rows[0]["value"] if rows else default
    except Exception:
        return default


def privacy_for(meta):
    """Auto-publish (YT_PRIVACY=public) unless the fact-check held the video back, the channel safety pause is on,
    or auto-publish is switched off in the app."""
    if meta.get("hold") or SAFETY_PAUSE or get_setting("autopublish", True) is False:
        return "private"
    return os.environ.get("YT_PRIVACY", "private")


def upload(path, title, desc, tags, short, privacy=None):
    from googleapiclient.http import MediaFileUpload

    # Shorts are detected from the vertical format; #Shorts lives in the description, keeping the title clean.
    title = re.sub(r"\s*#shorts\b", "", title.strip().strip('"'), flags=re.I)
    title = re.sub(r"[<>]", "", title)[:100]  # YouTube rejects < and > in titles and descriptions
    desc = re.sub(r"[<>]", "", desc)
    while len(desc.encode()) > 4990:
        desc = desc[:-200]
    body = {
        "snippet": {"title": title, "description": desc, "tags": tags,
                    "categoryId": os.environ.get("YT_CATEGORY", "28"), "defaultLanguage": LANG,
                    "defaultAudioLanguage": LANG},
        "status": {"privacyStatus": privacy or os.environ.get("YT_PRIVACY", "private"), "selfDeclaredMadeForKids": False,
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
            if tries > 5 or "exceeded the number of videos" in str(e):  # daily channel limit: retrying can't help
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


PLAYLISTS = {"en": ("TechPulse: Daily Tech & AI News (English)", "Every TechPulse tech and AI news video in English."),
             "hi": ("TechPulse Hindi: टेक और AI न्यूज़ हिंदी में", "TechPulse के सभी Hindi tech और AI news videos.")}


def add_to_series(vid, story):
    """When a story gets its 2nd video: a public "Full Story" playlist with every part, linked from the pinned
    comment - a series gives viewers a reason to subscribe (one-off videos gave ~1 subscriber per 2,000 views)."""
    if not story or not sb_on():
        return None
    try:
        ids = [r["youtube_id"] for r in sb_rest("GET", f"insights?select=youtube_id&story=eq.{story}&order=created_at.asc")]
        ids = [i for i in ids if i and i != vid] + [vid]
        if len(ids) < 2:
            return None
        yt = youtube_client()
        name = story.replace("-", " ").title()
        title = f"{name} - Full Story (all updates)" if LANG == "en" else f"{name} - पूरी कहानी (सभी updates)"
        lists, token = [], None
        for _ in range(4):
            page = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
            lists += page.get("items", [])
            token = page.get("nextPageToken")
            if not token:
                break
        pid = next((p["id"] for p in lists if p["snippet"]["title"] == title), None)
        have = set()
        if pid:
            have = {i["contentDetails"]["videoId"] for i in yt.playlistItems().list(
                part="contentDetails", playlistId=pid, maxResults=50).execute().get("items", [])}
        else:
            pid = yt.playlists().insert(part="snippet,status", body={
                "snippet": {"title": title[:150], "description": f"Every {CHANNEL()} update on {name}, newest first.",
                            "defaultLanguage": LANG}, "status": {"privacyStatus": "public"}}).execute()["id"]
        for v in [i for i in ids if i not in have]:
            for attempt in range(4):  # 409 right after creating = not ready yet
                try:
                    yt.playlistItems().insert(part="snippet", body={"snippet": {
                        "playlistId": pid, "position": 0, "resourceId": {"kind": "youtube#video", "videoId": v}}}).execute()
                    break
                except Exception as e:
                    if "409" not in str(e) or attempt == 3:
                        raise
                    time.sleep(15 * (attempt + 1))
        log(f"  series playlist '{title}' ({len(ids)} parts)")
        return f"https://www.youtube.com/playlist?list={pid}"
    except Exception as e:
        log(f"  series playlist skipped: {str(e)[:120]}")
        return None


def series_note(n):
    """Script instruction for the n-th video (n >= 2) on a story: say it is part of an ongoing series."""
    return (f". SERIES: this is update #{n} on this story on our channel - say once, naturally, that it's part {n} and"
            " that every part is in the full-story playlist") if n >= 2 else ""


def add_to_playlist(vid):
    """One playlist per language: autoplay into the next video = longer sessions, which the algorithm rewards."""
    try:
        yt = youtube_client()
        title, desc = PLAYLISTS[LANG]
        items = yt.playlists().list(part="snippet", mine=True, maxResults=50).execute().get("items", [])
        pid = next((p["id"] for p in items if p["snippet"]["title"] == title), None)
        if not pid:
            pid = yt.playlists().insert(part="snippet,status", body={
                "snippet": {"title": title, "description": desc, "defaultLanguage": LANG},
                "status": {"privacyStatus": "public"}}).execute()["id"]
        for attempt in range(4):  # 409 right after a playlist or video is created = not ready yet; wait and retry
            try:
                yt.playlistItems().insert(part="snippet", body={"snippet": {
                    "playlistId": pid, "position": 0, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
                break
            except Exception as e:
                if "409" not in str(e) or attempt == 3:
                    raise
                time.sleep(15 * (attempt + 1))
        log("  added to playlist")
    except Exception as e:
        log(f"  playlist skipped: {str(e)[:120]}")


REPLY_DAILY_CAP = 15     # natural volume, and keeps YouTube quota for uploads (50 units per reply)
REPLY_MIN_AGE_MIN = 25   # wait a while like a person would, never reply within seconds
# What happens to each type of viewer comment (see GROWTH_PLAN_OCT26.md, part B)
ALWAYS_REPLY = {"question", "ai_callout", "fake", "correction", "request", "risky"}
SOMETIMES_REPLY = {"opinion": 0.6, "praise": 0.5, "criticism": 0.5}  # random share: natural, not a bot on every comment
HIDE_TYPES = {"abuse", "spam"}  # hate, insults, scams, links, self-promotion: hidden (never honest criticism)


def reply_comments(limit=3, force=False):
    """Every new viewer comment on every video, about once an hour: give it a type, then act - honest replies
    (never claims to be human), fact re-check on "fake"/"wrong" (correction if the viewer is right), hide abuse and
    spam, save viewer topic requests. Everything is stored in the comments table for the app and for learning."""
    now = datetime.datetime.now(datetime.timezone.utc)
    state = get_setting("comment_replies", {}) or {}
    last = state.get("checked")
    yt = youtube_client()
    apply_hide_requests(yt)  # "Hide" taps in the app
    if not force and last and now - datetime.datetime.fromisoformat(last) < datetime.timedelta(minutes=55):
        return
    today = str(datetime.date.today())
    sent_today = state.get("count", 0) if state.get("date") == today else 0
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    known = {r["id"] for r in sb_rest("GET", f"comments?select=id&handled_at=gte.{days_ago(60)}")}
    known |= set(state.get("decided", []))  # decided by the older reply logic
    titles = {r["youtube_id"]: r for r in sb_rest("GET", "insights?select=youtube_id,title,topic,lang")}
    cands, token = [], None
    for _ in range(3):  # newest first, up to 300 threads: every video, not just recent ones
        page = yt.commentThreads().list(part="snippet", allThreadsRelatedToChannelId=me, order="time", maxResults=100,
                                        textFormat="plainText", pageToken=token).execute()
        for t in page.get("items", []):
            top = t["snippet"]["topLevelComment"]["snippet"]
            age_min = (now - datetime.datetime.fromisoformat(top["publishedAt"].replace("Z", "+00:00"))).total_seconds() / 60
            if (t["id"] in known or top.get("authorChannelId", {}).get("value") == me or age_min < REPLY_MIN_AGE_MIN
                    or age_min > 60 * 24 * 30):
                continue
            v = titles.get(top["videoId"], {})
            cands.append({"id": t["id"], "video_id": top["videoId"], "video": v.get("title", ""), "topic": v.get("topic", ""),
                          "lang": v.get("lang", "en"), "text": top["textDisplay"][:400], "at": top["publishedAt"],
                          "answered": t["snippet"].get("totalReplyCount", 0) > 0})
        token = page.get("nextPageToken")
        if not token:
            break
    sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates",
            json={"key": "comment_replies", "value": {**state, "checked": now.isoformat()}})
    if not cands:
        return
    cands = cands[:20]
    res = llm_json(f"""You run the YouTube channel {CHANNEL()} (AI-made tech & AI news Shorts; voice and visuals are AI,
facts come from the news sources listed in each description). Sort each viewer comment and draft a reply.
TYPES: question, ai_callout (says it is AI / AI slop / bot), fake (says the news is fake or wrong without details),
correction (points out a specific fact we got wrong), request (asks for a video on a topic), risky (wants piracy,
mods, cracks or anything unsafe), opinion, praise, criticism (boring, bad voice, too many videos...), abuse (insults,
hate, harassment), spam (links, self-promotion, scams, bots), emoji (only emoji or one word).
REPLY RULES: short (4-25 words), casual, specific to what THEY said, same language and script as the comment
(Hinglish -> Hinglish). Every reply in this batch must use DIFFERENT wording and sentence shape (no two replies alike); sometimes lowercase; at most one emoji. Never claim to be human, never say
"our team", never argue, no links, no "subscribe" requests, no stock phrases like "Great question".
- ai_callout: agree honestly ("yep, it's AI-made") and point to the sources in the description; invite them to say
  if a fact looks wrong.
- fake: calm, name that the story comes from the news outlets listed in the description.
- question: answer only from the video topic, or say honestly you're not sure yet.
- risky: friendly warning about the risk, never instructions.
- request: thank them and say it's noted.
- abuse, spam, emoji: reply "".
Also give "sentiment" (positive/neutral/negative) and for "request" the requested "request_topic".
COMMENTS:
{json.dumps([{k: c[k] for k in ("id", "video", "text")} for c in cands], ensure_ascii=False, indent=1)}
Return JSON only: {{"comments": [{{"id": "...", "type": "...", "sentiment": "...", "reply": "...", "request_topic": ""}}]}}""",
                   required=("comments",))
    by_id = {c["id"]: c for c in cands}
    rows, replies = [], []
    for r in res.get("comments", []):
        c = by_id.get(r.get("id"))
        if not c:
            continue
        kind, text = (r.get("type") or "opinion").strip().lower(), (r.get("reply") or "").strip()[:300]
        row = {"id": c["id"], "video_id": c["video_id"], "video_title": c["video"][:200], "lang": c["lang"],
               "text": c["text"], "type": kind, "sentiment": r.get("sentiment") or "neutral",
               "action": "answered_before" if c["answered"] else "skipped",
               "reply": None, "needs_you": False, "commented_at": c["at"], "handled_at": now.isoformat()}
        if kind in HIDE_TYPES:
            try:
                yt.comments().setModerationStatus(id=c["id"], moderationStatus="rejected").execute()
                row["action"] = "hidden"
            except Exception as e:
                row.update(action="flagged", needs_you=True)
                log(f"  hide failed: {str(e)[:100]}")
        elif kind in ("fake", "correction"):
            check = recheck_video(c)
            if check.get("verdict") == "unsure":  # second, deeper look: search the news for the viewer's own claim
                check = recheck_video(c, query=f"{c.get('topic') or c['video']} {c['text'][:80]}")
            if check.get("verdict") == "viewer_right" and check.get("correction"):
                text = check.get("reply") or text
                add_correction(yt, c["video_id"], check["correction"])
                save_lesson(f"Viewers corrected: {check['correction']} (video '{c['video'][:60]}')")
                row["action"] = "corrected"
            elif check.get("verdict") == "unsure" and kind == "correction":
                # still unclear: thank them, change nothing (never "correct" a video on an unverified claim)
                text = ("thanks, we'll double-check that against the sources" if c["lang"] == "en"
                        else "thanks, हम sources से दोबारा check करेंगे")
        if re.search(r"copyright|lawsuit|legal action|lawyer|dmca|my (video|footage|photo|image) (was )?used",
                     c["text"], re.I):
            row["needs_you"] = True  # rights/legal claims: a person decides (handled at the owner's checks)
        elif kind == "request" and r.get("request_topic"):
            add_topic_request(r["request_topic"], c["lang"])
        if text and not c["answered"] and (kind in ALWAYS_REPLY or random.random() < SOMETIMES_REPLY.get(kind, 0)):
            replies.append((row, text))
        rows.append(row)
    random.shuffle(replies)
    replies.sort(key=lambda x: x[0]["type"] not in ALWAYS_REPLY)  # important ones first
    sent = 0
    for row, text in replies[:max(0, min(limit + 2, REPLY_DAILY_CAP - sent_today))]:
        try:
            if sent:
                time.sleep(random.uniform(20, 75))  # not a burst of replies in the same second
            yt.comments().insert(part="snippet", body={"snippet": {"parentId": row["id"], "textOriginal": text}}).execute()
            row.update(reply=text, action=row["action"] if row["action"] == "corrected" else "replied")
            sent += 1
        except Exception as e:
            log(f"  reply failed: {str(e)[:100]}")
    if rows:
        sb_rest("POST", "comments?on_conflict=id", prefer="resolution=merge-duplicates", json=rows)
    value = {"date": today, "count": sent_today + sent, "checked": now.isoformat()}
    sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates",
            json={"key": "comment_replies", "value": value})
    types = {}
    for row in rows:
        types[row["type"]] = types.get(row["type"], 0) + 1
    log(f"comments: {len(rows)} new {types}, {sent} replied ({sent_today + sent}/{REPLY_DAILY_CAP} today), "
        f"{sum(r['action'] == 'hidden' for r in rows)} hidden, {sum(r['needs_you'] for r in rows)} need you")


def recheck_video(c, query=None):
    """A viewer says the video is fake or wrong: compare their claim with our description and fresh headlines."""
    try:
        # from YouTube itself: the app's video records are cleaned up after a week, the description stays
        items = youtube_client().videos().list(part="snippet", id=c["video_id"]).execute().get("items", [])
        desc = items[0]["snippet"].get("description", "") if items else ""
        ctx = story_context(query or c.get("topic") or c["video"], n=10, days=30)  # the video may be weeks old
        return llm_json(f"""A viewer commented on our news Short "{c['video']}": "{c['text']}"
OUR VIDEO DESCRIPTION (what the video said, plus its sources):
{desc[:2500]}
FRESH NEWS HEADLINES on the topic:
{json.dumps(ctx, ensure_ascii=False)[:3000]}
Did the viewer point out a REAL error in our video? Be strict and fair.
- "viewer_right": the headlines clearly support the viewer and contradict our video
- "video_right": the headlines support our video
- "unsure": cannot tell from these headlines
If viewer_right: "correction" = one plain sentence with the correct fact; "reply" = short thanks + the correction in
the comment's language (never claim to be human). Otherwise "correction" = "" and "reply" = "".
Return JSON only: {{"verdict": "...", "correction": "...", "reply": "..."}}""", required=("verdict",))
    except Exception as e:
        log(f"  re-check failed: {str(e)[:100]}")
        return {"verdict": "unsure"}


def add_correction(yt, vid, correction):
    """Puts the correction at the top of the video's description (pinning comments is not possible via the API)."""
    try:
        snip = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"]
        if "Correction:" in snip.get("description", ""):
            return
        body = {k: snip[k] for k in ("title", "description", "tags", "categoryId", "defaultLanguage",
                                     "defaultAudioLanguage") if k in snip}
        body["description"] = f"Correction: {correction[:300]}\n\n" + snip.get("description", "")
        yt.videos().update(part="snippet", body={"id": vid, "snippet": body}).execute()
        log(f"  correction added to {vid}")
    except Exception as e:
        log(f"  correction not added: {str(e)[:100]}")


def save_lesson(text):
    """Viewer feedback the script writer must respect from now on (shown to the writer by learned_block)."""
    lessons = (get_setting("comment_lessons", []) or [])[-29:] + [{"text": text[:300], "at": str(datetime.date.today())}]
    sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates",
            json={"key": "comment_lessons", "value": lessons})


def add_topic_request(topic, lang):
    """A viewer asked for a video on this: the topic picker prefers it for 7 days (if news outlets cover it)."""
    week_ago = str(datetime.date.today() - datetime.timedelta(days=7))
    reqs = [r for r in (get_setting("topic_requests", []) or []) if r.get("at", "") >= week_ago]
    if not any(repeats(topic, [r["topic"]]) for r in reqs):
        reqs.append({"topic": topic[:100], "lang": lang, "at": str(datetime.date.today())})
    sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates",
            json={"key": "topic_requests", "value": reqs[-30:]})


def apply_hide_requests(yt):
    """Comments the owner tapped "Hide" on in the app."""
    for r in sb_rest("GET", "comments?select=id&hide_requested=eq.true&action=neq.hidden"):
        try:
            yt.comments().setModerationStatus(id=r["id"], moderationStatus="rejected").execute()
            sb_rest("PATCH", f"comments?id=eq.{r['id']}", json={"action": "hidden"})
        except Exception as e:
            log(f"  hide failed: {str(e)[:100]}")


def upload_existing(work):
    """Upload an already-rendered video folder (used by the dashboard's Upload button)."""
    work = Path(work).resolve()
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    short = "_short_" in work.name
    desc = (work / "description.txt").read_text(encoding="utf-8")
    vid = upload(work / "final.mp4", meta["title"], desc, clean_tags(meta), short)
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


def sb_rest(method, path, prefer="return=representation", **kw):
    r = requests.request(method, f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path}",
                         headers=sb_headers({"Content-Type": "application/json", "Prefer": prefer}), timeout=60, **kw)
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


# words shared by unrelated stories ("Oppo vs iPhone Face-off" is not a repeat of "Moto vs iPhone Face-off")
GENERIC_WORDS = {"the", "and", "new", "google", "iphone", "samsung", "apple", "pro", "max", "ultra", "plus", "mini",
                 "lite", "face", "off", "update", "news", "price", "launch", "review", "phone", "battery", "camera",
                 "india", "vs", "with", "for", "leak", "leaks", "features", "feature"}


def repeats(topic, recent):
    """True if `topic` shares most of its key words with a recent topic ("Google Chrome Update" ~ "Chrome update")."""
    key = lambda t: {w for w in re.findall(r"\w+", t.lower()) if len(w) > 2 and w not in GENERIC_WORDS}
    a = key(topic)
    return bool(a) and any(len(a & key(r)) >= max(1, round(0.6 * min(len(a), len(key(r)) or 1))) for r in recent)


def remember_dropped(topic):
    """A topic dropped for safety or failed fact-checks is kept out of planning for 3 days."""
    if not sb_on():
        return
    st = [d for d in (get_setting("dropped_topics", []) or []) if d.get("at", "") >= days_ago(3)]
    st.append({"topic": topic, "at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates",
            json={"key": "dropped_topics", "value": st[-50:]})


def used_topics():
    if sb_on():
        since = days_ago(14)
        # oldest first, so callers' used[-40:] really is the most recent 40 (unordered rows let repeats slip through);
        # topics dropped for safety / fact-check in the last 3 days come last so they count as recent
        dropped = [d["topic"] for d in (get_setting("dropped_topics", []) or []) if d.get("at", "") >= days_ago(3)]
        return [r["topic"] for r in sb_rest("GET", f"videos?select=topic&lang=eq.{LANG}&created_at=gte.{since}"
                                                    "&order=created_at.asc") if r.get("topic")] + dropped
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
    row = sb_rest("POST", "videos", json={
        "kind": kind, "lang": LANG, "topic": meta["topic"], "title": meta["title"], "description": desc,
        "tags": meta.get("tags", [])[:15], "youtube_id": vid,
        "privacy": privacy_for(meta) if vid else None,
        "status": "published" if vid and privacy_for(meta) == "public" else ("uploaded" if vid else "rendered"),
        "duration_s": round(duration, 1),
        "meta": {**{k: meta.get(k) for k in ("pinned_comment", "keywords", "thumbnail_text", "fact_check", "host")},
                 "hold": bool(meta.get("hold"))}})
    if vid:
        sb_rest("POST", "insights", prefer="return=representation,resolution=merge-duplicates", json={"youtube_id": vid, "lang": LANG, "kind": kind, "topic": meta["topic"], "title": meta["title"],
                      "variant": meta.get("variant") or ("weekly" if meta.get("weekly") else None),
                      "format": meta.get("format"), "followup_of": meta.get("followup_of"),
                      "script_score": meta.get("script_score"), "story": meta.get("story")})
    try:  # app preview files are a convenience: a failure here must not lose the record above
        paths = {"preview_path": sb_upload(make_preview(work, kind), f"{prefix}/preview.mp4", "video/mp4")}
        if thumb:
            paths["thumb_path"] = sb_upload(thumb, f"{prefix}/thumb.jpg", "image/jpeg")
        sb_rest("PATCH", f"videos?id=eq.{row[0]['id']}", json=paths)
    except Exception as e:
        log(f"[{kind}] app preview skipped: {str(e)[:120]}")
    log(f"[{kind}] saved to Supabase")


def publish_pending():
    global LANG
    rows = sb_rest("GET", "videos?select=id,youtube_id,title,meta,lang&publish_requested=is.true&status=neq.published"
                          "&youtube_id=not.is.null")
    current = LANG
    try:
        for row in rows:
            LANG = row.get("lang") or "en"  # pick that language's channel login
            publish_one(row)
    finally:
        LANG = current  # never change the language of the run that called this
    if not rows:
        log("nothing to publish")


def publish_one(row):
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
        if getattr(getattr(e, "resp", None), "status", 0) in (400, 403, 404):  # gone/refused: stop retrying
            sb_rest("PATCH", f"videos?id=eq.{row['id']}", json={"status": "failed", "publish_requested": False})


def update_stats(full=True):
    """Refresh views/likes/comments for the last ~6 months (insights) and the app's 7-day list (videos).
    One channel for all languages, so one batched API call per 50 videos (1 quota unit each)."""
    since = days_ago(180 if full else 7)
    rows = sb_rest("GET", f"insights?select=youtube_id,created_at,views_24h&created_at=gte.{since}")
    ids = {r["youtube_id"] for r in rows}
    # views at 24 h old: the fair way to compare videos (an older video always has more views, a newer one more
    # views/hour). Saved once, when a video is 24-30 h old; older videos stay empty rather than skew the numbers.
    nowdt = datetime.datetime.now(datetime.timezone.utc)
    snap = {r["youtube_id"] for r in rows if r.get("views_24h") is None and datetime.timedelta(hours=24)
            <= nowdt - datetime.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < datetime.timedelta(hours=30)}
    ids |= {r["youtube_id"] for r in sb_rest("GET", "videos?select=youtube_id&youtube_id=not.is.null")}
    ids = sorted(ids)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        resp = youtube_client().videos().list(part="statistics,status", id=",".join(batch)).execute()
        found = {v["id"] for v in resp.get("items", [])}
        for gone in set(batch) - found:  # removed by YouTube (or deleted by hand)
            sb_rest("PATCH", f"insights?youtube_id=eq.{gone}&health=is.null", json={"health": "missing", "health_at": now})
        for v in resp.get("items", []):
            st = v["status"]
            if st.get("uploadStatus") in ("rejected", "failed", "deleted") or st.get("rejectionReason"):
                sb_rest("PATCH", f"insights?youtube_id=eq.{v['id']}&health=is.null", json={
                    "health": f"{st.get('uploadStatus')}:{st.get('rejectionReason') or st.get('failureReason') or ''}",
                    "health_at": now})
            s = v.get("statistics", {})
            st = {k: int(s.get(k, 0)) for k in ("viewCount", "likeCount", "commentCount")}
            sb_rest("PATCH", f"videos?youtube_id=eq.{v['id']}", json={"privacy": v["status"]["privacyStatus"], "stats": st})
            sb_rest("PATCH", f"insights?youtube_id=eq.{v['id']}", json={
                "views": st["viewCount"], "likes": st["likeCount"], "comments": st["commentCount"], "updated_at": now,
                **({"views_24h": st["viewCount"]} if v["id"] in snap else {})})
    log(f"stats updated for {len(ids)} videos")
    save_channel_stats()  # 1 quota unit: keeps the app's subscriber/view tiles fresh every 10 minutes
    try:
        double_down()
    except Exception as e:
        log(f"double-down skipped: {str(e)[:160]}")
    if not full:  # quick refresh (publish checks): view counts + channel totals, feeds the views-per-hour learning
        try:
            update_goals()  # database only, no quota
        except Exception as e:
            log(f"goals skipped: {str(e)[:160]}")
        return
    try:
        update_analytics(ids)
    except Exception as e:
        log(f"analytics skipped: {str(e)[:160]}")
    try:
        update_goals()
    except Exception as e:
        log(f"goals skipped: {str(e)[:160]}")
    try:
        optimize_titles()
    except Exception as e:
        log(f"titles skipped: {str(e)[:160]}")
    try:
        learn_rules()
    except Exception as e:
        log(f"learning skipped: {str(e)[:160]}")
    channel_health()


def update_analytics(ids):
    """Watch time and retention per video, plus channel watch hours (last 365 days, the monetization window).
    YouTube Analytics lags about 2 days behind."""
    ya = analytics_client()
    if not ya:
        log("analytics: not authorized yet (log in again with --auth to grant watch-time access)")
        return
    today = datetime.date.today()
    for i in range(0, len(ids), 150):
        rows = ya.reports().query(ids="channel==MINE", startDate="2020-01-01", endDate=str(today),
                                  metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
                                  dimensions="video", filters="video==" + ",".join(ids[i:i + 150]),
                                  maxResults=200).execute().get("rows", [])
        for vid, _views, minutes, avg_s, avg_pct in rows:
            sb_rest("PATCH", f"insights?youtube_id=eq.{vid}", json={
                "watch_minutes": minutes, "avg_view_s": avg_s, "avg_view_pct": round(avg_pct, 1)})
    total = ya.reports().query(ids="channel==MINE", startDate=str(today - datetime.timedelta(days=365)),
                               endDate=str(today), metrics="estimatedMinutesWatched").execute().get("rows", [[0]])
    hours = round((total[0][0] if total else 0) / 60, 1)
    sb_rest("PATCH", f"channel_stats?day=eq.{datetime.datetime.now(datetime.timezone.utc).date()}", json={"watch_hours": hours})
    log(f"analytics: {hours} watch hours in the last 365 days")
    recent = sb_rest("GET", f"insights?select=youtube_id,kind&views=gte.15&created_at=gte.{days_ago(30)}&order=created_at.desc")
    retention_lessons(ya, recent)


def save_channel_stats():
    """One row per day of subscribers / views / video count, for the app's growth chart."""
    s = youtube_client().channels().list(part="statistics", mine=True).execute()["items"][0]["statistics"]
    # The channel total lags hours behind YouTube Studio; per-video counts are fresher, so use whichever is higher.
    video_views = sum(r["views"] or 0 for r in sb_rest("GET", "insights?select=views"))
    sb_rest("POST", "channel_stats", prefer="return=minimal,resolution=merge-duplicates", json={
        "day": str(datetime.datetime.now(datetime.timezone.utc).date()),
        "subscribers": int(s.get("subscriberCount", 0)), "views": max(int(s.get("viewCount", 0)), video_views),
        "videos": int(s.get("videoCount", 0)),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    log(f"channel: {s.get('subscriberCount')} subscribers, {s.get('viewCount')} views, {s.get('videoCount')} videos")


def factory_busy(token, repo):
    if not (token and repo):
        return False
    for status in ("in_progress", "queued"):
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows/factory.yml/runs?status={status}",
                         headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code != 200 or r.json().get("total_count"):
            return True
    return False


FOLLOWUPS_PER_WINNER, FOLLOWUPS_PER_DAY, FOLLOWUP_GAP_H = 1, 3, 6  # was 2/5: part 2s piled onto one story


def double_down():
    """Breakout rule: a Short that clearly outperforms the channel (3x the median views/hour, 300+ views) gets up to
    2 follow-up Shorts on the same story from new angles, at least 6 h apart - the Shorts feed already showed the
    audience wants this topic. Queued as run requests (started when no factory run is busy)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    state = get_setting("followups", {}) or {}
    today = str(now.date())
    made_today = state.get("count", 0) if state.get("date") == today else 0
    done = state.get("done", {})  # youtube_id -> [iso times of queued follow-ups]
    if made_today >= FOLLOWUPS_PER_DAY:
        return
    queued = []
    recent = recent_stories()
    for lang in LANGS:
        base = [r["vph"] for r in scored_videos(lang, days=14) if r["kind"] == "short"]
        if len(base) < 5:
            continue
        median = sorted(base)[len(base) // 2]
        for r in scored_videos(lang, days=2, min_hours=1):
            if (r["kind"] != "short" or r["views"] < 300 or r["vph"] < max(30, 3 * median)
                    or r.get("followup_of")):  # a part 2 never gets its own part 2 (no chains of near-duplicates)
                continue
            vid = r.get("youtube_id")
            times = done.get(vid, [])
            if not vid or len(times) >= FOLLOWUPS_PER_WINNER or (
                    times and now - datetime.datetime.fromisoformat(times[-1]) < datetime.timedelta(hours=FOLLOWUP_GAP_H)):
                continue
            if sb_rest("GET", f"run_requests?select=id&followup=eq.{vid}&status=in.(pending,starting)"):
                continue  # already queued (another job saw it first)
            if story_count({"topic": r.get("topic") or r["title"], "story": r.get("story")}, recent) >= STORY_MAX:
                continue  # story on cooldown: a part 2 would be the 3rd+ video on it in 48 h
            done[vid] = times + [now.isoformat()]
            made_today += 1
            # save the decision before queueing, so a parallel job does not queue the same part 2
            sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates", json={
                "key": "followups", "value": {"date": today, "count": made_today, "done": dict(list(done.items())[-200:])}})
            sb_rest("POST", "run_requests", json={"lang": lang, "long": 0, "shorts": 1, "followup": vid})
            queued.append(f"{lang} {r['title'][:50]} ({r['vph']:.0f}/h vs median {median:.1f})")
            if made_today >= FOLLOWUPS_PER_DAY:
                break
        if made_today >= FOLLOWUPS_PER_DAY:
            break
    if queued:
        log("double-down: follow-up Shorts queued for " + "; ".join(queued))


def plan_viral(trends, niche, used):
    """Viral-format track: an evergreen-style Short (versus, top 3, budget list, hidden trick, what-if, money/risk)
    on a subject people search for now, still built only from fresh source articles."""
    try:
        return _plan_viral(trends, niche, used)
    except Exception as e:  # fail the run (no traceback noise) so the clock retries the slot once
        log(f"viral: planning failed ({str(e)[:160]})")
        raise SystemExit(1)


def _plan_viral(trends, niche, used):
    names = VIRAL_FORMATS[LANG]
    fmt_name = choose_format(names)
    rejected = []
    recent = recent_stories()
    for attempt in range(4):
        shown = trends[:60] if not rejected else random.sample(trends[:80], min(60, len(trends[:80])))
        avoid = (f"\nREJECTED just now as repeats of recent videos: {json.dumps(rejected, ensure_ascii=False)}. Pick a "
                 "subject about a DIFFERENT company or product.") if rejected else ""
        pick = llm_json(f"""You plan one YouTube Short for {CHANNEL()} ({niche}), language: {L()['name']}.
FORMAT: {SHORT_FORMATS[fmt_name]}
Choose ONE concrete subject that a huge audience ({'India' if LANG == 'hi' else 'the US'}) searches for right now
(popular phones, iPhone/Samsung/Pixel, ChatGPT/Gemini, WhatsApp, UPI, cheap gadgets, viral AI tools) and that recent
news articles cover, so the facts can be sourced. Prefer famous brands and things people own.
Trending now (for inspiration):
{trends_text(shown)}
Already covered recently (do not repeat): {json.dumps(used[-40:], ensure_ascii=False)}{avoid}
{stories_block(recent)}
{TOPIC_SCORE}
{SAFE_TOPICS}
Return JSON only: {{"topic": "short name", "story": "product-or-event-slug", "search_query": "3-6 word news search query", "angle": "the hook"}}""",
                        required=("topic", "search_query"))
        # a real repeat is never accepted (3 Hindi "Chrome update" Shorts got ~25 views each); if all 4 tries repeat,
        # the run fails and the clock retries the slot later with fresh trends
        if repeats(pick["topic"], used[-15:]) or story_count(pick, recent) >= STORY_MAX:
            log(f"viral: '{pick['topic']}' repeats a recent video or story, trying another subject")
            rejected.append(pick["topic"])
            used = used + [pick["topic"]]
            continue
        ctx = story_context(pick["search_query"], n=10)
        if len({c["source"] for c in ctx if c["source"]}) >= MIN_OUTLETS:
            break
        log(f"viral: '{pick['topic']}' has too few news outlets, trying another subject")
        used = used + [pick["topic"]]
    else:  # no usable subject: fail the run so the clock retries the slot later instead of losing it
        raise RuntimeError("no subject with enough sources")
    kw = keyword_research(pick["search_query"])
    variant = "fast" if fmt_name in FAST_FORMATS else "core"
    n_story = len(sb_rest("GET", f"insights?select=youtube_id&story=eq.{story_slug(pick)}")) if sb_on() else 0
    pick = {**pick, "angle": pick.get("angle", "") + series_note(n_story + 1)}
    try:
        meta = write_checked(lambda note: write_short({**pick, "angle": pick.get("angle", "") + note}, ctx, kw, variant,
                                                      fmt_name), ctx, "short")
    except RuntimeError as e:
        if str(e).startswith("dropped"):
            remember_dropped(pick["topic"])  # the clock's retry must pick a different subject, not the same one
        raise
    meta.update({"variant": variant, "sources": sorted({c["source"] for c in ctx if c["source"]})[:8],
                 "search_suggestions": kw, "story": story_slug(pick)})
    log(f"viral: {fmt_name} - '{pick['topic']}' ({len(ctx)} sources)")
    return [("short", meta)]


def plan_followup(vid):
    """Planner for a follow-up Short: same story as a breakout Short, a NEW angle, labelled as part 2."""
    def planner(trends, niche, used):
        try:
            return _planner(trends, niche, used)
        except Exception as e:
            log(f"follow-up: planning failed ({str(e)[:160]})")
            return []

    def _planner(trends, niche, used):
        rows = sb_rest("GET", f"insights?select=title,topic,lang,story&youtube_id=eq.{vid}")
        if not rows or not rows[0].get("topic"):
            log(f"follow-up: {vid} not found")
            return []
        orig = rows[0]
        if story_count({"topic": orig["topic"], "story": orig.get("story")}, recent_stories()) >= STORY_MAX:
            log(f"follow-up: story of '{orig['title']}' already has {STORY_MAX}+ videos in 48 h, skipping")
            return []
        part = 2 + len(sb_rest("GET", f"insights?select=youtube_id&followup_of=eq.{vid}"))
        ctx = story_context(orig["topic"])
        if len({c["source"] for c in ctx if c["source"]}) < MIN_OUTLETS:
            log(f"follow-up: not enough news outlets for '{orig['topic']}'")
            return []
        kw = keyword_research(orig["topic"])
        pick = {"topic": orig["topic"], "angle": (
            f"FOLLOW-UP (part {part}) to our Short '{orig['title']}', which viewers loved. Use a NEW angle and "
            "different facts (what happens next, reactions, what it means for you); do not repeat earlier parts. "
            f"Mention naturally that this is part {part}.")}
        variant = pick_short_variant(0)
        fmt_names = [f for f in NEWS_FORMATS if f != "hot_take"]
        fmt = random.choice(fmt_names)
        meta = write_checked(lambda note: write_short({**pick, "angle": pick["angle"] + note}, ctx, kw, variant, fmt),
                             ctx, "short")
        meta.update({"variant": variant, "followup_of": vid, "sources": sorted({c["source"] for c in ctx if c["source"]})[:8],
                     "search_suggestions": kw, "story": orig.get("story") or slugify(orig["topic"])})
        log(f"follow-up: part {part} of '{orig['title']}'")
        return [("short", meta)]
    return planner


def process_requests():
    """'Run now' taps in the app become factory runs. Runs inside GitHub Actions with its own short-lived token;
    capped so the daily YouTube upload limit (about 6) is never exceeded."""
    pending = sb_rest("GET", "run_requests?select=*&status=eq.pending&order=created_at.asc")
    if not pending:
        log("run requests: none")
        return
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if factory_busy(token, repo):
        log("run requests: a factory run is busy, starting the next request later")
        return
    for req in pending[:1]:  # GitHub keeps one waiting run per group: a second dispatch would cancel the first
        want = req["long"] + req["shorts"]
        uploads = uploads_24h(req["lang"])  # this language's Google project
        if want == 0:
            status = "skipped: nothing requested"
        elif not (token and repo):
            status = "failed: not running in the cloud"
        elif uploads + want > UPLOAD_CAP:
            status = f"skipped: daily upload limit ({uploads} in 24 h)"
        else:
            sb_rest("PATCH", f"run_requests?id=eq.{req['id']}", json={"status": "starting"})
            r = requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/factory.yml/dispatches",
                              headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                              json={"ref": "main", "inputs": {"lang": req["lang"], "long": str(req["long"]),
                                                              "shorts": str(req["shorts"]),
                                                              **({"followup": req["followup"]} if req.get("followup") else {})}},
                              timeout=30)
            status = "started" if r.status_code == 204 else f"failed: GitHub {r.status_code}"
            if r.status_code == 204:
                uploads += want
        sb_rest("PATCH", f"run_requests?id=eq.{req['id']}", json={"status": status})
        log(f"run request {req['id']} ({req['lang']} {req['long']}L+{req['shorts']}S): {status}")


def update_goals():
    """Compare progress with the targets set in the app (default 10,000 subscribers and 2,000 watch hours by the
    deadline), work out today's required pace, project the result from the last 7 days, and pick a strategy:
    'reach' (subscribers behind -> broad, viral, shareable stories) or 'watch' (hours behind -> depth, more long)."""
    goals = get_setting("goals", {"subscribers": 10000, "watch_hours": 2000, "deadline": "2026-11-21"})
    rows = sb_rest("GET", "channel_stats?select=day,subscribers,watch_hours&order=day.asc")
    if not rows:
        return
    last = rows[-1]
    today = datetime.date.fromisoformat(last["day"])
    base = next((r for r in reversed(rows) if datetime.date.fromisoformat(r["day"]) <= today - datetime.timedelta(days=7)),
                rows[0])
    span = max(1, (today - datetime.date.fromisoformat(base["day"])).days)
    hours, base_hours = last.get("watch_hours") or 0, base.get("watch_hours") or 0
    rate_s, rate_h = (last["subscribers"] - base["subscribers"]) / span, (hours - base_hours) / span
    days_left = max(1, (datetime.date.fromisoformat(goals["deadline"]) - today).days)
    proj_s, proj_h = last["subscribers"] + rate_s * days_left, hours + rate_h * days_left
    ratio_s, ratio_h = proj_s / goals["subscribers"], proj_h / goals["watch_hours"]
    mode = "watch" if ratio_h < ratio_s else "reach"
    views = {}
    if goals.get("shorts_views"):  # Level 1 via Shorts: 3M Shorts views in 90 days + 500 subs -> always 'reach'
        shorts, page = [], 0
        while True:
            rows_ = sb_rest("GET", f"insights?select=views,created_at&kind=eq.short&created_at=gte.{days_ago(90)}"
                                   f"&order=created_at.asc&limit=1000&offset={page * 1000}")
            shorts += rows_
            if len(rows_) < 1000:
                break
            page += 1
        total = sum(r["views"] or 0 for r in shorts)
        week = sum(r["views"] or 0 for r in shorts if r["created_at"] >= days_ago(7))
        rate_v, proj_v = week / 7, total + week / 7 * days_left
        ratio_h, mode = proj_v / goals["shorts_views"], "reach"
        views = {"shorts_views": total, "need_views_per_day": round(max(0, goals["shorts_views"] - total) / days_left),
                 "rate_views_per_day": round(rate_v), "projected_views": round(proj_v)}
    status = {
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(), "days_left": days_left, "mode": mode,
        "subscribers": last["subscribers"], "watch_hours": hours,
        "need_subs_per_day": round(max(0, goals["subscribers"] - last["subscribers"]) / days_left, 1),
        "need_hours_per_day": round(max(0, goals["watch_hours"] - hours) / days_left, 1),
        "rate_subs_per_day": round(rate_s, 1), "rate_hours_per_day": round(rate_h, 1),
        "projected_subs": round(proj_s), "projected_hours": round(proj_h, 1),
        "on_track": ratio_s >= 1 and ratio_h >= 1, **views}
    sb_rest("PATCH", "settings?key=eq.goal_status", json={"value": status})
    log(f"goals: {last['subscribers']}/{goals['subscribers']} subs, {hours}/{goals['watch_hours']} h"
        + (f", {views['shorts_views']}/{goals['shorts_views']} Shorts views" if views else "") + "; need "
        f"+{status['need_subs_per_day']} subs and +{status['need_hours_per_day']} h per day; strategy: {mode}")


def retention_block():
    notes = get_setting("retention_notes", "") or ""
    return f"RETENTION DATA FROM THIS CHANNEL (write to fix these weak spots): {notes}" if notes else ""


def goal_focus():
    """One line for the story picker: what today's strategy needs."""
    st = get_setting("goal_status", {}) or {}
    if st.get("mode") == "watch":
        return ("TODAY'S CHANNEL GOAL: more watch time. Prefer stories with real depth that hold attention for minutes "
                "(big launches, major changes people want explained).")
    return ("TODAY'S CHANNEL GOAL: more subscribers and reach. Prefer the most broadly appealing, surprising and shareable "
            "stories (huge brands, things everyone uses, 'wait, really?' moments).")


def retention_lessons(ya, rows):
    """Where viewers leave: audience retention curves of recent videos -> short lessons fed to the script writer."""
    curves = {"short": [], "long": []}
    for r in rows[:12]:
        try:
            pts = ya.reports().query(ids="channel==MINE", startDate="2020-01-01", endDate=str(datetime.date.today()),
                                     metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio",
                                     filters=f"video=={r['youtube_id']}").execute().get("rows", [])
        except Exception:
            continue
        if len(pts) >= 10:
            curves[r["kind"] if r["kind"] in curves else "long"].append(pts)
    notes = []
    for kind, cs in curves.items():
        if not cs:
            continue
        at = lambda c, x: min(c, key=lambda p: abs(p[0] - x))[1]
        avg = lambda x: sum(at(c, x) for c in cs) / len(cs)
        drops = []
        for c in cs:
            d = max(range(1, len(c)), key=lambda i: c[i - 1][1] - c[i][1])
            drops.append(c[d][0])
        worst = sum(drops) / len(drops)
        notes.append(f"{kind.title()} videos ({len(cs)} measured): still watching at 10% = {avg(0.1):.0%}, at 50% = "
                     f"{avg(0.5):.0%}, at 90% = {avg(0.9):.0%}; the biggest drop is usually around {worst:.0%} of the video.")
    if notes:
        notes.append("Fix: make the first 2 seconds stronger, put a new surprising fact right before the usual drop "
                     "point, and keep every sentence moving the story forward.")
        sb_rest("PATCH", "settings?key=eq.retention_notes", json={"value": " ".join(notes)})
        log("retention lessons: " + " | ".join(notes[:-1]))


def optimize_titles(limit=3):
    """Second chance for weak videos: 2-7 days old, under 40% of the typical (median) views for its language and
    format over 30 days -> one new title from fresh search phrases. Each video is re-titled at most once."""
    global LANG
    current = LANG
    base = sb_rest("GET", f"insights?select=lang,kind,views&created_at=gte.{days_ago(30)}&created_at=lt.{days_ago(2)}")
    median = {}
    for key in {(r["lang"], r["kind"]) for r in base}:
        v = sorted(r["views"] for r in base if (r["lang"], r["kind"]) == key)
        if len(v) >= 5:
            median[key] = v[len(v) // 2]
    rows = sb_rest("GET", f"insights?select=youtube_id,lang,kind,topic,title,views&retitled=is.null&health=is.null"
                          f"&created_at=gte.{days_ago(7)}&created_at=lt.{days_ago(2)}&order=views.asc")
    weak = [r for r in rows if (r["lang"], r["kind"]) in median and r["views"] < 0.4 * median[(r["lang"], r["kind"])]]
    yt = youtube_client()
    for r in weak[:limit]:
        try:
            LANG = r["lang"] or "en"
            kw = keyword_research(r["topic"] or r["title"])
            new = llm_json(f"""This YouTube {r['kind']} video gets far fewer views than usual. Write ONE better title.
Current title: {r['title']}
Topic: {r['topic']}
YOUTUBE SEARCH SUGGESTIONS: {', '.join(kw) or '(none)'}
{SEO_RULES}
{lang_rules()}
The new title must be clearly different, honest (same story, no new claims), keyword first, max {55 if r['kind'] == 'short' else 70}
characters, no hashtags. Return JSON only: {{"title": "..."}}""", required=("title",))["title"].strip().strip('"')
            if not new or new.lower() == r["title"].lower():
                continue
            snip = yt.videos().list(part="snippet", id=r["youtube_id"]).execute()["items"][0]["snippet"]
            body = {k: snip[k] for k in ("description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
                    if k in snip}
            yt.videos().update(part="snippet", body={"id": r["youtube_id"], "snippet": {**body, "title": new[:100]}}).execute()
            sb_rest("PATCH", f"insights?youtube_id=eq.{r['youtube_id']}", json={"retitled": r["title"], "title": new[:100]})
            sb_rest("PATCH", f"videos?youtube_id=eq.{r['youtube_id']}", json={"title": new[:100]})
            log(f"re-titled ({r['views']} views): '{r['title']}' -> '{new}'")
        except Exception as e:
            log(f"re-title failed for {r['youtube_id']}: {str(e)[:120]}")
    LANG = current
    if not weak:
        log("titles: no weak videos to re-title")


def channel_health():
    """Any video YouTube rejected or removed in the last 14 days = pause auto-publishing (upload as private)
    until it clears, so one problem cannot snowball into strikes."""
    global SAFETY_PAUSE
    # 'missing' = deleted (usually by hand) - not a strike signal; rejections count for 14 days from when they happened
    bad = sb_rest("GET", f"insights?select=youtube_id,title,health&health=not.is.null&health=neq.missing"
                         f"&health_at=gte.{days_ago(14)}")
    SAFETY_PAUSE = bool(bad) and os.environ.get("SAFETY_PAUSE_OFF") != "1"
    if bad:
        log(f"SAFETY: {len(bad)} video(s) rejected/removed recently -> new uploads stay private: "
            + "; ".join(f"{b['youtube_id']} {b['health']}" for b in bad[:5]))
    else:
        log("SAFETY: channel healthy")


def views_per_hour(r):
    """Early, fair signal: views divided by hours online (YouTube Analytics lags ~2 days; this works after hours)."""
    age = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
    return r["views"] / max(1.0, age)


def scored_videos(lang=None, days=30, min_hours=6):
    """Recent videos (online >= min_hours) ranked by views per hour, with % watched when known."""
    q = (f"insights?select=youtube_id,kind,lang,title,topic,story,variant,format,followup_of,views,likes,avg_view_pct,views_24h,created_at&created_at=gte.{days_ago(days)}"
         f"&created_at=lt.{(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=min_hours)).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if lang:
        q += f"&lang=eq.{lang}"
    rows = sb_rest("GET", q)
    for r in rows:
        r["vph"] = round(views_per_hour(r), 2)
    return sorted(rows, key=lambda r: -r["vph"])


def performance_block():
    """What has worked on this channel for this language: fed to the story picker so it learns over time."""
    if not sb_on():
        return ""
    rows = scored_videos(LANG)
    if len(rows) < 4:
        return ""
    fmt = lambda r: (f"- [{r['kind']}] {r['title']} - {r['vph']} views/hour, {r['views']} views"
                     + (f", {r['avg_view_pct']:.0f}% watched" if r.get("avg_view_pct") is not None else ""))
    return ("CHANNEL PERFORMANCE, ranked by views per hour (pick more stories like the winners, fewer like the losers):\n"
            "Best:\n" + "\n".join(fmt(r) for r in rows[:8])
            + ("\nWorst:\n" + "\n".join(fmt(r) for r in rows[max(8, len(rows) - 5):]) if len(rows) > 8 else ""))


_MARKET = {}


def market_block():
    """What is winning on ALL of YouTube right now in tech for this audience (1 quota unit, cached per run)."""
    if LANG not in _MARKET:
        try:
            items = youtube_client().videos().list(part="snippet,statistics", chart="mostPopular", regionCode=L()["geo"],
                                                   videoCategoryId="28", maxResults=15).execute().get("items", [])
            _MARKET[LANG] = [f"- {v['snippet']['title']} ({int(v['statistics'].get('viewCount', 0)):,} views)" for v in items]
        except Exception:
            _MARKET[LANG] = []
    if not _MARKET[LANG]:
        return ""
    return ("TOP TECH VIDEOS ON YOUTUBE RIGHT NOW in this market (learn their title style, hooks and topics; never copy):\n"
            + "\n".join(_MARKET[LANG]))


def learned_block():
    lr = get_setting("learned_rules", {}) or {}
    rules = lr.get("rules") or []
    # facts viewers corrected (from comments): never repeat those mistakes
    rules += [x["text"] for x in (get_setting("comment_lessons", []) or [])[-8:] if isinstance(x, dict)]
    return ("LESSONS THIS CHANNEL HAS LEARNED (follow them):\n" + "\n".join(f"- {x}" for x in rules)) if rules else ""


def viewer_feedback():
    """What viewers said in the last 14 days, per format: fed to the daily learning so comments shape the videos."""
    try:
        rows = sb_rest("GET", f"comments?select=video_id,type,sentiment,text&handled_at=gte.{days_ago(14)}")
    except Exception:
        return ""
    if not rows:
        return ""
    fmt = {r["youtube_id"]: r.get("format") or r.get("kind") for r in sb_rest("GET", f"insights?select=youtube_id,format,kind"
                                                                             f"&created_at=gte.{days_ago(30)}")}
    counts = {}
    for r in rows:
        key = f"{fmt.get(r['video_id'], '?')}:{r['type']}"
        counts[key] = counts.get(key, 0) + 1
    critic = [r["text"][:120] for r in rows if r["type"] in ("criticism", "ai_callout", "fake", "correction")][:12]
    return ("VIEWER COMMENTS (last 14 days), format:type -> count: " + json.dumps(counts) + "\n"
            "Recent critical comments: " + json.dumps(critic, ensure_ascii=False))


def learn_rules():
    """Once a day: compare the best and worst videos (views/hour, % watched) plus what wins on YouTube now, and write
    concrete rules every script and story pick then follows. This is the fast learning loop."""
    lr = get_setting("learned_rules", {}) or {}
    today = str(datetime.date.today())
    if lr.get("date") == today:
        return
    rows = scored_videos(days=21)
    if len(rows) < 6:
        log("learning: not enough videos yet")
        return
    global LANG
    current, market = LANG, []
    for lang in LANGS:
        LANG = lang
        market.append(f"[{lang}] " + market_block())
    LANG = current
    line = lambda r: (f"[{r['lang']} {r['kind']}{'/' + r['variant'] if r.get('variant') else ''}"
                      f"{'/' + r['format'] if r.get('format') else ''}] {r['title']} | "
                      f"{r['vph']} views/h | {r['views']} views"
                      + (f" | {r['avg_view_pct']:.0f}% watched" if r.get("avg_view_pct") is not None else ""))
    res = llm_json(f"""You are the growth analyst of a YouTube tech news channel ({CHANNEL()}).
Our videos, best first (views per hour since upload is the main score; % watched = retention):
{chr(10).join(line(r) for r in rows[:40])}

{chr(10).join(market)}

{viewer_feedback()}

Find what separates our winners from our losers (topics, brands, title wording, length/format, language) and what
the market rewards right now. If viewers complain about something repeatedly (e.g. "AI slop", repeated topics,
wrong facts, the voice), include a rule that fixes it. Write 6-8 SHORT, concrete, actionable rules for choosing stories and writing titles and
scripts (e.g. "Titles naming Apple or Samsung get ~3x views/hour: put the brand first"). Only rules the data supports.
The mix of long videos and Shorts is fixed by the channel goals (long videos earn the watch hours needed for
monetization): never tell us to stop or reduce a format - instead give rules that make weak formats perform better.
Return JSON only: {{"summary": "one sentence: the biggest lesson", "rules": ["...", "..."]}}""", required=("rules",))
    value = {"date": today, "summary": res.get("summary", ""), "rules": [str(x) for x in res["rules"][:8]]}
    sb_rest("PATCH", "settings?key=eq.learned_rules", json={"value": value})
    log("learning: " + value["summary"])


def cleanup():
    cutoff = days_ago(KEEP_DAYS)
    old = sb_rest("GET", f"videos?select=id,preview_path,thumb_path&created_at=lt.{cutoff}")
    sb_remove([p for r in old for p in (r["preview_path"], r["thumb_path"]) if p])
    if old:
        sb_rest("DELETE", f"videos?created_at=lt.{cutoff}")
    sb_rest("DELETE", f"insights?created_at=lt.{days_ago(180)}")
    log(f"cleanup: removed {len(old)} records older than {KEEP_DAYS} days (YouTube videos are kept)")
    storage_cap()


STORAGE_CAP_MB, STORAGE_TARGET_MB = 800, 650  # free plan has 1 GB of file storage


def storage_files():
    """{path: bytes} of every file in the bucket (paths are day/video/file.ext)."""
    def ls(prefix):
        r = requests.post(f"{os.environ['SUPABASE_URL'].rstrip('/')}/storage/v1/object/list/{BUCKET}",
                          headers=sb_headers({"Content-Type": "application/json"}), timeout=60,
                          json={"prefix": prefix, "limit": 1000})
        r.raise_for_status()
        return r.json()
    files = {}
    def walk(prefix, depth):
        for x in ls(prefix):
            path = f"{prefix}/{x['name']}" if prefix else x["name"]
            if x.get("id") is None and depth < 3:  # folder
                walk(path, depth + 1)
            elif x.get("metadata"):
                files[path] = int(x["metadata"].get("size") or 0)
    walk("", 0)
    return files


def storage_cap():
    """Hard guard: if app previews ever exceed STORAGE_CAP_MB (e.g. many long weekly videos), delete the oldest
    previews until under STORAGE_TARGET_MB. Records, thumbnails and the YouTube videos themselves stay."""
    files = storage_files()
    total = sum(files.values()) / 1048576
    if total <= STORAGE_CAP_MB:
        log(f"storage: {total:.0f} MB of 1 GB used")
        return
    rows = sb_rest("GET", "videos?select=id,preview_path,thumb_path&order=created_at.asc")
    known = {p for r in rows for p in (r["preview_path"], r["thumb_path"]) if p}
    orphans = [p for p in files if p not in known]
    if orphans:  # files left behind by failed writes or deleted records
        sb_remove(orphans)
        total -= sum(files[p] for p in orphans) / 1048576
    for r in [r for r in rows if r["preview_path"]]:
        if total <= STORAGE_TARGET_MB:
            break
        sb_remove([r["preview_path"]])
        sb_rest("PATCH", f"videos?id=eq.{r['id']}", json={"preview_path": None})
        total -= files.get(r["preview_path"], 0) / 1048576
    log(f"storage: over {STORAGE_CAP_MB} MB, oldest previews removed -> {total:.0f} MB")


# ---------- main ----------
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "video"


UPLOAD_CAP = 20  # per Google project per rolling day; an upload costs ~100 quota units since Dec 2025 (was 1,600)


CHANNEL_UPLOAD_CAP = 10  # YouTube refused the 11th upload in 24 h ("exceeded the number of videos they may upload")


def channel_uploads_24h():
    """Uploads to the channel in the last 24 h, all languages (YouTube's daily upload limit is per channel)."""
    if not sb_on():
        return 0
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return len(sb_rest("GET", f"videos?select=id&youtube_id=not.is.null&created_at=gte.{since}"))


JUNK_TOKEN = re.compile(r"(?<![\w-])[a-z]{1,4}\d{3,}[a-z]*(?![\w-])")  # e.g. "dw065e" an LLM leaked into a title


def tidy_title(title, topic=""):
    """Drop stray ID-like tokens (lowercase letters + 3+ digits) the model sometimes leaks into titles."""
    clean = re.sub(r"\s{2,}", " ", JUNK_TOKEN.sub("", title)).strip(" -:|")
    return clean or topic or title


def upload_room(reserve=0):
    """Free uploads in YouTube's rolling 24 h channel limit (setting 'upload_cap' can raise it as the channel grows),
    minus `reserve` kept back for higher-priority videos (long videos, viral formats, breaking news, part 2s)."""
    cap = int(get_setting("upload_cap", CHANNEL_UPLOAD_CAP) or CHANNEL_UPLOAD_CAP)
    # what YouTube allows (cap) vs what we choose to post (target, set by volume_check): never more than either
    cap = min(cap, int(get_setting("upload_target", UPLOAD_TARGET) or UPLOAD_TARGET))
    return cap - channel_uploads_24h() - reserve


UPLOAD_TARGET = 15      # first step of daily uploads; volume_check() moves it up to UPLOAD_MAX when views hold
UPLOAD_MAX = 20
RAMP_PER_DAY = 3        # raise the cap by at most this much per day, so growth looks natural to YouTube


def probe_due():
    """May this run try one upload above the cap? Only while below the target, at most RAMP_PER_DAY raises a day,
    and never again on a day YouTube refused one - fully automatic, no one has to watch for it."""
    cap = int(get_setting("upload_cap", CHANNEL_UPLOAD_CAP) or CHANNEL_UPLOAD_CAP)
    if cap >= int(get_setting("upload_target", UPLOAD_TARGET) or UPLOAD_TARGET):
        return False
    if (get_setting("volume", {}) or {}).get("braked") == str(datetime.date.today()):
        return False  # the automatic brake fired today: no growth
    st = get_setting("upload_probe", {}) or {}
    if st.get("date") != str(datetime.date.today()):
        return True
    return not st.get("refused") and st.get("raised", 0) < RAMP_PER_DAY


def note_upload_limit(count, ok):
    """Learn the real limit: a success above the cap raises 'upload_cap'; a refusal stops probing for today."""
    if not sb_on():
        return
    cap = int(get_setting("upload_cap", CHANNEL_UPLOAD_CAP) or CHANNEL_UPLOAD_CAP)
    upsert = lambda key, value: sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates",
                                        json={"key": key, "value": value})
    st = get_setting("upload_probe", {}) or {}
    today = str(datetime.date.today())
    if st.get("date") != today:
        st = {"date": today, "raised": 0}
    if ok and count > cap:
        upsert("upload_cap", count)
        upsert("upload_probe", {**st, "raised": st.get("raised", 0) + 1})
        log(f"upload limit: YouTube accepted upload #{count} in 24 h -> daily cap raised to {count}")
    elif not ok:
        upsert("upload_probe", {**st, "refused": True, "limit_at": count})
        if count < cap:  # the limit is lower than we thought
            upsert("upload_cap", max(1, count))
        log(f"upload limit: YouTube refused upload #{count + 1} in 24 h (limit still {count})")


def volume_check():
    """Once a day: does the extra volume still pay? Compares the median views each Short had at 24 h old (fair:
    same age) for Shorts from the last 4 days vs the 7 days before. Falls >25% -> brake: target -2 (min 10), no
    growth today. Holds or improves (>=100%) at the target -> target +2 (max UPLOAD_MAX), at most once a week.
    (The old views/hour comparison favoured newer videos and raised volume while real reach per video fell.)"""
    if not sb_on():
        return
    today = str(datetime.date.today())
    st = get_setting("volume", {}) or {}
    if st.get("date") == today:
        return
    upsert = lambda key, value: sb_rest("POST", "settings?on_conflict=key", prefer="resolution=merge-duplicates",
                                        json={"key": key, "value": value})
    rows = [r for r in scored_videos(days=11, min_hours=24) if r["kind"] == "short" and r.get("views_24h") is not None]
    cut = days_ago(4)
    recent = sorted(r["views_24h"] for r in rows if r["created_at"] >= cut)
    base = sorted(r["views_24h"] for r in rows if r["created_at"] < cut)
    st = {k: v for k, v in st.items() if k in ("target_raised",)} | {"date": today}
    if len(recent) < 6 or len(base) < 6:
        upsert("volume", {**st, "note": f"collecting fair 24-hour numbers ({len(recent)} new / {len(base)} older Shorts"
                                        " so far); volume stays as it is"})
        return
    med = lambda v: v[len(v) // 2]
    ratio = round(med(recent) / max(med(base), 1), 2)
    target = int(get_setting("upload_target", UPLOAD_TARGET) or UPLOAD_TARGET)
    cap = int(get_setting("upload_cap", CHANNEL_UPLOAD_CAP) or CHANNEL_UPLOAD_CAP)
    st.update(ratio=ratio, note=f"views per Short at 24 h: {med(recent)} now vs {med(base)} before ({ratio:.0%})")
    if ratio < 0.75:
        upsert("upload_target", max(10, target - 2))
        st.update(braked=today, note=st["note"] + f" -> brake: target {target} -> {max(10, target - 2)}")
    elif ratio >= 1.0 and cap >= target and target < UPLOAD_MAX and st.get("target_raised", "") <= days_ago(7)[:10]:
        upsert("upload_target", min(UPLOAD_MAX, target + 2))
        st.update(target_raised=today, note=st["note"] + f" -> target {target} -> {min(UPLOAD_MAX, target + 2)}")
    upsert("volume", st)
    log(f"volume check: {st['note']}")


def uploads_24h(lang):
    """Uploads in the last 24 h for this language = this language's Google project usage (EN -> 1, HI -> 2)."""
    if not sb_on():
        return 0
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return len(sb_rest("GET", f"videos?select=id&youtube_id=not.is.null&lang=eq.{lang}&created_at=gte.{since}"))


def plan_breaking(trends, niche, used):
    """Only when something BIG broke in the last few hours (several outlets, big brand, huge search interest)
    and the channel has not covered it: one fast Short. Otherwise nothing."""
    pick = llm_json(f"""You watch tech news for a YouTube channel ({niche}). Trending items right now:
{trends_text(trends)}

Already covered (do not repeat): {json.dumps(used[-40:], ensure_ascii=False)}
{SAFE_TOPICS}

Is there BREAKING tech news from roughly the last 6 hours that is genuinely big: a major launch, outage, acquisition,
leak or announcement from a huge brand, reported by several outlets, that millions will search for today?
Be strict: most of the time the answer is no.
Return JSON only: {{"breaking": false}} or
{{"breaking": true, "topic": "short name", "search_query": "3-6 word news search query", "angle": "why it matters now"}}""",
                    required=("breaking",))
    if not pick.get("breaking") or not pick.get("topic"):
        log("breaking: nothing big enough right now")
        return []
    ctx = story_context(pick.get("search_query") or pick["topic"])
    if len({c["source"] for c in ctx if c["source"]}) < 3:  # not confirmed by enough different outlets yet
        log(f"breaking: '{pick['topic']}' has fewer than 3 news outlets, skipping")
        return []
    if story_count(pick, recent_stories()) >= STORY_MAX:
        log(f"breaking: story of '{pick['topic']}' already has {STORY_MAX}+ videos in 48 h, skipping")
        return []
    log(f"breaking: '{pick['topic']}' ({len(ctx)} sources)")
    kw = keyword_research(pick.get("search_query") or pick["topic"])
    meta = write_checked(lambda note: write_short({**pick, "angle": pick.get("angle", "") + ". This is BREAKING news from "
                                                   "the last few hours: open with what just happened." + note}, ctx, kw,
                                                  "fast", "hot_take"), ctx, "short")
    meta.update({"variant": "breaking", "sources": sorted({c["source"] for c in ctx if c["source"]})[:8],
                 "search_suggestions": kw, "story": story_slug(pick)})
    return [("short", meta)]


def run_breaking(args):
    global LANG
    for lang in LANGS:
        LANG = lang
        done = uploads_24h(lang)
        if done >= UPLOAD_CAP:
            log(f"breaking [{lang}]: daily upload room used ({done}/{UPLOAD_CAP}), skipping")
            continue
        try:
            run_videos(args, plan_breaking, "breaking news Short")
        except Exception as e:
            log(f"breaking [{lang}] failed: {str(e)[:200]}")


RUN_STARTED = datetime.datetime.now(datetime.timezone.utc)


def slot_status(status, reason=None, videos=None, note=""):
    """What this slot did and why (running / uploaded / skipped / failed), shown in the app's 'Today' panel.
    Runs without a clock slot (part 2s, app 'Run now') are named after their start time."""
    if not sb_on():
        return
    slot = os.environ.get("CLOCK_SLOT") or f"{RUN_STARTED:%Y-%m-%d %H:%M} {note or 'extra run'}"
    run = os.environ.get("GITHUB_RUN_ID")
    try:
        sb_rest("POST", "slot_log?on_conflict=key", prefer="resolution=merge-duplicates", json={
            "key": f"{slot}|{LANG}", "slot": slot, "lang": LANG, "status": status, "reason": (reason or "")[:300],
            "videos": videos or [], "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "run_url": f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}"
                       f"/actions/runs/{run}" if run and os.environ.get("GITHUB_REPOSITORY") else None})
    except Exception as e:
        log(f"slot log not saved ({str(e)[:100]})")


def run_videos(args, planner, note):
    """Plan -> make -> upload -> record. `planner(trends, niche, used)` returns [(kind, meta)]; [] = skip."""
    try:
        return _run_videos(args, planner, note)
    except BaseException as e:  # crash or SystemExit(1): record why, then fail as before so the clock retries
        if not isinstance(e, SystemExit) or e.code not in (0, None):
            slot_status("failed", f"{type(e).__name__}: {e}" if str(e) not in ("", "1") else
                        "planning failed (AI services busy or no usable story); the clock retries", note=note)
        raise


def _run_videos(args, planner, note):
    global PROJECT
    PROJECT = 2 if LANG == "hi" and project2_available() else 1  # Hindi uploads use the second project's quota
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    used = used_topics()
    niche = os.environ.get("NICHE", "technology and AI")
    slot_status("running", f"started: {note}", note=note)
    log(f"Fetching trends ({L()['name']}, {L()['geo']})")
    trends = fetch_trends(L()["geo"])
    if not trends:
        raise RuntimeError("No trends from any source")
    if not args.no_upload:
        try:
            volume_check()
        except Exception as e:
            log(f"volume check skipped ({str(e)[:120]})")
        # plain news Short slots keep 1 upload free for long videos, viral formats, breaking news and part 2s
        plain_short = note.endswith("Shorts") and not getattr(args, "long", 0)
        want = (getattr(args, "long", 0) or 0) + (getattr(args, "shorts", 0) or 0) if note.endswith("Shorts") else 1
        room = upload_room(reserve=1 if plain_short else 0)
        # every slot may probe (until YouTube refuses one today): after the channel's verification the real limit is
        # likely higher, and each accepted upload above the cap raises it - so all slots run again as soon as it is
        if room < max(1, want) and probe_due():
            log("upload limit probe: trying one upload above the current cap (YouTube may have raised the limit)")
            # one more upload than the cap allows; the trim below keeps the long video first (it used to turn a
            # long + Short slot into a Short only, which lost the day's long video)
            room = max(0, room) + 1
        if room < 1:  # with 1 upload of room a long + Short slot still makes its long video (trim below)
            used24 = channel_uploads_24h()
            log(f"skipped: YouTube's daily channel upload limit is nearly used ({used24} uploads in "
                f"24 h); this slot is left for higher-priority videos")
            slot_status("skipped", f"daily upload limit reached ({used24} uploads in the last 24 h)", note=note)
            return 0
        if want > room:  # e.g. long + Short but only 1 upload left: make the long video only
            args.shorts = max(0, room - (getattr(args, "long", 0) or 0))
    log(f"Planning: {note} (uploads via Google Cloud project {PROJECT})")
    jobs = planner(trends, niche, used)
    if not jobs:
        log("nothing to make this run")
        slot_status("skipped", "no big breaking news right now" if "breaking" in note else
                    "no suitable story found (or all scripts failed the fact-check)", note=note)
        return 0
    run_id = None
    if sb_on():
        run_id = sb_rest("POST", "runs", json={"lang": LANG, "note": note})[0]["id"]
    counts = {"made": 0, "published": 0, "held": 0, "failed": 0}

    def finish_run(note=None):
        if run_id:
            sb_rest("PATCH", f"runs?id=eq.{run_id}", json={
                **counts, "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                **({"note": note} if note else {})})

    run_dir = OUT / f"{datetime.datetime.now():%Y-%m-%d_%H%M}_{LANG}"
    run_dir.mkdir(parents=True, exist_ok=True)


    failures, done, errors = 0, [], []
    for i, (kind, meta) in enumerate(jobs):
        try:
            work = run_dir / f"{i}_{kind}_{slugify(meta['topic'])}"
            work.mkdir(parents=True, exist_ok=True)
            (work / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            meta["title"] = tidy_title(meta["title"], meta["topic"])
            log(f"=== {kind}: {meta['topic']} | {meta['title']}")
            host = pick_voice(i)
            meta["host"] = host
            r = make_video(work, kind, meta, host)
            meta["music_credit"] = r["music_credit"]
            if kind == "short":
                meta["related_url"] = latest_long_url()
            desc = description(meta, kind == "short", meta["topic"], r["credits"], r["chapters"])
            (work / "description.txt").write_text(desc, encoding="utf-8")
            thumb = make_thumbnail(work, meta.get("thumbnail_text") or meta["topic"], r["duration"] * 0.25,
                                   r["first_photo"]) if kind == "long" else None
            log(f"[{kind}] rendered {r['video']}")
            entry = {"date": str(datetime.date.today()), "kind": kind, "topic": meta["topic"],
                     "title": meta["title"], "video": str(r["video"])}
            vid = None
            if not args.no_upload:
                privacy = privacy_for(meta)
                before = channel_uploads_24h()
                try:
                    vid = upload(r["video"], meta["title"], desc, clean_tags(meta), kind == "short", privacy)
                except Exception as e:
                    if "exceeded the number of videos" in str(e):
                        note_upload_limit(before, ok=False)
                    raise
                note_upload_limit(before + 1, ok=True)
                log(f"[{kind}] uploaded https://youtu.be/{vid} ({privacy}{', held by fact-check' if meta.get('hold') else ''})")
                # YouTube rejects comments on private videos; publish_pending() posts it once public.
                comment = meta.get("pinned_comment")
                if comment and meta.get("related_url") and kind == "long":
                    comment += f"\n\n{L()['text']['full_story']} {meta['related_url']}"
                series = add_to_series(vid, meta.get("story")) if privacy == "public" else None
                if comment and series:
                    comment += f"\n\n▶ {'All parts' if LANG == 'en' else 'सभी parts'}: {series}"
                after_upload(vid, thumb, comment if privacy == "public" else None)
                if kind == "long" and privacy == "public":
                    LATEST_LONG[LANG] = f"https://youtu.be/{vid}"
                add_to_playlist(vid)
                entry["youtube_id"] = vid
                done.append({"id": vid, "title": meta["title"], "kind": kind, "privacy": privacy})
            record(work, kind, meta, desc, r["duration"], vid, thumb)
            history.append(entry)
            HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
            counts["made"] += 1
            counts["held"] += 1 if meta.get("hold") else 0
            counts["published"] += 1 if vid and privacy_for(meta) == "public" else 0
        except Exception as e:  # one bad video must not stop the rest of the run
            failures += 1
            counts["failed"] += 1
            log(f"[{kind}] FAILED: {e}")
            errors.append(f"{kind}: " + ("YouTube refused: daily upload limit" if "exceeded the number of videos"
                                         in str(e) else str(e)[:150]))
    finish_run()
    if done:
        slot_status("uploaded", "; ".join(errors), done, note=note)
    elif errors:
        slot_status("failed", "; ".join(errors), note=note)
    else:
        slot_status("skipped", "made without upload", note=note)
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--long", type=int, help="number of long videos (0 or 1, default 1)")
    ap.add_argument("--shorts", type=int, help="number of Shorts (default 1)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--lang", choices=sorted(LANGS), default="en", help="video language (en or hi)")
    ap.add_argument("--upload-dir", help="upload an already-rendered video folder")
    ap.add_argument("--publish-pending", action="store_true", help="make app-approved videos public")
    ap.add_argument("--stats", action="store_true", help="refresh YouTube stats in Supabase")
    ap.add_argument("--quick-stats", action="store_true", help="refresh view counts only (cheap, for frequent runs)")
    ap.add_argument("--cleanup", action="store_true", help=f"delete Supabase records/files older than {KEEP_DAYS} days")
    ap.add_argument("--reply-comments", action="store_true", help="reply to a random share of new valid viewer comments (hourly, capped per day)")
    ap.add_argument("--process-requests", action="store_true", help="start runs requested from the app")
    ap.add_argument("--weekly", action="store_true", help="make the long video the weekly Top 10 (default: Sundays)")
    ap.add_argument("--breaking", action="store_true", help="check for big breaking news; make a Short if found")
    ap.add_argument("--followup", help="make a part-2 Short for this breakout Short (YouTube id)")
    ap.add_argument("--viral", action="store_true", help="make one viral-format Short (versus, top 3, tricks...)")
    ap.add_argument("--project", type=int, choices=(1, 2), default=1, help="with --auth: which Google Cloud project to log in")
    args = ap.parse_args()
    load_env()
    global LANG, PROJECT, SAFETY_PAUSE
    LANG = args.lang
    if args.auth:
        PROJECT = args.project
        tok = project_files(PROJECT)[0]
        tok.unlink(missing_ok=True)  # --auth always means a fresh browser login (never a failover to the other project)
        youtube_client()
        log(f"YouTube auth OK, {tok.name} saved")
        push_login_to_github(PROJECT)
        return
    if args.upload_dir:
        upload_existing(args.upload_dir)
        return
    maintenance = [f for flag, f in ((args.process_requests, process_requests),
                                     (args.publish_pending, publish_pending), (args.stats, update_stats),
                                     (args.quick_stats and not args.stats, lambda: update_stats(full=False)),
                                     (args.cleanup, cleanup), (args.reply_comments, reply_comments)) if flag]
    for f in maintenance:
        try:  # maintenance must never block making today's videos
            f()
        except Exception as e:
            log(f"{f.__name__} failed: {str(e)[:200]}")
    if (args.breaking or args.viral or args.followup or args.long or args.shorts) and not args.no_upload:
        try:
            channel_health()
        except Exception as e:  # unknown health = upload as private, never risk a strike
            SAFETY_PAUSE = True
            log(f"SAFETY: health check failed ({str(e)[:120]}) -> uploads stay private this run")
    if args.breaking:
        if get_setting("paused", False) is not True:
            run_breaking(args)
        return
    if maintenance and args.long is None and args.shorts is None and not (args.viral or args.followup):
        return
    args.long = 1 if args.long is None else args.long
    args.shorts = 1 if args.shorts is None else args.shorts
    if get_setting("paused", False) is True:
        log("PAUSED from the app (Controls > Pause automation): no new videos this run")
        return
    if args.viral:
        failures = run_videos(args, plan_viral, "viral-format Short")
        if failures:
            raise SystemExit(f"{failures} video(s) failed")
        return
    if args.followup:
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", args.followup):
            raise SystemExit("bad --followup id")
        failures = run_videos(args, plan_followup(args.followup), "follow-up Short")
        if failures:
            raise SystemExit(f"{failures} video(s) failed")
        return
    goal = get_setting("goal_status", {}) or {}
    if os.environ.get("CLOCK_SLOT") and goal.get("mode") == "watch" and (args.long, args.shorts) == (0, 1):
        args.long, args.shorts = 1, 0  # watch hours behind target: the single-Short slot becomes a long video
        log("goal strategy 'watch': this run makes a long video instead of a Short")

    weekly = args.weekly or datetime.datetime.now(datetime.timezone.utc).weekday() == 6  # Sunday = weekly Top 10
    failures = run_videos(args, lambda tr, niche, used: plan_videos(tr, niche, used, args.long, args.shorts, weekly=weekly),
                          f"{args.long} long + {args.shorts} Shorts")
    if failures:
        raise SystemExit(f"{failures} video(s) failed")


if __name__ == "__main__":
    main()
