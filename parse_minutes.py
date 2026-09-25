"""
Cambridge Record — CPS minutes parser (votes)

School Committee minutes (PDF, posted on the CPS portal weeks after the
meeting) record every vote in a consistent form:

    On a motion by Mayor Siddiqui, seconded by Member Jaikumar, #26-177 was
    adopted on the following roll call vote: Member Jaikumar, YEA; Mayor
    Siddiqui, YEA; ... Chair Weinstein, YEA

Parsing is anchored on each vote's *outcome* — a roll-call tally, "on a
voice vote", or "it was voted to" — and looks back from there for the
motion, mover and seconder. That copes with the variants seen in 2026
minutes: missing commas, votes with no "On a motion" sentence, voice
votes, NAYs, and tallies with a member's vote left out.

Minutes say what was voted, not when. start_seconds stays None here and
is filled in by matching roll calls against the transcript (later step).

Usage (prints what it finds; writes nothing):
    python parse_minutes.py https://portal.cpsd.us/school_committee/admin/minutes/613_2026-08-04.pdf
    python parse_minutes.py path/to/minutes.pdf --json
"""

import argparse
import io
import json
import re

import requests
from pypdf import PdfReader

HEADERS = {'User-Agent': 'CambridgeRecord/0.1 (+https://www.mediatechaction.com)'}

# "Member de Paula Santos", "Vice Chair Dube", "Mayor Siddiqui".
# pypdf sometimes splits a word after its first letter ("S antos", "YE A"),
# so names and votes tolerate one stray space; _clean() removes it.
NAME = (r"(?:Vice Chair|Chair|Mayor|Memb?er)\s+"
        r"(?:(?:de|da|del|van|von|la|le)\s+)*[A-Z]\s?[\w’'\-]+"
        r"(?:\s+(?:(?:de|da|del)\s+)?[A-Z]\s?[a-z][\w’'\-]*){0,2}")
NAME_RE = re.compile(NAME)
VOTE = r'Y\s?E\s?A|N\s?A\s?Y|YES|NO|A\s?B\s?S\s?E\s?N\s?T|P\s?R\s?E\s?S\s?E?\s?N\s?T|ABSTAIN(?:ED)?|RECUSED'
# In elections (chair, vice chair) members vote for a person: "Member Hudson, MEMBER DUBE"
CANDIDATE = r"(?:VICE CHAIR|CHAIR|MAYOR|MEMBER)\s+[A-Z][A-Z’'\-]+(?:\s+[A-Z][A-Z’'\-]+){0,2}"
PAIR_RE = re.compile(rf'(?P<member>{NAME})\s*,\s*(?:(?P<vote>{VOTE})|(?P<candidate>{CANDIDATE}))\b')
VOTE_ALIASES = {'YES': 'YEA', 'NO': 'NAY', 'ABSTAINED': 'ABSTAIN', 'PRESNT': 'PRESENT'}
# Between pairs: separators, plus a stray bare vote ("Mayor Siddiqui, YEA; YEA; Chair …")
TALLY_SEP_RE = re.compile(r'[\s,;]*(?:(?:YEA|NAY)\s*;\s*)?')

OUTCOME_RE = re.compile(
    r'(?P<roll>(?:on\s+)?(?:the\s+)?(?:following\s+)?roll\s+call(?:\s+vote)?(?=\s*[:,]))'
    r'|(?P<voice>on\s+a\s+voice\s+vote)'
    r'|(?P<voted>\bit\s+was\s+voted\s+to\b)',
    re.I,
)
# Case-sensitive on purpose: names must be capitalized ("Member Jaikumar the meeting" is not a name)
MOTION_RE  = re.compile(rf'(?:(?i:On a motion)(?:\s+by)?\s+)?(?P<mover>{NAME})\s*,?\s*(?i:seconded\s+by)\s+(?P<seconder>{NAME})\s*,?\s*')
DOCKET_RE  = re.compile(r'#\s?(\d{2})\s?-\s?(\d{3})')
# A sentence end — but not the one in "10:30 p.m." or an initial
SENTENCE_END_RE = re.compile(r'(?<![ap]\.m)(?<!\b[A-Z])\.\s+(?=[A-Z#])')

