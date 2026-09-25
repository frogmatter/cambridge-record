"""
Cambridge Record — improve meeting captions with the Cambridge terms list

cambridge_terms.txt (see its header) holds three kinds of line:
    wrong|right    fixes, applied automatically
    ?wrong|right   suggestions, listed for a person to check
    term           vocabulary for the MediaScribe / Cablecast dictionaries

Fixes are applied by enrich_meetings.py every run, always starting from the
original caption text (kept as text_original), so editing the terms file and
re-running is safe. This script reports on how much fixing transcripts need,
exports corrected captions for uploading back to Cablecast, and prints the
vocabulary list.

Usage:
    python improve_captions.py --report                 # all meetings: fixes, likely errors, per hour
    python improve_captions.py --report --show 11498    # one meeting, with details
    python improve_captions.py --export --show 11498    # corrected .vtt/.scc/.srt for Cablecast → exports/
    python improve_captions.py --vocabulary             # terms to paste into MediaScribe / Cablecast
    python improve_captions.py --sample --show 11498 --at 0:02:17   # 10-min worksheet for a person to correct
    python improve_captions.py --score samples/2026-08-04_11498_137.txt  # error rates + staff time
"""

import argparse
import collections
import json
import re
import sqlite3
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent
TERMS_PATH = ROOT / 'cambridge_terms.txt'

# Words that are normal in these meetings even though English overall rarely uses them
EXTRA_WORDS = set('''
okay ok um uh uhm hmm yeah yep nope gonna wanna gotta kinda sorta y'all email emails online website websites
internet zoom covid app apps chromebook chromebooks laptop laptops smartphone smartphones iphone iphones
podcast wifi texting screenshot login logins dashboard dashboards data metadata stakeholder stakeholders
superintendent's covid-19 pre-k prek k-12 k-8 multilingual neurodivergent nonbinary lgbtq lgbtqia bipoc
dei equity edtech esl ell ells sped iep ieps mcas fy fy26 fy27 fy28 ai subcommittee subcommittees
workgroup workgroups onboarding offboarding upskilling microschool preschool preschoolers
'''.split())


# ── Terms ──────────────────────────────────────────────────────────────────────

def load_terms(path=TERMS_PATH):
    """{'fixes': [(wrong, right)], 'suggestions': [(wrong, right)], 'vocabulary': [term]}"""
    fixes, suggestions, vocabulary = [], [], []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split(' #')[0].strip()
        if not line or line.startswith('#'):
            continue
        if '|' in line:
            wrong, right = (part.strip() for part in line.split('|', 1))
            if not wrong or not right:
                continue
            (suggestions if wrong.startswith('?') else fixes).append((wrong.lstrip('?').strip(), right))
            vocabulary.append(right)
        elif not line.startswith('('):
            vocabulary.append(line)
    # Longer phrases first: "member to Paula Santos" before "Paula Santos"
    fixes.sort(key=lambda f: -len(f[0]))
    return {'fixes': fixes, 'suggestions': suggestions, 'vocabulary': sorted(set(vocabulary), key=str.lower)}


def _phrase_re(phrase):
    body = r'\s+'.join(re.escape(w) for w in phrase.split())
    return re.compile(rf"(?<![\w’'-]){body}(?![\w’'-])", re.I)


@lru_cache(maxsize=4)
def _compiled(terms_key):
    terms = load_terms(Path(terms_key))
    return ([(w, r, _phrase_re(w)) for w, r in terms['fixes']],
            [(w, r, _phrase_re(w)) for w, r in terms['suggestions']])


def correct_text(text, terms_path=TERMS_PATH):
    """
    Apply fixes to one caption. Returns (text, [(said, fixed), …]).
    Repeats until nothing changes, so fixes chain ("Remember Jake Amar" →
    "Remember Jaikumar" → "Member Jaikumar"). A fix never applies where the
    right form is already there ("Paula Santos" inside "de Paula Santos").
    """
    fixes, _ = _compiled(str(terms_path))
    changes = []
    for _ in range(4):
        before = text
        for wrong, right, rx in fixes:
            offset = right.lower().find(wrong.lower())

            def repl(m, right=right, offset=offset):
                said = m.group(0)
                if said == right:
                    return said
                if offset >= 0:
                    start = m.start() - offset
                    if start >= 0 and text[start:start + len(right)] == right:
                        return said
                changes.append((said, right))
                return right

            text = rx.sub(repl, text)
        if text == before:
            break
    return text, changes


