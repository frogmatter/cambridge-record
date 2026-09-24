# Cambridge Record — WordPress theme

Public theme for the Cambridge Record meeting archive. Requires the
**Cambridge Record plugin** (`../cambridge-record-plugin.zip`) — all meeting
data comes from its REST endpoints. No build step, no dependencies, no
third-party requests (system fonts only).

## Pages

| URL | Template | Data |
|---|---|---|
| `/` | `front-page.php` + `assets/js/meetings.js` | `GET /wp-json/cambridge-record/v1/meetings` |
| `/?s=term` | `search.php` + `assets/js/search.js` | `GET /wp-json/cambridge-record/v1/search?q=term&limit=50` |
| `/meeting/{slug}/` | `single-cr_meeting.php` + `assets/js/meeting.js` | `GET /wp-json/wp/v2/meeting/{id}?_fields=id,meta` |

Everything else (e.g. an AI Constitution page) uses `index.php`.

## Meeting page

- Cablecast embed on the left (sticky), transcript on the right.
- Caption cues are grouped into paragraphs (speaker change `>>`, or ~40–90s).
- Click any line or timestamp → the video jumps there and plays.
- While the video plays, the spoken line is highlighted and kept in view.
  Scrolling yourself pauses that; "Follow video" resumes it.
- Agenda (`agenda_json`) and auto-flagged votes (`votes_json`) link to moments.
- "Find in this meeting" highlights matches with next/previous.
- Deep links: `/meeting/{slug}/#t=3725` opens at 1:02:05;
  `?q=budget#t=…` (what search results link to) also highlights the term.

How it talks to the Cablecast player (see the top of `assets/js/meeting.js`):
the embed URL takes `?seek=N` (not `t`); after it loads, the page sends
`postMessage({type: 'player-cue', value: N})` to jump without reloading,
and the player sends back `timeupdate` / `playing` / `ready` messages.

## ⚠ Cablecast embed allowlist

The Cablecast embed sends
`Content-Security-Policy: frame-ancestors …` listing only cpsd.us,
youthviewcambridge.org, *.cambridgema.gov, *.cablecast.tv, Google Sites,
and Finalsite. mediatechaction.com was added in Sept 2026. Any new domain (a staging
site, a new host) must be added in Cablecast too, or browsers block the
player. The "Watch on Cablecast ↗" link under the player is the fallback.

## Install

1. Zip this folder (or use `../cambridge-record-theme.zip`).
2. WP admin → **Appearance → Themes → Add New → Upload Theme** → Activate.
3. **Settings → Reading**: "Your latest posts" is fine — the theme's
   `front-page.php` shows the meeting list either way.
4. Optional: **Appearance → Menus** → assign a menu to "Primary navigation".
   Without one, the header shows Meetings / Search.
