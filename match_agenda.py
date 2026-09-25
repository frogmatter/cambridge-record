"""
Cambridge Record — place votes and agenda items on the video timeline

Minutes say what was voted; captions say when. This module:

  1. Finds roll calls in the captions — a burst of vote words (yes / no /
     absent / present) interleaved with titles (member / mayor / chair).
     Caption names are unreliable ("Doobie", "Jake Amara"); titles and vote
     words are not.
  2. Pairs roll calls with the minutes' votes, in order, scoring each pair
     by how well the tallies agree. A monotonic alignment means one misheard
     roll call can't shift every vote after it.
  3. Times each vote at the motion just before its roll call.
  4. Times each docketed agenda item at the first mention of its number
     ("item 26177") after the previous vote — skipping public commenters who
     cite it earlier — or at its vote if it's never said aloud.
  5. Times agenda sections at the chair's transition ("that brings us to
     unfinished business"), which works even before minutes are posted.

Every time written here is a best guess from captions: items carry
match_method and match_score so a person can review them.
"""

import re

VOTE_WORDS = {
    'yes':     re.compile(r'\b(?:yes|yea|yeah|aye)\b', re.I),
    'no':      re.compile(r'\b(?:no|nay)\b', re.I),
    'absent':  re.compile(r'\babsent\b', re.I),
    'present': re.compile(r'\bpresent\b', re.I),
}
TITLE_RE       = re.compile(r'\b(?:re)?member\b|\bmayor\b|\bchair\b', re.I)   # "Remember Hudson" = "Member Hudson"
ROLL_CALL_RE   = re.compile(r'roll\s*call', re.I)
VOICE_VOTE_RE  = re.compile(r'\ball\s+(?:those\s+)?in\s+favou?r\b', re.I)
MOTION_RE      = re.compile(r'\b(?:motion|move|moved|second|seconded)\b', re.I)

# How agenda sections are announced: a transition phrase, then the section name
TRANSITION = r'(?:next item(?: on (?:our|the) agenda)? is|now we(?: are|\'re) at|moves? us|brings? us to|(?:now )?hear from|begin with|start with|bring(?:ing)? forth|(?:move|moved|moving|turn|turning|go|going) (?:on )?(?:to|into)|bring(?:ing)? forward|now (?:we )?(?:have|move to|bring forward)|next (?:is|up|we have)|on to)'
SECTION_WORDS = {
    '1':  r'public comment',
    '2':  r'student (?:school committee )?report',
    '3':  r'(?:presentation of the )?records',
    '4':  r'reconsideration',
    '5':  r'unfinished business',
    '6':  r'awaiting reports?',
    '7':  r"superintendent'?s agenda",
    '7a': r"superintendent'?s update",
    '7b': r'presentations?(?! of (?:the )?records)',
    '7c': r'district plan',
    '7d': r'consent agenda',
    '8':  r'non[- ]?consent',
    '9':  r'school committee agenda',
    '10': r'resolutions?',
    '11': r'announcements?',
    '12': r'late orders?',
    '13': r'communications',
}

CLUSTER_GAP     = 20    # max seconds between votes of one roll call (clerks pause, re-call members)
MIN_VOTE_WORDS  = 4
MIN_TITLE_WORDS = 3
MOTION_LOOKBACK = 60    # seconds before a roll call to look for the motion
MIN_PAIR_SCORE  = 0.4


def fix_mojibake(text):
    """'Iâ\x80\x99ll' → 'I’ll' (UTF-8 captions that were decoded as Latin-1 at ingest)."""
    if 'â' not in text and 'Ã' not in text:
        return text
    try:
        return text.encode('latin-1').decode('utf-8')
    except UnicodeError:
        return text


def _clean(text):
    # Captions use curly apostrophes; section patterns use straight ones
    return fix_mojibake(text).replace('’', "'").replace('‘', "'")


# ── 1. Roll calls in the captions ──────────────────────────────────────────────

VOTE_TOKENS  = {'yes': 'yes', 'yea': 'yes', 'yeah': 'yes', 'aye': 'yes', 'no': 'no', 'nay': 'no',
                'absent': 'absent', 'present': 'present'}