def find_suggestions(text, terms_path=TERMS_PATH):
    _, suggestions = _compiled(str(terms_path))
    return [(m.group(0), right) for wrong, right, rx in suggestions for m in rx.finditer(text)]


def correct_segments(segments, terms_path=TERMS_PATH):
    """
    Correct every segment in place from its original text. Keeps the
    caption as Cablecast had it in text_original. Returns the number of fixes.
    """
    total = 0
    for seg in segments:
        original = seg.get('text_original', seg['text'])
        fixed, changes = correct_text(original, terms_path)
        total += len(changes)
        if changes:
            seg['text_original'], seg['text'] = original, fixed
        else:
            seg['text'] = original
            seg.pop('text_original', None)
    return total


# ── Likely errors (words English doesn't use) ─────────────────────────────────
#
# A word is a likely captioning error when it's rare in English overall
# (wordfreq Zipf score below RARE_ZIPF — "Jacoar", "Stey", "Siki") and isn't
# in the terms list. Real but rare words ("paraprofessionals" 1.7,
# "Banneker" 1.9) score above it. Errors that are real words ("Jake Moore")
# can't be caught this way — that's what the fixes, and a person, are for.

RARE_ZIPF = 1.5


@lru_cache(maxsize=1)
def known_words():
    words = set(EXTRA_WORDS)
    for term in load_terms()['vocabulary']:
        words.update(w.lower().strip('.,') for w in re.findall(r"[\w’'.&-]+", term))
    return words


@lru_cache(maxsize=50000)
def _is_known(word):
    from wordfreq import zipf_frequency
    w = word.lower().replace('’', "'")
    if w in known_words() or len(w) <= 2:
        return True
    if zipf_frequency(w, 'en') >= RARE_ZIPF:
        return True
    return all(zipf_frequency(part, 'en') >= RARE_ZIPF or part in known_words() for part in w.split('-') if part)


def unknown_words(text):
    return [w for w in re.findall(r"[A-Za-z][A-Za-z’'-]*[A-Za-z]|[A-Za-z]", text) if not _is_known(w)]


# ── Reports ────────────────────────────────────────────────────────────────────

def analyze(segments):
    """Per-meeting numbers for the report. Segments may already be corrected."""
    hours = max((s.get('end_seconds') or s['start_seconds'] for s in segments), default=0) / 3600
    fixes = collections.Counter()
    unknown = collections.Counter()
    suggestions = []
    words = 0
    for seg in segments:
        original = seg.get('text_original', seg['text'])
        fixed, changes = correct_text(original)
        fixes.update(f'{said} → {right}' for said, right in changes)
        words += len(fixed.split())
        unknown.update(w for w in unknown_words(fixed))
        suggestions += [(seg['start_seconds'], said, right) for said, right in find_suggestions(fixed)]
    n_fix, n_unknown = sum(fixes.values()), sum(unknown.values())
    return {
        'hours': hours, 'words': words,
        'fixes': n_fix, 'fixes_per_hour': n_fix / hours if hours else 0,
        'unknown': n_unknown, 'unknown_per_hour': n_unknown / hours if hours else 0,
        'unknown_pct': 100 * n_unknown / words if words else 0,
        'top_fixes': fixes.most_common(), 'top_unknown': unknown.most_common(),
        'suggestions': suggestions,
    }


def fmt_time(s):
    s = int(s)
    return f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}'


# ── WordPress access ───────────────────────────────────────────────────────────

def _wp():
    import requests
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    return requests, env['WP_BASE_URL'].rstrip('/'), (env['WP_USERNAME'], env['WP_APP_PASSWORD'])


