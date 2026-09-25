# Cambridge Record — Project Documentation
## How it was built, how to run it, and where it's going

**Project:** Cambridge Record  
**Site:** mediatechaction.com  
**Started:** September 2026  
**Target:** NEACM Conference, November 17, 2026  
**Author:** Matt, Media Arts Manager, Cambridge Public Schools  
**Current versions:** plugin 0.4.0 · theme 0.4.1

---

## What this is

A civic meeting archive that makes Cambridge School Committee meetings
searchable, structured, and navigable across time — by topic, by moment,
by keyword. A resident can search "transportation" and see every moment
the word was spoken across all meetings, with a link that jumps the video
to that exact second. Each meeting shows its agenda and the official
votes from the minutes; each School Committee member has a page with
every roll-call vote they've cast.

Built on WordPress (DreamHost shared hosting), populated by a local
Python pipeline that pulls captions from Cablecast's public CDN and
agendas and minutes from the CPS School Committee portal, and pushes
structured data to WordPress via the REST API.

Inspired by: publicrecord.studio (Brookline Interactive Group / Weird Machine)

---

## Working with meetings — day to day

This section is the operator's guide: how a meeting gets onto the site,
what to check before and after publishing, and how to fix things.
Commands run in Terminal from the project folder after
`source venv/bin/activate`.

### The life of a meeting

```
Cablecast video + captions ──► ingest ──► DRAFT in WordPress
CPS portal agenda (48h before) ──► enrich ──► agenda + section times
                                   │
                         review, then PUBLISH  ◄── you
                                   │
CPS portal minutes (weeks later) ──► enrich again ──► official votes,
                                                      vote times,
                                                      officials' records
```

1. **Ingest** creates the meeting as a **draft**: title and date from
   Cablecast, the full transcript, the video embed. It then looks the
   meeting up on the CPS portal and adds the agenda.
2. **You review and publish.** Nothing is public until you publish it —
   the AI Constitution's "a human approves every meeting".
3. **Minutes arrive weeks later.** Re-running enrich adds the official
   votes, places them on the video, and every member's voting record
   updates automatically.

### Adding new meetings

```
python backfill.py --since 2026-09-01 --dry-run    # what's new on the portal?
python backfill.py --since 2026-09-01              # ingest it
```

`backfill.py` reads the CPS portal's meeting list, where each row links its
video by Cablecast show ID, and ingests every full-committee meeting (Regular
and Special) not yet ingested. It's safe to re-run — already-ingested
meetings are skipped. It ends with a summary that flags any meeting whose
Cablecast date disagrees with the portal's (see *Fixing a wrong title or
date* below).

For one specific video: `python ingest_cablecast.py --show 11522`.