TITLE_TOKENS = {'member', 'remember', 'mayor', 'chair'}   # "Remember Hudson" = "Member Hudson"
PAIR_REACH   = 4    # max name tokens between a title and its vote ("Member. De Paula Santos. Yes")
MIN_PAIRS    = 4    # title→vote pairs needed to count as a roll call


def _tokens(segments):
    """Flat [(time, word, is_roll_call_marker)] across all cues."""
    out = []
    for s in segments:
        t = float(s['start_seconds'])
        text = _clean(s['text'])
        if ROLL_CALL_RE.search(text):
            out.append((t, '<roll call>', True))
        out += [(t, w.lower(), False) for w in re.findall(r"[A-Za-z']+", text)]
    return out


def _pairs(tokens):
    """
    Title→vote pairs: 'Member. Hudson. Yes.' → (time, 'yes', 'member').
    A pair can't reach across another title, so 'Member. Hudson. Member.
    Chair. Weinstein. Yes.' gives Weinstein's vote to the chair only.
    """
    pairs = []
    for i, (t, w, marker) in enumerate(tokens):
        if marker or w not in TITLE_TOKENS:
            continue
        title = 'vice chair' if w == 'chair' and i and tokens[i - 1][1] == 'vice' else w
        for t2, w2, marker2 in tokens[i + 1:i + 1 + PAIR_REACH + 1]:
            if marker2 or w2 in TITLE_TOKENS or w2 == 'vice':
                break
            if w2 in VOTE_TOKENS:
                pairs.append({'time': t2, 'index': i, 'vote': VOTE_TOKENS[w2], 'title': title})
                break
    return pairs


def find_roll_calls(segments):
    """
    Returns [{start, end, counts: {yes, no, absent, present}, pairs, kind}] in
    time order. kind is 'roll_call', 'attendance' (present/absent only) or
    'voice'. A roll call is a run of title→vote pairs; it ends at a gap, at a
    new "roll call, please", or after the chair votes (the chair votes last).
    """
    tokens = _tokens(segments)
    markers = [i for i, tok in enumerate(tokens) if tok[2]]

    groups, cur = [], []
    for p in _pairs(tokens):
        if cur:
            gap = p['time'] - cur[-1]['time'] > CLUSTER_GAP
            new_call = any(cur[-1]['index'] < m < p['index'] for m in markers)
            after_chair = cur[-1]['title'] == 'chair'
            if gap or new_call or after_chair:
                groups.append(cur)
                cur = []
        cur.append(p)
    if cur:
        groups.append(cur)

    found = []
    for g in groups:
        if len(g) < MIN_PAIRS:
            continue
        counts = {k: sum(1 for p in g if p['vote'] == k) for k in ('yes', 'no', 'absent', 'present')}
        first_title = tokens[g[0]['index']][0]
        start = first_title
        # Start at "we have a roll call, please" if it's just before
        for m in markers:
            if first_title - 15 <= tokens[m][0] <= first_title:
                start = tokens[m][0]
        kind = 'attendance' if counts['yes'] + counts['no'] == 0 and counts['present'] else 'roll_call'
        found.append({'start': start, 'end': g[-1]['time'], 'counts': counts, 'pairs': len(g), 'kind': kind})

    for s in segments:
        if VOICE_VOTE_RE.search(s['text']):
            t = float(s['start_seconds'])
            if not any(r['start'] - 5 <= t <= r['end'] + 5 for r in found):
                found.append({'start': t, 'end': t + 10, 'counts': {}, 'pairs': 0, 'kind': 'voice'})

    return sorted(found, key=lambda r: r['start'])


# ── 2. Pair minutes votes with caption roll calls ──────────────────────────────