def fetch_meetings(show_id=None):
    """[(show_id, wp_id, title, date, segments)] for ingested meetings."""
    requests, base, auth = _wp()
    from match_agenda import fix_mojibake
    sql = "SELECT cablecast_show_id, wp_meeting_id FROM ingested_shows WHERE status = 'complete'"
    args = ()
    if show_id:
        sql += ' AND cablecast_show_id = ?'
        args = (show_id,)
    out = []
    for sid, wp_id in sqlite3.connect(ROOT / 'pipeline.db').execute(sql + ' ORDER BY show_date', args):
        r = requests.get(f'{base}/meeting/{wp_id}', auth=auth, timeout=120,
                         params={'context': 'edit', '_fields': 'title,meta.meeting_date,meta.segments_json'})
        r.raise_for_status()
        d = r.json()
        segments = json.loads(d['meta']['segments_json'] or '[]')
        for seg in segments:
            if 'text_original' in seg:
                seg['text_original'] = fix_mojibake(seg['text_original'])
            seg['text'] = fix_mojibake(seg['text'])
        out.append((sid, wp_id, d['title']['raw'], d['meta']['meeting_date'], segments))
    return out


# ── Export for Cablecast ───────────────────────────────────────────────────────

def _ts(seconds, sep):
    ms = int(round(seconds * 1000))
    return f'{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d}{sep}{ms % 1000:03d}'


# Broadcast (CEA-608) captions have no curly quotes or dashes; in SCC a
# character outside the basic set overwrites the one before it ("I’ll" →
# "’ll"), so the SCC file gets plain punctuation.
PLAIN_PUNCTUATION = {'’': "'", '‘': "'", '“': '"', '”': '"', '—': '--', '–': '-', '…': '...'}


def _plain(text):
    for fancy, plain in PLAIN_PUNCTUATION.items():
        text = text.replace(fancy, plain)
    return text


def write_scc(vtt_text, path):
    """
    SCC (for Cablecast playback) from WebVTT, via PBS's pycaption. Read back
    and compared word for word before it's kept. SCC pop-on captions appear
    about half a second after the WebVTT times — the time broadcast captions
    take to send — which is normal.
    """
    from pycaption import SCCReader, SCCWriter, WebVTTReader
    plain = _plain(vtt_text)
    source = WebVTTReader().read(plain)
    scc = SCCWriter().write(source)
    back = SCCReader().read(scc)
    words = lambda caps: ' '.join(c.get_text() for c in caps.get_captions(caps.get_languages()[0])).split()
    sent, received = words(source), words(back)
    if sent != received:
        bad = next(i for i, (a, b) in enumerate(zip(sent + [''], received + [''])) if a != b)
        raise RuntimeError(f'SCC check failed near word {bad}: {sent[bad:bad + 5]} vs {received[bad:bad + 5]}')
    path.write_text(scc, encoding='utf-8')
    return len(sent)


def export_captions(segments, stem):
    """
    Write corrected captions for Cablecast, keeping the original timings:
    .vtt (Cablecast VOD), .scc (Cablecast playback), .srt (other uses).
    """
    out_dir = ROOT / 'exports'
    out_dir.mkdir(exist_ok=True)
    cues = []
    for i, seg in enumerate(segments):
        start = float(seg['start_seconds'])
        end = seg.get('end_seconds') or (segments[i + 1]['start_seconds'] if i + 1 < len(segments) else start + 3)
        end = max(float(end), start + 0.5)
        fixed, _ = correct_text(seg.get('text_original', seg['text']))
        cues.append((start, end, fixed))
    vtt = ['WEBVTT', ''] + [f'{_ts(s, ".")} --> {_ts(e, ".")}\n{t}\n' for s, e, t in cues]
    srt = [f'{n}\n{_ts(s, ",")} --> {_ts(e, ",")}\n{t}\n' for n, (s, e, t) in enumerate(cues, 1)]
    (out_dir / f'{stem}.vtt').write_text('\n'.join(vtt), encoding='utf-8')
    (out_dir / f'{stem}.srt').write_text('\n'.join(srt), encoding='utf-8')
    write_scc('\n'.join(vtt), out_dir / f'{stem}.scc')
    return out_dir / f'{stem}.vtt', out_dir / f'{stem}.scc', out_dir / f'{stem}.srt'


