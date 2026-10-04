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
import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import requests
from dotenv import dotenv_values

from improve_captions import correct_segments
from match_agenda import fix_mojibake, time_agenda, time_votes

from parse_minutes import docket_titles, minutes_text, parse_votes
from scrape_agenda import call_of_meeting, get_portal_meetings, notice_text, scrape_agenda_items

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


def _digest(text):
    return hashlib.sha1(str(text).encode('utf-8')).hexdigest()[:8]


def add_review_keys(agenda, votes):
    """
    Stable keys that Meetings → Review times files people's decisions under.
    They depend only on what the minutes and agenda say, so they survive
    re-runs as long as those documents don't change.
    """
    for v in votes:
        v['key'] = f"v{v['index']}-{_digest(v['motion_text'])}"
    for a in agenda:
        a['key'] = f"a-{a['docket']}" if a.get('docket') else f"a-{a.get('item_number') or 'x'}-{_digest(a['title'])}"


def apply_review(items, decisions, embed):
    """
    Re-apply people's review decisions (same rule as cr_apply_decision() in
    the plugin): a confirmed or corrected time wins over the pipeline's
    match; 'cleared' means the item isn't in the video.
    """
    applied = 0
    for item in items:
        d = decisions.get(item.get('key'))
        if not d:
            continue
        seconds = d.get('start_seconds')
        item.update({
            'start_seconds': seconds,
            'deep_link_url': seek_url(embed, seconds) if (embed and seconds is not None) else None,
            'matched':       seconds is not None,
            'reviewed':      d['status'],
        })
        if d['status'] != 'confirmed':
            item['match_method'] = 'reviewed_not_in_video' if d['status'] == 'cleared' else 'reviewed'
            item['match_score'] = 0 if seconds is None else 1
        applied += 1
    return applied


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
        params={'context': 'edit', '_fields': 'id,title,meta.meeting_date,meta.cablecast_embed_url,meta.segments_json,meta.review_json'},
    )
    current.raise_for_status()
    current = current.json()
    wp_date = current['meta'].get('meeting_date')
    if wp_date and wp_date != portal['date']:
        log.warning(f'  Show {show_id}: WordPress date {wp_date} ≠ portal date {portal["date"]} '
                    f'({portal["meeting_type"]}) — check the meeting date')

    agenda = scrape_agenda_items(portal['agenda_url']) if portal['agenda_url'] else []

    votes, minutes_titles, text = None, {}, None
    if portal['minutes_url']:
        text = minutes_text(portal['minutes_url'])
        votes = parse_votes(text, source_url=portal['minutes_url'])
        minutes_titles = docket_titles(text)

    link_votes_and_agenda(agenda, votes or [], minutes_titles)

    # Transcript: repair apostrophes garbled at ingest (before the
    # fetch_captions.py decoding fix), apply the Cambridge terms fixes
    # (from the original caption text, kept in text_original), then place
    # things on the timeline.
    segments = json.loads(current['meta'].get('segments_json') or '[]')
    stored = json.dumps(segments)
    repaired = 0
    for seg in segments:
        for field in ('text', 'text_original'):
            if field in seg:
                fixed = fix_mojibake(seg[field])
                if fixed != seg[field]:
                    seg[field] = fixed
                    repaired += field == 'text'
    corrections = correct_segments(segments)
    transcript_changed = json.dumps(segments) != stored

    embed = current['meta'].get('cablecast_embed_url')
    if segments:
        if votes:
            time_votes(votes, segments)
        time_agenda(agenda, votes or [], segments)
        for item in agenda + (votes or []):
            if item.get('start_seconds') is not None and embed:
                item['deep_link_url'] = seek_url(embed, item['start_seconds'])

    # People's decisions from Meetings → Review times win over the matching
    add_review_keys(agenda, votes or [])
    review = json.loads(current['meta'].get('review_json') or '{}')
    reviewed = apply_review(votes or [], review.get('votes', {}), embed) + apply_review(agenda, review.get('agenda', {}), embed)

    meta = {
        'agenda_json':       json.dumps(agenda),
        'agenda_item_count': sum(1 for a in agenda if a['item_type'] != 'section'),
    }
    if portal['agenda_url']:
        meta['agenda_url'] = portal['agenda_url']
    if portal.get('body'):
        meta['meeting_body'] = portal['body']
    # Why the meeting was called — from the notice, else the minutes. Only
    # for meetings without an agenda: a regular meeting's notice just says
    # "for the purpose of discussing the agenda items listed below", or
    # describes only its executive session.
    purpose = None
    if not portal['agenda_url']:
        purpose = (call_of_meeting(notice_text(portal['notice_url'])) if portal.get('notice_url') else None) \
            or call_of_meeting(text)
    meta['meeting_purpose'] = purpose or ''
    if portal.get('notice_url'):
        meta['notice_url'] = portal['notice_url']
    if votes is not None:
        meta['votes_json'] = json.dumps(votes)
        meta['vote_count'] = len(votes)
    payload = {'meta': meta}
    meta['caption_corrections'] = corrections
    if transcript_changed:
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
        'corrections':  corrections,
        'reviewed':     reviewed,
        'date_mismatch': (wp_date, portal['date']) if wp_date and wp_date != portal['date'] else None,
    }
    log.info(f"  Show {show_id} → WP {wp_id}: {summary['portal']} | "
             f"{summary['agenda_items']} agenda items ({summary['agenda_timed']}/{len(agenda)} rows timed) | "
             + (f"{len(votes)} votes from minutes ({summary['votes_timed']} placed in video)" if votes is not None
                else 'minutes not posted yet (caption vote flags kept)')
             + (f" | repaired {repaired} garbled transcript lines" if repaired else '')
             + (f" | {corrections} caption fixes" if corrections else '')
             + (f" | kept {reviewed} reviewed time(s)" if reviewed else ''))
    for v in votes or []:
        if v.get('start_seconds') is None and not v.get('reviewed'):
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