# Words that should be said around a vote, by result (minutes → captions)
RESULT_WORDS = {
    'closed':            r'public comment|close',
    'reopened':          r'public comment|reopen',
    'approved':          r'records|minutes',
    'accepted':          r'records|minutes|accept|report',
    'tabled':            r'\btabl',
    'rules suspended':   r'suspend|bring forward|brought forward|bring forth',
    'brought forward':   r'bring forward|brought forward|bring forth',
    'extended':          r'\bextend',
    'adjourned':         r'\badjourn',
    'executive session': r'executive session',
    'referred':          r'\brefer',
    'amended':           r'\bamend',
    'postponed':         r'postpone',
    'placed on calendar': r'calendar|unfinished business',
}
# Words for votes named by agenda section rather than result
SECTION_CONTEXT = {
    '1':  r'public comment',
    '3':  r'records|minutes',
    '7d': r'consent',
    '8':  r'non[- ]?consent|pulled',
    '10': r'resolution',
    '12': r'late order|\border\b',
    '13': r'\badjourn',
}
PAIR_BONUS = 0.5   # per matched pair: prefer matching every vote over a higher-scoring subset


def _context_text(segments, start, end):
    """Captions from the previous roll call up to just after this one — the discussion this vote closes."""
    return ' '.join(_clean(s['text']) for s in segments if start <= float(s['start_seconds']) <= end + 10)


def _context_score(vote, text):
    """
    0–1 from what's said around the roll call: 1 if the vote's docket number
    (or late order / resolution) is mentioned, or its result word ("table",
    "adjourn"); 0.5 when there's nothing distinctive to look for.
    """
    cues = [_docket_patterns(d) for d in vote.get('dockets', [])]
    words = RESULT_WORDS.get(vote['result'])
    section_words = SECTION_CONTEXT.get(vote.get('section'))
    if 'late order' in vote['motion_text'].lower():
        words = SECTION_CONTEXT['12']
    elif section_words and (not words or len(cues) > 1):
        # e.g. a consent-agenda bundle: "approve the consent agenda", not each number
        words = section_words if not words else f'{words}|{section_words}'
    if not cues and not words:
        return 0.5
    if any(c.search(text) for c in cues) or (words and re.search(words, text, re.I)):
        return 1.0
    return 0.0


def _pair_score(vote, rc, context=''):
    """
    0–1: how well a caption roll call matches a minutes vote — half from the
    tally agreeing, half from the right docket/topic being said nearby.
    """
    return 0.5 * _tally_score(vote, rc) + 0.5 * _context_score(vote, context) if _tally_score(vote, rc) else 0.0


def _tally_score(vote, rc):
    """0–1: how well the caption tally matches the minutes tally."""
    if vote['method'] == 'voice':
        return 0.8 if rc['kind'] == 'voice' else 0.0
    if rc['kind'] == 'voice':
        return 0.0

    tally = {'yes': 0, 'no': 0, 'absent': 0, 'present': 0}
    for p in vote.get('roll_call', []):
        key = {'YEA': 'yes', 'NAY': 'no', 'ABSENT': 'absent', 'PRESENT': 'present'}.get(p['vote'])
        if key:
            tally[key] += 1
    if not sum(tally.values()):
        return 0.3   # vote with no recorded tally: weak, order-only match
    if rc['kind'] == 'attendance' and tally['yes'] + tally['no']:
        return 0.0

    members = max(sum(tally.values()), 1)
    diff = sum(abs(tally[k] - rc['counts'].get(k, 0)) for k in tally)
    return max(0.0, 1 - diff / (2 * members))


def align_votes(votes, roll_calls, segments):
    """
    Monotonic alignment (like a weighted longest-common-subsequence):
    returns {vote_index: (roll_call_index, score)} maximizing total score.
    """
    n, m = len(votes), len(roll_calls)
    contexts = [_context_text(segments, roll_calls[j - 1]['end'] if j else 0.0, rc['end'])
                for j, rc in enumerate(roll_calls)]
    score = {(i, j): _pair_score(votes[i], roll_calls[j], contexts[j]) for i in range(n) for j in range(m)}
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = [(best[i - 1][j], 'skip_vote'), (best[i][j - 1], 'skip_rc')]
            s = score[(i - 1, j - 1)]
            if s >= MIN_PAIR_SCORE:
                options.append((best[i - 1][j - 1] + s + PAIR_BONUS, 'pair'))
            best[i][j], move[i][j] = max(options, key=lambda o: o[0])

    pairs, i, j = {}, n, m
    while i > 0 and j > 0:
        step = move[i][j]
        if step == 'pair':
            pairs[i - 1] = (j - 1, score[(i - 1, j - 1)])
            i, j = i - 1, j - 1
        elif step == 'skip_vote':
            i -= 1
        else:
            j -= 1
    return pairs


