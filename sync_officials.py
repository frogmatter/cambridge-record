"""
Cambridge Record — sync School Committee officials to WordPress

officials.json is the roster. This creates or updates one cr_official post
per person, matched on minutes_name (the surname the minutes use), so it's
safe to re-run after editing the roster. It never deletes posts: when
someone leaves the committee, set their term_end rather than removing them,
so their voting record stays on the site.

Requires Cambridge Record plugin 0.3.0+ (minutes_name / subcommittees_json meta).

Usage:
    python sync_officials.py --dry-run     # show what would change
    python sync_officials.py               # create/update as published
    python sync_officials.py --draft       # create new ones as drafts
"""

import argparse
import json
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).parent
ENV = dotenv_values(ROOT / '.env')
WP_BASE = ENV['WP_BASE_URL'].rstrip('/')
WP_AUTH = (ENV['WP_USERNAME'], ENV['WP_APP_PASSWORD'])

META_FIELDS = ('full_name', 'official_title', 'minutes_name', 'is_voting_member', 'term_start', 'term_end')


def plugin_ready():
    """True when WordPress knows the minutes_name field (plugin 0.3.0+); otherwise it would silently drop it."""
    r = requests.options(f'{WP_BASE}/official', auth=WP_AUTH, timeout=30)
    r.raise_for_status()
    meta = r.json().get('schema', {}).get('properties', {}).get('meta', {}).get('properties', {})
    return 'minutes_name' in meta


def existing_officials():
    """{minutes_name.lower(): post} for every official post, any status."""
    r = requests.get(f'{WP_BASE}/official', auth=WP_AUTH, timeout=30, params={
        'context': 'edit', 'per_page': 100, 'status': 'publish,draft,pending,private',
        '_fields': 'id,status,title,meta',
    })
    r.raise_for_status()
    return {(p['meta'].get('minutes_name') or p['title']['raw']).lower(): p for p in r.json()}


def main():
    parser = argparse.ArgumentParser(description='Sync officials.json to WordPress')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without writing')
    parser.add_argument('--draft', action='store_true', help='Create new officials as drafts instead of published')
    args = parser.parse_args()

    if not plugin_ready():
        raise SystemExit('WordPress is running an older Cambridge Record plugin (no minutes_name field). '
                         'Upload wordpress/cambridge-record-plugin.zip (0.3.0+) first.')

    roster = json.loads((ROOT / 'officials.json').read_text())['officials']
    current = existing_officials()

    for person in roster:
        meta = {k: person[k] for k in META_FIELDS}
        meta['subcommittees_json'] = json.dumps(person.get('subcommittees', []))
        body = {'title': person['full_name'], 'meta': meta}

        post = current.get(person['minutes_name'].lower())
        if post:
            changed = [k for k, v in meta.items() if post['meta'].get(k) != v]
            if post['title']['raw'] != person['full_name']:
                changed.append('title')
            if not changed:
                print(f"  = {person['full_name']} (unchanged)")
                continue
            print(f"  ~ {person['full_name']}: update {', '.join(changed)}")
            url = f"{WP_BASE}/official/{post['id']}"
        else:
            body['status'] = 'draft' if args.draft else 'publish'
            print(f"  + {person['full_name']}: create ({body['status']})")
            url = f'{WP_BASE}/official'

        if not args.dry_run:
            r = requests.post(url, json=body, auth=WP_AUTH, timeout=30)
            r.raise_for_status()

    if args.dry_run:
        print('[DRY RUN] Nothing written')


if __name__ == '__main__':
    main()