# Agenda section headings as they appear in the minutes ("7d. Consent Agenda:")
SECTION_RE = re.compile(
    r'(?<![\w$.,:])(?P<num>1[0-3]|[1-9][a-d]?)\.\s+(?P<title>Public Comment|Student School Committee Report'
    r'|Presentation of the Records for Approval|Reconsiderations|Unfinished Business/Calendar|Awaiting Reports'
    r"|Superintendent[’']s (?:Agenda|Update)|Presentations|CPS District Plan|Consent Agenda|Non-Consent Agenda"
    r'|School Committee Agenda|Resolutions|Announcements|Late Orders|Communications and Reports from City Officers)'
)
# Running page header pypdf leaves mid-text: "Cambridge School Committee August 4, 2026 Regular Meeting 12"
PAGE_HEADER_RE = re.compile(r'Cambridge School Committee\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s+[A-Za-z()& ]{0,40}?Meeting\s+\d{1,3}\b')

RESULTS = [   # first match wins
    (r'nominations?', 'election'),
    (r'\bfailed\b|was not adopted|was defeated', 'failed'),
    (r'\btabled\b', 'tabled'),
    (r'\bpostponed\b', 'postponed'),
    (r'remained on the calendar', 'placed on calendar'),
    (r'\breferred\b', 'referred'),
    (r'unfinished business calendar', 'placed on calendar'),
    (r'\bamend', 'amended'),
    (r'executive session', 'executive session'),
    (r'\badjourn', 'adjourned'),
    (r'\bsuspended\b', 'rules suspended'),
    (r'\bre-?\s?opened\b', 'reopened'),
    (r'\bclosed\b', 'closed'),
    (r'\bextended\b', 'extended'),
    (r'brought (?:forth|forward)', 'brought forward'),
    (r'\baccepted\b', 'accepted'),
    (r'\bapproved\b', 'approved'),
    (r'\badopted\b', 'adopted'),
]


# ── Text ───────────────────────────────────────────────────────────────────────

def minutes_text(source):
    """Flattened text of a minutes PDF (URL or local path), page headers removed."""
    if re.match(r'https?://', source):
        r = requests.get(source, headers=HEADERS, timeout=60)
        r.raise_for_status()
        reader = PdfReader(io.BytesIO(r.content))
    else:
        reader = PdfReader(source)
    text = ' '.join(page.extract_text() or '' for page in reader.pages)
    text = ' '.join(text.split())
    return PAGE_HEADER_RE.sub(' ', text)


def _clean_name(name):
    """'Member de Paula S antos' → 'Member de Paula Santos'"""
    name = re.sub(r'^Memer\b', 'Member', ' '.join(name.split()))
    return re.sub(r'\b([A-Z]) (?=[a-z])', r'\1', name)


def _clean_text(text):
    """Undo pypdf artifacts in short phrases: '#26- 177', '11: 00', 're- opened', 'S uspended'."""
    text = re.sub(r'#\s?(\d{2})\s?-\s?(\d{3})', r'#\1-\2', text)
    text = re.sub(r'(\d{1,2}):\s(\d{2})', r'\1:\2', text)
    text = re.sub(r'\b([Rr]e)-\s(?=[a-z])', r'\1', text)
    text = re.sub(r'\b([A-Z]) (?=[a-z]{3,})', r'\1', text)
    return ' '.join(text.split())


def _norm_docket(m):
    return f'{m.group(1)}-{m.group(2)}'


# ── Tallies ────────────────────────────────────────────────────────────────────