def _motion_time(segments, roll_start, not_before):
    """Earliest motion/second cue in the lead-up to a roll call."""
    lo = max(not_before, roll_start - MOTION_LOOKBACK)
    for s in segments:
        t = float(s['start_seconds'])
        if lo <= t < roll_start and MOTION_RE.search(s['text']):
            return t
    return roll_start


def time_votes(votes, segments):
    """Set start_seconds / roll_call_seconds / match fields on minutes votes, in place."""
    roll_calls = find_roll_calls(segments)
    pairs = align_votes(votes, roll_calls, segments)

    prev_end = 0.0
    for i, v in enumerate(votes):
        if i not in pairs:
            v.update({'start_seconds': None, 'roll_call_seconds': None, 'end_seconds': None,
                      'matched': False, 'match_score': 0})
            continue
        j, score = pairs[i]
        rc = roll_calls[j]
        start = _motion_time(segments, rc['start'], prev_end)
        v.update({
            'start_seconds':     round(start, 2),
            'roll_call_seconds': round(rc['start'], 2),
            'end_seconds':       round(rc['end'], 2),
            'matched':           True,
            'match_method':      'roll_call' if rc['kind'] != 'voice' else 'voice_vote',
            'match_score':       round(score, 2),
        })
        prev_end = rc['end']
    return votes


# ── 3. Agenda items and sections ───────────────────────────────────────────────

def _docket_patterns(docket):
    """'26-177' as spoken in captions: '26177', '26-177', '26 177', 'item 177'."""
    year, num = docket.split('-')
    return re.compile(rf'\b{year}\s?-?\s?{num}\b|\b(?:item|motion|number)\s+{num}\b', re.I)


def _first_mention(segments, pattern, after, before=None):
    for s in segments:
        t = float(s['start_seconds'])
        if t <= after or (before is not None and t > before):
            continue
        if pattern.search(_clean(s['text'])):
            return t
    return None


