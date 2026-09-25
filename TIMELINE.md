# Cambridge Record — 8-Week Timeline
## Target: NEACM Conference, November 17, 2026

Today: September 19, 2026
Conference: November 17, 2026
Available weeks: 8

---

## Week 1 (Sep 19–26) — Groundwork
**Goal: answer the unknowns before building anything**

- [ ] Reach out to Stephen Walter
      - Introduce Cambridge pilot, MassAccess expansion idea
      - Ask about Cablecast adapter, NEACM co-presentation interest
- [ ] Check DreamHost account tier — upgrade to VPS if on shared hosting
- [ ] Register or identify domain for the site
- [ ] Confirm Cablecast API access:
      - Log into Cablecast admin and locate API settings
      - Find API base URL and authentication method
      - Confirm SCC files are accessible per VOD record
      - Test timestamp deep-links in the embed player
- [ ] Inspect CPS meeting page HTML structure for agenda scraper
- [ ] Pull 2-3 SCC files manually from Cablecast to examine format
- [ ] Install Ollama + Qwen3:8b on MacBook Pro (parallel learning)

**Deliverable:** All open questions from PROJECT_SPEC.md answered.
              You know what you're building before asking Claude Code
              to build it.

---

## Week 2 (Sep 27–Oct 3) — WordPress foundation
**Goal: Phase 1 complete — working data model, testable REST API**

- [ ] Install WordPress on DreamHost VPS
- [ ] Install ACF Free and Custom Post Type UI plugins
- [ ] Register all 6 custom post types:
      meeting / segment / agenda_item / official / vote / issue
- [ ] Define all custom fields per PROJECT_SPEC.md
- [ ] Enable ACF fields in REST API with `show_in_rest: true`
- [ ] Generate WordPress Application Password for API auth
- [ ] Test REST API manually:
      `curl https://[domain]/wp-json/wp/v2/meeting -u "user:apppassword"`
- [ ] Create one test meeting manually in WP admin
      Confirm all fields save and are returned by the API
- [ ] Set up local Python environment for the pipeline
      `python3 -m venv venv && pip install -r requirements.txt`

**Deliverable:** Empty but correctly structured WordPress site.
              API access confirmed working.
              Can be handed to Claude Code for Phase 2.

---

## Week 3 (Oct 4–10) — Cablecast ingestion (Phase 2)
**Goal: real Cambridge meetings in WordPress**

- [ ] Build `ingest_cablecast.py`:
      - Authenticate with Cablecast API
      - Fetch School Committee VOD list
      - Download SCC files per VOD
      - Parse SCC → timestamped segments with pycaption
      - Push meeting + segments to WordPress REST API
      - Track state in pipeline.db (SQLite)
- [ ] Test with 1 meeting end-to-end before running on full archive
- [ ] Run pipeline on 6–12 meetings from 2025–2026 school year
- [ ] Spot-check segment data in WordPress admin for 2-3 meetings
- [ ] Review and manually publish first test meeting

**Deliverable:** 6–12 real Cambridge School Committee meetings
              in WordPress with full transcripts.
              Pipeline is re-runnable and resumable.

---

## Week 4 (Oct 11–17) — Structure extraction (Phase 3)
**Goal: agenda items and votes linked to transcript timestamps**

- [ ] Build `scrape_agenda.py` for CPS meeting pages
      (adjust selectors to actual HTML structure)
- [ ] Build `match_agenda.py` — keyword matching agenda → segments
- [ ] Build `detect_votes.py` — pattern matching roll calls
- [ ] Run structure extraction on all ingested meetings
- [ ] Manual review: spot-check agenda matching accuracy
      Note which meetings need manual correction
- [ ] Enter School Committee members as `official` records
- [ ] Link extracted votes to officials where identified

**Deliverable:** Meetings have agenda items linked to timestamps.
              Votes are extracted with for/against counts.
              This is the moment the data gets genuinely useful.

---

## Week 5 (Oct 18–24) — Public interface (Phase 4, part 1)
**Goal: working site residents can use, unstyled but functional**

