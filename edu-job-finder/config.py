"""
config.py  —  All the knobs for your daily early-educator job finder.

============================================================================
 CONFIGURED FOR: Schofields, NSW, Australia
============================================================================
 - "Sponsorship" = Australian employer visa sponsorship (e.g. 482 / TSS,
   186 / ENS, DAMA, regional sponsorship, relocation support).
 - "4-hour driving radius" is treated as a ~300 km straight-line radius from
   Schofields (4 h of NSW driving reaches roughly Newcastle, Canberra,
   Bathurst, Port Macquarie). Tune RADIUS_KM, or switch on the true
   drive-time check near the bottom.
 - Early Childhood Teacher is on Australia's skilled occupation lists, so
   centres genuinely do advertise sponsorship — the keyword scan looks for it.
============================================================================
"""

import os

# ---------------------------------------------------------------------------
# 1. WHERE YOU LIVE  (the centre of your search radius)
# ---------------------------------------------------------------------------
# To fine-tune, search your address on Google Maps, right-click -> the
# lat,lon is shown at the top of the menu. Paste it here.
HOME_CITY = "Schofields NSW"       # text location used for the Adzuna query
HOME_LAT  = -33.7050               # Schofields, NSW
HOME_LON  = 150.8770

# How far you'll travel, as a straight-line radius in km.
# 4 hours of NSW driving ~= 280-320 km straight-line.
RADIUS_KM = 300

# ---------------------------------------------------------------------------
# 2. WHAT YOU'RE LOOKING FOR
# ---------------------------------------------------------------------------
# A job matches if ANY of these (lowercase) appears in its title/description.
EDUCATOR_KEYWORDS = [
    "early childhood", "early learning", "early years",
    "early childhood educator", "early childhood teacher",
    "childcare educator", "child care educator", "childcare",
    "child care", "preschool", "pre-school", "kindergarten",
    "long day care", "outside school hours", "oshc", "vacation care",
    "family day care", "nursery", "diploma educator",
    "certificate iii educator", "cert iii", "room leader", "ect",
    "educational leader", "montessori", "toddler", "infant educator",
]

# If any of these appear in the TITLE, the job is dropped (kills false hits
# like "Physical Education Teacher" or unrelated "education" roles).
EXCLUDE_TITLE_KEYWORDS = [
    "physical education", "higher education", "adult education",
    "education sales", "education consultant", "special education teacher aide tafe",
    "tutor", "university", "lecturer",
]

# ---------------------------------------------------------------------------
# 3. SPONSORSHIP DETECTION  (keyword scan — Australian terms)
# ---------------------------------------------------------------------------
SPONSORSHIP_KEYWORDS = [
    "visa sponsorship", "sponsorship available", "willing to sponsor",
    "will sponsor", "we sponsor", "sponsor your visa", "employer sponsored",
    "employer sponsorship", "sponsored visa", "482 visa", "482",
    "tss visa", "subclass 482", "186 visa", "subclass 186", "ens",
    "skilled visa", "skills in demand", "sid visa", "dama",
    "regional sponsorship", "relocation", "relocate", "visa support",
    "work visa", "work rights sponsorship",
    "visa nomination", "employer nomination",  # was bare "nomination"
]

# Show jobs whose sponsorship status is UNKNOWN (no keyword)?
# Default False = only "likely". Override per-run with --include-unknown.
INCLUDE_UNKNOWN_SPONSORSHIP = False

# ---------------------------------------------------------------------------
# 4. DATA SOURCES
# ---------------------------------------------------------------------------
# -- Arbeitnow is a Europe/DACH board, so it's OFF for an Australia search.
USE_ARBEITNOW = False
ARBEITNOW_MAX_PAGES = 5

# -- Adzuna: free tier, covers Australia. Get a free app_id + app_key at
#    https://developer.adzuna.com/  and put them in env vars / a .env file.
USE_ADZUNA = True
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_COUNTRIES = ["au"]           # Australia
ADZUNA_MAX_PAGES = 3                # per query, 50 results/page
# The keyword searches sent to Adzuna (kept short to respect rate limits):
ADZUNA_QUERIES = [
    "early childhood educator", "early childhood teacher",
    "childcare educator", "preschool", "kindergarten teacher",
    "long day care educator",
]

