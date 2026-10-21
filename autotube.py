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
    "long": dict(w=1920, h=1080, orientation="landscape", font=104, align=2, margin_v=90, per_line=5, clip_secs=6),
    "short": dict(w=1080, h=1920, orientation="portrait", font=150, align=5, margin_v=0, per_line=3, clip_secs=4),  # visual change every ~4s holds Shorts viewers
}
FONT = "Anton"  # bundled in fonts/ (OFL) so captions look the same on Windows and the Linux cloud runner


def subs_filter(work, ass):
    fontsdir = os.path.relpath(ROOT / "fonts", work).replace("\\", "/")
    return f"subtitles={ass}:fontsdir={fontsdir}"
LENGTHS = {"long": (680, 820), "short": (110, 140)}

# Each language = its own audience: trends region, news edition, voices, lip-sync mode, YouTube language, UI text.
LANGS = {
    "en": {"name": "English", "geo": "US", "news": "hl=en-US&gl=US&ceid=US:en", "suggest_hl": "en",
           "voices": {"male": "en-US-AndrewMultilingualNeural", "female": "en-US-AvaMultilingualNeural"},
           "lipsync": "pocketSphinx",
           "ui": {"news": "TECH NEWS", "fact": "FACT", "subscribe": "SUBSCRIBE", "like": "LIKE", "comment": "COMMENT",
                  "share": "SHARE"},
           "follow_line": "Follow TechPulse for daily tech news.",
           "text": {"in_video": "In this video:", "sources": "Sources",
                    "subscribe": "Subscribe to {c} for daily tech & AI news in minutes.",
                    "more_short": "Watch the full stories on our channel.", "more_long": "Quick versions in our Shorts.",
                    "ai": "Voice and visuals are AI-assisted. Facts are based on the sources listed above.",
                    "credits": "Image credits (Wikimedia Commons / stock):"},
           "style": "Natural spoken American English."},
    "hi": {"name": "Hindi", "geo": "IN", "news": "hl=en-IN&gl=IN&ceid=IN:en", "suggest_hl": "hi",
           "voices": {"male": "hi-IN-MadhurNeural", "female": "hi-IN-SwaraNeural"},
           "lipsync": "phonetic",  # Rhubarb's English recognizer does not know Hindi; phonetic mode is language-neutral
           "ui": {"news": "टेक न्यूज़", "fact": "तथ्य", "subscribe": "SUBSCRIBE", "like": "लाइक", "comment": "कमेंट",
                  "share": "शेयर"},
           "follow_line": "ऐसी ही tech news के लिए TechPulse को follow करें।",
           "text": {"in_video": "इस वीडियो में:", "sources": "Sources",
                    "subscribe": "रोज़ की Tech और AI news के लिए {c} को Subscribe करें।",
                    "more_short": "पूरी कहानी हमारे channel पर देखें।", "more_long": "छोटे updates हमारे Shorts में देखें।",
                    "ai": "Voice और visuals AI की मदद से बनाए गए हैं। Facts ऊपर दिए गए sources पर आधारित हैं।",
                    "credits": "Image credits (Wikimedia Commons / stock):"},
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
- summary: 2-3 plain sentences with natural related search phrases.
- tags: 15-20 tags; mix exact search phrases from the suggestions, the topic, company/product names and broad
  tags like 'tech news'. No '#', no '<' or '>'.
- hashtags: exactly 3, CamelCase, no spaces, most relevant first (e.g. "TechNews", "iPhone", "Apple")."""


def lang_rules():
    if LANG == "hi":
        return ("LANGUAGE: Write the spoken script, description_hook, summary, key_points, facts, pinned_comment and section"
                f" headings in Hindi. {L()['style']}\n"
                "Title: Hinglish - start with the English search keyword Indians actually type (e.g. 'iPhone 17 Launch:'),"
                " then a short Hindi hook in Devanagari. thumbnail_text and hook_text: short, English letters or Hinglish.\n"
                "Tags: mix English search phrases, Hinglish phrases and Hindi words (e.g. 'tech news hindi', 'AI news in hindi').")
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


def topic_rules(niche, used):
    audience = ("Audience: Indian viewers. Prefer stories Indians care about (India launches, prices in India, Jio/Airtel,"
                " Indian startups, global big-tech news that affects India)." if LANG == "hi" else "Audience: US/global English viewers.")
    focus = DAY_FOCUS[LANG][datetime.date.today().toordinal() % 7]
    return (f"Channel: {CHANNEL()}, niche: {niche or 'tech'}. {audience}\n"
            f"Today's preferred theme when stories are otherwise equal: {focus}.\n"
            f"{SAFE_TOPICS}\n"
            f"Pick stories that fit the niche, are fresh today, and have the biggest audience (high searches,"
            f" points, upvotes, views; covered by several sources = bigger). Prefer stories viewers will have strong"
            f" feelings about (big brands, money, privacy, jobs, AI, new gadgets).\n"
            f"Do NOT pick these already-covered topics: {json.dumps(used, ensure_ascii=False)}")


def pick_topics(trends, niche, used, n_long, n_shorts):
    data = llm_json(f"""You run a viral tech & AI news YouTube channel. Today's trending items:
{trends_text(trends)}

{topic_rules(niche, used)}

{performance_block()}

Pick {n_long} story for a long video and {n_shorts} DIFFERENT stories for Shorts (all different from each other).
Return JSON only:
{{"long": [{{"topic": "short topic name", "search_query": "3-6 word news search query", "angle": "why viewers care"}}],
 "shorts": [{{"topic": "...", "search_query": "...", "angle": "..."}}]}}""", required=("long", "shorts"))
    return data["long"][:n_long], data["shorts"][:n_shorts]


def story_context(query, n=10):
    """Recent headlines from several outlets: the fact base for the script and the 'Sources' list."""
    try:
        items = rss_items("https://news.google.com/rss/search?q=" + requests.utils.quote(f"{query} when:3d")
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


def write_long(pick, ctx, kw):
    lo, hi = LENGTHS["long"]
    meta = llm_json(f"""Write a {lo}-{hi} word (about 4-5 minute) YouTube video script for {CHANNEL()}, a tech & AI news channel.
STORY: {pick['topic']} - angle: {pick.get('angle', '')}

{facts_block(ctx, kw)}

Structure as 6-8 sections in this order: hook (1-2 sentences), why it is trending now, background,
key details, reactions / what people are saying (attribute to outlets), what happens next,
what it means for YOU the viewer, closing (one comment question + ask to subscribe to {CHANNEL()}).
Count words carefully: total under {lo - 30} words is too short.
{RULES}
{SEO_RULES}
{lang_rules()}

Return JSON only:
{{"topic": "short topic name",
 "primary_keyword": "...",
 "title": "max 70 chars",
 "description_hook": "...",
 "summary": "...",
 "key_points": ["3-5 short bullet points of what the video covers"],
 "tags": ["..."],
 "hashtags": ["...", "...", "..."],
 "thumbnail_text": "2-4 punchy words for the thumbnail",
 "pinned_comment": "one engaging question for viewers",
 "sections": [{{"heading": "chapter title, 2-5 words",
               "fact": "on-screen fact card for this section, max 7 words, only a sourced fact or empty string",
               "text": "spoken text"}}],
 "keywords": ["12 image search terms"]}}""", required=("topic", "title", "sections", "keywords"))
    for _ in range(2):
        n = sum(len(s["text"].split()) for s in meta["sections"])
        if n >= lo * 0.92:
            break
        log(f"[long] script only {n} words, expanding")
        fixed = llm_json(f"""Expand these video script sections to {lo}-{hi} words in total. Keep headings, facts,
order, hook and ending. Add depth without inventing numbers, quotes or dates. Keep the same language and style.
{lang_rules()}

{json.dumps(meta['sections'], ensure_ascii=False)}

Return JSON only: {{"sections": [{{"heading": "...", "fact": "...", "text": "..."}}]}}""", required=("sections",))
        meta["sections"] = fixed["sections"]
    meta["script"] = " ".join(s["text"].strip() for s in meta["sections"])
    return meta


def write_short(pick, ctx, kw):
    lo, hi = LENGTHS["short"]
    meta = llm_json(f"""Write a YouTube Short script ({lo}-{hi} words, 40-50 seconds) for {CHANNEL()}, a tech & AI news channel.
STORY: {pick['topic']} - angle: {pick.get('angle', '')}

{facts_block(ctx, kw)}

Shorts rules: first sentence is the hook; one fast idea per sentence; build to the most surprising fact;
the LAST sentence must flow naturally back into the first sentence so the Short loops seamlessly
(looping replays boost Shorts). Just before that last sentence, in this order: one comment question, then exactly this
short line: "{L()['follow_line']}"
{RULES}
{SEO_RULES}
{lang_rules()}
For Shorts the title must be max 55 characters.

Return JSON only:
{{"topic": "short topic name",
 "primary_keyword": "...",
 "title": "max 55 chars",
 "hook_text": "max 6 punchy words shown on screen in the first 3 seconds",
 "description_hook": "...",
 "summary": "...",
 "tags": ["..."],
 "hashtags": ["...", "...", "..."],
 "pinned_comment": "one engaging question",
 "facts": ["2-3 on-screen fact cards, max 7 words each, only sourced facts"],
 "script": "...",
 "keywords": ["6 image search terms"]}}""", required=("topic", "title", "script", "keywords"))
    if len(meta["script"].split()) < lo * 0.9:
        log(f"[short] '{meta['topic']}' too short, expanding")
        meta["script"] = expand(meta["script"], lo, hi)
    return meta


def fact_check(meta, ctx, kind):
    """Second, strict pass: every claim must be backed by the source headlines. Unsupported sentences are softened or
    removed; if the story itself is unsupported the video is held private (auto-publish skips it)."""
    body = (json.dumps(meta["sections"], ensure_ascii=False) if kind == "long" else meta["script"])
    heads = "\n".join(f"- {c['headline']} ({c['source']}, {c['date']})" for c in ctx) or "- (none)"
    shape = '"sections": [{"heading": "...", "fact": "...", "text": "..."}]' if kind == "long" else '"script": "..."'
    res = llm_json(f"""You are a strict news fact-checker for a YouTube channel.
SOURCE HEADLINES (the only allowed facts):
{heads}

TITLE: {meta['title']}
SCRIPT:
{body}

Check every factual claim (numbers, prices, dates, names, quotes, events, specs) in the script, title and on-screen facts.
- Supported by the headlines: keep.
- Not supported: rewrite that sentence as hedged context ("reports suggest", "not confirmed yet") or remove it.
Keep everything else (language, tone, hook, length, structure) the same.
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
            meta["script"] = " ".join(s["text"].strip() for s in meta["sections"])
        elif kind == "short" and res.get("script"):
            meta["script"] = res["script"]
        if res.get("title"):
            meta["title"] = res["title"]
    meta["fact_check"] = {"verdict": v, "issues": res.get("issues", [])[:8]}
    meta["hold"] = v == "fail"
    log(f"[{kind}] fact-check: {v}" + (f" ({len(res.get('issues', []))} issues)" if res.get("issues") else ""))
    return meta


def plan_videos(trends, niche, used, n_long, n_shorts):
    longs, shorts = pick_topics(trends, niche, used, n_long, n_shorts)
    jobs = []
    for kind, picks, writer in (("long", longs, write_long), ("short", shorts, write_short)):
        for p in picks:
            try:
                query = p.get("search_query") or p["topic"]
                ctx, kw = story_context(query), keyword_research(query)
                log(f"[{kind}] '{p['topic']}': {len(ctx)} source headlines, {len(kw)} search suggestions")
                meta = fact_check(writer(p, ctx, kw), ctx, kind)
                meta["sources"] = sorted({c["source"] for c in ctx if c["source"]})[:8]
                meta["search_suggestions"] = kw
                jobs.append((kind, meta))
            except Exception as e:
                log(f"[{kind}] script failed for '{p.get('topic')}': {e}")
    return jobs


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


VOICES = {"male": "en-US-AndrewMultilingualNeural", "female": "en-US-AvaMultilingualNeural"}
CHARACTERS = {"male": "max", "female": "nova"}


def pick_voice(i):
    """Alternate male/female across videos and days, so the channel has two recurring hosts."""
    genders = [g.strip() for g in os.environ.get("HOSTS", "male,female").split(",") if g.strip() in VOICES]
    g = genders[(datetime.date.today().toordinal() + i + (1 if LANG == "hi" else 0)) % len(genders)]
    return {"gender": g, "voice": L()["voices"][g], "character": CHARACTERS[g]}


def tts(text, mp3, kind, voice=None):
    for attempt in range(4):
        try:
            # English a little brisk for energy; Hindi at natural pace so it stays easy to follow.
            rate = os.environ.get("TTS_RATE") or ("+0%" if LANG == "hi" else "+6%")
            return asyncio.run(_tts(text, voice or VOICES["male"], rate, mp3))
        except Exception as e:
            if attempt == 3:
                raise
            log(f"[{kind}] TTS failed ({e}), retrying")
            time.sleep(10 * (attempt + 1))


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
        # Too few shared words = usually off-topic (and showing the wrong real person is misleading).
        if words and score < min(2, len(words)):
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


def render_motion(work, kind, words, duration, clips, title, sections, host=None, mouth=(), facts=()):
    """Animated style (Remotion): presenter character, kinetic captions, headline/fact cards.
    Assets are served from the work folder."""
    fmt = FORMATS[kind]
    fps, total = 30, duration + 0.8
    images = [c for c in clips if c["is_image"]]
    scenes = []
    if images:
        n = max(len(images), round(total / fmt["clip_secs"]))
        seg = total / n
        scenes = [{"start": round(i * seg, 3), "end": round((i + 1) * seg, 3), "src": images[i % len(images)]["path"].name}
                  for i in range(n)]
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
             "music": music,
             "facts": [{"t": round(t, 2), "text": x} for t, x in facts]}
    (work / "props.json").write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    npx = shutil.which("npx") or "npx"
    subprocess.run([npx, "remotion", "render", "src/index.jsx", "Long" if kind == "long" else "Short",
                    str(work / "final.mp4"), f"--props={work / 'props.json'}", f"--public-dir={work}",
                    "--log=error", "--crf=20"], cwd=ROOT / "motion", check=True)
    return work / "final.mp4"


def fact_times(meta, kind, words, duration, chapter_list):
    """When each on-screen fact card appears: long = 2s into its section, short = spread through the video."""
    if kind == "long":
        heads = {h: t for t, h in chapter_list}
        return [(heads[s["heading"].strip()] + 2.0, s["fact"].strip()) for s in meta.get("sections", [])
                if s.get("fact", "").strip() and s["heading"].strip() in heads]
    facts = [f.strip() for f in meta.get("facts", []) if f.strip()][:3]
    return [(duration * (i + 1) / (len(facts) + 1), f) for i, f in enumerate(facts)]


def make_video(work, kind, meta, host=None):
    fmt = FORMATS[kind]
    work.mkdir(parents=True, exist_ok=True)
    host = host or pick_voice(0)
    log(f"[{kind}] voice ({host['gender']} host)")
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
            video = render_motion(work, kind, words, duration, clips, title, section_list, host, mouth,
                                  fact_times(meta, kind, words, duration, section_list))
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


def token_file():
    """Hindi can upload to its own channel: token_hi.json (or secret YT_TOKEN_JSON_HI). Otherwise the main channel."""
    if LANG != "en" and ((ROOT / f"token_{LANG}.json").exists() or os.environ.get(f"YT_TOKEN_JSON_{LANG.upper()}")
                         or AUTH_MODE):
        return ROOT / f"token_{LANG}.json", f"YT_TOKEN_JSON_{LANG.upper()}"
    return ROOT / "token.json", "YT_TOKEN_JSON"


AUTH_MODE = False


def youtube_client():
    tok, tok_var = token_file()
    if tok.name in _YT:
        return _YT[tok.name]
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # user may untick optional scopes on consent screen
    # Cloud runner: credentials come from encrypted GitHub Secrets, written to git-ignored files at runtime.
    for path, var in ((tok, tok_var), (ROOT / "client_secret.json", "YT_CLIENT_SECRET_JSON")):
        if not path.exists() and os.environ.get(var):
            path.write_text(os.environ[var].lstrip("\ufeff"), encoding="utf-8")  # PowerShell pipes add a BOM
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / "client_secret.json"), SCOPES)
            creds = flow.run_local_server(port=0)
        tok.write_text(creds.to_json())
    _YT[tok.name] = build("youtube", "v3", credentials=creds)
    return _YT[tok.name]