def time_agenda(agenda, votes, segments):
    """Set start_seconds / match fields on agenda items and sections, in place."""
    by_index = {v['index']: v for v in votes}
    timed_votes = sorted((v for v in votes if v.get('start_seconds') is not None), key=lambda v: v['start_seconds'])

    # Items: first mention after the previous (timed) vote, before their own vote
    for a in agenda:
        a.update({'start_seconds': None, 'matched': False, 'match_method': None})
        if a['item_type'] == 'section':
            continue
        own = [by_index[i] for i in a.get('vote_indexes', []) if by_index.get(i, {}).get('start_seconds') is not None]
        if not own:
            continue
        first_vote = min(own, key=lambda v: v['start_seconds'])
        earlier = [v for v in timed_votes if v['end_seconds'] < first_vote['start_seconds']]
        after = earlier[-1]['end_seconds'] if earlier else 0.0
        mention = _first_mention(segments, _docket_patterns(a['docket']), after, first_vote['start_seconds']) if a.get('docket') else None
        if mention is not None:
            a.update({'start_seconds': round(mention, 2), 'matched': True, 'match_method': 'docket_mention'})
        else:
            a.update({'start_seconds': first_vote['start_seconds'], 'matched': True, 'match_method': 'vote',
                      '_window_start': after})

    # Sections: the chair's transition phrase, searched in agenda order
    windows = []   # (time, text of this cue + the one before it)
    prev = ''
    for s in segments:
        text = _clean(s['text'])
        windows.append((float(s['start_seconds']), f'{prev} {text}'))
        prev = text

    # Sections are usually taken in order, but not always (records before
    # the student report, an item brought forward), so each is searched
    # across the whole meeting, preferring a match after the previous one.
    cursor = 0.0
    sections = [a for a in agenda if a['item_type'] == 'section']
    for idx, sec in enumerate(sections):
        words = SECTION_WORDS.get(sec['item_number'])
        found = None
        if words:
            rx = re.compile(rf'{TRANSITION}\W+(?:\w+\W+){{0,4}}?(?:the\s+)?{words}', re.I)
            hits = [t for t, text in windows if rx.search(text)]
            parent = re.match(r'^(\d+)[a-d]$', sec['item_number'] or '')
            parent_start = next((p['start_seconds'] for p in sections
                                 if parent and p['item_number'] == parent.group(1) and p.get('start_seconds') is not None), None)
            if parent_start is not None:   # a subsection can't start before its section
                hits = [t for t in hits if t >= parent_start]
            found = next((t for t in hits if t > cursor), hits[0] if hits else None)
            if sec['item_number'] == '1' and found is None:
                found = next((t for t, text in windows if re.search(words, text, re.I)), None)
        # Otherwise: the earliest timed item in the section
        children = []
        for a in agenda[agenda.index(sec) + 1:]:
            if a['item_type'] == 'section':
                break
            children.append(a)
        child_times = [c['start_seconds'] for c in children if c.get('start_seconds') is not None]
        if found is not None:
            sec.update({'start_seconds': round(found, 2), 'matched': True, 'match_method': 'section_phrase'})
            cursor = max(cursor, found)
        elif child_times:
            sec.update({'start_seconds': min(child_times), 'matched': True, 'match_method': 'first_item'})

        # Items never mentioned by number start when the chair opens their
        # section (if that's after the previous vote); untimed items such as
        # records presented for approval take the section's time.
        if sec.get('start_seconds') is not None:
            for c in children:
                if c.get('match_method') == 'vote' and c['_window_start'] <= sec['start_seconds'] < c['start_seconds']:
                    c.update({'start_seconds': sec['start_seconds'], 'match_method': 'section_phrase'})
                elif c.get('start_seconds') is None and c['item_type'] in ('records', 'other'):
                    c.update({'start_seconds': sec['start_seconds'], 'matched': True, 'match_method': 'section'})

    # No vote to anchor on (minutes not posted yet): an item starts at the
    # first mention of its number inside its section's time span, or at the
    # section start for consent items that are never read out individually.
    timed_sections = [a for a in sections if a.get('start_seconds') is not None]
    for sec in timed_sections:
        later = [t['start_seconds'] for t in timed_sections if t['start_seconds'] > sec['start_seconds']]
        until = min(later) if later else None
        i = agenda.index(sec) + 1
        while i < len(agenda) and agenda[i]['item_type'] != 'section':
            item = agenda[i]
            if item.get('start_seconds') is None and item.get('docket'):
                mention = _first_mention(segments, _docket_patterns(item['docket']), sec['start_seconds'] - 1, until)
                if mention is not None:
                    item.update({'start_seconds': round(mention, 2), 'matched': True, 'match_method': 'docket_mention'})
                elif item['item_type'] == 'recommendation' and sec['item_number'] == '7d':
                    item.update({'start_seconds': sec['start_seconds'], 'matched': True, 'match_method': 'section'})
            elif item.get('start_seconds') is None and item['item_type'] in ('records', 'other', 'late_order', 'resolution'):
                item.update({'start_seconds': sec['start_seconds'], 'matched': True, 'match_method': 'section'})
            i += 1

    # A first subsection ("7a. Superintendent's Update") starts with its parent
    starts = {a['item_number']: a['start_seconds'] for a in sections if a.get('start_seconds') is not None}
    for sec in sections:
        m = re.match(r'^(\d+)a$', sec['item_number'] or '')
        if sec.get('start_seconds') is None and m and m.group(1) in starts:
            sec.update({'start_seconds': starts[m.group(1)], 'matched': True, 'match_method': 'parent_section'})

    for a in agenda:
        a.pop('_window_start', None)
    return agenda
