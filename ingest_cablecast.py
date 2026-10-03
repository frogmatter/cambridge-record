"""
Cambridge Record — Cablecast Ingestion Pipeline
Pulls School Committee meeting data from Cablecast, parses transcripts,
and pushes structured records to WordPress on mediatechaction.com.

Usage:
    source venv/bin/activate
    python ingest_cablecast.py              # ingest all new meetings
    python ingest_cablecast.py --limit 1    # test on one meeting only
    python ingest_cablecast.py --show 11522 # ingest one specific show ID
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from fetch_captions import fetch_hls_captions
from scrape_agenda import FULL_COMMITTEE, find_portal_meeting, meeting_title

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────

CABLECAST_BASE  = os.environ['CABLECAST_BASE_URL'].rstrip('/')
REFLECT_BASE    = 'https://reflect-video-ondemand-cpsd.cablecast.tv'
SHOW_ID         = int(os.environ['SCHOOL_COMMITTEE_SHOW_ID'])
WP_BASE         = os.environ['WP_BASE_URL'].rstrip('/')
WP_AUTH         = (os.environ['WP_USERNAME'], os.environ['WP_APP_PASSWORD'])
DB_PATH         = Path(__file__).parent / 'pipeline.db'
LOG_PATH        = Path(__file__).parent / 'pipeline.log'

LANGUAGES = {
    'en': 'English',
    'am': 'Amharic',
    'ar': 'Arabic',
    'bn': 'Bengali',
    'ht': 'Haitian Creole',
    'pt': 'Portuguese (Brazilian)',
    'zh': 'Chinese (Simplified)',
}

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s  %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


# ── Database ───────────────────────────────────────────────────────────────────

def init_db(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingested_shows (
            cablecast_show_id   INTEGER PRIMARY KEY,
            wp_meeting_id       INTEGER,
            show_date           TEXT,
            segment_count       INTEGER,
            ingested_at         TEXT,
            status              TEXT
        )
    ''')
    conn.commit()

def already_ingested(conn, show_id):
    row = conn.execute(
        'SELECT status FROM ingested_shows WHERE cablecast_show_id = ?',
        (show_id,)
    ).fetchone()
    return row is not None and row[0] == 'complete'

def mark_ingested(conn, show_id, wp_id, date, count):
    conn.execute('''
        INSERT OR REPLACE INTO ingested_shows
        VALUES (?, ?, ?, ?, ?, 'complete')
    ''', (show_id, wp_id, date, count, datetime.now().isoformat()))
    conn.commit()

def mark_failed(conn, show_id, reason):
    conn.execute('''
        INSERT OR REPLACE INTO ingested_shows
        VALUES (?, NULL, NULL, 0, ?, 'failed')
    ''', (show_id, f"{datetime.now().isoformat()} — {reason}"))
    conn.commit()


# ── Cablecast API ──────────────────────────────────────────────────────────────

def get_show(show_id):
    """Fetch a single show record from Cablecast."""
    r = requests.get(f'{CABLECAST_BASE}/shows/{show_id}', timeout=15)
    r.raise_for_status()
    return r.json()['show']

def get_all_school_committee_shows(limit=None):
    """
    Fetch all shows whose title contains 'School Committee'.
    Cablecast doesn't filter by show ID reliably across all versions,
    so we search by title instead.
    """
    shows = []
    page = 1
    while True:
        r = requests.get(
            f'{CABLECAST_BASE}/shows',
            params={'search': 'School Committee', 'per_page': 50, 'page': page},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        batch = data if isinstance(data, list) else data.get('shows', [])

        if not batch:
            break

        for show in batch:
            title = show.get('cgTitle') or show.get('title', '')
            if 'school committee' in title.lower():
                shows.append(show)

        if limit and len(shows) >= limit:
            shows = shows[:limit]
            break

        if len(batch) < 50:
            break
        page += 1

    # Sort newest first by eventDate
    shows.sort(
        key=lambda s: s.get('eventDate', '') or '',
        reverse=True
    )
    return shows


def get_vod_for_show(show_id):
    """Get the VOD record for a show. Returns None if no VOD exists."""
    show = get_show(show_id)
    vod_ids = show.get('vods', [])
    if not vod_ids:
        return None

    r = requests.get(
        f'{CABLECAST_BASE}/vods/{vod_ids[0]}',
        timeout=15
    )
    r.raise_for_status()
    return r.json().get('vod')


def build_embed_url(show_id):
    """Build the Cablecast embed player URL for a show."""
    return (
        f'{REFLECT_BASE}/internetchannel/watch-vod-embed'
        f'?showId={show_id}&site=1'
    )


def build_timestamped_url(show_id, seconds):
    """Build a deep-link URL that starts playback at the given second.
    The Cablecast embed reads ?seek=N (it ignores &t=)."""
    return (
        f'{REFLECT_BASE}/internetchannel/watch-vod-embed'
        f'?showId={show_id}&site=1&seek={int(seconds)}'
    )


def get_transcript_urls(show):
    """
    Build transcript URLs for all available languages using the Cablecast API.

    Strategy (fully API-driven):
      1. Get the VOD ID from the show record  (show.vods[0])
      2. Fetch the VOD record via /vods/{id}  (no auth required)
      3. Read the VOD's 'url' field — the direct video file URL:
             .../store-4/11522-SC091526-v2/vod.mp4
      4. Transcripts live in the same folder:
             .../store-4/11522-SC091526-v2/transcript.en.txt
             .../store-4/11522-SC091526-v2/transcript.am.txt  etc.

    Returns dict of {lang_code: url} for every language we produce.
    The caller verifies each URL exists before parsing.
    """
    transcripts = {}

    vod_ids = show.get('vods', [])
    if not vod_ids:
        log.warning('  Show has no VOD IDs — cannot build transcript URLs')
        return transcripts

    vod_id = vod_ids[0]

    try:
        r = requests.get(f'{CABLECAST_BASE}/vods/{vod_id}', timeout=15)
        r.raise_for_status()
        vod = r.json().get('vod', {})
    except Exception as e:
        log.warning(f'  Could not fetch VOD {vod_id}: {e}')
        return transcripts

    # 'url' example:
    #   https://reflect-video-ondemand-cpsd.cablecast.tv/store-4/11522-SC091526-v2/vod.mp4
    vod_file_url = vod.get('url', '')
    if not vod_file_url:
        log.warning(f'  VOD {vod_id} has no url field')
        return transcripts

    # Strip filename to get the folder
    folder_url = vod_file_url.rsplit('/', 1)[0]
    log.info(f'  Transcript base: {folder_url}/')

    for lang in LANGUAGES:
        transcripts[lang] = f'{folder_url}/transcript.{lang}.txt'

    return transcripts


# ── Transcript parsing ─────────────────────────────────────────────────────────

# Matches a standalone timestamp line: 00:00:37,601
# May have text after the timestamp on the same line.
TS_RE = re.compile(r'^(\d{2}):(\d{2}):(\d{2})[,.](\d+)\s*(.*)')

# Approximate words per second for interpolating timestamps between known ones.
# Cambridge SC meetings are measured speech; ~2 wps is a reasonable middle.
WORDS_PER_SECOND = 2.0

# Max words per search segment before we split even without a new timestamp.
# Keeps segments short enough for keyword search and display.
MAX_WORDS_PER_SEGMENT = 80


def _ts_to_seconds(h, mn, s, ms_str):
    return int(h)*3600 + int(mn)*60 + int(s) + float(f'0.{ms_str}')


def parse_transcript(text):
    """
    Parse the Cambridge plain-text transcript format.

    Observed format:
      - The file is mostly one long run of text.
      - Timestamps appear SPARSELY — maybe once every few minutes:
            00:00:37,601   text continues here...
        The timestamp is on its own line or at the start of a line,
        with the rest of that line being speech.
      - Between timestamps, text runs on continuously with no markup.

    Strategy:
      1. First pass: split the raw text into chunks at each timestamp,
         recording the known time for each chunk.
      2. Second pass: break each chunk into ~MAX_WORDS_PER_SEGMENT word
         sub-segments, interpolating timestamps linearly across the chunk
         based on word count and WORDS_PER_SECOND.

    This gives us hundreds of short, individually addressable segments
    with approximate timestamps — good enough for keyword search and
    deep-link URLs that land within a minute or two of the right moment.

    Returns list of dicts:
      {index, start_seconds, end_seconds, text, is_vote}
    """
    lines = text.splitlines()

    # ── Pass 1: split at timestamps ────────────────────────────────────────
    # Build list of (start_seconds, text_block)
    timed_chunks = []
    current_ts   = 0.0
    current_text = []

    for line in lines:
        line = line.strip()
        if not line:
            # Blank lines: keep as sentence boundary hint
            if current_text:
                current_text.append('')
            continue

        m = TS_RE.match(line)
        if m:
            # Save whatever we've accumulated so far
            block = ' '.join(t for t in current_text if t).strip()
            if block:
                timed_chunks.append((current_ts, block))
            current_text = []

            current_ts = _ts_to_seconds(m.group(1), m.group(2),
                                         m.group(3), m.group(4))
            inline = m.group(5).strip()
            if inline:
                current_text.append(inline)
        else:
            current_text.append(line)

    # Flush the last chunk
    block = ' '.join(t for t in current_text if t).strip()
    if block:
        timed_chunks.append((current_ts, block))

    if not timed_chunks:
        return []

    # ── Pass 2: break each chunk into short segments, interpolate times ────
    raw_segments = []  # list of (start_seconds, text)

    for chunk_idx, (chunk_start, chunk_text) in enumerate(timed_chunks):
        # Estimate the end time of this chunk
        if chunk_idx + 1 < len(timed_chunks):
            chunk_end = timed_chunks[chunk_idx + 1][0]
        else:
            # Last chunk: estimate from word count
            word_count = len(chunk_text.split())
            chunk_end  = chunk_start + word_count / WORDS_PER_SECOND

        chunk_duration = max(chunk_end - chunk_start, 0.1)

        # Split chunk text into sub-segments by sentence boundary or word limit
        words = chunk_text.split()
        total_words = len(words)

        # Walk through words, emitting a segment every MAX_WORDS_PER_SEGMENT
        pos = 0
        while pos < total_words:
            end_pos = min(pos + MAX_WORDS_PER_SEGMENT, total_words)

            # Try to break at a sentence boundary (period, ?, !) within range
            # to keep segments more natural
            if end_pos < total_words:
                for boundary in range(end_pos, max(pos + 10, end_pos - 20), -1):
                    if boundary < total_words and words[boundary - 1][-1] in '.?!':
                        end_pos = boundary
                        break

            seg_text = ' '.join(words[pos:end_pos]).strip()
            if seg_text:
                # Interpolate timestamp based on word position
                word_fraction = pos / max(total_words, 1)
                seg_start = chunk_start + word_fraction * chunk_duration
                raw_segments.append((round(seg_start, 1), seg_text))

            pos = end_pos

    # ── Build final segment dicts ──────────────────────────────────────────
    segments = []
    for i, (start, seg_text) in enumerate(raw_segments):
        end = raw_segments[i + 1][0] if i + 1 < len(raw_segments) else None
        segments.append({
            'index':         i,
            'start_seconds': start,
            'end_seconds':   end,
            'text':          seg_text,
            'is_vote':       False,
        })

    return segments

    # Build final segment dicts
    segments = []
    for i, (start, text) in enumerate(raw_segments):
        end = raw_segments[i+1][0] if i+1 < len(raw_segments) else None
        segments.append({
            'index':        i,
            'start_seconds': round(start, 2),
            'end_seconds':   round(end, 2) if end is not None else None,
            'text':          text,
            'is_vote':       False,   # set by detect_votes.py later
        })

    return segments


def fetch_transcript(url):
    """Download and parse an English transcript from Cablecast."""
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return parse_transcript(r.text)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise


# ── Vote detection (simple pass — expand in detect_votes.py) ──────────────────

VOTE_PATTERNS = [
    r'\ball in favor\b',
    r'\broll call vote\b',
    r'\bmotion (?:passes|carries|fails)\b',
    r'\bunanimously (?:approved|adopted|passed)\b',
    r'\bvote[sd]?\s+\d+\s*(?:to|–|-)\s*\d+\b',
]
VOTE_RE = re.compile('|'.join(VOTE_PATTERNS), re.IGNORECASE)

def flag_votes(segments):
    """Quick pass to flag segments that look like vote moments."""
    for seg in segments:
        if VOTE_RE.search(seg['text']):
            seg['is_vote'] = True
    return segments


# ── WordPress push ─────────────────────────────────────────────────────────────

def meeting_identity(show, portal):
    """
    (title, date, body) for a new meeting. The CPS portal is the reference:
    Cablecast titles and dates are sometimes wrong (show 11317 is dated
    2025-03-19 for a 3/19/26 meeting). Falls back to Cablecast for shows
    the portal doesn't link.
    """
    # eventDate format: 2026-09-15T00:00:00-04:00
    cc_date  = (show.get('eventDate') or '')[:10]
    cc_title = show.get('cgTitle') or show.get('title') or f'School Committee {cc_date}'
    if portal and not portal.get('body'):
        log.warning(f"  The portal lists this as \"{portal['meeting_type']}\", which isn't a body we ingest "
                    f"(see scrape_agenda.classify_meeting) — using Cablecast's title and date")
    if not portal or not portal.get('body'):
        return cc_title, cc_date, FULL_COMMITTEE
    if cc_date != portal['date']:
        log.warning(f"  Cablecast date {cc_date} ≠ portal date {portal['date']} — using the portal's")
    return meeting_title(portal), portal['date'], portal['body']


def create_wp_meeting(title, date_str, body, show, segment_count, transcript_urls, show_id):
    """Create a cr_meeting post in WordPress. Returns WP post ID."""
    langs = ','.join(transcript_urls.keys())

    payload = {
        'title':  title,
        'status': 'draft',
        'meta': {
            'meeting_date':        date_str,
            'meeting_body':        body,
            'cablecast_vod_id':    show.get('vods', [None])[0],
            'cablecast_embed_url': build_embed_url(show_id),
            'segment_count':       segment_count,
            'vote_count':          0,
            'agenda_item_count':   0,
            'cr_status':           'processing',
            'summary_origin':      'pending',
            'languages_available': langs,
            'segments_json':       '',   # filled in next step
            'agenda_json':         '[]',
            'votes_json':          '[]',
        }
    }

    r = requests.post(
        f'{WP_BASE}/meeting',
        json=payload,
        auth=WP_AUTH,
        timeout=30
    )
    r.raise_for_status()
    return r.json()['id']


def push_segments_json(wp_id, segments, show_id):
    """
    Store all segments as a single JSON blob in the meeting's segments_json
    meta field. Also stores deep_link_url for each segment.
    """
    enriched = []
    for seg in segments:
        enriched.append({
            **seg,
            'deep_link_url': build_timestamped_url(show_id, seg['start_seconds']),
        })

    # Count votes for the meeting-level meta
    vote_count = sum(1 for s in enriched if s.get('is_vote'))

    # Build votes_json from flagged segments
    votes = []
    for seg in enriched:
        if seg.get('is_vote'):
            votes.append({
                'segment_index': seg['index'],
                'start_seconds': seg['start_seconds'],
                'deep_link_url': seg['deep_link_url'],
                'raw_context':   seg['text'],
                'result':        'unknown',
                'vote_for':      None,
                'vote_against':  None,
            })

    r = requests.post(
        f'{WP_BASE}/meeting/{wp_id}',
        json={
            # Store all segment text in post_content so WordPress can
            # index and search it natively — much faster than LIKE on JSON.
            'content': ' '.join(s['text'] for s in enriched),
            'meta': {
                'segments_json': json.dumps(enriched),
                'votes_json':    json.dumps(votes),
                'vote_count':    vote_count,
                'cr_status':     'ready',
            }
        },
        auth=WP_AUTH,
        timeout=60
    )
    r.raise_for_status()
    log.info(f'  WP post {wp_id}: pushed {len(enriched)} segments, '
             f'{vote_count} vote(s) flagged')


# ── Main pipeline ──────────────────────────────────────────────────────────────

def ingest_show(show_id, conn, dry_run=False, enrich=True, portal=None):
    """Ingest one School Committee show into WordPress.
    enrich=False skips the agenda/minutes step (backfill.py runs it itself).
    portal is the show's CPS portal row (looked up if not given); its
    title, date and body win over Cablecast's."""
    log.info(f'Processing show {show_id}...')

    if already_ingested(conn, show_id):
        log.info(f'  Already ingested — skipping')
        return True

    try:
        show = get_show(show_id)
        if portal is None:
            portal = find_portal_meeting(show_id)
            if portal is None:
                log.warning('  Not linked from the CPS portal — using Cablecast\'s title and date')
        title, date, body = meeting_identity(show, portal)
        log.info(f'  Title: {title}  |  Date: {date}  |  Body: {body}')

        transcript_urls = get_transcript_urls(show)
        if 'en' not in transcript_urls:
            log.warning(f'  No transcript URL found — skipping')
            mark_failed(conn, show_id, 'No transcript URL')
            return False

        # Derive VOD folder URL from transcript URL
        # e.g. .../store-4/11522-SC091526-v2/transcript.en.txt -> .../store-4/11522-SC091526-v2
        folder_url = transcript_urls['en'].rsplit('/', 1)[0]

        # Fetch precise per-cue timestamps from HLS VTT caption segments
        segments = fetch_hls_captions(folder_url, lang='en')

        if not segments:
            log.warning(f'  No captions found — skipping')
            mark_failed(conn, show_id, 'Empty captions')
            return False

        log.info(f'  Parsed {len(segments)} segments')
        segments = flag_votes(segments)
        vote_count = sum(1 for s in segments if s['is_vote'])
        log.info(f'  Vote moments flagged: {vote_count}')

        if dry_run:
            log.info(f'  [DRY RUN] Would create WP post and push segments')
            return True

        wp_id = create_wp_meeting(title, date, body, show, len(segments), transcript_urls, show_id)
        log.info(f'  Created WordPress post ID: {wp_id}')

        push_segments_json(wp_id, segments, show_id)
        mark_ingested(conn, show_id, wp_id, date, len(segments))

        # Agenda + official votes from the CPS portal. Non-fatal: the
        # captions are in, and enrich_meetings.py can be re-run later
        # (minutes are usually posted weeks after the meeting anyway).
        if enrich:
            try:
                from enrich_meetings import enrich_show
                enrich_show(show_id, wp_id)
            except Exception as e:
                log.warning(f'  Agenda/minutes step failed ({e}) — run: python enrich_meetings.py --show {show_id}')

        log.info(f'  Done. Show {show_id} → WP post {wp_id}')
        return True

    except Exception as e:
        log.error(f'  FAILED: {e}')
        mark_failed(conn, show_id, str(e))
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Ingest Cambridge School Committee meetings into WordPress'
    )
    parser.add_argument('--limit',   type=int, help='Max meetings to ingest')
    parser.add_argument('--show',    type=int, help='Ingest a specific show ID')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse transcripts but do not write to WordPress')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.show:
        # Single show mode
        ingest_show(args.show, conn, dry_run=args.dry_run)
    else:
        # Batch mode: fetch all School Committee shows
        log.info('Fetching School Committee shows from Cablecast...')
        shows = get_all_school_committee_shows(limit=args.limit)
        log.info(f'Found {len(shows)} show(s) to process')

        success = 0
        skipped = 0
        failed  = 0

        for show in shows:
            sid = show['id']
            if already_ingested(conn, sid):
                skipped += 1
                continue

            ok = ingest_show(sid, conn, dry_run=args.dry_run)
            if ok:
                success += 1
            else:
                failed += 1

            time.sleep(2)  # be polite to the server

        log.info(
            f'\nDone. Ingested: {success}  Skipped (already done): {skipped}'
            f'  Failed: {failed}'
        )

    conn.close()


if __name__ == '__main__':
    main()
