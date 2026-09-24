# The Cambridge Record — Project Specification
## A civic meeting archive for Cambridge Public Schools

**Version:** 0.1 (pilot scope)
**Target:** New England Alliance for Community Media Conference, November 17, 2026
**Builder:** Matt, Media Arts Manager, Cambridge Public Schools
**Inspiration:** publicrecord.studio (Brookline Interactive Group / Weird Machine)

---

## Project overview

A public-facing web tool that makes Cambridge School Committee meetings searchable,
structured, and navigable across time — by topic, by official, by vote. Built on
WordPress (DreamHost VPS), populated by a local Python pipeline that pulls from the
Cablecast API and parses SCC caption files. No login required, no tracking, no ads.
AI is additive and disclosed; the record is readable without it.

This is a pilot for one governing body (Cambridge School Committee) intended to
demonstrate a replicable pattern for MassAccess member stations across Massachusetts.
The Cablecast ingestion adapter is the key reusable piece.

---

## What Cambridge already has (do not rebuild these)

| Asset | Source | Format | Notes |
|---|---|---|---|
| Meeting video | Cablecast VOD | Streaming embed | Accessible via Cablecast API |
| English captions | Cablecast (MediaScribe → SCC) | .scc per VOD | Already attached to VOD records |
| Translations (7 languages) | Cablecast | Likely SCC or VTT | Already produced post-meeting |
| Agenda + support docs | Cambridge Public Schools website | HTML pages | Publicly accessible, one page per meeting |
| Meeting schedule | CPS website | HTML | Listing of past and upcoming meetings |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Matt's MacBook Pro (M4, local pipeline)            │
│                                                     │
│  python ingest.py                                   │
│    ├── Cablecast API → VOD records + SCC files      │
│    ├── pycaption → timestamped segments             │
│    ├── CPS website scraper → agenda items           │
│    ├── pattern matcher → roll calls + votes         │
│    └── WordPress REST API → push all structured data│
└───────────────────────┬─────────────────────────────┘
                        │ HTTPS REST API