def hashtags(meta, short, topic):
    tags = [re.sub(r"[^\w]", "", h.lstrip("#")) for h in meta.get("hashtags", [])]
    tags = [t for t in tags if t] or ["TechNews", "AI", re.sub(r"\W", "", topic.title())]
    tags = list(dict.fromkeys(tags))[:3]
    return " ".join(f"#{t}" for t in (["Shorts"] + tags[:2] if short else tags))


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


def description(meta, short, topic, credits, chapter_list=()):
    """Search-friendly layout: keyword sentence first (shown in search), summary, chapters, sources, hashtags."""
    channel = os.environ.get("CHANNEL_NAME", "TechPulse")
    tx = L()["text"]
    first = meta.get("description_hook") or meta.get("description", "")
    parts = [first.strip()]
    if meta.get("summary"):
        parts.append(meta["summary"].strip())
    if meta.get("key_points") and not short:
        parts.append(tx["in_video"] + "\n" + "\n".join(f"- {p}" for p in meta["key_points"][:5]))
    if chapter_list:
        parts.append("Chapters:\n" + "\n".join(f"{ts(t)} {h}" for t, h in chapter_list))
    if meta.get("sources"):
        parts.append(f"{tx['sources']}: " + ", ".join(meta["sources"]))
    parts.append(tx["subscribe"].format(c=channel) + "\n" + (tx["more_short"] if short else tx["more_long"]))
    parts.append(tx["ai"])
    if meta.get("music_credit"):
        parts.append(meta["music_credit"])
    tail = hashtags(meta, short, topic)
    head = "\n\n".join(p for p in parts if p)
    if credits:
        block = tx["credits"] + "\n"
        budget = 4800 - len(head) - len(tail)
        for c in credits:
            if len(block) + len(c) + 1 > budget:
                break
            block += c + "\n"
        head += "\n\n" + block.strip()
    return f"{head}\n\n{tail}"


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
    title = re.sub(r"\s*#shorts\b", "", title.strip().strip('"'), flags=re.I)[:100]
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