# ── Measuring human editing: worksheets and scores ─────────────────────────────
#
# How much editing does a meeting need? Only a person listening can say.
# --sample writes a worksheet for a stretch of a meeting (the automatically
# corrected text, one timestamped caption per line); a person corrects it
# while listening and notes the minutes it took. --score compares their
# version with the raw captions and with the automatic fixes: the word error
# rate of each, and minutes of work per hour of meeting.

def parse_clock(text):
    parts = [float(p) for p in str(text).split(':')]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def write_sample(show_id, start, minutes):
    (sid, wp_id, title, day, segments), = fetch_meetings(show_id)
    end = start + minutes * 60
    lines = [s for s in segments if start <= s['start_seconds'] < end]
    if not lines:
        raise SystemExit('No captions in that stretch')
    requests, base, auth = _wp()
    embed = requests.get(f'{base}/meeting/{wp_id}', auth=auth, timeout=30,
                         params={'context': 'edit', '_fields': 'link,meta.cablecast_embed_url'}).json()
    out_dir = ROOT / 'samples'
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f'{day}_{sid}_{int(start)}.txt'
    header = [
        f'# Caption check — {title}',
        f'# show={sid} start={int(start)} end={int(end)}',
        f'# Watch: {embed["link"]}#t={int(start)}   ({fmt_time(start)} to {fmt_time(end)})',
        '#',
        '# 1. Note the time, then play the video from the start time above.',
        '# 2. Correct each line so it says what was actually said: fix wrong words,',
        '#    add missing ones, delete invented ones. Keep the [h:mm:ss] at the start',
        '#    of each line; don\'t worry about punctuation or capitals.',
        '# 3. When you reach the end time, fill in the minutes it took below and save.',
        '#',
        'MINUTES SPENT: ',
        '',
    ]
    body = [f'[{fmt_time(s["start_seconds"])}] {correct_text(s.get("text_original", s["text"]))[0]}' for s in lines]
    path.write_text('\n'.join(header + body) + '\n', encoding='utf-8')
    return path


def _words(text):
    text = text.lower().replace('’', "'")
    text = re.sub(r'\[\d+:\d\d:\d\d\]', ' ', text)
    return re.findall(r"[a-z0-9']+", text.replace('>>', ' '))


def word_error_rate(reference, hypothesis):
    """Word-level edit distance / reference length (substitutions + insertions + deletions)."""
    r, h = _words(reference), _words(hypothesis)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / max(len(r), 1), prev[-1], len(r)


