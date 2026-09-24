# Cambridge Record — Pipeline Specification
## For Claude Code / AI-assisted development

This document specifies the local Python pipeline that ingests Cambridge
School Committee meeting data from Cablecast and pushes it to WordPress.
Runs on Matt's MacBook Pro (M4, 24GB RAM). No server-side compute needed
on DreamHost.

---

## Confirmed technical details (do not second-guess these)

These were verified against the actual Cambridge Cablecast instance:

| Question | Answer |
|---|---|
| Timestamp deep-links | ✅ `?t=83` (integer seconds) appended to VOD URL |
| API authentication | ✅ API key, Matt has one, has used it in prior Python scripts |
| Caption format for web | ✅ WebVTT (.vtt) — auto-generated from SCC for web playback |
| Caption API location | VOD/Media endpoint, not Show record |
| VTT query path | VOD record → media/captions endpoint → .vtt download URL |
| SCC files | Available on Show record as raw attachments if needed, but VTT is preferred for this pipeline |

**Use WebVTT, not SCC.** VTT is served by the web player, is simpler
to parse, and is already timestamped in HH:MM:SS.mmm format.
The pipeline never needs to deal with SCC frame-rate math.

**Timestamp links:** Every segment deep-link is:
`{cablecast_vod_base_url}?t={start_seconds_integer}`
e.g. `https://cambridge.cablecast.tv/vod/1234?t=3661`

---

## Environment

- Python 3.12+
- Virtual environment at `./venv`
- Configuration in `.env` (never committed to git)
- Local SQLite database `pipeline.db` tracks ingestion state
  (allows safe re-runs, avoids duplicate WordPress records)

### `.env` structure

```
CABLECAST_BASE_URL=https://[cambridge-cablecast-host]/cablecastapi/v1
CABLECAST_API_KEY=[key]
SCHOOL_COMMITTEE_SHOW_ID=[id]
WP_BASE_URL=https://[domain]/wp-json/wp/v2
WP_USERNAME=[wordpress-username]
WP_APP_PASSWORD=[wordpress-application-password]
CPS_MEETINGS_URL=https://www.cpsd.us/school_committee/school_committee_meetings
```

**SCHOOL_COMMITTEE_SHOW_ID:** The Cablecast Show ID for "Cambridge School
Committee." Locate this by querying `/cablecastapi/v1/shows` and filtering
by name, or by finding it in the Cablecast admin UI.

### Dependencies (`requirements.txt`)

```
requests==2.32.3
beautifulsoup4==4.12.3
python-dotenv==1.0.1
lxml==5.2.2
```

No `pycaption` needed — WebVTT is parsed with stdlib (see below).

---

## Phase 2 — Cablecast ingestion (`ingest_cablecast.py`)

### Step 1: List School Committee VODs

```python
import os, requests, sqlite3, time, re
from dotenv import load_dotenv
load_dotenv()

BASE = os.environ['CABLECAST_BASE_URL']
KEY  = os.environ['CABLECAST_API_KEY']
HEADERS = {'X-API-Key': KEY}
# NOTE: confirm actual auth header name against Cambridge Cablecast
# instance — may be 'Authorization: Bearer {key}' depending on version

def get_school_committee_vods() -> list[dict]:
    """
    Returns all VODs associated with the School Committee show,
    newest first, with their base embed URLs.
    """
    show_id = os.environ['SCHOOL_COMMITTEE_SHOW_ID']
    vods = []
    page = 1

    while True:
        resp = requests.get(
            f"{BASE}/vods",
            headers=HEADERS,
            params={
                'showId': show_id,
                'page': page,
                'per_page': 50,
                'sort': 'date',
                'direction': 'desc',
            }
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get('vods', data)  # handle both wrapped and bare responses

        if not batch:
            break

        vods.extend(batch)
        if len(batch) < 50:
            break
        page += 1

    return vods
```

### Step 2: Get the WebVTT caption URL for a VOD

```python
def get_vtt_url(vod_id: int) -> str | None:
    """
    Queries the VOD media/captions endpoint and returns the WebVTT
    download URL, or None if no captions are available.
    """
    # Try the captions sub-endpoint first
    resp = requests.get(
        f"{BASE}/vods/{vod_id}/captions",
        headers=HEADERS
    )

    if resp.status_code == 200:
        data = resp.json()
        # Look for a .vtt entry in the response
        captions = data if isinstance(data, list) else data.get('captions', [])
        for cap in captions:
            url = cap.get('url', '') or cap.get('path', '')
            if url.endswith('.vtt'):
                return url

    # Fallback: check the VOD record's media attachments directly
    resp2 = requests.get(f"{BASE}/vods/{vod_id}", headers=HEADERS)
    if resp2.status_code == 200:
        vod = resp2.json()
        # Cablecast may nest caption URL in different fields depending on version
        # Check common locations:
        for key in ['captionUrl', 'vttUrl', 'webVttUrl', 'captions']:
            val = vod.get(key)
            if val and isinstance(val, str) and '.vtt' in val:
                return val

    return None  # No captions available for this VOD
```

