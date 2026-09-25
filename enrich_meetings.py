"""
Cambridge Record — add agenda and official votes to ingested meetings

For each ingested Cablecast show:
  1. Find its row on the CPS portal (rows link videos by show ID)
  2. Scrape the agenda page → agenda_json
  3. If minutes are posted, parse the votes → votes_json
     (replacing the caption-based guesses from ingest)
  4. Place votes, agenda items and sections on the video timeline by
     matching against the captions (match_agenda.py)
  5. Update the WordPress meeting in place

Minutes are posted weeks after a meeting, so run this again later to pick
them up. It is safe to re-run: each run rewrites agenda_json/votes_json.
It never changes a meeting's title, date, or publish status.

Usage:
    python enrich_meetings.py --show 11498            # one meeting
    python enrich_meetings.py --all                   # every ingested meeting
    python enrich_meetings.py --all --dry-run         # show what would change
"""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import requests
from dotenv import dotenv_values

from match_agenda import fix_mojibake, time_agenda, time_votes

from parse_minutes import docket_titles, minutes_text, parse_votes
from scrape_agenda import get_portal_meetings, scrape_agenda_items

ROOT = Path(__file__).parent
ENV = dotenv_values(ROOT / '.env')
WP_BASE = ENV['WP_BASE_URL'].rstrip('/')
WP_AUTH = (ENV['WP_USERNAME'], ENV['WP_APP_PASSWORD'])
DB_PATH = ROOT / 'pipeline.db'

log = logging.getLogger(__name__)


def ingested_meetings(conn, show_id=None):
    """[(show_id, wp_meeting_id)] for completed ingests."""
    sql = "SELECT cablecast_show_id, wp_meeting_id FROM ingested_shows WHERE status = 'complete'"
    args = ()
    if show_id is not None:
        sql += ' AND cablecast_show_id = ?'
        args = (show_id,)
    return conn.execute(sql + ' ORDER BY show_date', args).fetchall()


def seek_url(embed_url, seconds):
    """Cablecast embed URL that starts at `seconds` (the embed reads ?seek=, not &t=)."""
    parts = urlsplit(embed_url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ('t', 'seek')]
    query.append(('seek', str(int(seconds))))
    return urlunsplit(parts._replace(query=urlencode(query)))


def link_votes_and_agenda(agenda, votes, minutes_titles):
    """
    Cross-reference by docket number: each vote gets `items` [{docket, title}],
    each agenda item gets `vote_indexes`. Titles come from the agenda, or
    from the minutes' own headings for items not on the agenda page.
    """
    agenda_titles = {a['docket']: a['title'] for a in agenda if a.get('docket')}
    for v in votes:
        v['items'] = [
            {'docket': d, 'title': agenda_titles.get(d) or minutes_titles.get(d)}
            for d in v['dockets']
        ]
    for a in agenda:
        a['vote_indexes'] = [v['index'] for v in votes if a.get('docket') and a['docket'] in v['dockets']]

    # Late orders have no docket number; the minutes just say "the Late Order
    # was adopted". Link them when there's exactly one of each in section 12.
    late_items = [a for a in agenda if a['item_type'] == 'late_order' and not a['docket']]
    late_votes = [v for v in votes if v['section'] == '12' and not v['dockets'] and 'late order' in v['motion_text'].lower()]
    if len(late_items) == 1 and len(late_votes) == 1:
        late_items[0]['vote_indexes'] = [late_votes[0]['index']]
        late_votes[0]['items'] = [{'docket': None, 'title': late_items[0]['title']}]


