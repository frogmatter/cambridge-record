"""
Cambridge Record — sync School Committee officials to WordPress

officials.json is the roster. This creates or updates one cr_official post
per person, matched on minutes_name (the surname the minutes use), so it's
safe to re-run after editing the roster. It never deletes posts: when
someone leaves the committee, set their term_end rather than removing them,
so their voting record stays on the site.

It also creates one cr_subcommittee post per subcommittee in the roster,
matched on meeting_body: each roster name ("Special Education/Student
Services") is mapped to the body its meetings are filed under ("Special
Education and Student Supports Subcommittee") by the same
classify_meeting() the pipeline uses. "Budget (Committee of the Whole)"
maps to no body, since it is the full committee, and gets no page.
Subcommittee pages are never deleted or renamed; their descriptions are
written in WP admin and left alone here.

Requires Cambridge Record plugin 0.7.0+ (subcommittee pages).

Usage:
    python sync_officials.py --dry-run     # show what would change
    python sync_officials.py               # create/update as published
    python sync_officials.py --draft       # create new ones as drafts
"""

import argparse
import json
import re
from pathlib import Path

import requests
from dotenv import dotenv_values

from scrape_agenda import FULL_COMMITTEE, classify_meeting

ROOT = Path(__file__).parent
ENV = dotenv_values(ROOT / '.env')
WP_BASE = ENV['WP_BASE_URL'].rstrip('/')
WP_AUTH = (ENV['WP_USERNAME'], ENV['WP_APP_PASSWORD'])

META_FIELDS = ('full_name', 'official_title', 'minutes_name', 'is_voting_member', 'term_start', 'term_end')


def plugin_ready():
    """True when WordPress has subcommittee pages (plugin 0.7.0+), and so the minutes_name field too."""
    r = requests.options(f'{WP_BASE}/subcommittee', auth=WP_AUTH, timeout=30)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    meta = r.json().get('schema', {}).get('properties', {}).get('meta', {}).get('properties', {})
    return 'meeting_body' in meta


def subcommittee_body(name):
    """The meeting_body a roster subcommittee meets as, or None (the Budget committee of the whole)."""
    body, _ = classify_meeting(name)
    return body if body and body != FULL_COMMITTEE else None


def subcommittee_slug(body):
    """/subcommittee/governance/, not /subcommittee/governance-subcommittee/."""
    return re.sub(r'[^a-z0-9]+', '-', body.lower().removesuffix(' subcommittee')).strip('-')


def sync_subcommittees(roster, dry_run):
    """Create a cr_subcommittee post for each body in the roster that doesn't have one."""
    r = requests.get(f'{WP_BASE}/subcommittee', auth=WP_AUTH, timeout=30, params={
        'context': 'edit', 'per_page': 100, 'status': 'publish,draft,pending,private', '_fields': 'id,meta',
    })
    r.raise_for_status()
    existing = {p['meta'].get('meeting_body') for p in r.json()}
    bodies = sorted({sc['body'] for person in roster for sc in person['subcommittees'] if sc['body']})
    for body in bodies:
        if body in existing:
            print(f'  = {body} (page exists)')
            continue
        print(f'  + {body}: create page')
        if not dry_run:
            r = requests.post(f'{WP_BASE}/subcommittee', auth=WP_AUTH, timeout=30, json={
                'title': body, 'slug': subcommittee_slug(body), 'status': 'publish', 'meta': {'meeting_body': body},
            })
            r.raise_for_status()


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
        raise SystemExit('WordPress is running an older Cambridge Record plugin (no subcommittee pages). '
                         'Upload wordpress/cambridge-record-plugin.zip (0.7.0+) first.')

    roster = json.loads((ROOT / 'officials.json').read_text())['officials']
    for person in roster:
        person['subcommittees'] = [{**sc, 'body': subcommittee_body(sc['name'])}
                                   for sc in person.get('subcommittees', [])]

    print('Subcommittees')
    sync_subcommittees(roster, args.dry_run)

    print('Officials')
    current = existing_officials()

    for person in roster:
        meta = {k: person[k] for k in META_FIELDS}
        meta['subcommittees_json'] = json.dumps(person['subcommittees'])
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