- [ ] Build custom WordPress theme (or child theme of minimal base)
- [ ] Meeting index page — list of all meetings, newest first
- [ ] Individual meeting page:
      - Cablecast video embed at top
      - Agenda items listed with timestamp links
      - Full transcript below, scrollable, searchable
      - Votes extracted and displayed
- [ ] Officials page — list of School Committee members
- [ ] Basic keyword search across segments (WordPress built-in search
      extended to custom post types)

**Deliverable:** Functional site, functional search.
              Not pretty yet. But a resident could use it.

---

## Week 6 (Oct 25–31) — Public interface (Phase 4, part 2)
**Goal: polished enough for a conference demo**

- [ ] Design pass: typography, layout, colors
      Reference publicrecord.studio design principles —
      clean, text-forward, no decorative chrome
- [ ] Mobile-responsive layout
- [ ] Issue pages — 2–3 hand-curated topic threads
      (e.g. "School Budget 2025–2026", "AI in Schools")
      showing the topic across multiple meetings
- [ ] Officials voting record pages
- [ ] AI Constitution page (draft and publish)
- [ ] Add meeting status indicators and disclosure labels
- [ ] Accessibility check — keyboard nav, screen reader basics

**Deliverable:** Conference-ready public site.
              Looks good in a browser demo.

---

## Week 7 (Nov 1–7) — Buffer and polish
**Goal: fix what breaks, add depth to the demo story**

- [ ] Fix bugs found during Week 6 testing
- [ ] Add more meetings to the archive if pipeline is stable
- [ ] If time: Phase 5 AI layer — meeting summaries with Gemini Flash,
      labeled with model name and fallback to extractive summary
- [ ] If time: semantic search via embedding API
- [ ] Write conference presentation outline
- [ ] Prepare live demo flow (which meetings, which searches to show)
- [ ] Brief Stephen Walter on where things stand; confirm co-presentation
      if he is participating

**Deliverable:** Stable, polished site.
              Presentation outline drafted.

---

## Week 8 (Nov 8–14) — Conference prep
**Goal: presentation ready, demo rehearsed**

- [ ] Finalize presentation slides
- [ ] Rehearse live demo — have a backup (screenshots/video) if live
      demo internet is unreliable at the conference venue
- [ ] Prepare "how to replicate this at your station" handout
      One page: what you need, what it costs, where the code lives
- [ ] Confirm any logistics with NEACM conference organizers
- [ ] Final site check — all meetings published, search working,
      AI Constitution page live

**Deliverable:** Ready to present.

---

## Conference day (November 17)

**Presentation arc (suggested 20 minutes):**

1. *The problem* (3 min)
   School committee meetings are hard to navigate. 3 hours of video,
   no way to search, no record of who voted for what. This is true
   everywhere in Massachusetts, not just Cambridge.

2. *The approach* (3 min)
   Values first — transparency, community ownership, AI that is
   additive not load-bearing. Show the AI Constitution page.
   "Here's what we promised before we built anything."

3. *Live demo* (8 min)
   - Search "special education" across all meetings
   - Click a result → jump to that moment in the video
   - Show a vote — who voted, on what, when
   - Show an issue thread across multiple meetings
   - Show the officials page

4. *The Cablecast adapter* (3 min)
   "If your station uses Cablecast, this works for your meetings too.
   The code is open source. Here's how to deploy it."

5. *The MassAccess opportunity* (3 min)
   Invitation to other stations to pilot. What it takes.
   How to get involved.

---

## What this costs

- **DreamHost VPS:** ~$12/month (upgrade from shared if needed)
- **Domain:** ~$15/year if new domain needed
- **Gemini API (Phase 5, optional):** Pay-per-use, very low cost at
  this scale (~$1-5 for the full archive)
- **Your time:** Estimated 4–8 hours/week for 8 weeks
- **Claude Code / AI assistance:** For the heavy lifting on pipeline
  and theme code

**Total estimated cash cost: under $50 for the pilot**
