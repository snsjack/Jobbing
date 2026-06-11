# Daily early-educator job finder (with visa sponsorship)

Scours job boards every day for **early-childhood / educator roles that offer
visa sponsorship**, keeps only the ones **within driving range of your home**,
removes duplicates, and serves you a clean digest (HTML + CSV, optionally
emailed). Built to run unattended on a daily schedule.

**Configured for Schofields, NSW, Australia.**

## What it does

- Pulls live listings from two free sources:
  - **Adzuna** (free tier, covers Australia, returns coordinates).
  - **JSearch** (free tier via RapidAPI) — pulls from **Google for Jobs**,
    which indexes **Indeed, LinkedIn, Glassdoor, ZipRecruiter** and more, so a
    single key reaches the big boards indirectly. Bonus: it returns the *full*
    job description, so sponsorship detection is more accurate than on Adzuna's
    snippets. Each result is tagged with the board it came from.
  - *(A third source, Arbeitnow, is built in but only covers Europe, so it's
    switched off for an Australia search.)*
- Flags listings whose text mentions sponsorship/relocation/482/186 etc. as
  **🟡 Sponsorship likely**; the rest are **⚪ unclear**.
- Filters to early-childhood roles using Australian terminology
  (ECT, educator, long day care, OSHC, Cert III/Diploma, preschool, …).
- Geofilters by distance from Schofields, dedupes across sources (the same job
  on Adzuna and JSearch collapses to one), and estimates drive time.
- **Publishes a daily-updating webpage** (`docs/index.html`) listing every
  current role, each stamped with the date it was added to the page and
  filterable by that date (Today / 3 / 7 / 30 days / All) plus search. Hosted
  free on GitHub Pages. Can also email a digest instead, if you prefer.
- Remembers what it already showed you, so each digest is only **new** jobs.
- Writes `digest.html` + `jobs.csv`, and can **email** them to you.

> Open `sample_digest.html` to see what a daily digest looks like.

## Assumptions baked into the defaults (edit in `config.py`)

1. Home base = **Schofields, NSW** (≈ -33.705, 150.877) → set `HOME_LAT` /
   `HOME_LON` to your exact address if you want.
2. "4-hour radius" ≈ **300 km** straight-line (reaches ~Newcastle, Canberra,
   Bathurst, Port Macquarie) → tune `RADIUS_KM`, or switch on the real
   driving-time check (free OpenRouteService key).
3. Searches **Australia** on Adzuna (`ADZUNA_COUNTRIES = ["au"]`).
4. "Sponsorship" = Australian employer visa sponsorship (482/TSS, 186/ENS,
   DAMA, regional, relocation support). Early Childhood Teacher is on the
   skilled lists, so this is a realistic ask.

## Quick start (run it once on your computer)

```bash
pip install -r requirements.txt

# get a free Adzuna key at https://developer.adzuna.com/  then:
export ADZUNA_APP_ID=your_id
export ADZUNA_APP_KEY=your_key

# (recommended) free JSearch key: https://rapidapi.com/ -> search "JSearch"
# -> Subscribe to the free Basic plan -> copy your key:
export JSEARCH_API_KEY=your_rapidapi_key

python job_finder.py
```

Open the generated `digest.html`. Useful flags:

| Flag                 | Effect                                             |
|----------------------|----------------------------------------------------|
| `--include-unknown`  | also show roles with no clear sponsorship signal   |
| `--all`              | show every current match, not just new ones        |
| `--no-email`         | generate files but don't send email                |
| `--reset-seen`       | forget history (everything counts as new again)    |

It works with either key on its own, or both together. With no keys at all
you'll get nothing (the Europe-only source is off), so set at least one.

## Get it emailed to you daily

Fill in the email block in `config.py` (or set the env vars in `.env`). For
Gmail, create an **App Password** (Google Account → Security → 2-Step
Verification → App passwords) and use that as `SMTP_PASSWORD`.

### Option A — daily webpage on GitHub Pages (recommended, free, hands-off)

The included workflow (`.github/workflows/daily-jobs.yml`) runs each morning,
rebuilds `docs/index.html`, and commits it back to the repo. GitHub Pages
serves that folder as your live site. The daily commit also keeps the repo
"active", so the schedule never hits GitHub's 60-day idle shut-off.

1. Create a GitHub repo and push this folder to it (or use "Use this template").
2. Add your keys under **Settings → Secrets and variables → Actions**:
   `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` (plus `JSEARCH_API_KEY` / `ORS_API_KEY`
   only if you use them).
3. **Actions** tab → run **"Daily job site"** once (Run workflow). This creates
   `docs/index.html`.
4. **Settings → Pages** → Source: **Deploy from a branch** → Branch: **main**,
   Folder: **/docs** → Save.
5. Your board is live at `https://<your-username>.github.io/<repo-name>/`.
   It refreshes every morning; new jobs appear under "Added today".

To change the daily time, edit the `cron` line (it's in UTC). To email a
digest *instead of / as well as* the page, add the email secrets (below) and
drop the `--no-email` flag from the workflow.

### Option B — email digest

Fill in the email block in `config.py` (or set the env vars in `.env`). For
Gmail, create an **App Password** (Google Account → Security → 2-Step
Verification → App passwords) and use that as `SMTP_PASSWORD`. For a
Foxmail/QQ address, use `smtp.qq.com`, port `465`, and an **authorization
code** (generated in QQ Mail's web settings) as the password.

### Option B — runs on your own machine

**macOS / Linux (cron):**
```bash
crontab -e
# run daily at 07:00 (adjust the path):
0 7 * * * cd /path/to/edu-job-finder && /usr/bin/python3 job_finder.py >> run.log 2>&1
```

**Windows (Task Scheduler):** create a Basic Task → Daily → Action "Start a
program" → program `python`, arguments `job_finder.py`, "Start in" set to this
folder.

## Files

```
config.py                 all settings & assumptions (start here)
job_finder.py             the program
requirements.txt          dependency (requests)
.env.example              template for keys/secrets
sample_digest.html        preview of the output
.github/workflows/        daily cloud schedule (GitHub Actions)
```

## Honest limits

- **No Australian free API cleanly tags "sponsorship,"** so sponsorship is
  detected by scanning each listing's text for terms like "visa sponsorship",
  "482", "186", "employer sponsored", "relocation". Jobs are therefore flagged
  **🟡 likely** rather than confirmed — **always confirm sponsorship in the
  actual ad** before applying. Run with `--include-unknown` now and then to
  surface borderline roles worth checking by hand.
- Adzuna returns only a description snippet, so a genuine sponsorship offer
  whose keyword sits deeper in the ad can be missed.
- Seek/Jora dominate Australian childcare listings but have no free API. You
  can supplement this with a saved Seek email alert, or add another `fetch_*()`
  source in `collect()` — the rest of the pipeline handles it.