### Step 3: Parse WebVTT into timestamped segments

WebVTT is a simple plain-text format. No library needed.

```
WEBVTT

00:00:05.000 --> 00:00:09.500
Good evening, and welcome to the Cambridge School Committee meeting.

00:00:09.500 --> 00:00:14.200
We'll begin with roll call. Chair Jones?
```

```python
def parse_vtt(vtt_text: str) -> list[dict]:
    """
    Parses WebVTT content into a list of timed text segments.
    Returns list of dicts: {start_seconds, end_seconds, text}

    Handles multi-line cues and strips VTT positioning tags (<c>, <v>).
    """
    segments = []
    blocks = vtt_text.strip().split('\n\n')

    TIME_RE = re.compile(
        r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+-->\s+'
        r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})'
    )
    TAG_RE = re.compile(r'<[^>]+>')

    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue

        # Find the timestamp line
        ts_line = None
        ts_idx = None
        for i, line in enumerate(lines):
            if '-->' in line:
                ts_line = line
                ts_idx = i
                break

        if ts_line is None:
            continue  # WEBVTT header or empty block

        m = TIME_RE.search(ts_line)
        if not m:
            continue

        def to_seconds(h, m, s, ms):
            return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

        start = to_seconds(m.group(1), m.group(2), m.group(3), m.group(4))
        end   = to_seconds(m.group(5), m.group(6), m.group(7), m.group(8))

        # Everything after the timestamp line is the caption text
        text_lines = lines[ts_idx + 1:]
        text = ' '.join(text_lines).strip()
        text = TAG_RE.sub('', text).strip()  # strip <v Speaker>, <c> tags

        if text:
            segments.append({
                'start_seconds': round(start, 1),
                'end_seconds': round(end, 1),
                'text': text,
            })

    return segments
```

### Step 4: Build the Cablecast embed URL

```python
def build_embed_url(vod: dict) -> str:
    """
    Constructs the Cablecast embed URL from a VOD record.
    Adjust field names to match the actual API response.
    """
    host = os.environ['CABLECAST_BASE_URL'].split('/cablecastapi')[0]
    vod_id = vod['id']

    # Cablecast embed URLs are typically one of:
    # https://[host]/vod/[id]                  (direct VOD link)
    # https://[host]/live/[channel]            (live stream)
    # https://[host]/CablecastPublicSite/embed/[id]  (older installs)
    # Confirm the correct pattern against the Cambridge instance.

    return f"{host}/vod/{vod_id}"


def build_timestamped_url(vod: dict, seconds: float) -> str:
    """
    Returns a URL that starts playback at the given time.
    Uses ?t=83 format (integer seconds) — confirmed working on Cablecast.
    """
    base = build_embed_url(vod)
    return f"{base}?t={int(seconds)}"
```

### Step 5: Push to WordPress

```python
WP_BASE = os.environ['WP_BASE_URL']
WP_AUTH = (os.environ['WP_USERNAME'], os.environ['WP_APP_PASSWORD'])


def create_wp_meeting(vod: dict, segment_count: int) -> int:
    """Creates a meeting post in WordPress. Returns WP post ID."""

    # Extract date from VOD — field name varies by Cablecast version
    # Common options: vod['eventDate'], vod['show']['date'], vod['createdAt']
    date_str = (
        vod.get('eventDate') or
        vod.get('show', {}).get('date') or
        vod.get('createdAt', '')[:10]
    )

    payload = {
        'title': f"School Committee Meeting — {date_str}",
        'status': 'draft',   # humans review before publishing
        'acf': {
            'meeting_date': date_str,
            'meeting_body': 'Cambridge School Committee',
            'cablecast_vod_id': vod['id'],
            'cablecast_embed_url': build_embed_url(vod),
            'segment_count': segment_count,
            'status': 'processing',
            'summary_origin': 'pending',
        }
    }
    resp = requests.post(
        f"{WP_BASE}/meeting",
        json=payload,
        auth=WP_AUTH
    )
    resp.raise_for_status()
    return resp.json()['id']


def push_segments_to_wp(wp_meeting_id: int, segments: list[dict],
                         vod: dict):
    """Pushes all segments for a meeting. Batched with rate limiting."""

    for i, seg in enumerate(segments):
        payload = {
            'title': f"Segment {i:05d}",
            'status': 'publish',
            'acf': {
                'parent_meeting': wp_meeting_id,
                'start_seconds': seg['start_seconds'],
                'end_seconds': seg['end_seconds'],
                'text': seg['text'],
                'segment_index': i,
                'is_vote': False,   # set later by detect_votes.py
                'deep_link_url': build_timestamped_url(vod, seg['start_seconds']),
            }
        }
        resp = requests.post(
            f"{WP_BASE}/segment",
            json=payload,
            auth=WP_AUTH
        )
        resp.raise_for_status()

        if i % 50 == 0 and i > 0:
            time.sleep(1)
            print(f"    {i}/{len(segments)} segments pushed")
```