def enrich_show(show_id, wp_id, portal_meetings=None, dry_run=False):
    """Scrape agenda + minutes for one show and update its WordPress meeting. Returns a summary dict."""
    portal_meetings = portal_meetings if portal_meetings is not None else get_portal_meetings()
    portal = next((m for m in portal_meetings if m['show_id'] == int(show_id)), None)
    if not portal:
        log.warning(f'  Show {show_id}: not linked from any meeting on the CPS portal — skipping')
        return {'show_id': show_id, 'found': False}

    current = requests.get(
        f'{WP_BASE}/meeting/{wp_id}', auth=WP_AUTH, timeout=30,
        params={'context': 'edit', '_fields': 'id,title,meta.meeting_date,meta.cablecast_embed_url,meta.segments_json'},
    )
    current.raise_for_status()
    current = current.json()
    wp_date = current['meta'].get('meeting_date')
    if wp_date and wp_date != portal['date']:
        log.warning(f'  Show {show_id}: WordPress date {wp_date} ≠ portal date {portal["date"]} '
                    f'({portal["meeting_type"]}) — check the meeting date')

    agenda = scrape_agenda_items(portal['agenda_url']) if portal['agenda_url'] else []

    votes, minutes_titles = None, {}
    if portal['minutes_url']:
        text = minutes_text(portal['minutes_url'])
        votes = parse_votes(text, source_url=portal['minutes_url'])
        minutes_titles = docket_titles(text)

    link_votes_and_agenda(agenda, votes or [], minutes_titles)

    # Transcript: repair apostrophes garbled at ingest (before the
    # fetch_captions.py decoding fix), then place things on the timeline.
    segments = json.loads(current['meta'].get('segments_json') or '[]')
    repaired = 0
    for seg in segments:
        fixed = fix_mojibake(seg['text'])
        if fixed != seg['text']:
            seg['text'], repaired = fixed, repaired + 1

    if segments:
        if votes:
            time_votes(votes, segments)
        time_agenda(agenda, votes or [], segments)
        embed = current['meta'].get('cablecast_embed_url')
        for item in agenda + (votes or []):
            if item.get('start_seconds') is not None and embed:
                item['deep_link_url'] = seek_url(embed, item['start_seconds'])

    meta = {
        'agenda_json':       json.dumps(agenda),
        'agenda_item_count': sum(1 for a in agenda if a['item_type'] != 'section'),
    }
    if portal['agenda_url']:
        meta['agenda_url'] = portal['agenda_url']
    if votes is not None:
        meta['votes_json'] = json.dumps(votes)
        meta['vote_count'] = len(votes)
    payload = {'meta': meta}
    if repaired:
        meta['segments_json'] = json.dumps(segments)
        payload['content'] = ' '.join(s['text'] for s in segments)   # what WordPress search indexes

    summary = {
        'show_id':      show_id,
        'wp_id':        wp_id,
        'found':        True,
        'portal':       f"{portal['date']} {portal['meeting_type']}",
        'agenda_items': meta['agenda_item_count'],
        'votes':        len(votes) if votes is not None else None,
        'votes_timed':  sum(1 for v in votes or [] if v.get('start_seconds') is not None),
        'agenda_timed': sum(1 for a in agenda if a.get('start_seconds') is not None),
        'repaired':     repaired,
    }
    log.info(f"  Show {show_id} → WP {wp_id}: {summary['portal']} | "
             f"{summary['agenda_items']} agenda items ({summary['agenda_timed']}/{len(agenda)} rows timed) | "
             + (f"{len(votes)} votes from minutes ({summary['votes_timed']} placed in video)" if votes is not None
                else 'minutes not posted yet (caption vote flags kept)')
             + (f" | repaired {repaired} garbled transcript lines" if repaired else ''))
    for v in votes or []:
        if v.get('start_seconds') is None:
            log.warning(f"    vote not found in captions: {v['motion_text'][:80]}")

    if dry_run:
        log.info('  [DRY RUN] Not writing to WordPress')
        return summary

    r = requests.post(f'{WP_BASE}/meeting/{wp_id}', json=payload, auth=WP_AUTH, timeout=120)
    r.raise_for_status()
    return summary


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s  %(levelname)s  %(message)s',
        handlers=[logging.FileHandler(ROOT / 'pipeline.log'), logging.StreamHandler()],
    )
    parser = argparse.ArgumentParser(description='Add CPS agenda and official votes to ingested meetings')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--show', type=int, help='Cablecast show ID')
    target.add_argument('--all', action='store_true', help='Every ingested meeting')
    parser.add_argument('--dry-run', action='store_true', help='Parse but do not write to WordPress')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    rows = ingested_meetings(conn, None if args.all else args.show)
    conn.close()
    if not rows:
        log.error(f'Show {args.show} has not been ingested — run ingest_cablecast.py --show {args.show} first')
        return

    portal_meetings = get_portal_meetings()
    for show_id, wp_id in rows:
        try:
            enrich_show(show_id, wp_id, portal_meetings, dry_run=args.dry_run)
        except Exception as e:
            log.error(f'  Show {show_id}: FAILED — {e}')


if __name__ == '__main__':
    main()
