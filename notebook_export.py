"""
Cambridge Record — meeting files for a notebook (NotebookLM / Gemini)

Writes one Markdown file per meeting, built from what WordPress already holds:
the meeting's details, the members, the agenda with times, the votes (official
from the minutes, or possible votes from the captions until minutes are
posted), and the corrected transcript in timestamped paragraphs with the
agenda's section headings at their times.

The captions don't say who is speaking, so neither does the file; its notes
tell the notebook how speakers can be worked out (the chair recognises
members by title, public speakers give their names).

Usage:
    python notebook_export.py --show 11610     # one meeting → exports/notebook/
    python notebook_export.py --all            # every published meeting
"""

import argparse
import json
import re
import sqlite3

from improve_captions import ROOT, _wp, fmt_time
from match_agenda import fix_mojibake

OUT_DIR = ROOT / 'exports' / 'notebook'

# A paragraph ends at the first sentence end after this many seconds,
# and at the latest after the longer limit
PARAGRAPH_SECONDS = 45
PARAGRAPH_MAX_SECONDS = 90

VOTE_WORDS = {'YEA': 'yes', 'NAY': 'no', 'ABSENT': 'absent', 'PRESENT': 'present',
              'ABSTAIN': 'abstained', 'RECUSED': 'recused', 'CANDIDATE': 'candidate'}


def fetch_meeting(wp_id):
    requests, base, auth = _wp()
    r = requests.get(f'{base}/meeting/{wp_id}', auth=auth, timeout=120,
                     params={'context': 'edit', '_fields': 'title,link,status,meta'})
    r.raise_for_status()
    return r.json()


def members_on(day):
    """Voting and non-voting officials serving on that date, in roster order."""
    roster = json.loads((ROOT / 'officials.json').read_text(encoding='utf-8'))['officials']
    return [o for o in roster
            if (o.get('term_start') or '') <= day and (not o.get('term_end') or day <= o['term_end'])]


def paragraphs(segments, headings):
    """[(kind, start_seconds, text)]: 'heading' and 'text' entries in time order."""
    headings = sorted(headings, key=lambda h: h[0])
    out, words, start = [], [], None

    def flush():
        nonlocal words, start
        if words:
            out.append(('text', start, ' '.join(words)))
        words, start = [], None

    for seg in segments:
        t = seg['start_seconds']
        while headings and headings[0][0] <= t:
            flush()
            out.append(('heading', *headings.pop(0)))
        text = fix_mojibake(seg['text']).strip()
        if not text:
            continue
        if start is None:
            start = t
        words.append(text)
        length = seg.get('end_seconds', t) - start
        if (length >= PARAGRAPH_SECONDS and re.search(r'[.?!]["”’]?$', text)) or length >= PARAGRAPH_MAX_SECONDS:
            flush()
    flush()
    out += [('heading', *h) for h in headings]
    return out


def vote_lines(vote):
    when = f'[{fmt_time(vote["start_seconds"])}] ' if vote.get('start_seconds') is not None else '[time not found] '
    if vote.get('source') == 'captions':
        said = fix_mojibake(vote.get('motion_text') or vote.get('raw_context') or '').strip()
        line = f'- {when}Possible {vote.get("method", "vote").replace("_", " ")}'
        if said:
            line += f': "{said}"'
        if vote.get('result') and vote['result'] != 'unknown':
            line += f' (chair: {vote["result"]})'
        if vote.get('vote_for') is not None:
            line += f' — {vote["vote_for"]} for, {vote.get("vote_against") or 0} against'
        return [line]
    dockets = ', '.join(f'#{d}' for d in vote.get('dockets') or [])
    motion = fix_mojibake(vote.get('motion_text') or '').strip()
    named = re.sub(r'(\d)-\s+(\d)', r'\1-\2', motion)   # "#26- 202" in the minutes
    if dockets and not any(d in named for d in vote['dockets']):
        motion = f'{dockets}: {motion}' if motion else dockets
    line = f'- {when}{motion or "Vote"}'
    by = [p for p in (f'moved by {vote["mover"]}' if vote.get('mover') else '',
                      f'seconded by {vote["seconder"]}' if vote.get('seconder') else '') if p]
    if by:
        line += f' ({", ".join(by)})'
    result = vote.get('result') or ('passed' if vote.get('passed') else '')
    if vote.get('method') == 'roll_call' and vote.get('vote_for') is not None:
        result += f', {vote["vote_for"]}–{vote.get("vote_against") or 0}'
    elif vote.get('method') == 'voice':
        result += ', on a voice vote'
    if result:
        line += f' — {result.strip(", ")}'
    lines = [line]
    if vote.get('roll_call'):
        lines.append('  - Roll call: ' + '; '.join(
            f'{r["member"]}: {r.get("candidate") or VOTE_WORDS.get(r["vote"], r["vote"].lower())}'
            for r in vote['roll_call']))
    return lines


