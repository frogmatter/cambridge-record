"""
Cambridge Record — CPS portal scraper (agendas)

The CPS School Committee portal lists every meeting in one table. Each row
links its video by Cablecast show ID, so a show maps directly to its portal
row — and from there to the agenda page and the minutes PDF.

    https://portal.cpsd.us/school_committee/                 meeting index
    .../view_agenda.php?meetingID=615                          agenda (HTML)
    .../admin/minutes/613_2026-08-04.pdf                       minutes (PDF, posted later)

Usage (prints what it finds; writes nothing):
    python scrape_agenda.py --show 11498
"""

import argparse
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

PORTAL_URL = 'https://portal.cpsd.us/school_committee/'
HEADERS    = {'User-Agent': 'CambridgeRecord/0.1 (+https://www.mediatechaction.com)'}

DOCKET_RE     = re.compile(r'#\s?(\d{2})\s?-\s?(\d{3})')
LATE_ORDER_RE = re.compile(r'^#?\s*Late Order\b[^:]*:\s*', re.I)
SECTION_RE    = re.compile(r'^(\d{1,2}[a-d]?)\.\s+(.+?)\s*:?\s*$')

# Item type implied by the agenda section it sits in
SECTION_TYPES = {'7d': 'recommendation', '8': 'recommendation', '10': 'resolution', '12': 'late_order'}


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r


# ── Meeting index ──────────────────────────────────────────────────────────────

def get_portal_meetings():
    """
    Parse the portal's meeting table. Returns a list of dicts:
        {date, meeting_type, location, portal_meeting_id, show_id,
         agenda_url, minutes_url, notice_url, presentations}
    """
    soup = BeautifulSoup(fetch(PORTAL_URL).text, 'lxml')
    meetings = []

    for tr in soup.select('tr'):
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 8:
            continue

        links = {}
        presentations = []
        for a in tds[-1].find_all('a', href=True):
            label = (a.get('title') or a.get_text()).strip()
            url = urljoin(PORTAL_URL, a['href'])
            if label == 'Watch Presentation':
                presentations.append(url)
            else:
                links[label] = url

        video = links.get('Watch Video', '')
        show = re.search(r'showId=(\d+)', video)
        agenda = links.get('Agenda', '')
        portal_id = re.search(r'meetingID=(\d+)', agenda)
        if not portal_id:
            portal_id = re.search(r'/(\d+)_\d{4}-\d{2}-\d{2}', links.get('Minutes', ''))

        meetings.append({
            'date':              tds[0].get_text(strip=True),
            'meeting_type':      tds[2].get_text(' ', strip=True),
            'location':          tds[5].get_text(' ', strip=True),
            'portal_meeting_id': int(portal_id.group(1)) if portal_id else None,
            'show_id':           int(show.group(1)) if show else None,
            'agenda_url':        agenda or None,
            'minutes_url':       links.get('Minutes'),
            'notice_url':        links.get('Notice'),
            'presentations':     presentations,
        })

    return meetings


def find_portal_meeting(show_id, meetings=None):
    """The portal row whose video link points at this Cablecast show, or None."""
    for m in meetings if meetings is not None else get_portal_meetings():
        if m['show_id'] == int(show_id):
            return m
    return None


# ── Agenda page ────────────────────────────────────────────────────────────────

def _agenda_lines(container):
    """
    Flatten the agenda container into lines: [{kind, text, href}].
    kind is 'line' (text ended by <br>), 'p' (a description paragraph)
    or 'li' (a list item, e.g. records presented for approval).
    """
    lines = []
    buf, href = [], None

    def flush():
        nonlocal buf, href
        text = ' '.join(''.join(buf).split())
        if text:
            lines.append({'kind': 'line', 'text': text, 'href': href})
        buf, href = [], None

    def walk(node):
        nonlocal href
        for child in node.children:
            if isinstance(child, NavigableString):
                buf.append(str(child))
            elif not isinstance(child, Tag):
                continue
            elif child.name == 'br':
                flush()
            elif child.name == 'p':
                flush()
                text = child.get_text(' ', strip=True)
                if text:
                    lines.append({'kind': 'p', 'text': ' '.join(text.split()), 'href': None})
            elif child.name in ('ul', 'ol'):
                flush()
                for li in child.find_all('li'):
                    text = li.get_text(' ', strip=True)
                    if text:
                        lines.append({'kind': 'li', 'text': ' '.join(text.split()), 'href': None})
            else:
                if child.name == 'a' and child.get('href') and href is None:
                    href = urljoin(PORTAL_URL, child['href'])
                walk(child)
    walk(container)
    flush()
    return lines