Subcommittee meetings are not ingested yet (see *What's not built yet*).

### Before you publish a meeting

Open the draft's **Preview** and check:

- **Title and date** match the CPS portal. Cablecast is sometimes wrong
  (9/8/26 was listed as a "Regular Meeting" on 9/1).
- **The video plays** and clicking a transcript line jumps it.
- **The agenda** appears (Special meetings often have none — that's normal).
- **Review times** (below) has nothing left for this meeting, or only
  items you've decided to leave.

Then publish it — one at a time from the editor, or several at once from
**Meetings → filter to Drafts → select → Bulk actions → Edit → Status:
Published**. The **Published** column on the Meetings list shows which
meetings residents can see.

### What publishing does

Only published meetings appear anywhere public:

| | Draft | Published |
|---|---|---|
| Meeting list (home page) | — | ✓ |
| Search results | — | ✓ |
| Officials' voting records and counts | — | ✓ |
| Meeting page | preview only (logged in) | ✓ |
| Review times queue | ✓ | ✓ |

**Unpublishing** (switch Status back to Draft) removes a meeting from all
of the above immediately, and its votes drop out of every member's record.
Use it if something is wrong and you need time to fix it. Nothing is lost.

### When minutes are posted

The portal posts minutes after they're approved, usually at a later
meeting. Every week or two, run:

```
python enrich_meetings.py --all              # every ingested meeting
python enrich_meetings.py --show 11522       # or just one
```

For each meeting this re-reads the portal: agenda, minutes (if posted
now), and places votes, agenda items and sections on the video. It is
**safe to re-run as often as you like**:

- It **never changes** a meeting's title, date, or published status.
- It **keeps your Review times decisions** — they're re-applied after the
  automatic matching.
- Until minutes are posted, the meeting keeps the caption-based "possible
  votes" guesses; once they're posted, official votes replace them.

After it runs, published meetings update on the site straight away —
no re-publishing needed. Check **Review times** for new items.

### Review times

**WP admin → Meetings → Review times** (the badge shows how many items
are waiting).

The pipeline places each official vote on the video by finding its roll
call in the captions. It can't always: on some recordings members'
answers weren't captioned, and some minutes aren't in the order things
happened. This screen lists every vote it **couldn't place** or placed
with **low confidence** (below 0.7), and docketed agenda items with no
time.

Click an item: the video loads at the best guess — for an unplaced
vote, just after the previous vote — and the transcript beside it follows
the player, with vote words (motion, second, yes, absent, roll call)
highlighted. Click any transcript line to jump there. Then:

- **Use current time** — saves where the player is now. Pause on the
  motion, just before the roll call; that's what "watch this vote" should
  show.
- **Looks right** — keeps the pipeline's time.
- **h:mm:ss + Set** — type a time.
- **Not in the video** — e.g. votes taken in executive session.
- **Undo my decision** — restores what the pipeline had found.

Decisions take effect on the public site immediately and are kept when
the pipeline re-runs. To spot-check a meeting the pipeline was confident
about, pick it in the Meeting menu and tick **Show every vote in this
meeting**.

### Fixing things

**A wrong title or date.**

```
python edit_meeting.py --show 11502                       # see what WordPress has
python edit_meeting.py --show 11502 --date 2026-09-08 --title "School Committee Special Meeting 9/8/26"
```

This changes only the title and date. (Avoid editing the date through the
editor's Custom Fields panel — it also holds the 1 MB transcript field.)
Fix it in Cablecast too, so a future re-ingest doesn't bring the error
back. `enrich_meetings.py` and `backfill.py` warn when WordPress and the
portal disagree on a date.

**A vote at the wrong moment, or missing its time.** Use Review times.

**A vote missing entirely, or with the wrong tally.** The votes come from
the minutes PDF on the portal. Check the PDF: if it's right there, the
parser missed a new phrasing — note the meeting and it can be fixed in
`parse_minutes.py`. If the minutes themselves are wrong, the site will
match them; that's by design (the minutes are the official record).

**Transcript text errors** (misheard names etc.) come from Cablecast's
captions. They can't be edited in WordPress without being overwritten;
the planned caption-correction step will handle them.

**Starting a meeting over.** Rarely needed — prefer `enrich_meetings.py`,
which refreshes everything except the transcript. If a meeting truly
needs re-ingesting (e.g. Cablecast replaced the video), delete it in
WordPress, then remove its pipeline record and ingest again:

```
sqlite3 pipeline.db "DELETE FROM ingested_shows WHERE cablecast_show_id = 11522"
python ingest_cablecast.py --show 11522
```

Deleting loses its Review times decisions, and the new post may get a
different address (links people shared to the old one will break).

### Officials

The roster lives in `officials.json`: names, titles, terms, subcommittees,
and each member's surname **exactly as the minutes write it** — that's
how votes are linked to people. After an election or a subcommittee
change, edit the file and run:

```
python sync_officials.py --dry-run
python sync_officials.py
```

It updates existing members in place and never deletes anyone: when a
member leaves, set their `term_end` so their voting record stays online.

### Sharing links

Every meeting page link can point at a moment:

| Link | Opens |
|---|---|
| `/meeting/{slug}/#t=3725` | the meeting at 1:02:05 |
| `/meeting/{slug}/?q=budget#t=3725` | …with "budget" highlighted in the transcript |
| `/?s=transportation` | search results |
| `/official/{name}/` | a member's voting record |

The meeting page's **Copy link to this moment** button builds the first
kind. Search results link to the second.

### Updating the plugin or theme

Both live in the repo (`wordpress/cambridge-record/`,
`wordpress/cambridge-record-theme/`) with ready-to-upload zips beside them.
Upload with **Plugins/Themes → Add New → Upload → Replace current with
uploaded**. Each release bumps its version number, so browsers fetch the
new files; if a page looks stale, hard-refresh (Cmd+Shift+R).

### Quick reference

| Task | Command / place |
|---|---|
| Ingest new meetings | `python backfill.py --since YYYY-MM-DD` |
| Ingest one video | `python ingest_cablecast.py --show ID` |
| Fix a title or date | `python edit_meeting.py --show ID --date … --title …` |
| Pick up posted minutes | `python enrich_meetings.py --all` |
| Check a meeting's agenda on the portal | `python scrape_agenda.py --show ID` |
| Check what the parser reads from minutes | `python parse_minutes.py <minutes PDF URL>` |
| Update the roster | edit `officials.json`, then `python sync_officials.py` |
| Fix vote times | WP admin → Meetings → Review times |
| Publish / unpublish | WP admin → Meetings → Status |
| Logs | `pipeline.log` |

---

## Architecture

```
Cablecast CDN (reflect-video-ondemand-cpsd.cablecast.tv)
  └── HLS manifest (.m3u8) → VTT subtitle segments (10 s each, per-cue timestamps)

CPS School Committee portal (portal.cpsd.us/school_committee/)
  ├── meeting table — each row links its video by Cablecast show ID
  ├── view_agenda.php?meetingID=… — agenda sections + docketed items (#26-178)
  └── admin/minutes/….pdf — official minutes: every motion and roll-call vote

Matt's MacBook (local pipeline)
  ├── backfill.py          — ingest every portal meeting since a date
  ├── ingest_cablecast.py  — one show: captions → WordPress draft
  ├── fetch_captions.py    — downloads VTT segments concurrently
  ├── enrich_meetings.py   — agenda + votes + video times → WordPress
  │     ├── scrape_agenda.py  — portal row + agenda page
  │     ├── parse_minutes.py  — votes from the minutes PDF
  │     └── match_agenda.py   — roll calls in captions ↔ votes in minutes
  ├── sync_officials.py    — officials.json → Official pages
  ├── edit_meeting.py      — correct a meeting's title/date
  └── pipeline.db          — SQLite: which show is which WordPress post

WordPress (mediatechaction.com / DreamHost shared hosting)
  ├── cambridge-record plugin — post types, meta, REST endpoints, Review times
  ├── cambridge-record-theme  — meeting list, meeting page, search, officials
  └── REST API (below)
```

---

## The Cablecast data path — what we discovered

This was the most important technical investigation of the project.
The path to accurate caption timestamps was not obvious.

### What we tried and why it didn't work

**1. Cablecast API `/shows/{id}` directly**  
Returns show metadata but `vodTranscripts` array is absent — only
appears in the embed page's JavaScript payload, not the raw API.

**2. `assetreellinks` endpoint**  
The SCC/VTT files are attached here, but this endpoint requires
authentication. We have no API key that grants access to it.

**3. Plain text transcript (`transcript.en.txt`)**  
Accessible publicly at a predictable URL derived from the VOD's `url`
field. Contains the full meeting text but with only ~3 sparse timestamps
across a 4-hour meeting — useless for deep-linking.

**4. `webVtt` field on VOD record**  
Points to `/vods/{id}/chapters` — this is a chapter marker file, not
captions. Returns empty for most meetings.

### What actually works

**The HLS subtitle stream**, discovered by fetching the master manifest:

```
GET .../store-4/{slug}/vod.m3u8
```

Returns an HLS manifest listing subtitle tracks for all 7 languages:
```
#EXT-X-MEDIA:TYPE=SUBTITLES,URI="captions.en.m3u8",LANGUAGE="en"
```

Each subtitle manifest (`captions.en.m3u8`) lists ~1,577 individual
10-second VTT segment files:
```
subtitles/captions.en.00000.vtt   (seconds 0-10)
subtitles/captions.en.00001.vtt   (seconds 10-20)
...
subtitles/captions.en.01576.vtt
```

Each VTT segment contains real, per-cue timestamps:
```
WEBVTT
00:00:05.000 --> 00:00:08.901
Alright well a quorum being present...
```

These are the same caption files the Cablecast web player uses to
display captions on screen. They are served by AWS CloudFront
(not the Cambridge Cablecast server) and are publicly accessible.

### Why this is better than the transcript

| Source | Timestamps | Coverage |
|---|---|---|
| `transcript.en.txt` | ~3 per 4-hour meeting | Full text |
| HLS VTT segments | Per cue, millisecond accuracy | Full text |

The VTT segments win on every dimension. A deep-link from VTT data
lands within a few seconds of the right moment. A deep-link from
interpolated transcript data could be 15+ minutes off.

### The pipeline in plain terms

1. Fetch show record from `/cablecastapi/v1/shows/{id}` → get VOD ID
2. Fetch VOD record from `/cablecastapi/v1/vods/{vod_id}` → get `url` field
3. Derive folder URL: strip `vod.mp4` from the VOD `url`
4. Fetch `{folder}/vod.m3u8` → confirm subtitle tracks exist
5. Fetch `{folder}/captions.en.m3u8` → get list of ~1,577 segment filenames
6. Fetch all VTT segments concurrently (20 parallel workers, ~6 seconds)
7. Parse cues, deduplicate boundary overlaps, sort by timestamp
8. Push to WordPress: post_content = all text concatenated (for search),
   segments_json = full structured data (for display and deep-links)

---

## Agendas, votes and the video timeline

The captions say *when*; the CPS portal says *what*.

**Finding a meeting's documents.** The portal's meeting table links each
meeting's video by Cablecast show ID, so a show maps directly to its
portal row — no date matching. The row links the agenda page (posted 48
hours before) and, later, the minutes PDF.

**Agenda** (`scrape_agenda.py`): numbered sections ("7d. Consent Agenda")
and items with docket numbers (#26-178), types (recommendation, motion,
resolution, late order) and sponsors.

**Votes** (`parse_minutes.py`): every vote in the minutes — motion, mover,
seconder, result, each member's vote, and the dockets it decided. Parsing
is anchored on each vote's outcome (a roll-call tally, "on a voice vote",
"it was voted") and reads back to the motion. Tested on 2026 minutes;
handles voice votes, NAYs, elections (votes for a candidate), and PDF
artifacts ("S antos", "YE A", "PRESNT", "Memer").

**Placing votes on the video** (`match_agenda.py`):

1. Find roll calls in the captions — title→vote pairs ("Member. Hudson.
   Yes."); or, where members' answers weren't captioned, a burst of
   titles read out ending with the chair, or followed by the chair's
   "on a vote of 7 in the affirmative".
2. Pair roll calls with minutes votes in order, scoring tally agreement
   and whether the item's docket number (or topic word) is said nearby.
   Leftover votes can pair out of order — minutes aren't always
   chronological.
3. A vote's time is the motion just before its roll call.
4. Agenda items: first mention of their docket number within their
   section; sections: the chair's transition ("that brings us to
   unfinished business").

Every time carries `match_method` and `match_score`; low scores go to
Review times. As of September 2026: 95 of 118 official votes placed
automatically.

---

## The WordPress data model

**Post types:**
- `cr_meeting` — one per meeting session
- `cr_official` — School Committee members (from `officials.json`)
- `cr_issue` — curated topic threads (not used yet)

**Meta on `cr_meeting`:**
- `segments_json` — every caption cue with timestamps
- `agenda_json` — sections and items, with times, docket numbers, vote links
- `votes_json` — official votes from the minutes (or caption-based guesses
  before minutes are posted), with roll calls, times and match scores
- `review_json` — people's decisions from Review times
- `meeting_date`, `meeting_body`, `cablecast_embed_url`, `agenda_url`,
  `languages_available`, `cr_status`, etc.

**Meta on `cr_official`:** `full_name`, `official_title`, `minutes_name`
(surname as the minutes write it), `is_voting_member`, `term_start`,
`term_end`, `subcommittees_json`.

**`post_content`** holds all transcript text — what WordPress's native
search indexes. The search endpoint finds candidate meetings that way,
then matches segments in PHP.

**REST endpoints** (public unless noted):
- `GET /wp-json/cambridge-record/v1/meetings` — published meetings
- `GET /wp-json/cambridge-record/v1/search?q=…` — grouped by meeting,
  newest first, with per-meeting totals and matching agenda items
- `GET /wp-json/cambridge-record/v1/officials` — members + vote summaries
- `GET /wp-json/cambridge-record/v1/officials/{id}` — one member's record
- `GET|POST /wp-json/cambridge-record/v1/review` — Review times (editors only)

---

## Hosting

DreamHost shared hosting (Shared Unlimited plan). The pipeline runs
locally on Matt's MacBook, not on DreamHost — DreamHost only stores
and serves. This keeps hosting costs at the existing plan price with
no upgrade needed.

The ~1.2MB `segments_json` field per meeting is within WordPress's
default meta size limits on shared hosting.

---

## Gotchas and hard-won lessons

**1. Cablecast's `showId` filter on `/vods` doesn't work reliably**  
Querying `/vods?showId=11522` returns all VODs, not just the one for
that show. Instead: fetch the show record, read `show.vods[0]`, fetch
that VOD directly.

**2. `publicsitedata` API returns transcript URLs, not VTT URLs**  
`GET /CablecastAPI/publicsitedata/shows/{id}` returns `vodTranscripts`
with the plain text `.txt` files, not the VTT caption files. The VTT
files are only discoverable via the HLS manifest chain.

**3. WordPress serializes long meta values**  
A `LIKE` query on the `segments_json` meta field doesn't work because
WordPress serializes PHP objects in some configurations. Solution: store
all text in `post_content` and use WordPress native search instead.

**4. VTT segments overlap at boundaries**  
Each 10-second VTT file includes cues that bleed slightly into the next
segment. Without deduplication, cues appear twice. Fixed with a
(start_seconds, text[:40]) key.

**5. Connection pool warnings with concurrent requests**  
Using `requests.Session()` with 20 workers exceeds the default pool
size. Fix: configure `HTTPAdapter(pool_maxsize=FETCH_WORKERS)`.

**6. The `vodTranscripts` array only appears in embed page JS**  
Not in the `/shows/{id}` API response. The correct way to find
transcript/caption URLs is via the VOD's `url` field → derive folder
path → check the HLS manifest.

**7. No API key needed for read access**  
Caption files, video files, and show metadata are all publicly accessible
via the Cablecast CDN. Authentication is only required for write
operations and internal asset endpoints (`assetreellinks`).

**8. The embed player's start-time parameter is `seek`, not `t`**  
`watch-vod-embed?showId=…&site=1&seek=1588` starts at 1588s;
`&t=` is silently ignored (video starts at 0:00). The player also talks
to the embedding page via `postMessage`: send
`{type: 'player-cue', value: seconds}` to jump without reloading; it
sends back `{message: 'timeupdate', value}`, `{message: 'playing', value}`
and `{message: 'ready'}`. Found by reading Cablecast's `VideoJs-*.js`
bundle. The embed also only allows framing from domains on its
`frame-ancestors` allowlist (mediatechaction.com added Sept 2026) — a
new domain or staging site must be added in Cablecast too.

**9. Caption files are UTF-8, but the CDN doesn't say so**  
With no charset header, `requests` decodes VTT as Latin-1 and every curly
apostrophe becomes "â€™". Decode `r.content` as UTF-8 explicitly.

**10. Cablecast titles and dates can be wrong; the portal is the reference**  
Show 11502 was a 9/8 Special Meeting listed as a 9/1 Regular Meeting.
`enrich_meetings.py` warns when WordPress and the portal disagree.

**11. Captions spell names wrong, but titles and vote words right**  
"Jake Amara" and "Jayakumar" for Jaikumar, "Doobie" for Dube — but
"Member", "Chair", "Yes", "Absent" come through reliably. Roll-call
detection keys on those.

**12. On some recordings, members' answers weren't captioned**  
Early-2026 captions have the clerk reading names but few "yes"es. The
chair's "on a vote of 7 in the affirmative" fills in the tally.

**13. Minutes aren't always in the order things happened, and have typos**  
The 1/6/26 minutes list a consent item before items it followed; others
have "PRESNT", "Memer", a stray "YEA;". Minutes also sometimes say "on a
voice vote" and then list every member's vote — treated as a roll call.

---

## What's working (as of late September 2026)

- ✅ 23 School Committee meetings (Jan–Sep 2026), all published
- ✅ Transcripts with per-cue timestamps; the transcript follows the video
- ✅ Search across every meeting, grouped by meeting, with agenda matches
- ✅ Agendas from the CPS portal, with times in the video
- ✅ Official votes from the minutes (118), 95 placed in the video
  automatically; the rest in Review times
- ✅ Officials pages with every member's roll-call voting record
- ✅ Review times screen for checking and correcting vote placements
- ✅ Draft/publish workflow (pipeline creates drafts, a person publishes)

---

## What's not built yet

**Subcommittee meetings** — on the portal with show IDs and (narrative)
minutes; need a body per meeting, a filter on the meeting list, and
subcommittee pages. Residents often take part in these conversations —
the site should never build pages or search facets for private
individuals, only for officials.

**Pages that follow an item across meetings** — one page per docket
number (e.g. #26-125, tabled on 6/2 and 8/4, back on 9/1) built from
existing data; a start on the `cr_issue` "issue threads".

**Caption improvement** — a correction pass on Cablecast captions from a
Cambridge terms list (names first), then a timed test of Whisper on one
meeting, with the transcript source labeled per meeting.

**Scheduled runs** — a weekly job on the Mac to ingest new meetings and
pick up minutes.

**Phase 5 — AI layer** — summaries, semantic search, issue clustering.
Additive; the site works without it, and every AI element must be
labeled with the model used.

---

## Longer-term goals

**Supporting documents and presentations**  
The CPS portal (portal.cpsd.us/school_committee/) links each meeting's
supporting material: recommendation PDFs (`admin/recommendations/26-180.pdf`),
motion/order PDFs (`admin/motion_order_files/…`), and presentations
(Google Drive links). Attach these to meetings and agenda items so a
resident can read the document being discussed next to the moment it's
discussed.

---

## For other MassAccess stations

The Cablecast pipeline is generic. Any station running Cablecast with:
- HLS video delivery (`.m3u8` files)
- MediaScribe or Cablecast Cloud captions
- Public VOD access

...can use the caption pipeline with only the Show ID and base URL
changed. The agenda and minutes steps are specific to the CPS portal;
another district would need its own `scrape_agenda.py` and a check of
how its minutes record roll calls.

The key discovery — that accurate timestamps live in the HLS subtitle
stream, not in any dedicated API endpoint — applies to all Cablecast
installations using cloud caption delivery.

---

## Next steps (toward NEACM, November 17)

**Done (Sep 23–25):** theme, meeting pages with synced transcript,
agenda + minutes pipeline, video times, officials, backfill of 2026,
search, Review times  
**Next:** work through Review times; subcommittee meetings; item-history
pages; caption corrections  
**Week of Oct 21:** AI layer if time allows, conference prep  
**Week of Oct 28:** Demo rehearsal, presentation slides, an offline
fallback for the demo (conference wifi)  
**Week of Nov 3:** Buffer, final fixes  
**Nov 17:** NEACM Conference presentation
