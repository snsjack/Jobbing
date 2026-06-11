#!/usr/bin/env python3
"""
job_finder.py — Finds early-educator jobs that offer sponsorship within a
driving radius of your home, dedupes against previous runs, writes an HTML
digest + CSV, and (optionally) emails it to you.

Run once:        python job_finder.py
First-run reset:  python job_finder.py --reset-seen
Include unknowns: python job_finder.py --include-unknown
Skip email:       python job_finder.py --no-email

Schedule it daily with cron / Task Scheduler / GitHub Actions (see README).
"""
from __future__ import annotations  # lets `float | None` hints work on Python 3.9

import argparse
import csv
import datetime as dt
import html
import json
import math
import os
import re
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass, field, asdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

import config as cfg

SEEN_FILE = os.path.join(cfg.OUTPUT_DIR, "seen_jobs.json")
GEOCACHE_FILE = os.path.join(cfg.OUTPUT_DIR, "geocode_cache.json")
HTML_FILE = os.path.join(cfg.OUTPUT_DIR, "digest.html")
CSV_FILE = os.path.join(cfg.OUTPUT_DIR, "jobs.csv")
JOBS_DB = os.path.join(cfg.OUTPUT_DIR, "jobs_db.json")
SITE_DIR = getattr(cfg, "SITE_DIR", "docs")
SITE_INDEX = os.path.join(SITE_DIR, "index.html")

USER_AGENT = "edu-job-finder/1.0 (personal job search)"