### Step 6: Local state tracking

```python
def init_db(conn: sqlite3.Connection):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingested_vods (
            cablecast_vod_id INTEGER PRIMARY KEY,
            wp_meeting_id    INTEGER,
            vod_date         TEXT,
            segment_count    INTEGER,
            ingested_at      TEXT,
            status           TEXT
        )
    ''')
    conn.commit()


def already_ingested(conn: sqlite3.Connection, vod_id: int) -> bool:
    row = conn.execute(
        "SELECT status FROM ingested_vods WHERE cablecast_vod_id = ?",
        (vod_id,)
    ).fetchone()
    return row is not None and row[0] == 'complete'


def mark_ingested(conn: sqlite3.Connection, vod_id: int,
                   wp_id: int, date: str, count: int):
    conn.execute('''
        INSERT OR REPLACE INTO ingested_vods
        VALUES (?, ?, ?, ?, datetime('now'), 'complete')
    ''', (vod_id, wp_id, date, count))
    conn.commit()
```

### Step 7: Main entry point

```python
def main():
    conn = sqlite3.connect('pipeline.db')
    init_db(conn)

    print("Fetching School Committee VODs from Cablecast...")
    vods = get_school_committee_vods()
    print(f"Found {len(vods)} VODs")

    for vod in vods:
        vod_id = vod['id']

        if already_ingested(conn, vod_id):
            print(f"  Skipping VOD {vod_id} (already ingested)")
            continue

        print(f"\nProcessing VOD {vod_id}...")

        vtt_url = get_vtt_url(vod_id)
        if not vtt_url:
            print(f"  No captions found for VOD {vod_id} — skipping")
            continue

        vtt_resp = requests.get(vtt_url, headers=HEADERS)
        vtt_resp.raise_for_status()
        segments = parse_vtt(vtt_resp.text)

        if not segments:
            print(f"  Empty transcript for VOD {vod_id} — skipping")
            continue

        print(f"  Parsed {len(segments)} segments")

        wp_id = create_wp_meeting(vod, len(segments))
        print(f"  Created WordPress meeting post ID {wp_id}")

        push_segments_to_wp(wp_id, segments, vod)
        mark_ingested(conn, vod_id, wp_id,
                      vod.get('eventDate', '')[:10], len(segments))

        print(f"  Done. VOD {vod_id} → WP post {wp_id}")
        time.sleep(2)  # brief pause between meetings

    print("\nIngestion complete.")
    conn.close()


if __name__ == '__main__':
    main()
```

---

## Phase 3a — Agenda scraper (`scrape_agenda.py`)

**Before building:** inspect the HTML source of a CPS School Committee
meeting page to identify the correct CSS selectors. The structure below
is a placeholder — selectors marked `# TODO` must be filled in from
the actual page.

```python
from bs4 import BeautifulSoup
import requests, os
from dotenv import load_dotenv
load_dotenv()


def get_meeting_urls() -> list[dict]:
    """Scrapes the CPS meetings index and returns list of meeting pages."""
    resp = requests.get(os.environ['CPS_MEETINGS_URL'])
    soup = BeautifulSoup(resp.text, 'lxml')

    meetings = []
    # TODO: inspect CPS website HTML and fill in correct selector
    # for links = soup.select('[CSS selector for meeting page links]'):
    #     meetings.append({
    #         'url': link['href'],
    #         'date': link.text.strip(),
    #     })

    return meetings


def scrape_agenda_items(meeting_url: str) -> list[dict]:
    """
    Scrapes a single CPS meeting page and returns agenda items.
    Each item: {item_number, title, support_doc_url}
    """
    resp = requests.get(meeting_url)
    soup = BeautifulSoup(resp.text, 'lxml')

    items = []
    # TODO: fill in selectors after inspecting the actual page HTML
    # for row in soup.select('[agenda item selector]'):
    #     items.append({
    #         'item_number': row.select_one('[number selector]').text.strip(),
    #         'title': row.select_one('[title selector]').text.strip(),
    #         'support_doc_url': row.select_one('a')['href'] if row.select_one('a') else None,
    #     })

    return items
```

