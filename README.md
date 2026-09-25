# Cambridge Record — Local Pipeline
## Setup instructions for your MacBook

This folder contains the scripts that pull data from Cablecast and
push it to mediatechaction.com. Everything runs on your Mac.

---

## First-time setup (do this once)

Open Terminal, navigate to this folder, and run:

```
chmod +x setup.sh
./setup.sh
```

That creates a Python environment and copies `.env.template` to `.env`.

---

## Fill in your credentials

Open `.env` in any text editor (TextEdit works, or VS Code).
Fill in every line that says `FILL_IN_THIS`:

- `CABLECAST_BASE_URL` — your Cablecast server address
- `CABLECAST_API_KEY` — from Cablecast admin → Settings → API
- `SCHOOL_COMMITTEE_SHOW_ID` — run `python find_show_id.py` to find this
- `WP_USERNAME` — your mediatechaction.com WordPress username
- `WP_APP_PASSWORD` — from WP admin → Users → Profile → Application Passwords

---

## Every time you open a new Terminal window

Before running any script, activate the Python environment:

```
source venv/bin/activate
```

You'll see `(venv)` appear at the start of your Terminal prompt.
That means Python is ready.

---

## Step-by-step: first run

```
source venv/bin/activate

# 1. Find your Cablecast Show ID (run once, then add to .env)
python find_show_id.py

# 2. Confirm WordPress is connected and the plugin is working
python test_api.py

# 3. Test the Cablecast ingestion on ONE meeting
python ingest_cablecast.py --limit 1

# 4. If that looks good, run on all meetings
python ingest_cablecast.py
```

Ingest also pulls the agenda (and votes, if minutes are posted) from the
CPS portal. Minutes usually appear weeks later — pick them up with:

```
python enrich_meetings.py --all
```

---

## Files in this folder

| File | What it does |
|---|---|
| `.env` | Your credentials — never share this |
| `.env.template` | Blank template — safe to share |
| `requirements.txt` | List of Python libraries |
| `setup.sh` | First-time setup script |
| `find_show_id.py` | Finds your Cablecast Show ID |
| `test_api.py` | Tests WordPress connection |
| `ingest_cablecast.py` | Main pipeline — pulls from Cablecast, pushes to WordPress |
| `scrape_agenda.py` | Finds a meeting on the CPS portal by Cablecast show ID and parses its agenda |
| `parse_minutes.py` | Parses official votes (motion, mover, roll call) from a minutes PDF |
| `match_agenda.py` | Places votes, agenda items and sections on the video timeline using the captions |
| `enrich_meetings.py` | Adds agenda + official votes to ingested meetings, with video times (re-run to pick up late minutes) |
| `officials.json` | School Committee roster (names, titles, terms, subcommittees, name as written in the minutes) |
| `sync_officials.py` | Creates/updates Official pages in WordPress from `officials.json` |
| `pipeline.db` | Local database tracking what's been ingested (created automatically) |
| `pipeline.log` | Log of all pipeline runs (created automatically) |