# -- JSearch (OpenWeb Ninja, via RapidAPI): pulls from Google for Jobs, which
#    indexes Indeed, LinkedIn, Glassdoor, ZipRecruiter and more. Get a free key:
#      1. Sign up at https://rapidapi.com/  (free, no card)
#      2. Subscribe to the JSearch API "Basic" plan (free: 200 requests/month)
#      3. Copy your RapidAPI key into the JSEARCH_API_KEY env var / .env file
#    NOTE the 200/month free cap: keep JSEARCH_QUERIES short. Each query in
#    each run = 1 request, so 3 queries x 30 days = 90/month (safe).
# -- JSearch returned no Australian results on the free plan (Google for Jobs
#    AU coverage is sparse), so it's OFF. Flip to True if you ever search a
#    country where it works (US/UK/etc.). Keys/queries below are kept for that.
USE_JSEARCH = False
JSEARCH_API_KEY = os.environ.get("JSEARCH_API_KEY", "")
JSEARCH_HOST    = "jsearch.p.rapidapi.com"
JSEARCH_COUNTRY = "au"
# Location anchor appended to each query ("<term> in <location>"). Google for
# Jobs spreads out around a metro; your own radius filter trims the rest.
JSEARCH_LOCATION = "Sydney NSW"
JSEARCH_QUERIES = [
    "early childhood educator",
    "early childhood teacher",
    "childcare educator",
]
JSEARCH_NUM_PAGES   = 1            # pages per query (each page = 1 request)
JSEARCH_DATE_POSTED = "month"      # all | today | 3days | week | month

# ---------------------------------------------------------------------------
# 7. WEBPAGE OUTPUT (GitHub Pages)
# ---------------------------------------------------------------------------
# Builds a daily-updating webpage (docs/index.html) listing all current jobs,
# each tagged with the date it was first added to the page, filterable by that
# date in the browser. GitHub Pages serves the /docs folder for free.
WEB_ENABLED    = True
SITE_DIR       = os.environ.get("SITE_DIR", "docs")   # GitHub Pages -> /docs
SITE_TITLE     = "Early-childhood roles with sponsorship"
SITE_SUBTITLE  = "Updated daily · within {radius} km of {city}"
# Drop a listing from the page once it hasn't been seen for this many days
# (so filled/expired jobs fall off instead of lingering forever).
RETENTION_DAYS = 45

# ---------------------------------------------------------------------------
# 5. HOW RESULTS ARE DELIVERED
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", ".")
SHOW_ONLY_NEW = True               # only jobs not seen on previous runs

# -- Email the digest to yourself (optional). Fill these in to enable.
#    For Gmail: create an "App Password" (Google account -> Security ->
#    2-Step Verification -> App passwords) and use that, NOT your login.
EMAIL_ENABLED   = bool(os.environ.get("EMAIL_TO"))
EMAIL_TO        = os.environ.get("EMAIL_TO", "")
EMAIL_FROM      = os.environ.get("EMAIL_FROM") or os.environ.get("SMTP_USER", "")
SMTP_HOST       = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT       = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER       = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD   = os.environ.get("SMTP_PASSWORD", "")

# ---------------------------------------------------------------------------
# 6. OPTIONAL: true driving-time check (instead of straight-line radius)
# ---------------------------------------------------------------------------
# Free key at https://openrouteservice.org/dev/ . When set, jobs are kept only
# if real road drive time <= MAX_DRIVE_HOURS. Off by default (adds an API call
# per job; free key has daily limits).
DRIVE_TIME_CHECK   = bool(os.environ.get("ORS_API_KEY"))
ORS_API_KEY        = os.environ.get("ORS_API_KEY", "")
MAX_DRIVE_HOURS    = 4.0

# Used for the *estimated* drive time shown on each card when the real check
# is off: straight_km * ROAD_FACTOR / AVG_KMH.
ROAD_FACTOR = 1.3
AVG_KMH     = 85
