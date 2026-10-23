"""Reliable scheduler. GitHub drops many `schedule:` runs under load, so this runs inside one long Actions job,
starts every factory slot on time (catching up late ones), triggers the publish checks every 10 minutes,
and re-starts itself before the 6-hour job limit. Each factory run is named after its slot so a slot never runs twice.
Standard library + the preinstalled `gh` CLI only."""
import datetime
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

# YouTube allows ~10 uploads per channel per rolling 24 h. The old plan wanted 13 and bunched them in the afternoon,
# so morning slots found the window full and were skipped. Now 9 uploads, one slot every 3 h, 1 spare for breaking
# news / part 2s. Data (Oct 16-22): EN news Shorts 100-800 views, HI viral Shorts ~60, HI plain/long only 10-28.
# (UTC time, language, long videos, Shorts)
SLOTS = [("00:13", "en", 0, 1), ("06:13", "en", 0, 1), ("12:13", "en", 1, 1), ("21:13", "en", 0, 1)]
# Viral-format track (versus tests, top 3, budget lists, tricks): HI 08:43 / 14:43 / 20:43 IST, EN 2:13 pm ET
VIRAL = [("03:13", "hi"), ("09:13", "hi"), ("15:13", "hi"), ("18:13", "en")]
BREAKING = [f"{h:02d}:29" for h in range(0, 24, 3)]   # breaking-news check every 3 hours
CATCH_UP = datetime.timedelta(hours=3)                # a late slot still runs within 3 h; older ones are skipped
BREAKING_WINDOW = datetime.timedelta(minutes=90)
RETRY_WINDOW = datetime.timedelta(hours=6)            # a slot whose factory run FAILED is re-run once within 6 h
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


def failed_slots(now):
    """Slots whose factory run failed (AI providers down, network drop, ...) and have not been retried yet:
    the clock re-runs each once, so a bad minute never costs a day's video and nobody has to step in."""
    r = gh("run", "list", "--workflow", "factory.yml", "--limit", "60", "--json", "displayTitle,conclusion,createdAt")
    try:
        runs = [] if r.returncode else json.loads(r.stdout)
    except ValueError:
        return []
    titles = {x["displayTitle"] for x in runs}
    out = []
    for x in runs:
        name = x["displayTitle"].removeprefix("Factory ")
        made = datetime.datetime.fromisoformat(x["createdAt"].replace("Z", "+00:00"))
        if (x["conclusion"] in ("failure", "timed_out", "cancelled") and now - made < RETRY_WINDOW and slot_inputs(name)
                and f"Factory {name} retry" not in titles):
            out.append(name)
    return out


def slot_inputs(name):
    """Workflow inputs for a slot name like '2026-10-22 12:13 en' or '... hi viral' (None: not retryable)."""
    parts = name.split()
    if len(parts) == 4 and parts[3] == "viral":
        return ["-f", f"lang={parts[2]}", "-f", "mode=viral"]
    if len(parts) == 3 and parts[2] in ("en", "hi"):
        for hm, lang, long_, shorts in SLOTS:
            if hm == parts[1] and lang == parts[2]:
                return ["-f", f"lang={lang}", "-f", f"long={long_}", "-f", f"shorts={shorts}"]
    return None  # breaking-news checks are time-sensitive and not retried


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


def sb(method, path, body=None):
    req = urllib.request.Request(f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None, headers={
        "apikey": os.environ["SUPABASE_SERVICE_KEY"], "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}",
        "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return json.loads(data) if data else None


def handle_logins():
    """'Log in to YouTube' in the phone app: Google sends a one-time code back to the app, which stores it. Trade it
    (within a minute, before it expires) for a lasting login and save that where the factory reads it."""
    if not os.environ.get("SUPABASE_SERVICE_KEY"):
        return
    try:
        pending = sb("GET", "yt_login_requests?select=*&status=eq.pending&order=id.asc")
    except Exception:
        return  # table not there yet, or Supabase busy: try again next minute
    for req in pending:
        status, error = "done", None
        try:
            client = json.loads(os.environ.get(f"OAUTH_WEB_JSON_{req['project']}") or "{}").get("web") or {}
            if not client.get("client_secret"):
                raise RuntimeError(f"web login client for project {req['project']} is not set up")
            form = urllib.parse.urlencode({"code": req["code"], "client_id": client["client_id"],
                                           "client_secret": client["client_secret"], "grant_type": "authorization_code",
                                           "redirect_uri": req["redirect_uri"]}).encode()
            with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=form, timeout=30) as r:
                tok = json.loads(r.read())
            if not tok.get("refresh_token"):
                raise RuntimeError("Google sent no lasting login (refresh token); log in again")
            sb("POST", "yt_logins?on_conflict=project", {"project": req["project"], "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "token": {
                "token": tok["access_token"], "refresh_token": tok["refresh_token"],
                "token_uri": "https://oauth2.googleapis.com/token", "client_id": client["client_id"],
                "client_secret": client["client_secret"], "scopes": tok.get("scope", "").split()}})
            sb("DELETE", f"settings?key=eq.login_expired_{req['project']}")
        except urllib.error.HTTPError as e:
            status, error = "error", f"Google: {e.read().decode(errors='replace')[:200]}"
        except Exception as e:
            status, error = "error", str(e)[:200]
        # the one-time code is useless after this either way; drop it from the table
        sb("PATCH", f"yt_login_requests?id=eq.{req['id']}", {"status": status, "error": error, "code": "-"})
        print("youtube login for project", req["project"], status, error or "", flush=True)


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
        if not pending and not factory_busy():
            pending = [(f"{name} retry", slot_inputs(name)) for name in failed_slots(now) if f"{name} retry" not in sent]
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
        try:
            handle_logins()
        except Exception as e:  # never let a login problem stop the video schedule
            print("login handling failed:", str(e)[:200], flush=True)
        if last_publish is None or now - last_publish >= datetime.timedelta(minutes=10):
            gh("workflow", "run", "publish.yml")
            last_publish = now
        time.sleep(60)
    gh("workflow", "run", "clock.yml")  # the next run waits until this one has ended, then takes over
    print("handing over to the next clock run", flush=True)


if __name__ == "__main__":
    main()
