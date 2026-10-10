"""
Cambridge Record — how well does match_agenda.py place votes?

Re-runs the vote matcher on every meeting that has minutes and compares
its times with the accepted ones in WordPress: people's Review times
decisions, and the placements nobody has questioned. Read-only.

The October 2026 review checked all 118 official votes by hand, so the
accepted times were ground truth then. Run this before and after changing
the matcher: "WRONG" means a vote placed confidently on another moment.

Usage:
    python evaluate_matching.py            # totals
    python evaluate_matching.py -v         # and every vote it gets wrong
    python evaluate_matching.py --anchored # with Review times decisions as anchors (as enrich runs it)
"""

import argparse
import copy
import json

import requests

import match_agenda
from sync_officials import WP_AUTH, WP_BASE

TOLERANCE = 60   # seconds either side of the accepted time


def fmt(seconds):
    if seconds is None:
        return '—'
    s = int(seconds)
    return f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}'


def meetings_with_minutes():
    """[(title, segments, votes, decisions)] for every meeting whose votes came from minutes."""
    cr = WP_BASE.replace('/wp/v2', '/cambridge-record/v1')
    ids = [m['id'] for m in requests.get(f'{cr}/review', auth=WP_AUTH, timeout=60).json()['meetings']]
    out = []
    for mid in ids:
        meta = requests.get(f'{WP_BASE}/meeting/{mid}', auth=WP_AUTH, timeout=60, params={
            'context': 'edit', '_fields': 'title,meta.segments_json,meta.votes_json,meta.review_json'}).json()
        votes = [v for v in json.loads(meta['meta']['votes_json'] or '[]') if v.get('source') == 'minutes']
        if not votes:
            continue
        review = json.loads(meta['meta']['review_json'] or '{}') or {}
        out.append((meta['title']['raw'], json.loads(meta['meta']['segments_json'] or '[]'),
                    votes, review.get('votes') or {}))
    return out


def accepted_times(votes, decisions):
    """{position: seconds or None}: a decision wins; otherwise the current placement, if any."""
    out = {}
    for i, v in enumerate(votes):
        d = decisions.get(v.get('key'))
        if d:
            out[i] = None if d['status'] == 'cleared' else d.get('start_seconds')
        elif v.get('start_seconds') is not None:
            out[i] = v['start_seconds']
    return out


def main():
    parser = argparse.ArgumentParser(description='Score the vote matcher against accepted times')
    parser.add_argument('-v', '--verbose', action='store_true', help='List every miss')
    parser.add_argument('--anchored', action='store_true', help='Pass Review times decisions as anchors')
    args = parser.parse_args()

    right = wrong = unplaced = 0
    misses = []
    for title, segments, votes, decisions in meetings_with_minutes():
        truth = accepted_times(votes, decisions)
        fresh = [copy.deepcopy(v) for v in votes]
        for v in fresh:
            for k in ('start_seconds', 'roll_call_seconds', 'end_seconds', 'matched', 'match_method', 'match_score', 'reviewed'):
                v.pop(k, None)
        pinned = None
        if args.anchored:
            pinned = {i: (None if (d := decisions[v['key']])['status'] == 'cleared' else d.get('start_seconds'))
                      for i, v in enumerate(fresh) if v.get('key') in decisions}
        match_agenda.time_votes(fresh, segments, pinned)
        for i, v in enumerate(fresh):
            if truth.get(i) is None:
                continue
            got = v.get('start_seconds')
            if got is None:
                unplaced += 1
                misses.append(('unplaced', title, v, truth[i]))
            elif abs(got - truth[i]) <= TOLERANCE:
                right += 1
            else:
                wrong += 1
                misses.append(('WRONG', title, v, truth[i]))

    total = right + wrong + unplaced
    print(f'{total} votes: {right} right, {wrong} WRONG (placed elsewhere), {unplaced} unplaced')
    if args.verbose:
        for kind, title, v, t in misses:
            print(f"  {kind:8} {title[-26:]:>26}  v{v['index']:<3} accepted {fmt(t):>8}  got {fmt(v.get('start_seconds')):>8}"
                  f"  score {v.get('match_score')}  | {v.get('motion_text', '')[:50]}")


if __name__ == '__main__':
    main()