def _parse_tally(text, pos, lead=250):
    """
    Read a run of 'Member X, YEA; Mayor Y, NAY; ...' pairs starting near pos.
    The first pair may come after up to `lead` chars of text (e.g. "it was
    voted to enter executive session:"); later pairs must follow directly,
    except that one member whose vote the minutes left out is skipped.
    Returns (pairs, lead_text, end).
    """
    first = PAIR_RE.search(text, pos, pos + lead)
    if not first:
        return [], '', pos

    lead_text = text[pos:first.start()].strip(' :,;')
    pairs, end, m = [], first.start(), first
    while m:
        if m.group('candidate'):
            pairs.append({'member': _clean_name(m.group('member')), 'vote': 'CANDIDATE',
                          'candidate': _clean_name(m.group('candidate').title().replace(' De ', ' de '))})
        else:
            vote = re.sub(r'\s', '', m.group('vote').upper())
            pairs.append({'member': _clean_name(m.group('member')), 'vote': VOTE_ALIASES.get(vote, vote)})
        end = m.end()
        sep = TALLY_SEP_RE.match(text, end).end()
        m = PAIR_RE.match(text, sep)
        if not m:   # "Vice Chair Dube, Member Harding, YEA" — skip the member with no vote
            skipped = re.compile(rf'(?:{NAME})\s*,\s*').match(text, sep)
            m = PAIR_RE.match(text, skipped.end()) if skipped else None
    return pairs, lead_text, end


# ── Votes ──────────────────────────────────────────────────────────────────────

def parse_votes(text, source_url=None):
    """List of vote dicts (plugin votes_json schema + extras) found in minutes text."""
    sections = [(m.start(), m.group('num'), m.group('title')) for m in SECTION_RE.finditer(text)]
    docket_heads = [(m.start(), _norm_docket(m)) for m in DOCKET_RE.finditer(text)]

    def section_at(pos):
        found = (None, None)
        for start, num, title in sections:
            if start > pos:
                break
            found = (num, title)
        return found

    votes, cursor = [], 0

    for ev in OUTCOME_RE.finditer(text):
        if ev.start() < cursor:
            continue   # already consumed (e.g. "roll call, it was voted to …")

        method = 'roll_call' if ev.group('roll') else 'voice' if ev.group('voice') else 'unrecorded'
        pairs, lead_text, end = _parse_tally(text, ev.end())

        if method == 'unrecorded':
            stop = re.search(r'\.\s|$', text[ev.end():])
            lead_text = 'voted to ' + text[ev.end():ev.end() + stop.start()].strip()
            end = ev.end() + stop.end()
        if method == 'voice' and pairs and all(p['vote'] in ('YEA', 'NAY') for p in pairs):
            pass   # some voice votes still list members; keep the tally
        elif method == 'voice':
            pairs = []

        # The motion clause: back to "On a motion" if there is one since the
        # last vote, otherwise back to the start of the sentence.
        window_start = max(cursor, ev.start() - 900)
        window = text[window_start:ev.start()]
        motion_at = window.rfind('On a motion')
        if motion_at == -1:
            seconded = list(MOTION_RE.finditer(window))
            limit = seconded[-1].start() if seconded else len(window)
            ends = list(SENTENCE_END_RE.finditer(window, 0, limit))
            motion_at = ends[-1].end() if ends else (seconded[-1].start() if seconded else 0)
        clause_start = window_start + motion_at
        clause = text[clause_start:ev.start()].strip()
        # A section heading inside the clause belongs to the previous context
        heads = list(SECTION_RE.finditer(clause))
        if heads and heads[-1].end() < len(clause) - 5 and not clause.startswith('On a motion'):
            clause = clause[heads[-1].end():].lstrip(' :')

        mover = seconder = None
        action = clause
        m = MOTION_RE.search(clause)
        if m:
            mover, seconder = _clean_name(m.group('mover')), _clean_name(m.group('seconder'))
            action = clause[m.end():]
        action = re.sub(r'^(?:On a motion\S*\s*)', '', action)
        action = ' '.join(filter(None, [action.strip(' ,;:'), lead_text]))
        action = _clean_text(re.sub(r'\s+(?:on|the)$', '', action.strip(' ,;:')))

        dockets = sorted({_norm_docket(d) for d in DOCKET_RE.finditer(action)})
        inferred = False
        section_num, section_title = section_at(clause_start)
        if not dockets and re.search(r'\b(motion|amendment|order|resolution|item)\b', action, re.I):
            section_start = max((s for s, n, _ in sections if s <= clause_start), default=0)
            prior = [d for pos, d in docket_heads if section_start <= pos < clause_start]
            if prior:
                dockets, inferred = [prior[-1]], True

        counts = {v: sum(1 for p in pairs if p['vote'] == v) for v in ('YEA', 'NAY', 'ABSENT', 'PRESENT')}
        abstain = sum(1 for p in pairs if p['vote'] in ('ABSTAIN', 'ABSTAINED', 'RECUSED'))
        # Some minutes record members as PRESENT/ABSENT instead of YEA/NAY
        # (e.g. votes to enter executive session) — no tally to report.
        tallied = bool(counts['YEA'] + counts['NAY'] + abstain)

        result = next((label for pattern, label in RESULTS if re.search(pattern, action, re.I)), 'passed')
        passed = result != 'failed'

        # Election: count votes per candidate; the winner goes in the text
        candidates = {}
        for p in pairs:
            if p['vote'] == 'CANDIDATE':
                candidates[p['candidate']] = candidates.get(p['candidate'], 0) + 1
        if candidates:
            method, result = 'election', 'elected'
            winner, n = max(candidates.items(), key=lambda kv: kv[1])
            action = re.sub(r'\s+(?:and\s+)?asked for an?$', '', action)
            action = f'{action} — {winner} elected with {n} vote{"s" if n != 1 else ""}'
            tallied = False
        if method == 'roll_call' and counts['YEA'] + counts['NAY'] and counts['YEA'] <= counts['NAY']:
            result, passed = 'failed', False

        votes.append({
            'index':           len(votes),
            'section':         section_num,
            'section_title':   section_title,
            'motion_text':     action,
            'mover':           mover,
            'seconder':        seconder,
            'method':          method,
            'result':          result,
            'passed':          passed,
            'vote_for':        counts['YEA'] if tallied else None,
            'vote_against':    counts['NAY'] if tallied else None,
            'vote_abstain':    abstain if tallied else None,
            'vote_absent':     counts['ABSENT'] if tallied else None,
            'voters_for':      [p['member'] for p in pairs if p['vote'] == 'YEA'],
            'voters_against':  [p['member'] for p in pairs if p['vote'] == 'NAY'],
            'roll_call':       pairs,
            'candidates':      candidates,
            'dockets':         dockets,
            'docket_inferred': inferred,
            'raw_context':     text[clause_start:end].strip()[:1200],
            'source':          'minutes',
            'source_url':      source_url,
            'segment_index':   None,
            'start_seconds':   None,
            'deep_link_url':   None,
        })
        cursor = max(end, ev.end())

    return votes


