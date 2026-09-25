"""
Cambridge Record — backfill meetings from the CPS portal

Walks the portal's meeting list (each row links its video by Cablecast show
ID) and, for every full-committee meeting not yet ingested: ingests the
captions, then adds the agenda and official votes (enrich_meetings.py).

New meetings arrive in WordPress as drafts — publish them after review
(Meetings → select → Bulk actions → Edit → Status: Published).

Usage:
    python backfill.py --since 2026-01-01 --dry-run    # list what would be ingested
    python backfill.py --since 2026-01-01              # ingest them
    python backfill.py --since 2026-01-01 --limit 2    # just the first two
"""

import argparse
import logging
import sqlite3
import time

from enrich_meetings import enrich_show
from ingest_cablecast import DB_PATH, already_ingested, ingest_show, init_db
from scrape_agenda import get_portal_meetings

log = logging.getLogger(__name__)

FULL_COMMITTEE = ('regular meeting', 'special meeting')


def is_full_committee(meeting):
    return any(k in meeting['meeting_type'].lower() for k in FULL_COMMITTEE)


def main():
    parser = argparse.ArgumentParser(description='Ingest School Committee meetings listed on the CPS portal')
    parser.add_argument('--since', required=True, help='YYYY-MM-DD — earliest meeting date')
    parser.add_argument('--until', help='YYYY-MM-DD — latest meeting date')
    parser.add_argument('--limit', type=int, help='Stop after this many new meetings')
    parser.add_argument('--dry-run', action='store_true', help='List meetings without ingesting')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    portal = get_portal_meetings()
    todo = sorted(
        (m for m in portal
         if m['show_id'] and is_full_committee(m)
         and m['date'] >= args.since and (not args.until or m['date'] <= args.until)
         and not already_ingested(conn, m['show_id'])),
        key=lambda m: m['date'],
    )[:args.limit]

    log.info(f'{len(todo)} meeting(s) to backfill')
    for m in todo:
        log.info(f"  {m['date']}  show {m['show_id']}  {m['meeting_type']}  "
                 f"(agenda: {'yes' if m['agenda_url'] else 'no'}, minutes: {'yes' if m['minutes_url'] else 'not yet'})")
    if args.dry_run:
        return

    results = []
    for m in todo:
        ok = ingest_show(m['show_id'], conn, enrich=False)
        row = conn.execute('SELECT wp_meeting_id FROM ingested_shows WHERE cablecast_show_id = ?', (m['show_id'],)).fetchone()
        summary = {'show_id': m['show_id'], 'date': m['date'], 'type': m['meeting_type'], 'ok': ok and row and row[0]}
        if summary['ok']:
            try:
                summary.update(enrich_show(m['show_id'], row[0], portal))
            except Exception as e:
                log.error(f"  Show {m['show_id']}: agenda/minutes step failed — {e}")
        results.append(summary)
        time.sleep(2)   # be polite to Cablecast and the portal

    log.info('\nBackfill summary')
    for r in results:
        if not r['ok']:
            log.info(f"  {r['date']}  show {r['show_id']}  FAILED to ingest — see pipeline.log")
            continue
        votes = f"{r.get('votes_timed', 0)}/{r['votes']} votes placed" if r.get('votes') is not None else 'no minutes yet'
        flag = f"  ⚠ date: Cablecast {r['date_mismatch'][0]} vs portal {r['date_mismatch'][1]}" if r.get('date_mismatch') else ''
        log.info(f"  {r['date']}  show {r['show_id']} → WP {r.get('wp_id')}  {r['type']:<16} "
                 f"{r.get('agenda_items', 0)} agenda items, {votes}{flag}")
    failed = sum(1 for r in results if not r['ok'])
    log.info(f'Done: {len(results) - failed} ingested as drafts, {failed} failed.')


if __name__ == '__main__':
    main()