PLAYLISTS = {"en": ("TechPulse: Daily Tech & AI News (English)", "Every TechPulse tech and AI news video in English."),
             "hi": ("TechPulse Hindi: टेक और AI न्यूज़ हिंदी में", "TechPulse के सभी Hindi tech और AI news videos.")}


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


def reply_comments(limit=5):
    """Reply to genuine viewer comments on recent videos (engagement signal). Max `limit` replies per run
    (50 quota units each). Spam, toxic or already-answered comments are skipped."""
    yt = youtube_client()
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    recent = sb_rest("GET", f"insights?select=youtube_id,title,lang&created_at=gte.{days_ago(14)}&order=views.desc&limit=12")
    cands = []
    for v in recent:
        try:
            threads = yt.commentThreads().list(part="snippet", videoId=v["youtube_id"], order="time", maxResults=20,
                                               textFormat="plainText").execute().get("items", [])
        except Exception:
            continue  # private video or comments off
        for t in threads:
            top = t["snippet"]["topLevelComment"]["snippet"]
            if t["snippet"].get("totalReplyCount", 0) or top.get("authorChannelId", {}).get("value") == me:
                continue
            cands.append({"id": t["id"], "video": v["title"], "lang": v["lang"], "text": top["textDisplay"][:400]})
    if not cands:
        log("comments: nothing new to reply to")
        return
    cands = cands[:20]
    res = llm_json(f"""You manage replies for {CHANNEL()}, a friendly tech & AI news YouTube channel.
For each viewer comment decide whether to reply. SKIP spam, self-promotion, links, hate, insults, or comments that need
no answer. Otherwise write a short warm reply (max 200 characters) in the SAME language as the comment
(Hindi comment -> Hindi/Hinglish reply). Answer only from the video topic; never invent facts or promises; no links;
sometimes end with a short question to keep the conversation going. Thank people who praise the video.

COMMENTS:
{json.dumps(cands, ensure_ascii=False, indent=1)}

Return JSON only: {{"replies": [{{"id": "comment thread id", "reply": "text or SKIP"}}]}}""", required=("replies",))
    sent = 0
    for r in res.get("replies", []):
        if sent >= limit or not r.get("reply") or r["reply"].strip().upper() == "SKIP":
            continue
        try:
            yt.comments().insert(part="snippet", body={"snippet": {"parentId": r["id"],
                                                                   "textOriginal": r["reply"].strip()[:300]}}).execute()
            sent += 1
        except Exception as e:
            log(f"  reply failed: {str(e)[:100]}")
    log(f"comments: replied to {sent} of {len(cands)} new comments")


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


