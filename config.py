"""
config.py  —  Settings for your daily early-educator job finder.

Now supports MULTIPLE LOCATIONS ("profiles"). Each location carries its own
coordinates, radius, country, sources, and (language-specific) keywords, so
switching location automatically switches which job sources are used:

  - Sydney / Schofields (Australia)      -> Adzuna (au)
  - Ludwigsburg / Baden-Württemberg (DE) -> Arbeitnow (DACH, has a real
                                            visa-sponsorship flag) + Adzuna (de/fr/at)

The daily build runs every location in ACTIVE_LOCATIONS and produces ONE
webpage with a location filter so you can switch between them in the browser.
"""

import os

# ===========================================================================
#  LOCATION PROFILES  — add/edit freely
# ===========================================================================
# Coordinates: search your town on Google Maps, right-click -> copy lat,lon.
LOCATIONS = [
    {
        "id": "sydney",
        "label": "Sydney · Schofields",
        "home_city": "Schofields NSW",        # text location for Adzuna
        "home_lat": -33.7050,
        "home_lon": 150.8770,
        "radius_km": 300,                      # ~4 h NSW driving
        "use_arbeitnow": False,                # Arbeitnow has no AU coverage
        "use_adzuna": True,
        "adzuna_countries": ["au"],
        "adzuna_queries": [
            "early childhood educator", "early childhood teacher",
            "childcare educator", "preschool", "kindergarten teacher",
            "long day care educator",
        ],
        "educator_keywords": [
            "early childhood", "early learning", "early years",
            "early childhood educator", "early childhood teacher",
            "childcare educator", "child care educator", "childcare",
            "child care", "preschool", "pre-school", "kindergarten",
            "long day care", "outside school hours", "oshc", "vacation care",
            "family day care", "nursery", "diploma educator", "cert iii",
            "room leader", "ect", "educational leader", "montessori",
            "toddler", "infant educator",
        ],
        "exclude_title_keywords": [
            "physical education", "higher education", "adult education",
            "tutor", "university", "lecturer",
        ],
        "sponsorship_keywords": [
            "visa sponsorship", "sponsorship available", "willing to sponsor",
            "will sponsor", "we sponsor", "sponsor your visa", "employer sponsored",
            "employer sponsorship", "sponsored visa", "482 visa", "482",
            "tss visa", "subclass 482", "186 visa", "subclass 186", "ens",
            "skilled visa", "skills in demand", "sid visa", "dama",
            "regional sponsorship", "relocation", "relocate", "visa support",
            "work visa", "visa nomination", "employer nomination",
        ],
    },
]

# Which locations to build. Default: all of them. Override with the LOCATION
# env var (e.g. LOCATION=sydney) or the --location flag to build just one.
ACTIVE_LOCATIONS = os.environ.get("LOCATION", "").split(",") if os.environ.get("LOCATION") \
    else [loc["id"] for loc in LOCATIONS]

# ===========================================================================
#  SOURCES — shared settings & API keys
# ===========================================================================
ARBEITNOW_MAX_PAGES = 5            # ~100 jobs per page (DACH)

# Adzuna: free key from https://developer.adzuna.com/
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_MAX_PAGES = 3               # per query, 50 results/page

# JSearch: off (no useful AU coverage on the free plan). See git history.
USE_JSEARCH = False
JSEARCH_API_KEY = os.environ.get("JSEARCH_API_KEY", "")
JSEARCH_HOST    = "jsearch.p.rapidapi.com"

# Show roles with no sponsorship keyword (so the page's sponsorship filter has
# both tiers to toggle between). True = include them; the page filters client-side.
INCLUDE_UNKNOWN_SPONSORSHIP = True

# ===========================================================================
#  WEBPAGE OUTPUT (GitHub Pages)
# ===========================================================================
WEB_ENABLED    = True
SITE_DIR       = os.environ.get("SITE_DIR", "docs")
SITE_TITLE     = "Early-childhood roles with sponsorship"
SITE_SUBTITLE  = "Updated daily · filter by location, date added, and posting date"
RETENTION_DAYS = 45                # drop listings not seen for this many days

# --- Windows-XP-style shell ------------------------------------------------
# A login screen (cosmetic only — static hosting can't truly gate the page)
# leading to an XP desktop of "project" icons. Each project opens in a window.
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "educator")   # change me (ASCII)
SITE_USER     = "Educator"                                    # name on the login tile
PROJECTS = [
    {"id": "jobs", "name": "Early Educator Jobs", "icon": "🍎", "kind": "board"},
    {"id": "readme", "name": "Read Me", "icon": "📄", "kind": "note",
     "note": "Welcome to the desktop.\n\nDouble-click a project icon to open it.\n\n"
             "“Early Educator Jobs” is a live board that refreshes every morning."},
    # Add more, e.g.:
    # {"id":"site","name":"Portfolio","icon":"🌐","kind":"link","target":"https://example.com"},
]

# ===========================================================================
#  EMAIL (optional alternative to the webpage)
# ===========================================================================
OUTPUT_DIR      = os.environ.get("OUTPUT_DIR", ".")
SHOW_ONLY_NEW   = True
EMAIL_ENABLED   = bool(os.environ.get("EMAIL_TO"))
EMAIL_TO        = os.environ.get("EMAIL_TO", "")
EMAIL_FROM      = os.environ.get("EMAIL_FROM") or os.environ.get("SMTP_USER", "")
SMTP_HOST       = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT       = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER       = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD   = os.environ.get("SMTP_PASSWORD", "")

# ===========================================================================
#  OPTIONAL: true driving-time check (OpenRouteService) — shared
# ===========================================================================
DRIVE_TIME_CHECK   = bool(os.environ.get("ORS_API_KEY"))
ORS_API_KEY        = os.environ.get("ORS_API_KEY", "")
MAX_DRIVE_HOURS    = 4.0
ROAD_FACTOR = 1.3
AVG_KMH     = 85
