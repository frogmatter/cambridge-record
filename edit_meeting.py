"""
Cambridge Record — correct a meeting's title or date

Cablecast is sometimes wrong (show 11502 was a 9/8 Special Meeting listed
as a 9/1 Regular Meeting). This updates just the title and/or date in
WordPress, leaving the transcript, agenda, votes and publish status alone.
Fix it in Cablecast too, so a future re-ingest doesn't bring it back.

Usage:
    python edit_meeting.py --show 11502                                  # show current title/date
    python edit_meeting.py --show 11502 --date 2026-09-08 \\
        --title "School Committee Special Meeting 9/8/26"                # change them
"""

import argparse
import re
import sqlite3
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).parent
ENV = dotenv_values(ROOT / '.env')
WP_BASE = ENV['WP_BASE_URL'].rstrip('/')
WP_AUTH = (ENV['WP_USERNAME'], ENV['WP_APP_PASSWORD'])


def main():
    parser = argparse.ArgumentParser(description="Correct a meeting's title or date in WordPress")
    parser.add_argument('--show', type=int, required=True, help='Cablecast show ID')
    parser.add_argument('--title', help='New title')
    parser.add_argument('--date', help='New meeting date, YYYY-MM-DD')
    args = parser.parse_args()

    if args.date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date):
        raise SystemExit('--date must look like 2026-09-08')

    row = sqlite3.connect(ROOT / 'pipeline.db').execute(
        "SELECT wp_meeting_id FROM ingested_shows WHERE cablecast_show_id = ? AND status = 'complete'", (args.show,)
    ).fetchone()
    if not row:
        raise SystemExit(f'Show {args.show} has not been ingested')
    url = f'{WP_BASE}/meeting/{row[0]}'

    r = requests.get(url, auth=WP_AUTH, timeout=30, params={'context': 'edit', '_fields': 'id,status,title,meta.meeting_date'})
    r.raise_for_status()
    post = r.json()
    print(f"WP post {post['id']} ({post['status']}): {post['title']['raw']}  |  {post['meta']['meeting_date']}")

    body = {}
    if args.title:
        body['title'] = args.title
    if args.date:
        body['meta'] = {'meeting_date': args.date}
    if not body:
        return

    r = requests.post(url, json=body, auth=WP_AUTH, timeout=30)
    r.raise_for_status()
    post = r.json()
    print(f"Updated → {post['title']['raw']}  |  {post['meta']['meeting_date']}")


if __name__ == '__main__':
    main()