def used_topics():
    if sb_on():
        since = days_ago(14)
        return [r["topic"] for r in sb_rest("GET", f"videos?select=topic&lang=eq.{LANG}&created_at=gte.{since}")
                if r.get("topic")]
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
        "kind": kind, "lang": LANG, "topic": meta["topic"], "title": meta["title"], "description": desc,
        "tags": meta.get("tags", [])[:15], "youtube_id": vid,
        "privacy": privacy_for(meta) if vid else None,
        "status": "published" if vid and privacy_for(meta) == "public" else ("uploaded" if vid else "rendered"),
        "preview_path": preview, "thumb_path": thumb_path, "duration_s": round(duration, 1),
        "meta": {**{k: meta.get(k) for k in ("pinned_comment", "keywords", "thumbnail_text", "fact_check", "host")},
                 "hold": bool(meta.get("hold"))}})
    if vid:
        sb_rest("POST", "insights", prefer="return=representation,resolution=merge-duplicates", json={"youtube_id": vid, "lang": LANG, "kind": kind, "topic": meta["topic"], "title": meta["title"]})
    log(f"[{kind}] saved to Supabase")


def publish_pending():
    global LANG
    rows = sb_rest("GET", "videos?select=id,youtube_id,title,meta,lang&publish_requested=is.true&status=neq.published"
                          "&youtube_id=not.is.null")
    for row in rows:
        LANG = row.get("lang") or "en"  # pick that language's channel login
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
    """Refresh views/likes/comments for the last ~6 months (insights) and the app's 7-day list (videos).
    One channel for all languages, so one batched API call per 50 videos (1 quota unit each)."""
    since = days_ago(180)
    ids = {r["youtube_id"] for r in sb_rest("GET", f"insights?select=youtube_id&created_at=gte.{since}")}
    ids |= {r["youtube_id"] for r in sb_rest("GET", "videos?select=youtube_id&youtube_id=not.is.null")}
    ids = sorted(ids)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        resp = youtube_client().videos().list(part="statistics,status", id=",".join(batch)).execute()
        found = {v["id"] for v in resp.get("items", [])}
        for gone in set(batch) - found:  # removed by YouTube (or deleted by hand)
            sb_rest("PATCH", f"insights?youtube_id=eq.{gone}", json={"health": "missing", "updated_at": now})
        for v in resp.get("items", []):
            st = v["status"]
            if st.get("uploadStatus") in ("rejected", "failed", "deleted") or st.get("rejectionReason"):
                sb_rest("PATCH", f"insights?youtube_id=eq.{v['id']}", json={
                    "health": f"{st.get('uploadStatus')}:{st.get('rejectionReason') or st.get('failureReason') or ''}",
                    "updated_at": now})
            s = v.get("statistics", {})
            st = {k: int(s.get(k, 0)) for k in ("viewCount", "likeCount", "commentCount")}
            sb_rest("PATCH", f"videos?youtube_id=eq.{v['id']}", json={"privacy": v["status"]["privacyStatus"], "stats": st})
            sb_rest("PATCH", f"insights?youtube_id=eq.{v['id']}", json={
                "views": st["viewCount"], "likes": st["likeCount"], "comments": st["commentCount"], "updated_at": now})
    log(f"stats updated for {len(ids)} videos")
    save_channel_stats()
    channel_health()