def _docket_item(text, href, section):
    """
    Parse an agenda item line:
        '#26-161 Recommendation: Title'
        '#26-125: Title | Motion by Member X: Download File'
        '#Late Order Larry Aaronson: Title | Joint Motion by …: Download File'
    """
    m = DOCKET_RE.match(text)
    if m:
        docket = f'{m.group(1)}-{m.group(2)}'
        rest = text[m.end():].lstrip(' :')
    else:
        docket = None
        rest = LATE_ORDER_RE.sub('', text)
    rest = re.sub(r':?\s*Download (File|Attachment)\s*$', '', rest).strip()

    title, sponsors = rest, None
    if '|' in rest:
        title, sponsors = (s.strip() for s in rest.split('|', 1))

    section_number = section['number'] if section else None
    item_type = SECTION_TYPES.get(section_number, 'other')
    if title.startswith('Recommendation:'):
        item_type, title = 'recommendation', title[len('Recommendation:'):].strip()
    elif item_type == 'other' and sponsors and re.search(r'\bResolution\b', sponsors):
        item_type = 'resolution'
    elif item_type == 'other' and sponsors and re.search(r'\bMotion\b', sponsors):
        item_type = 'motion'
    elif item_type == 'other' and re.search(r'Subcommittee|Report', title):
        item_type = 'report'

    return {
        'item_number':     docket,
        'docket':          docket,
        'section':         section_number,
        'title':           title,
        'item_type':       item_type,
        'sponsors':        re.sub(r'^(Joint )?(Motion|Resolution) by\s+', '', sponsors) if sponsors else None,
        'support_doc_url': href,
    }


def scrape_agenda_items(agenda_url):
    """
    Parse a view_agenda.php page into a flat list: each section heading
    (item_type 'section') followed by its items. Sections marked "None"
    are dropped. Fields follow the plugin's agenda_json schema, plus
    docket / section / sponsors / description. Times are filled in later
    by matching against the transcript.
    """
    soup = BeautifulSoup(fetch(agenda_url).text, 'lxml')
    container = soup.select_one('div.bg-white')
    if container is None:
        return []

    items, section = [], None

    for line in _agenda_lines(container):
        text, kind = line['text'], line['kind']
        heading = SECTION_RE.match(text) if kind == 'line' else None

        if heading and not DOCKET_RE.match(text):
            title, inline_none = re.subn(r':\s*None$', '', heading.group(2))
            section = {
                'item_number':     heading.group(1),
                'number':          heading.group(1),
                'title':           re.sub(r'\s*\(.*?\)\s*$', '', title).rstrip(':'),
                'item_type':       'section',
                'description':     None,
                'support_doc_url': line['href'],
                '_items':          [],
                '_none':           bool(inline_none),
            }
            items.append(section)
        elif section is None:
            continue
        elif text == 'None':
            section['_none'] = True
        elif DOCKET_RE.match(text) or LATE_ORDER_RE.match(text):
            section['_items'].append(_docket_item(text, line['href'], section))
        elif kind == 'p':
            section['description'] = ' '.join(filter(None, [section['description'], text]))
        else:
            section['_items'].append({
                'item_number':     None,
                'docket':          None,
                'section':         section['number'],
                'title':           text,
                'item_type':       'records' if kind == 'li' and section['number'] == '3' else 'other',
                'sponsors':        None,
                'support_doc_url': line['href'],
            })

    flat = []
    for s in items:
        children = s.pop('_items')
        is_none = s.pop('_none')
        s.pop('number')
        if is_none and not children and not s['description']:
            continue
        # Sections whose "items" are really bullet points of a description
        # (e.g. 7a Superintendent's Update) keep them in the description.
        if s['description'] and all(c['item_type'] == 'other' and not c['docket'] for c in children):
            s['description'] = ' '.join([s['description']] + [c['title'] for c in children])
            children = []
        flat.append(s)
        flat.extend(children)

    for item in flat:
        item.update({'start_seconds': None, 'end_seconds': None, 'deep_link_url': None, 'matched': False})
        item.setdefault('docket', None)
        item.setdefault('section', item['item_number'])
        item.setdefault('sponsors', None)
        item.setdefault('description', None)

    return flat


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Look up a Cablecast show on the CPS portal and print its agenda')
    parser.add_argument('--show', type=int, required=True, help='Cablecast show ID')
    parser.add_argument('--json', action='store_true', help='Print agenda_json instead of a summary')
    args = parser.parse_args()

    meeting = find_portal_meeting(args.show)
    if not meeting:
        print(f'Show {args.show} is not linked from any meeting on {PORTAL_URL}')
        return

    items = scrape_agenda_items(meeting['agenda_url']) if meeting['agenda_url'] else []
    if args.json:
        print(json.dumps(items, indent=2))
        return

    print(f"{meeting['date']}  {meeting['meeting_type']}  (portal meeting {meeting['portal_meeting_id']})")
    print(f"  agenda:  {meeting['agenda_url'] or '—'}")
    print(f"  minutes: {meeting['minutes_url'] or 'not posted yet'}")
    for item in items:
        if item['item_type'] == 'section':
            print(f"  {item['item_number']:>4}. {item['title']}")
        else:
            print(f"        {('#' + item['docket']) if item['docket'] else '-':>8}  [{item['item_type']}] {item['title'][:80]}")


if __name__ == '__main__':
    main()