def build(meeting, show_id):
    meta = meeting['meta']
    title = fix_mojibake(meeting['title']['raw'])
    day = meta['meeting_date']
    link = meeting['link']
    segments = json.loads(meta.get('segments_json') or '[]')
    agenda = json.loads(meta.get('agenda_json') or '[]')
    votes = json.loads(meta.get('votes_json') or '[]')
    official = any(v.get('source') == 'minutes' for v in votes)

    lines = [f'# {title}', '',
             f'- Date: {day}',
             f'- Body: {meta.get("meeting_body") or "Cambridge School Committee"}']
    if meta.get('meeting_purpose'):
        lines.append(f'- Called for the purpose of: {fix_mojibake(meta["meeting_purpose"])}')
    lines.append(f'- Video and transcript: {link} (add #t=SECONDS to open at a moment, e.g. {link}#t=3600)')
    if meta.get('agenda_url'):
        lines.append(f'- Agenda: {meta["agenda_url"]}')
    minutes_url = next((v['source_url'] for v in votes if v.get('source_url')), None)
    if minutes_url:
        lines.append(f'- Minutes: {minutes_url}')
    lines.append(f'- Cablecast show: {show_id}')

    lines += ['', '## About this document', '',
              'The transcript is the meeting\'s automatic captions, with Cambridge names corrected. '
              'It does not label speakers. The chair runs the meeting and recognises each speaker '
              '("Member Hudson", "Mr. Superintendent"), members are addressed by title and surname, and '
              'public commenters are called by name and usually state their name and address; use those '
              'cues to work out who is speaking, and say so when it is unclear. Times are [h:mm:ss] from '
              'the start of the video. Captions can mishear words; the minutes are the official record of '
              'what was decided.']

    members = members_on(day)
    if members:
        lines += ['', '## School Committee members', '']
        for o in members:
            subs = ', '.join(f'{s["name"]}{" (" + s["role"] + ")" if s.get("role") and s["role"] != "Member" else ""}'
                             for s in o.get('subcommittees') or [])
            vote_note = '' if o.get('is_voting_member', True) else ', non-voting'
            lines.append(f'- {o["official_title"]} {o["full_name"]} (addressed as "{o["official_title"]} '
                         f'{o["minutes_name"]}"{vote_note})' + (f'; subcommittees: {subs}' if subs else ''))

    if agenda:
        lines += ['', '## Agenda', '']
        for a in agenda:
            when = f' — at {fmt_time(a["start_seconds"])}' if a.get('start_seconds') is not None else ''
            name = fix_mojibake(a.get('title') or '').strip()
            if a.get('item_type') == 'section':
                lines.append(f'- **{a.get("item_number") or a.get("section") or ""}. {name}**{when}')
            else:
                docket = f'#{a["docket"]} ' if a.get('docket') else ''
                kind = f' ({a["item_type"]})' if a.get('item_type') and a['item_type'] not in ('other', 'records') else ''
                sponsors = f'; sponsors: {a["sponsors"]}' if a.get('sponsors') else ''
                lines.append(f'  - {docket}{name}{kind}{sponsors}{when}')

    if votes:
        lines += ['', '## Votes (official, from the minutes)' if official else
                  '## Possible votes (found in the captions; the minutes are not posted yet)', '']
        for v in sorted(votes, key=lambda v: (v.get('start_seconds') is None, v.get('start_seconds') or 0)):
            lines += vote_lines(v)

    headings = [(a['start_seconds'], f'{a.get("item_number") or a.get("section") or ""}. '
                                     f'{fix_mojibake(a.get("title") or "").strip()}')
                for a in agenda if a.get('item_type') == 'section' and a.get('start_seconds') is not None]
    lines += ['', '## Transcript', '']
    for kind, start, text in paragraphs(segments, headings):
        if kind == 'heading':
            lines += [f'### {text} [{fmt_time(start)}]', '']
        else:
            lines += [f'[{fmt_time(start)}] {text}', '']
    return title, day, '\n'.join(lines).rstrip() + '\n'


def export(show_id, wp_id, published_only=False):
    meeting = fetch_meeting(wp_id)
    if published_only and meeting['status'] != 'publish':
        return None
    title, day, text = build(meeting, show_id)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^\w.-]+', ' ', title.replace('/', '-')).strip()
    path = OUT_DIR / f'{day} {name}.md'
    path.write_text(text, encoding='utf-8')
    return path


def main():
    parser = argparse.ArgumentParser(description='Write meeting files for a notebook (NotebookLM / Gemini)')
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument('--show', type=int, help='Cablecast show ID')
    which.add_argument('--all', action='store_true', help='Every published meeting')
    args = parser.parse_args()

    sql = "SELECT cablecast_show_id, wp_meeting_id FROM ingested_shows WHERE status = 'complete'"
    params = ()
    if args.show:
        sql += ' AND cablecast_show_id = ?'
        params = (args.show,)
    rows = sqlite3.connect(ROOT / 'pipeline.db').execute(sql + ' ORDER BY show_date', params).fetchall()
    if not rows:
        raise SystemExit('No ingested meeting with that show ID')
    for show_id, wp_id in rows:
        path = export(show_id, wp_id, published_only=args.all)
        if not path:
            print(f'skipped show {show_id} (not published)')
            continue
        print(f'{path}  ({path.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