def save_channel_stats():
    """One row per day of subscribers / views / video count, for the app's growth chart."""
    s = youtube_client().channels().list(part="statistics", mine=True).execute()["items"][0]["statistics"]
    sb_rest("POST", "channel_stats", prefer="return=minimal,resolution=merge-duplicates", json={
        "day": str(datetime.datetime.now(datetime.timezone.utc).date()),
        "subscribers": int(s.get("subscriberCount", 0)), "views": int(s.get("viewCount", 0)),
        "videos": int(s.get("videoCount", 0)),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    log(f"channel: {s.get('subscriberCount')} subscribers, {s.get('viewCount')} views, {s.get('videoCount')} videos")


def process_requests():
    """'Run now' taps in the app become factory runs. Runs inside GitHub Actions with its own short-lived token;
    capped so the daily YouTube upload limit (about 6) is never exceeded."""
    pending = sb_rest("GET", "run_requests?select=*&status=eq.pending&order=created_at.asc")
    if not pending:
        log("run requests: none")
        return
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    today = str(datetime.datetime.now(datetime.timezone.utc).date())
    uploads = len(sb_rest("GET", f"videos?select=id&youtube_id=not.is.null&created_at=gte.{today}T00:00:00Z"))
    for req in pending:
        want = req["long"] + req["shorts"]
        if want == 0:
            status = "skipped: nothing requested"
        elif not (token and repo):
            status = "failed: not running in the cloud"
        elif uploads + want > 6:
            status = f"skipped: daily upload limit ({uploads} today)"
        else:
            r = requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/factory.yml/dispatches",
                              headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                              json={"ref": "main", "inputs": {"lang": req["lang"], "long": str(req["long"]),
                                                              "shorts": str(req["shorts"])}}, timeout=30)
            status = "started" if r.status_code == 204 else f"failed: GitHub {r.status_code}"
            if r.status_code == 204:
                uploads += want
        sb_rest("PATCH", f"run_requests?id=eq.{req['id']}", json={"status": status})
        log(f"run request {req['id']} ({req['lang']} {req['long']}L+{req['shorts']}S): {status}")


def channel_health():
    """Any video YouTube rejected or removed in the last 14 days = pause auto-publishing (upload as private)
    until it clears, so one problem cannot snowball into strikes."""
    global SAFETY_PAUSE
    bad = sb_rest("GET", f"insights?select=youtube_id,title,health&health=not.is.null&updated_at=gte.{days_ago(14)}")
    SAFETY_PAUSE = bool(bad) and os.environ.get("SAFETY_PAUSE_OFF") != "1"
    if bad:
        log(f"SAFETY: {len(bad)} video(s) rejected/removed recently -> new uploads stay private: "
            + "; ".join(f"{b['youtube_id']} {b['health']}" for b in bad[:5]))
    else:
        log("SAFETY: channel healthy")


def performance_block():
    """What has worked on this channel for this language: fed to the story picker so it learns over time."""
    if not sb_on():
        return ""
    rows = sb_rest("GET", f"insights?select=kind,title,views,likes,created_at&lang=eq.{LANG}&created_at=gte.{days_ago(60)}"
                          f"&created_at=lt.{days_ago(2)}&order=views.desc")
    if len(rows) < 4:
        return ""
    fmt = lambda r: f"- [{r['kind']}] {r['title']} - {r['views']} views, {r['likes']} likes"
    return ("CHANNEL PERFORMANCE (learn from this; pick more stories like the winners, fewer like the losers):\n"
            "Best:\n" + "\n".join(fmt(r) for r in rows[:8])
            + ("\nWorst:\n" + "\n".join(fmt(r) for r in rows[max(8, len(rows) - 5):]) if len(rows) > 8 else ""))


def cleanup():
    cutoff = days_ago(KEEP_DAYS)
    old = sb_rest("GET", f"videos?select=id,preview_path,thumb_path&created_at=lt.{cutoff}")
    sb_remove([p for r in old for p in (r["preview_path"], r["thumb_path"]) if p])
    if old:
        sb_rest("DELETE", f"videos?created_at=lt.{cutoff}")
    sb_rest("DELETE", f"insights?created_at=lt.{days_ago(180)}")
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
    ap.add_argument("--lang", choices=sorted(LANGS), default="en", help="video language (en or hi)")
    ap.add_argument("--upload-dir", help="upload an already-rendered video folder")
    ap.add_argument("--publish-pending", action="store_true", help="make app-approved videos public")
    ap.add_argument("--stats", action="store_true", help="refresh YouTube stats in Supabase")
    ap.add_argument("--cleanup", action="store_true", help=f"delete Supabase records/files older than {KEEP_DAYS} days")
    ap.add_argument("--reply-comments", action="store_true", help="reply to new viewer comments (max 5 per run)")
    ap.add_argument("--process-requests", action="store_true", help="start runs requested from the app")
    args = ap.parse_args()
    load_env()
    global LANG, AUTH_MODE
    LANG = args.lang
    if args.auth:
        AUTH_MODE = True
        youtube_client()
        log(f"YouTube auth OK, {token_file()[0].name} saved")
        return
    if args.upload_dir:
        upload_existing(args.upload_dir)
        return
    maintenance = [f for flag, f in ((args.publish_pending, publish_pending), (args.stats, update_stats),
                                     (args.cleanup, cleanup), (args.reply_comments, reply_comments),
                                     (args.process_requests, process_requests)) if flag]
    for f in maintenance:
        try:  # maintenance must never block making today's videos
            f()
        except Exception as e:
            log(f"{f.__name__} failed: {str(e)[:200]}")
    if maintenance and args.long is None and args.shorts is None:
        return
    args.long = 1 if args.long is None else args.long
    args.shorts = 1 if args.shorts is None else args.shorts
    if get_setting("paused", False) is True:
        log("PAUSED from the app (Controls > Pause automation): no new videos this run")
        return

    run_id = None
    if sb_on():
        run_id = sb_rest("POST", "runs", json={"lang": LANG, "note": f"{args.long} long + {args.shorts} Shorts"})[0]["id"]
    counts = {"made": 0, "published": 0, "held": 0, "failed": 0}

    def finish_run(note=None):
        if run_id:
            sb_rest("PATCH", f"runs?id=eq.{run_id}", json={
                **counts, "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                **({"note": note} if note else {})})

    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    used = used_topics()
    niche = os.environ.get("NICHE", "technology and AI")
    run_dir = OUT / f"{datetime.datetime.now():%Y-%m-%d_%H%M}_{LANG}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log(f"Fetching trends ({L()['name']}, {L()['geo']})")
    trends = fetch_trends(L()["geo"])
    if not trends:
        finish_run("no trends from any source")
        raise RuntimeError("No trends from any source")

    log(f"Picking stories: {args.long} long, {args.shorts} Shorts")
    jobs = plan_videos(trends, niche, used, args.long, args.shorts)
    if not jobs:
        finish_run("no scripts written (AI models unavailable)")
        raise SystemExit("no scripts written")

    failures = 0
    for i, (kind, meta) in enumerate(jobs):
        try:
            work = run_dir / f"{i}_{kind}_{slugify(meta['topic'])}"
            work.mkdir(parents=True, exist_ok=True)
            (work / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            log(f"=== {kind}: {meta['topic']} | {meta['title']}")
            host = pick_voice(i)
            meta["host"] = host
            r = make_video(work, kind, meta, host)
            meta["music_credit"] = r["music_credit"]
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
                vid = upload(r["video"], meta["title"], desc, clean_tags(meta), kind == "short", privacy)
                log(f"[{kind}] uploaded https://youtu.be/{vid} ({privacy}{', held by fact-check' if meta.get('hold') else ''})")
                # YouTube rejects comments on private videos; publish_pending() posts it once public.
                after_upload(vid, thumb, meta.get("pinned_comment") if privacy == "public" else None)
                add_to_playlist(vid)
                entry["youtube_id"] = vid
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
    finish_run()
    if failures:
        raise SystemExit(f"{failures} video(s) failed")


if __name__ == "__main__":
    main()