def _redact(text) -> str:
    """Strip API keys/secrets out of any string before it's printed or logged.
    Adzuna requires its key in the URL, so raw error text would otherwise leak
    it into the terminal and into run.log."""
    s = str(text)
    # mask key=value pairs in URLs/query strings
    s = re.sub(r'(?i)\b(app_id|app_key|api[_-]?key|key|token)=([^&\s"\']+)',
               r'\1=***', s)
    # mask any literal secret values that appear elsewhere (headers, bodies)
    for v in (getattr(cfg, "ADZUNA_APP_ID", ""), getattr(cfg, "ADZUNA_APP_KEY", ""),
              getattr(cfg, "JSEARCH_API_KEY", ""), getattr(cfg, "ORS_API_KEY", "")):
        if v:
            s = s.replace(v, "***")
    return s


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Job:
    uid: str                 # stable de-dupe id: "source:nativeid"
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str
    posted: str = ""         # ISO date string if known
    lat: float | None = None
    lon: float | None = None
    distance_km: float | None = None
    drive_hours: float | None = None
    sponsorship: str = "unknown"   # confirmed | likely | unknown


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Geocoding (only needed for sources that don't return coordinates)
# ---------------------------------------------------------------------------
_geocache = load_json(GEOCACHE_FILE, {})


def geocode(place: str):
    """Return (lat, lon) for a place string using OpenStreetMap Nominatim.
    Cached on disk; returns None on failure. Polite 1s delay per new lookup."""
    if not place:
        return None
    key = place.strip().lower()
    if key in _geocache:
        v = _geocache[key]
        return tuple(v) if v else None
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": place, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        time.sleep(1)  # be nice to the free service
        if data:
            latlon = (float(data[0]["lat"]), float(data[0]["lon"]))
            _geocache[key] = latlon
            save_json(GEOCACHE_FILE, _geocache)
            return latlon
    except Exception as e:
        print(f"  ! geocode failed for {place!r}: {_redact(e)}")
    _geocache[key] = None
    save_json(GEOCACHE_FILE, _geocache)
    return None


# ---------------------------------------------------------------------------
# Source: Arbeitnow (free, no key, native visa_sponsorship flag)
# ---------------------------------------------------------------------------
def fetch_arbeitnow():
    jobs = []
    base = "https://arbeitnow.com/api/job-board-api"
    for page in range(1, cfg.ARBEITNOW_MAX_PAGES + 1):
        try:
            resp = requests.get(base, params={"page": page},
                                headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            print(f"  ! Arbeitnow page {page} failed: {_redact(e)}")
            break
        rows = payload.get("data", [])
        if not rows:
            break
        for r in rows:
            jobs.append(Job(
                uid=f"arbeitnow:{r.get('slug')}",
                source="Arbeitnow",
                title=r.get("title", ""),
                company=r.get("company_name", ""),
                location=r.get("location", ""),
                url=r.get("url", ""),
                description=strip_html(r.get("description", "")),
                posted=_unix_to_iso(r.get("created_at")),
                sponsorship="confirmed" if r.get("visa_sponsorship") else "unknown",
            ))
    print(f"  Arbeitnow: pulled {len(jobs)} raw jobs")
    return jobs


def _unix_to_iso(ts):
    try:
        return dt.datetime.utcfromtimestamp(int(ts)).date().isoformat()
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Source: Adzuna (free tier key, returns coordinates, broad coverage)
# ---------------------------------------------------------------------------
def fetch_adzuna():
    jobs = []
    if not (cfg.ADZUNA_APP_ID and cfg.ADZUNA_APP_KEY):
        print("  Adzuna: skipped (no ADZUNA_APP_ID / ADZUNA_APP_KEY set)")
        return jobs
    # Search terms come from config (ADZUNA_QUERIES) so they're easy to tune.
    queries = getattr(cfg, "ADZUNA_QUERIES",
                      ["early childhood", "kindergarten", "preschool"])
    for country in cfg.ADZUNA_COUNTRIES:
        for q in queries:
            for page in range(1, cfg.ADZUNA_MAX_PAGES + 1):
                url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
                params = {
                    "app_id": cfg.ADZUNA_APP_ID,
                    "app_key": cfg.ADZUNA_APP_KEY,
                    "what": q,
                    "where": cfg.HOME_CITY,
                    "distance": cfg.RADIUS_KM,
                    "results_per_page": 50,
                    "content-type": "application/json",
                }
                try:
                    resp = requests.get(url, params=params,
                                        headers={"User-Agent": USER_AGENT}, timeout=30)
                    if resp.status_code == 429:
                        print("  ! Adzuna rate limit hit; pausing 5s")
                        time.sleep(5)
                        continue
                    resp.raise_for_status()
                    results = resp.json().get("results", [])
                except Exception as e:
                    print(f"  ! Adzuna {country}/{q} p{page} failed: {_redact(e)}")
                    break
                if not results:
                    break
                for r in results:
                    loc = r.get("location", {}) or {}
                    jobs.append(Job(
                        uid=f"adzuna:{r.get('id')}",
                        source=f"Adzuna ({country.upper()})",
                        title=r.get("title", ""),
                        company=(r.get("company", {}) or {}).get("display_name", ""),
                        location=loc.get("display_name", ""),
                        url=r.get("redirect_url", ""),
                        description=strip_html(r.get("description", "")),
                        posted=(r.get("created", "") or "")[:10],
                        lat=r.get("latitude"),
                        lon=r.get("longitude"),
                    ))
                time.sleep(0.4)  # gentle pacing
    print(f"  Adzuna: pulled {len(jobs)} raw jobs")
    return jobs


# ---------------------------------------------------------------------------
# Source: JSearch (Google for Jobs -> Indeed, LinkedIn, Glassdoor, etc.)
# ---------------------------------------------------------------------------
def fetch_jsearch():
    jobs = []
    if not cfg.JSEARCH_API_KEY:
        print("  JSearch: skipped (no JSEARCH_API_KEY set)")
        return jobs
    headers = {
        "X-RapidAPI-Key": cfg.JSEARCH_API_KEY,
        "X-RapidAPI-Host": cfg.JSEARCH_HOST,
    }
    url = f"https://{cfg.JSEARCH_HOST}/search"
    for q in cfg.JSEARCH_QUERIES:
        params = {
            "query": f"{q} in {cfg.JSEARCH_LOCATION}",
            "page": "1",
            "num_pages": str(cfg.JSEARCH_NUM_PAGES),
            "country": cfg.JSEARCH_COUNTRY,
            "date_posted": cfg.JSEARCH_DATE_POSTED,
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except Exception as e:
            print(f"  ! JSearch query {q!r} request error: {_redact(e)}")
            continue
        if resp.status_code == 429:
            print("  ! JSearch quota/rate limit hit (free plan = 200/month) — stopping JSearch")
            break
        if resp.status_code != 200:
            # surface the API's own reason (e.g. 'not subscribed', bad key)
            print(f"  ! JSearch query {q!r} HTTP {resp.status_code}: {_redact(resp.text[:200])}")
            continue
        try:
            payload = resp.json()
        except Exception as e:
            print(f"  ! JSearch query {q!r} bad JSON: {_redact(e)}")
            continue
        status = payload.get("status")
        if status and status != "OK":
            reason = payload.get("error") or payload.get("message") or ""
            print(f"  ! JSearch status={status} for {q!r}: {_redact(str(reason))[:200]}")
            continue
        n_before = len(jobs)
        for r in payload.get("data", []):
            city = r.get("job_city") or ""
            state = r.get("job_state") or ""
            country = r.get("job_country") or ""
            loc = ", ".join(x for x in (city, state, country) if x)
            publisher = r.get("job_publisher") or "web"
            jobs.append(Job(
                uid=f"jsearch:{r.get('job_id')}",
                source=f"JSearch/{publisher}",
                title=r.get("job_title", ""),
                company=r.get("employer_name", "") or "",
                location=loc,
                url=r.get("job_apply_link", "") or r.get("job_google_link", ""),
                description=strip_html(r.get("job_description", "")),
                posted=(r.get("job_posted_at_datetime_utc", "") or "")[:10],
                lat=r.get("job_latitude"),
                lon=r.get("job_longitude"),
            ))
        print(f"    JSearch {q!r}: {len(jobs) - n_before} results")
        time.sleep(0.5)
    print(f"  JSearch: pulled {len(jobs)} raw jobs")
    return jobs


# ---------------------------------------------------------------------------
# Filtering / enrichment
# ---------------------------------------------------------------------------
def matches_educator(job: Job) -> bool:
    title = job.title.lower()
    for bad in cfg.EXCLUDE_TITLE_KEYWORDS:
        if bad in title:
            return False
    blob = f"{title} {job.description.lower()}"
    return any(k in blob for k in cfg.EDUCATOR_KEYWORDS)


def _compile_sponsor_patterns(terms):
    """Whole-word patterns so short terms don't match inside other words
    (e.g. 'ens' must not match 'gardens'; '482' must not match '4821').
    Spaces become flexible whitespace so 'visa  sponsorship' still matches."""
    pats = []
    for t in terms:
        esc = re.escape(t.strip()).replace(r"\ ", r"\s+").replace(" ", r"\s+")
        pats.append(re.compile(rf"\b{esc}\b", re.IGNORECASE))
    return pats


_SPONSOR_PATTERNS = _compile_sponsor_patterns(cfg.SPONSORSHIP_KEYWORDS)


def classify_sponsorship(job: Job) -> str:
    if job.sponsorship == "confirmed":
        return "confirmed"
    blob = f"{job.title} {job.description}"
    if any(p.search(blob) for p in _SPONSOR_PATTERNS):
        return "likely"
    return "unknown"


def ors_drive_hours(lat, lon):
    """Real driving time in hours via OpenRouteService, or None on failure."""
    try:
        resp = requests.post(
            "https://api.openrouteservice.org/v2/directions/driving-car",
            headers={"Authorization": cfg.ORS_API_KEY,
                     "Content-Type": "application/json"},
            json={"coordinates": [[cfg.HOME_LON, cfg.HOME_LAT], [lon, lat]]},
            timeout=30,
        )
        resp.raise_for_status()
        secs = resp.json()["routes"][0]["summary"]["duration"]
        return secs / 3600.0
    except Exception as e:
        print(f"  ! ORS drive-time failed: {_redact(e)}")
        return None


def add_distance(job: Job) -> bool:
    """Attach distance + drive estimate; return True if within radius/time."""
    if job.lat is None or job.lon is None:
        coords = geocode(job.location)
        if coords:
            job.lat, job.lon = coords
    if job.lat is None or job.lon is None:
        # Location couldn't be resolved. Keep it (better to show niche hits),
        # but mark distance unknown so you can eyeball it.
        return True
    job.distance_km = round(haversine_km(cfg.HOME_LAT, cfg.HOME_LON,
                                         job.lat, job.lon), 1)
    if cfg.DRIVE_TIME_CHECK and cfg.ORS_API_KEY:
        h = ors_drive_hours(job.lat, job.lon)
        if h is not None:
            job.drive_hours = round(h, 1)
            return h <= cfg.MAX_DRIVE_HOURS
    # Estimated drive time from straight-line distance
    job.drive_hours = round(job.distance_km * cfg.ROAD_FACTOR / cfg.AVG_KMH, 1)
    return job.distance_km <= cfg.RADIUS_KM


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def collect(include_unknown: bool):
    raw = []
    if cfg.USE_ARBEITNOW:
        raw += fetch_arbeitnow()
    if cfg.USE_ADZUNA:
        raw += fetch_adzuna()
    if getattr(cfg, "USE_JSEARCH", False):
        raw += fetch_jsearch()

    # de-dupe identical uids and obvious title+company repeats across sources
    seen_uid, seen_pair, deduped = set(), set(), []
    for j in raw:
        pair = (j.title.lower().strip(), j.company.lower().strip())
        if j.uid in seen_uid or pair in seen_pair:
            continue
        seen_uid.add(j.uid)
        seen_pair.add(pair)
        deduped.append(j)

    kept = []
    for j in deduped:
        if not matches_educator(j):
            continue
        j.sponsorship = classify_sponsorship(j)
        if j.sponsorship == "unknown" and not include_unknown:
            continue
        if not add_distance(j):
            continue
        kept.append(j)

    rank = {"confirmed": 0, "likely": 1, "unknown": 2}
    kept.sort(key=lambda j: (rank[j.sponsorship],
                             j.distance_km if j.distance_km is not None else 1e9,
                             j.posted), reverse=False)
    return kept


def split_new(jobs):
    seen = load_json(SEEN_FILE, {})
    today = dt.date.today().isoformat()
    new = [j for j in jobs if j.uid not in seen]
    for j in jobs:
        seen.setdefault(j.uid, today)
    save_json(SEEN_FILE, seen)
    return new


# ---------------------------------------------------------------------------
# Output: HTML digest + CSV
# ---------------------------------------------------------------------------
TIER = {
    "confirmed": ("✅ Sponsorship confirmed", "#0f7b3f", "#e6f4ea"),
    "likely":    ("🟡 Sponsorship likely",   "#9a6700", "#fdf3d7"),
    "unknown":   ("⚪ Sponsorship unclear",   "#5a5a5a", "#eeeeee"),
}


def render_html(jobs, title):
    e = html.escape
    today = dt.date.today().strftime("%A, %d %B %Y")
    cards = []
    for j in jobs:
        label, fg, bg = TIER[j.sponsorship]
        if j.distance_km is not None:
            dist = f"{j.distance_km:.0f} km · ~{j.drive_hours:.1f} h drive"
        else:
            dist = "distance unknown — check listing"
        snippet = e(j.description[:240]) + ("…" if len(j.description) > 240 else "")
        cards.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="margin:0 0 14px 0;border:1px solid #e4e4e4;border-radius:10px;">
          <tr><td style="padding:16px 18px;">
            <span style="display:inline-block;font:600 12px/1 -apple-system,Segoe UI,Roboto,sans-serif;
                         color:{fg};background:{bg};padding:5px 9px;border-radius:99px;">{label}</span>
            <h3 style="margin:10px 0 2px;font:600 17px/1.3 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;">
              {e(j.title)}</h3>
            <div style="font:400 14px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;color:#444;">
              {e(j.company) or "Company not listed"} &nbsp;·&nbsp; {e(j.location) or "—"}</div>
            <div style="margin-top:4px;font:600 13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;color:#1a5;">
              📍 {dist}</div>
            <p style="margin:10px 0 12px;font:400 13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#555;">
              {snippet}</p>
            <a href="{e(j.url)}" style="display:inline-block;background:#111;color:#fff;text-decoration:none;
               font:600 14px/1 -apple-system,Segoe UI,Roboto,sans-serif;padding:11px 18px;border-radius:8px;">
               Apply →</a>
            <span style="font:400 12px/1 -apple-system,Segoe UI,Roboto,sans-serif;color:#999;margin-left:10px;">
              {e(j.source)}{' · posted ' + e(j.posted) if j.posted else ''}</span>
          </td></tr>
        </table>""")

    if not cards:
        body = """<p style="font:400 15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;color:#555;">
                  No new matching jobs today. The search ran fine — there just
                  weren't fresh listings that fit. It'll check again tomorrow.</p>"""
    else:
        body = "".join(cards)

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="margin:0;background:#f6f6f4;padding:24px 0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
        <table role="presentation" width="640" cellpadding="0" cellspacing="0"
               style="max-width:640px;width:100%;">
          <tr><td style="padding:0 18px;">
            <h1 style="margin:0 0 2px;font:700 22px/1.2 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;">
              {html.escape(title)}</h1>
            <p style="margin:0 0 18px;font:400 14px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;color:#777;">
              {today} · {len(jobs)} job{'s' if len(jobs)!=1 else ''} ·
              within {cfg.RADIUS_KM} km of {html.escape(cfg.HOME_CITY)}</p>
            {body}
            <p style="margin:22px 0 0;font:400 12px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#aaa;">
              Sources: Arbeitnow (live visa-sponsorship flag) + Adzuna. "Likely" means a
              sponsorship/relocation keyword was found in the listing — always confirm in
              the ad before applying.</p>
          </td></tr>
        </table>
      </td></tr></table>
    </body></html>"""


def write_csv(jobs):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sponsorship", "title", "company", "location",
                    "distance_km", "drive_hours", "source", "posted", "url"])
        for j in jobs:
            w.writerow([j.sponsorship, j.title, j.company, j.location,
                        j.distance_km, j.drive_hours, j.source, j.posted, j.url])


# ---------------------------------------------------------------------------
# Persistent job database + daily webpage (GitHub Pages)
# ---------------------------------------------------------------------------
_SITE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#FCFCFA; --ink:#16191D; --muted:#5C636E; --line:#E7E7E2;
    --card:#FFFFFF; --teal:#0E6E7A; --teal-ink:#0A4E58;
    --green:#0F7A52; --green-bg:#E4F3EC; --amber:#8A6A12; --amber-bg:#FBF1D6;
    --slate:#5A6472; --slate-bg:#EDEFF2; --shadow:0 1px 2px rgba(16,25,30,.05);
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--paper);color:var(--ink);
    font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    line-height:1.5;}
  .wrap{max-width:860px;margin:0 auto;padding:0 18px}
  header.site{padding:40px 0 18px}
  .eyebrow{font:600 12px/1 Inter,sans-serif;letter-spacing:.14em;
    text-transform:uppercase;color:var(--teal);margin:0 0 10px}
  h1{font-family:"Bricolage Grotesque",sans-serif;font-weight:800;
    font-size:clamp(28px,5vw,44px);line-height:1.02;letter-spacing:-.02em;margin:0}
  .sub{color:var(--muted);margin:10px 0 0;font-size:15px}
  .stats{margin:18px 0 0;font-size:14px;color:var(--muted)}
  .stats b{color:var(--ink)}
  /* sticky filter rail */
  .bar{position:sticky;top:0;z-index:10;background:rgba(252,252,250,.92);
    backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
    padding:12px 0;margin-top:18px}
  .bar .wrap{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
  .chips{display:flex;gap:6px;flex-wrap:wrap}
  .chip{font:600 13px/1 Inter,sans-serif;color:var(--muted);background:transparent;
    border:1px solid var(--line);border-radius:99px;padding:8px 13px;cursor:pointer;
    transition:background .12s,color .12s,border-color .12s}
  .chip:hover{border-color:var(--teal)}
  .chip[aria-pressed="true"]{background:var(--teal);border-color:var(--teal);color:#fff}
  .grow{flex:1 1 160px;min-width:140px}
  input[type=search]{width:100%;font:400 14px Inter,sans-serif;color:var(--ink);
    background:#fff;border:1px solid var(--line);border-radius:9px;padding:9px 12px}
  select{font:500 13px Inter,sans-serif;color:var(--ink);background:#fff;
    border:1px solid var(--line);border-radius:9px;padding:9px 10px;cursor:pointer}
  :focus-visible{outline:2px solid var(--teal);outline-offset:2px;border-radius:6px}
  /* date groups + cards */
  main{padding:8px 0 60px}
  .group{margin:26px 0 0}
  .group h2{font-family:"Bricolage Grotesque",sans-serif;font-weight:700;
    font-size:15px;letter-spacing:.01em;color:var(--ink);margin:0 0 12px;
    display:flex;align-items:baseline;gap:9px}
  .group h2 .n{font:500 12px Inter,sans-serif;color:var(--muted)}
  .card{background:var(--card);border:1px solid var(--line);border-radius:13px;
    padding:16px 18px;margin:0 0 11px;box-shadow:var(--shadow)}
  .pill{display:inline-block;font:600 11px/1 Inter,sans-serif;padding:5px 9px;
    border-radius:99px;vertical-align:middle}
  .pill.confirmed{color:var(--green);background:var(--green-bg)}
  .pill.likely{color:var(--amber);background:var(--amber-bg)}
  .pill.unknown{color:var(--slate);background:var(--slate-bg)}
  .added{float:right;font:500 12px Inter,sans-serif;color:var(--muted)}
  .title{font-family:"Bricolage Grotesque",sans-serif;font-weight:700;
    font-size:18px;line-height:1.25;margin:11px 0 3px}
  .org{font-size:14px;color:var(--muted)}
  .dist{margin-top:5px;font:600 13px Inter,sans-serif;color:var(--teal-ink)}
  .desc{margin:10px 0 13px;font-size:13px;color:var(--muted);line-height:1.55}
  .apply{display:inline-block;background:var(--ink);color:#fff;text-decoration:none;
    font:600 14px Inter,sans-serif;padding:10px 17px;border-radius:9px;
    transition:transform .1s,background .12s}
  .apply:hover{background:#000;transform:translateY(-1px)}
  .src{font:400 12px Inter,sans-serif;color:#9aa0a8;margin-left:11px}
  .empty{text-align:center;color:var(--muted);padding:60px 20px;font-size:15px}
  footer{border-top:1px solid var(--line);padding:22px 0 50px;color:#9aa0a8;font-size:12px}
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
  @media (max-width:520px){.added{float:none;display:block;margin-top:6px}}
</style>
</head>
<body>
<header class="site"><div class="wrap">
  <p class="eyebrow">Daily job board</p>
  <h1>__TITLE__</h1>
  <p class="sub">__SUBTITLE__</p>
  <p class="stats" id="stats"></p>
</div></header>

<div class="bar"><div class="wrap">
  <div class="chips" id="chips" role="group" aria-label="Filter by date added">
    <button class="chip" data-days="0">Added today</button>
    <button class="chip" data-days="2">Last 3 days</button>
    <button class="chip" data-days="6">Last 7 days</button>
    <button class="chip" data-days="29">Last 30 days</button>
    <button class="chip" data-days="all" aria-pressed="true">All</button>
  </div>
  <span class="grow"><input type="search" id="q" placeholder="Search title, employer, suburb…" aria-label="Search listings"></span>
  <select id="spons" aria-label="Filter by sponsorship">
    <option value="all">Any sponsorship</option>
    <option value="likely">Likely / confirmed only</option>
  </select>
</div></div>

<main><div class="wrap" id="list"></div></main>

<footer><div class="wrap">
  Built __BUILD__ · __COUNT__ listings tracked · sources: Adzuna (aggregates employer sites, agencies &amp; smaller boards).
  "Likely" means a sponsorship/relocation keyword was found in the ad — always confirm in the listing before applying.
</div></footer>

<script>
const DATA = __DATA__;
const BUILD = new Date("__BUILD__T00:00:00");
const state = {days:"all", q:"", spons:"all"};

const dayMs = 86400000;
function daysAgo(iso){ return Math.round((BUILD - new Date(iso+"T00:00:00"))/dayMs); }
function addedLabel(d){ return d<=0?"today":d===1?"yesterday":d+" days ago"; }
function groupOf(d){
  if(d<=0) return ["0","Added today"];
  if(d===1) return ["1","Added yesterday"];
  if(d<=6) return ["2","Earlier this week"];
  if(d<=29) return ["3","Earlier this month"];
  return ["4","Older"];
}
function distText(j){
  if(j.distance_km==null) return "Distance unknown — check listing";
  const d = j.drive_hours!=null ? " · ~"+j.drive_hours+" h drive" : "";
  return Math.round(j.distance_km)+" km"+d;
}
const TIER={confirmed:"Sponsorship confirmed",likely:"Sponsorship likely",unknown:"Sponsorship unclear"};
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function render(){
  const max = state.days==="all" ? Infinity : +state.days;
  const q = state.q.trim().toLowerCase();
  const rows = DATA.filter(j=>{
    if(daysAgo(j.date_added) > max) return false;
    if(state.spons==="likely" && j.sponsorship==="unknown") return false;
    if(q){ const blob=(j.title+" "+j.company+" "+j.location).toLowerCase(); if(!blob.includes(q)) return false; }
    return true;
  });
  // stats
  const todayN = DATA.filter(j=>daysAgo(j.date_added)<=0).length;
  document.getElementById("stats").innerHTML =
    "<b>"+rows.length+"</b> shown · <b>"+todayN+"</b> added today";
  // group
  const order=["0","1","2","3","4"], titles={};
  const groups={};
  rows.forEach(j=>{ const [k,t]=groupOf(daysAgo(j.date_added)); (groups[k]=groups[k]||[]).push(j); titles[k]=t; });
  const list=document.getElementById("list");
  if(!rows.length){ list.innerHTML='<p class="empty">No listings match this filter. Try widening the date range or clearing the search — the board refreshes every morning.</p>'; return; }
  let html="";
  order.forEach(k=>{
    if(!groups[k]) return;
    html+='<section class="group"><h2>'+esc(titles[k])+' <span class="n">'+groups[k].length+'</span></h2>';
    groups[k].forEach(j=>{
      const tier=j.sponsorship||"unknown";
      html+='<article class="card">'+
        '<span class="pill '+tier+'">'+TIER[tier]+'</span>'+
        '<span class="added">Added '+addedLabel(daysAgo(j.date_added))+'</span>'+
        '<h3 class="title">'+esc(j.title)+'</h3>'+
        '<div class="org">'+(esc(j.company)||"Employer not listed")+' · '+(esc(j.location)||"—")+'</div>'+
        '<div class="dist">📍 '+esc(distText(j))+'</div>'+
        (j.description?'<p class="desc">'+esc(j.description)+'</p>':'<div style="height:8px"></div>')+
        '<a class="apply" href="'+esc(j.url)+'" target="_blank" rel="noopener">Apply</a>'+
        '<span class="src">'+esc(j.source)+(j.posted?' · posted '+esc(j.posted):'')+'</span>'+
      '</article>';
    });
    html+='</section>';
  });
  list.innerHTML=html;
}

document.getElementById("chips").addEventListener("click",e=>{
  const b=e.target.closest(".chip"); if(!b) return;
  [...document.querySelectorAll(".chip")].forEach(c=>c.setAttribute("aria-pressed","false"));
  b.setAttribute("aria-pressed","true");
  state.days=b.dataset.days; render();
});
document.getElementById("q").addEventListener("input",e=>{state.q=e.target.value;render();});
document.getElementById("spons").addEventListener("change",e=>{state.spons=e.target.value;render();});
render();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Persistent job database + daily webpage (GitHub Pages)
# ---------------------------------------------------------------------------
def update_jobs_db(matches):
    """Merge today's matches into a persistent store, stamping each job with the
    date it was first added to the page. Prunes listings not seen recently.
    Returns the listings sorted newest-added first, then nearest."""
    db = load_json(JOBS_DB, {})
    today = dt.date.today().isoformat()
    for j in matches:
        fields = dict(
            uid=j.uid, source=j.source, title=j.title, company=j.company,
            location=j.location, url=j.url, description=j.description[:280],
            distance_km=j.distance_km, drive_hours=j.drive_hours,
            sponsorship=j.sponsorship, posted=j.posted, last_seen=today,
        )
        if j.uid in db:
            fields["date_added"] = db[j.uid].get("date_added", today)
            db[j.uid].update(fields)
        else:
            fields["date_added"] = today
            db[j.uid] = fields

    retention = getattr(cfg, "RETENTION_DAYS", 45)
    cutoff = (dt.date.today() - dt.timedelta(days=retention)).isoformat()
    db = {u: e for u, e in db.items() if e.get("last_seen", "") >= cutoff}
    save_json(JOBS_DB, db)

    entries = sorted(db.values(),
                     key=lambda e: e["distance_km"] if e.get("distance_km") is not None else 1e9)
    entries.sort(key=lambda e: e.get("date_added", ""), reverse=True)  # stable
    return entries


def render_site(entries):
    os.makedirs(SITE_DIR, exist_ok=True)
    build_date = dt.date.today().isoformat()
    radius = getattr(cfg, "RADIUS_KM", "")
    city = getattr(cfg, "HOME_CITY", "")
    title = getattr(cfg, "SITE_TITLE", "Jobs with sponsorship")
    subtitle = getattr(cfg, "SITE_SUBTITLE", "").format(radius=radius, city=city)
    data_json = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")

    html_doc = _SITE_TEMPLATE
    for key, val in {
        "__TITLE__": html.escape(title),
        "__SUBTITLE__": html.escape(subtitle),
        "__BUILD__": build_date,
        "__COUNT__": str(len(entries)),
        "__DATA__": data_json,
    }.items():
        html_doc = html_doc.replace(key, val)

    with open(SITE_INDEX, "w", encoding="utf-8") as f:
        f.write(html_doc)


def send_email(html_body, count):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🍎 {count} new educator job{'s' if count != 1 else ''} (sponsorship) — {dt.date.today():%d %b}"
    msg["From"] = cfg.EMAIL_FROM
    msg["To"] = cfg.EMAIL_TO
    msg.attach(MIMEText("Open in an HTML-capable client to view your jobs.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    if int(cfg.SMTP_PORT) == 465:
        # implicit SSL from the start (QQ Mail / Foxmail, and many others)
        with smtplib.SMTP_SSL(cfg.SMTP_HOST, int(cfg.SMTP_PORT),
                              context=ssl.create_default_context()) as s:
            s.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
            s.sendmail(cfg.EMAIL_FROM, [cfg.EMAIL_TO], msg.as_string())
    else:
        # STARTTLS (Gmail 587, and QQ also supports 587)
        with smtplib.SMTP(cfg.SMTP_HOST, int(cfg.SMTP_PORT)) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
            s.sendmail(cfg.EMAIL_FROM, [cfg.EMAIL_TO], msg.as_string())
    print(f"  Emailed digest to {cfg.EMAIL_TO}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Daily early-educator job finder")
    ap.add_argument("--include-unknown", action="store_true",
                    help="also show jobs with no sponsorship signal")
    ap.add_argument("--no-email", action="store_true", help="don't send email")
    ap.add_argument("--no-web", action="store_true", help="don't build the webpage")
    ap.add_argument("--all", action="store_true",
                    help="show all current matches, not just new ones")
    ap.add_argument("--reset-seen", action="store_true",
                    help="forget previously-seen jobs (treat everything as new)")
    args = ap.parse_args()

    if args.reset_seen and os.path.exists(SEEN_FILE):
        os.remove(SEEN_FILE)
        print("Reset: cleared seen-jobs history.")

    include_unknown = args.include_unknown or cfg.INCLUDE_UNKNOWN_SPONSORSHIP

    print("Fetching jobs…")
    matches = collect(include_unknown)
    print(f"Matched {len(matches)} educator + sponsorship jobs in radius.")

    to_show = matches if args.all or not cfg.SHOW_ONLY_NEW else split_new(matches)
    if cfg.SHOW_ONLY_NEW and not args.all:
        print(f"{len(to_show)} are NEW since the last run.")

    title = "New early-educator jobs with sponsorship"
    html_body = render_html(to_show, title)
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_body)
    write_csv(to_show)
    print(f"Wrote {HTML_FILE} and {CSV_FILE}")

    if getattr(cfg, "WEB_ENABLED", False) and not args.no_web:
        entries = update_jobs_db(matches)
        render_site(entries)
        added_today = sum(1 for e in entries if e.get("date_added") == dt.date.today().isoformat())
        print(f"Wrote {SITE_INDEX} — {len(entries)} listings on the page, {added_today} added today.")

    if cfg.EMAIL_ENABLED and not args.no_email:
        try:
            send_email(html_body, len(to_show))
        except Exception as e:
            print(f"  ! Email failed: {_redact(e)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