---

## Phase 3b — Agenda-to-transcript matching (`match_agenda.py`)

```python
def match_agenda_to_segments(
    agenda_items: list[dict],
    segments: list[dict]
) -> list[dict]:
    """
    For each agenda item, finds the best matching transcript segment
    by searching for the item number or title keywords.
    Sets start_seconds where matched; flags unmatched for manual review.
    """
    for item in agenda_items:
        search_terms = [
            item['item_number'].strip(),
            item['title'][:50].lower(),
        ]

        for seg in segments:
            seg_text = seg['text'].lower()
            if any(t.lower() in seg_text for t in search_terms if t):
                item['start_seconds'] = seg['start_seconds']
                item['matched'] = True
                break
        else:
            item['matched'] = False  # needs manual review

    unmatched = [i for i in agenda_items if not i.get('matched')]
    if unmatched:
        print(f"Warning: {len(unmatched)} agenda items not matched "
              f"— review manually: {[i['title'] for i in unmatched]}")

    return agenda_items
```

---

## Phase 3c — Roll call detector (`detect_votes.py`)

No AI. Pure pattern matching on Cambridge School Committee language.

```python
import re

VOTE_TRIGGER_PATTERNS = [
    r'\ball in favor\b',
    r'\broll call vote\b',
    r'\bmove(?:d)? (?:to )?(?:approve|adopt|accept|table|postpone)\b',
    r'\bmotion (?:passes|carries|fails|is (?:approved|adopted))\b',
    r'\bunanimously (?:approved|adopted|passed|voted)\b',
    r'\b(\d)\s+(?:in favor|yes|aye)\b',
    r'\bvote[sd]?\s+(\d+)\s*(?:to|–|-)?\s*(\d+)\b',
]

COUNT_RE = re.compile(r'(\d+)\s*(?:to|–|-)\s*(\d+)')


def detect_votes(segments: list[dict]) -> list[dict]:
    """
    Returns a list of vote dicts detected in the transcript.
    Each vote: {segment_index, start_seconds, raw_context,
                vote_for, vote_against, result}
    """
    votes = []

    for i, seg in enumerate(segments):
        text = seg['text'].lower()
        triggered = any(re.search(p, text) for p in VOTE_TRIGGER_PATTERNS)

        if not triggered:
            continue

        # Grab context window: 4 segments before and after
        ctx_start = max(0, i - 4)
        ctx_end   = min(len(segments), i + 5)
        context   = ' '.join(s['text'] for s in segments[ctx_start:ctx_end])

        vote = {
            'segment_index': i,
            'start_seconds': seg['start_seconds'],
            'raw_context': context,
            'vote_for': None,
            'vote_against': None,
            'result': 'unknown',
        }

        # Extract vote counts
        count_match = COUNT_RE.search(context.lower())
        if count_match:
            vote['vote_for']     = int(count_match.group(1))
            vote['vote_against'] = int(count_match.group(2))

        # Determine result
        if re.search(r'unanimously', context, re.I):
            vote['result'] = 'passes'
        elif re.search(r'(?:motion )?fails\b', context, re.I):
            vote['result'] = 'fails'
        elif re.search(r'(?:motion (?:passes|carries)|approved|adopted)', context, re.I):
            vote['result'] = 'passes'

        votes.append(vote)

    return votes
```

---

## Running the pipeline

```bash
# First time only
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Phase 2: ingest meetings from Cablecast
python ingest_cablecast.py

# Phase 3: add structure
python scrape_agenda.py      # scrape CPS website for agenda items
python match_agenda.py       # match agenda items to transcript timestamps
python detect_votes.py       # extract roll calls and vote counts

# Review in WordPress admin, then publish manually
```

---

## Error handling rules (follow these strictly)

- **Never modify Cablecast data.** Read-only.
- **Check `pipeline.db` before every VOD** to prevent duplicate records.
- **Log everything** to `pipeline.log` with timestamps and VOD IDs.
- **On failure,** record `status='failed'` in `pipeline.db` with the
  error message. The main loop catches exceptions per-VOD and continues.
- **WordPress status stays `draft`** until a human publishes it.
  The pipeline never calls `status: publish` on a meeting.
- **All field names from the Cablecast API response** are treated as
  potentially wrong until tested. Log the raw response for the first
  VOD and confirm field names before processing the full archive.