┌───────────────────────▼─────────────────────────────┐
│  DreamHost VPS — WordPress                          │
│                                                     │
│  Custom post types:                                 │
│    meeting / segment / agenda_item / official /vote │
│                                                     │
│  Public interface:                                  │
│    Meeting pages → Cablecast embed + transcript     │
│    Search → across all meetings and segments        │
│    Issues → topic threads across meetings           │
│    Officials → voting records                       │
└─────────────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│  Cablecast server (Cambridge)                       │
│  Video embeds served from here                      │
│  SCC caption files pulled via API during ingest     │
└─────────────────────────────────────────────────────┘
```

**Key principle:** DreamHost/WordPress does zero processing. It stores structured
data and serves the public interface. All intelligence runs locally on Matt's Mac
and is pushed to WordPress via the REST API. The Cablecast server is never
modified — only read.

---

## Phase 1 — WordPress data model

**Goal:** A correctly structured, empty WordPress site that the pipeline can
populate. No frontend styling yet. REST API endpoints working and tested.

### DreamHost setup prerequisites
- DreamHost VPS (not shared hosting — need adequate PHP memory for large datasets)
- WordPress installed at target domain (TBD — suggestion: record.cambridgepublicschools.org
  or similar, or a subdomain of an existing domain Matt controls)
- WordPress application password generated for API authentication
- Permalink structure set to "Post name" (required for REST API to function correctly)

### Required plugins (install before building)
- **Advanced Custom Fields (ACF) Free** — for custom field definitions
- **Custom Post Type UI** — for registering post types (or handle in code)
- **WP REST API** — built into WordPress core since 5.0, no install needed
  - Confirm REST API is accessible at `/wp-json/wp/v2/`

### Custom post types to register

#### 1. `meeting`
Represents a single School Committee meeting session.

| Field name | ACF type | Notes |
|---|---|---|
| `meeting_date` | Date picker | YYYY-MM-DD |
| `meeting_body` | Text | e.g. "Cambridge School Committee" |
| `cablecast_vod_id` | Number | Cablecast internal VOD ID |
| `cablecast_embed_url` | URL | Full embed URL for the video player |
| `cablecast_timestamp_base` | URL | Base URL for timestamp deep-links (if supported) |
| `agenda_url` | URL | Link to agenda page on CPS website |
| `duration_seconds` | Number | Total meeting length in seconds |
| `segment_count` | Number | Set by pipeline after ingestion |
| `summary` | Textarea | AI-generated summary (labeled), or extractive fallback |
| `summary_origin` | Text | `ai:gemini-flash` or `extractive` — required for disclosure |
| `languages_available` | Checkbox | English + 7 languages from Cablecast |
| `status` | Select | `draft` / `published` / `processing` |

#### 2. `segment`
A single captioned unit of transcript — one or a few sentences,
with a start timestamp. The atomic unit of search and display.

| Field name | ACF type | Notes |
|---|---|---|
| `parent_meeting` | Post object | Relationship to `meeting` |
| `start_seconds` | Number | Start time in seconds from meeting start |
| `end_seconds` | Number | End time in seconds |
| `speaker_label` | Text | Raw label from SCC file (may need cleanup) |
| `speaker_official` | Post object | Relationship to `official` (set during matching) |
| `text` | Textarea | The caption text |
| `agenda_item` | Post object | Relationship to `agenda_item` (set during matching) |
| `is_vote` | True/False | Flagged by roll call detector |
| `segment_index` | Number | Position in meeting (0-based) |

#### 3. `agenda_item`
A single item from the meeting agenda, scraped from the CPS website.

| Field name | ACF type | Notes |
|---|---|---|
| `parent_meeting` | Post object | Relationship to `meeting` |
| `item_number` | Text | e.g. "3.a", "VII.2" |
| `title` | Text | Agenda item title |
| `start_seconds` | Number | Estimated start time (matched from transcript) |
| `end_seconds` | Number | Estimated end time |
| `support_doc_url` | URL | Link to supporting document on CPS site |
| `item_type` | Select | `action` / `discussion` / `report` / `public_comment` |

#### 4. `official`
A School Committee member or administrator who appears in meetings.

| Field name | ACF type | Notes |
|---|---|---|
| `full_name` | Text | |
| `title` | Text | e.g. "Chair", "Member", "Superintendent" |
| `term_start` | Date picker | |
| `term_end` | Date picker | Leave blank if current |
| `is_voting_member` | True/False | |
| `photo` | Image | Optional |

#### 5. `vote`
A single recorded vote on a motion.

| Field name | ACF type | Notes |
|---|---|---|
| `parent_meeting` | Post object | |
| `parent_segment` | Post object | The segment where the vote was detected |
| `agenda_item` | Post object | What was being voted on |
| `motion_text` | Textarea | Extracted from transcript |
| `result` | Select | `passes` / `fails` / `tabled` / `unknown` |
| `vote_for` | Number | Count of yes votes |
| `vote_against` | Number | Count of no votes |
| `vote_abstain` | Number | |
| `voters_for` | Post object (multiple) | Relationship to `official` |
| `voters_against` | Post object (multiple) | |
| `raw_transcript` | Textarea | Exact transcript text the vote was extracted from |

#### 6. `issue`
A recurring topic tracked across multiple meetings.
**Note:** In Phase 1, issues are seeded manually or by simple keyword matching.
AI-powered clustering comes in Phase 5.

| Field name | ACF type | Notes |
|---|---|---|
| `issue_name` | Text | Plain language topic name |
| `description` | Textarea | Brief description |
| `first_appearance` | Date picker | Earliest meeting where issue appears |
| `latest_appearance` | Date picker | Most recent |
| `meeting_count` | Number | How many meetings this appears in |
| `related_meetings` | Post object (multiple) | |

### REST API endpoints the pipeline will use

WordPress exposes these automatically for registered post types.
The pipeline uses Application Passwords for authentication.

```
POST   /wp-json/wp/v2/meeting          → create a meeting record
POST   /wp-json/wp/v2/segment          → create a segment
POST   /wp-json/wp/v2/agenda_item      → create an agenda item
POST   /wp-json/wp/v2/official         → create an official
POST   /wp-json/wp/v2/vote             → create a vote
GET    /wp-json/wp/v2/meeting?per_page=100  → list meetings
PUT    /wp-json/wp/v2/meeting/{id}     → update a meeting
```

ACF fields are accessible via REST API with the ACF to REST API plugin,
OR by registering fields with `show_in_rest: true` in code.
**Use `show_in_rest: true` in code rather than an additional plugin.**

### Test the data model

After Phase 1 is complete, manually create one test meeting via the
WordPress admin UI to confirm all fields save and are retrievable via
the REST API before writing any pipeline code.

```bash
# Test REST API is working
curl https://[your-domain]/wp-json/wp/v2/meeting \
  -u "username:application-password"