def docket_titles(text):
    """
    Titles for dockets as headed in the minutes, e.g.
    '#26-176 School Climate Subcommittee Report – June 18, 2026'.
    Used for items that were voted on but aren't on the agenda page.
    """
    titles = {}
    stop = r'(?=\s+(?:WHEREAS|RESOLVED|ORDERED|On a motion|There was|The Superintendent|Member|Mayor|Chair|Vice Chair|#\d)|\s*$)'
    for m in re.finditer(rf'#\s?(\d{{2}})\s?-\s?(\d{{3}})\s*:?\s+([A-Z][^#]{{3,110}}?){stop}', text):
        docket = f'{m.group(1)}-{m.group(2)}'
        title = m.group(3).strip(' –-:')
        if docket not in titles and not re.match(r'(was|were|and)\b', title):
            titles[docket] = title
    return titles


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Parse votes from a School Committee minutes PDF')
    parser.add_argument('source', help='Minutes PDF URL or local path')
    parser.add_argument('--json', action='store_true', help='Print votes_json instead of a summary')
    args = parser.parse_args()

    text = minutes_text(args.source)
    votes = parse_votes(text, source_url=args.source)
    if args.json:
        print(json.dumps(votes, indent=2))
        return

    print(f'{len(votes)} vote(s)')
    for v in votes:
        tally = f"{v['vote_for']}-{v['vote_against']}" if v['vote_for'] is not None else v['method']
        against = f" (nay: {', '.join(v['voters_against'])})" if v['voters_against'] else ''
        dockets = ' '.join('#' + d for d in v['dockets']) + ('?' if v['docket_inferred'] else '')
        print(f"  {v['section'] or '-':>3}  {v['result']:<17} {tally:<9}{against}  {dockets}  | {v['motion_text'][:90]}")


if __name__ == '__main__':
    main()
