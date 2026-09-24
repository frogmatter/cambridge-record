# Cambridge Record — Project Documentation
## How it was built, what we learned, and where it's going

**Project:** Cambridge Record  
**Site:** mediatechaction.com  
**Started:** September 2026  
**Target:** NEACM Conference, November 17, 2026  
**Author:** Matt, Media Arts Manager, Cambridge Public Schools  

---

## What this is

A civic meeting archive that makes Cambridge School Committee meetings
searchable, structured, and navigable across time — by topic, by moment,
by keyword. A resident can search "transportation" and see every moment
the word was spoken across all meetings, with a link that jumps the video
to that exact second.

Built on WordPress (DreamHost shared hosting), populated by a local
Python pipeline that pulls from Cablecast's public CDN and pushes
structured data to WordPress via the REST API.

Inspired by: publicrecord.studio (Brookline Interactive Group / Weird Machine)

---

## Architecture

```
Cablecast CDN (reflect-video-ondemand-cpsd.cablecast.tv)
  └── HLS manifest (.m3u8)
        └── 1,577 VTT subtitle segments × 10 seconds each
              └── Per-cue timestamps accurate to millisecond

Matt's MacBook (local pipeline)
  ├── ingest_cablecast.py  — orchestrates everything
  ├── fetch_captions.py    — downloads VTT segments concurrently
  └── pipeline.db          — SQLite, tracks what's been ingested

WordPress (mediatechaction.com / DreamHost shared hosting)
  ├── cambridge-record plugin — registers post types + REST endpoints
  ├── cr_meeting posts — one per meeting, segments stored as JSON in post_content + meta
  └── REST API
        ├── /wp-json/cambridge-record/v1/meetings  — meeting index
        └── /wp-json/cambridge-record/v1/search?q= — full-text search
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

## The WordPress data model

**Post types:**
- `cr_meeting` — one per meeting session
- `cr_official` — School Committee members
- `cr_issue` — curated topic threads (manually maintained)

**Key meta fields on `cr_meeting`:**
- `segments_json` — JSON array of all caption cues with timestamps
- `votes_json` — extracted vote moments
- `agenda_json` — agenda items (Phase 3, not yet built)
- `meeting_date`, `cablecast_embed_url`, `languages_available`, etc.

**`post_content`** holds all segment text concatenated — this is what
WordPress's native search indexes. The search endpoint finds meetings
via WordPress search, then filters segments in PHP.

**REST endpoints (no auth required):**
- `GET /wp-json/cambridge-record/v1/meetings`
- `GET /wp-json/cambridge-record/v1/search?q={term}&limit={n}`

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

---

## What's working (as of September 2026)

- ✅ Pipeline: Cablecast → WordPress in ~60 seconds per meeting
- ✅ Accurate timestamps (millisecond precision from HLS VTT)
- ✅ Full-text search across all meetings via REST API
- ✅ Deep-links that jump to the exact video moment
- ✅ 7 languages tracked (en, am, ar, bn, ht, pt, zh)
- ✅ Draft/publish workflow (pipeline creates drafts, human publishes)

---

## What's not built yet

**Phase 3 — Agenda structure**  
Scraping agenda items from the CPS website and linking them to
transcript timestamps. The CPS website HTML structure needs to be
inspected before writing selectors.

**Phase 4 — Public theme**  
The WordPress theme that residents actually use. Currently the data
is only accessible via the JSON API. Needs: meeting list page,
individual meeting page with video + synchronized transcript, search UI.

**Phase 5 — AI layer**  
Meeting summaries, semantic search, issue clustering across meetings.
Additive — the site works without this.

**Vote extraction improvement**  
Currently flags segments matching voting language patterns. Needs
more Cambridge-specific tuning and linking to named officials.

**Officials pages**  
School Committee members are in the database but not yet linked to
votes or displayed publicly.

---

## For other MassAccess stations

The Cablecast pipeline is generic. Any station running Cablecast with:
- HLS video delivery (`.m3u8` files)
- MediaScribe or Cablecast Cloud captions
- Public VOD access

...can use this pipeline with only the Show ID and base URL changed.

The key discovery — that accurate timestamps live in the HLS subtitle
stream, not in any dedicated API endpoint — applies to all Cablecast
installations using cloud caption delivery.

---

## Next steps (toward NEACM, November 17)

**Week of Sep 23:** Documentation (this), ingest more meetings  
**Week of Sep 30:** WordPress theme Phase 1 (meeting list, search UI)  
**Week of Oct 7:** WordPress theme Phase 2 (individual meeting pages)  
**Week of Oct 14:** Polish, agenda scraper, officials pages  
**Week of Oct 21:** AI layer if time allows, conference prep  
**Week of Oct 28:** Demo rehearsal, presentation slides  
**Week of Nov 3:** Buffer, final fixes  
**Nov 17:** NEACM Conference presentation  

---

## Reach out

Stephen Walter, Brookline Interactive Group / Weird Machine  
steve@brooklineinteractive.org  
Community AI Project, Public Record Studio  
publicrecord.studio