def score_sample(path):
    text = Path(path).read_text(encoding='utf-8')
    m = re.search(r'show=(\d+) start=(\d+) end=(\d+)', text)
    if not m:
        raise SystemExit('Not a worksheet made by --sample (no show=… line)')
    sid, start, end = (int(g) for g in m.groups())
    spent = re.search(r'MINUTES SPENT:\s*([\d.]+)', text)
    corrected = '\n'.join(l for l in text.splitlines() if not l.startswith('#') and not l.startswith('MINUTES SPENT'))

    (_, _, title, day, segments), = fetch_meetings(sid)
    lines = [s for s in segments if start <= s['start_seconds'] < end]
    raw = ' '.join(s.get('text_original', s['text']) for s in lines)
    fixed = ' '.join(correct_text(s.get('text_original', s['text']))[0] for s in lines)

    wer_raw, err_raw, n = word_error_rate(corrected, raw)
    wer_fixed, err_fixed, _ = word_error_rate(corrected, fixed)
    minutes = (end - start) / 60
    print(f'{title} — {fmt_time(start)} to {fmt_time(end)} ({minutes:.0f} min of video, {n} words)')
    print(f'  Cablecast captions:        {wer_raw:6.1%} of words wrong ({err_raw} edits)')
    print(f'  After automatic fixes:     {wer_fixed:6.1%} of words wrong ({err_fixed} edits)')
    if spent:
        per_hour = float(spent.group(1)) / minutes * 60
        print(f'  Time to correct by hand:   {float(spent.group(1)):.0f} min → about {per_hour / 60:.1f} hours per hour of meeting')
    else:
        print('  (Fill in MINUTES SPENT to estimate staff time.)')


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Improve meeting captions with cambridge_terms.txt')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--report', action='store_true', help='How much fixing do transcripts need?')
    mode.add_argument('--export', action='store_true', help='Write corrected .vtt/.scc/.srt for Cablecast (needs --show)')
    mode.add_argument('--vocabulary', action='store_true', help='Print terms for the caption dictionaries')
    mode.add_argument('--sample', action='store_true', help='Write a correction worksheet (needs --show, --at)')
    mode.add_argument('--score', metavar='WORKSHEET', help='Score a corrected worksheet')
    parser.add_argument('--show', type=int, help='Cablecast show ID')
    parser.add_argument('--at', default='0:10:00', help='Worksheet start, h:mm:ss (default 0:10:00)')
    parser.add_argument('--minutes', type=float, default=10, help='Worksheet length in minutes (default 10)')
    args = parser.parse_args()

    if args.sample:
        if not args.show:
            raise SystemExit('--sample needs --show')
        print(write_sample(args.show, parse_clock(args.at), args.minutes))
        return
    if args.score:
        score_sample(args.score)
        return

    if args.vocabulary:
        print('\n'.join(load_terms()['vocabulary']))
        return

    if args.export:
        if not args.show:
            raise SystemExit('--export needs --show')
        for sid, wp_id, title, day, segments in fetch_meetings(args.show):
            files = export_captions(segments, f'{day}_{sid}_corrected')
            a = analyze(segments)
            print(f'{title}: {a["fixes"]} fixes applied (SCC checked word for word)')
            print('\n'.join(f'  {f}' for f in files))
        return

    meetings = fetch_meetings(args.show)
    rows = [(sid, title, day, analyze(segments)) for sid, wp_id, title, day, segments in meetings]
    total_hours = sum(a['hours'] for *_, a in rows)
    all_unknown = collections.Counter()
    for *_, a in rows:
        all_unknown.update(dict(a['top_unknown']))

    lines = [f'# Caption report — {date.today().isoformat()}', '',
             f'{len(rows)} meeting(s), {total_hours:.1f} hours.', '',
             '| Date | Meeting | Hours | Fixes | Fixes/hour | Likely errors | Likely errors/hour | % of words |',
             '|---|---|---|---|---|---|---|---|']
    for sid, title, day, a in rows:
        lines.append(f"| {day} | {title} | {a['hours']:.1f} | {a['fixes']} | {a['fixes_per_hour']:.0f} | "
                     f"{a['unknown']} | {a['unknown_per_hour']:.0f} | {a['unknown_pct']:.1f}% |")
    tf = sum(a['fixes'] for *_, a in rows)
    tu = sum(a['unknown'] for *_, a in rows)
    lines += [f"| **All** | | **{total_hours:.1f}** | **{tf}** | **{tf / total_hours:.0f}** | **{tu}** | "
              f"**{tu / total_hours:.0f}** | |", '',
              '"Likely errors" are words English almost never uses (wordfreq Zipf < 1.5) and that '
              'aren\'t in the terms list — mostly captioning mistakes, some real names. It is a floor, '
              'not a total: mistakes that are real words ("Jake Moore") aren\'t counted. A person '
              'correcting a sample gives the true error rate.', '',
              '## Words to check — candidates for cambridge_terms.txt', '',
              '| Word | Times | Meetings |', '|---|---|---|']
    for word, n in all_unknown.most_common(60):
        m = sum(1 for *_, a in rows if word in dict(a['top_unknown']))
        lines.append(f'| {word} | {n} | {m} |')

    if args.show and rows:
        sid, title, day, a = rows[0]
        lines += ['', f'## Fixes applied — {title}', ''] + [f'- {n}× {fix}' for fix, n in a['top_fixes']]
        lines += ['', '## Suggestions to check', ''] + [f'- {fmt_time(t)} "{said}" → {right}?' for t, said, right in a['suggestions']]

    out_dir = ROOT / 'reports'
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f'caption_report_{date.today().isoformat()}{"_" + str(args.show) if args.show else ""}.md'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:len(rows) + 8]))
    print(f'\nFull report: {path}')


if __name__ == '__main__':
    main()
