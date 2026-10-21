"""Reliable scheduler. GitHub drops many `schedule:` runs under load, so this runs inside one long Actions job,
starts every factory slot on time (catching up late ones), triggers the publish checks every 10 minutes,
and re-starts itself before the 6-hour job limit. Each factory run is named after its slot so a slot never runs twice.
Standard library + the preinstalled `gh` CLI only."""
import datetime
import json
import os
import subprocess
import time

# (UTC time, language, long videos, Shorts): EN 1 long + 3 Shorts, HI 1 long + 4 Shorts (India = biggest Shorts market)
SLOTS = [("12:17", "en", 1, 1), ("16:43", "en", 0, 1), ("21:23", "en", 0, 1),
         ("01:33", "hi", 0, 1), ("07:47", "hi", 0, 1), ("10:03", "hi", 0, 1), ("13:37", "hi", 1, 1)]
# Viral-format track on top (versus tests, top 3, budget lists, tricks): HI 10:43 + 20:43 IST, EN 10:13 + 15:03 ET
VIRAL = [("05:13", "hi"), ("15:13", "hi"), ("14:13", "en"), ("19:03", "en")]
BREAKING = [f"{h:02d}:29" for h in range(0, 24, 3)]   # breaking-news check every 3 hours
CATCH_UP = datetime.timedelta(hours=3)                # a late slot still runs within 3 h; older ones are skipped
BREAKING_WINDOW = datetime.timedelta(minutes=90)
RUN_FOR = datetime.timedelta(hours=5, minutes=40)     # job limit is 6 h; the next clock run takes over


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode:
        print("gh failed:", " ".join(args[:3]), r.stderr.strip()[:200], flush=True)
    return r


def started_slots():
    r = gh("run", "list", "--workflow", "factory.yml", "--limit", "60", "--json", "displayTitle")
    try:
        return None if r.returncode else {x["displayTitle"] for x in json.loads(r.stdout)}
    except ValueError:
        return None  # unknown: skip this minute rather than risk running a slot twice


def factory_busy():
    for status in ("in_progress", "queued", "pending", "waiting"):
        r = gh("run", "list", "--workflow", "factory.yml", "--status", status, "--json", "databaseId")
        if r.returncode or json.loads(r.stdout or "[]"):
            return True  # also "busy" when gh fails, so nothing is started blind
    return False


def due(now):
    """Slots whose start time has passed but are still inside their catch-up window."""
    for day in (now.date() - datetime.timedelta(days=1), now.date()):
        for hm, lang, long_, shorts in SLOTS:
            at = datetime.datetime.combine(day, datetime.time.fromisoformat(hm), datetime.timezone.utc)
            if at <= now < at + CATCH_UP:
                yield f"{at:%Y-%m-%d %H:%M} {lang}", ["-f", f"lang={lang}", "-f", f"long={long_}", "-f", f"shorts={shorts}"]
        for hm, lang in VIRAL:
            at = datetime.datetime.combine(day, datetime.time.fromisoformat(hm), datetime.timezone.utc)
            if at <= now < at + CATCH_UP:
                yield f"{at:%Y-%m-%d %H:%M} {lang} viral", ["-f", f"lang={lang}", "-f", "mode=viral"]
        for hm in BREAKING:
            at = datetime.datetime.combine(day, datetime.time.fromisoformat(hm), datetime.timezone.utc)
            if at <= now < at + BREAKING_WINDOW:
                yield f"{at:%Y-%m-%d %H:%M} breaking", ["-f", "mode=breaking"]


def other_clock_running():
    """True if an OLDER clock run is still live. Newer ones are ignored, so when two runs start together the older
    one keeps the job and the newer one steps aside - never both."""
    r = gh("run", "list", "--workflow", "clock.yml", "--status", "in_progress", "--json", "databaseId")
    me = int(os.environ.get("GITHUB_RUN_ID") or 0)
    try:
        return any(x["databaseId"] < me for x in json.loads(r.stdout or "[]"))
    except ValueError:
        return False


def main():
    for _ in range(9):  # a handed-over run waits for the old one to finish; a watchdog run finds a live clock and exits
        if not other_clock_running():
            break
        time.sleep(20)
    else:
        print("another clock is running; exiting", flush=True)
        return
    start = datetime.datetime.now(datetime.timezone.utc)
    sent, last_publish = set(), None
    while (now := datetime.datetime.now(datetime.timezone.utc)) - start < RUN_FOR:
        pending = [(slot, inputs) for slot, inputs in due(now) if slot not in sent]
        # Factory runs share one concurrency group where GitHub keeps only ONE waiting run (a second would cancel
        # the first), so start one slot at a time and only when no factory run is busy; late slots catch up.
        if pending and not factory_busy():
            done = started_slots()
            for slot, inputs in pending if done is not None else []:
                if f"Factory {slot}" in done:
                    sent.add(slot)
                    continue
                if gh("workflow", "run", "factory.yml", "-f", f"slot={slot}", *inputs).returncode == 0:
                    sent.add(slot)
                    print(now.strftime("%H:%M"), "started", slot, flush=True)
                break
        if last_publish is None or now - last_publish >= datetime.timedelta(minutes=10):
            gh("workflow", "run", "publish.yml")
            last_publish = now
        time.sleep(60)
    gh("workflow", "run", "clock.yml")  # the next run waits until this one has ended, then takes over
    print("handing over to the next clock run", flush=True)


if __name__ == "__main__":
    main()