```

---

## Phase 2 — Cablecast ingestion pipeline

**Goal:** A Python script (`ingest.py`) that runs locally on Matt's MacBook,
pulls School Committee VODs from Cablecast, parses their SCC files, and pushes
structured meeting + segment records to WordPress.

See `PIPELINE_SPEC.md` for full details.

---

## Phase 3 — Structure extraction

**Goal:** Extend the pipeline to parse agenda pages from the CPS website,
match agenda items to transcript segments by timestamp, and detect roll calls.

See `PIPELINE_SPEC.md` for full details.

---

## Phase 4 — Public interface

**Goal:** A custom WordPress theme providing the public-facing site.

See `THEME_SPEC.md` for full details.

---

## Phase 5 — AI layer (if time before November 17)

Optional for the conference demo. The site works and is useful without this.
If added, every AI-generated element must be labeled at the point of display
with the model used and must have a non-AI fallback.

---

## AI Constitution (to be published on the site)

Modeled on publicrecord.studio/ai. Cambridge Record version will commit to:

1. The transcript is the source. AI summarizes; it never replaces.
2. Every AI-generated element is labeled with the model name at the point of display.
3. The site is readable with all AI features removed.
4. Residents are never fed to models. No accounts, no tracking, no analytics.
5. A human approves every meeting before it is published.
6. The code is open source. Every prompt is public.

---

## Conference demo target (November 17)

**Minimum viable demo:**
- 6–12 Cambridge School Committee meetings from 2025–2026 school year
- Full transcript search across all meetings
- Each meeting page shows video embed + synchronized transcript
- Agenda items linked to transcript timestamps
- Roll calls / votes extracted and displayed
- Officials page with voting records
- One or two hand-curated issue pages showing a topic across multiple meetings
- Published AI Constitution

**Story to tell:**
"Here's what your school committee meetings look like when they're
searchable. Here's the Cablecast adapter that any MassAccess station can
use. Here's how we built it with our values first."

---

## Open questions to resolve before or during Phase 2

1. **Cablecast API credentials** — does Matt have API access? What endpoint
   structure does the Cambridge Cablecast instance use?
2. **SCC file access** — are SCC files accessible as attachments to VOD
   records via the API, or do they need to be exported manually?
3. **Cablecast timestamp deep-links** — does the Cablecast embed player
   support `?t=` or similar URL parameters for jumping to a timestamp?
4. **CPS agenda page structure** — is the HTML structure consistent enough
   to scrape reliably, or will agenda input need to be semi-manual?
5. **Domain** — where will the site live? Subdomain of an existing domain,
   or new domain?
6. **DreamHost tier** — VPS strongly recommended over shared hosting.

---

## What to discuss with Stephen Walter (BIG/Weird Machine)

- Would he be willing to co-present at the NEACM conference November 17?
- Is the Community Highlighter's ingestion layer modular for Cablecast sources?
- Interest in co-developing a Cablecast adapter for MassAccess stations?
- His experience with WordPress as display layer vs. static files
- Open invitation to expand the pilot to other MassAccess stations

Contact: steve@brooklineinteractive.org
