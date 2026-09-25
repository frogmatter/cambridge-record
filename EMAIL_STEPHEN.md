# Draft: Email to Stephen Walter, BIG/Weird Machine

Subject: Public Record Studio → Cambridge pilot + MassAccess expansion

---

Hi Stephen,

We spoke briefly last year — I'm Matt, Media Arts Manager at Cambridge
Public Schools, and I'm on the board of MassAccess. I've been running
a project called Community AI focused on helping community media centers
understand and build their own AI tools, including workshops at the
Alliance for Community Media conference in Madison this past year and
ongoing work in the Cambridge schools.

I've been exploring Public Record Studio and the broader Community AI
Project toolkit at BIG, and I think what you've built is exactly the
right model for what community media centers should be doing. I'd like
to build something similar for Cambridge — starting with Cambridge School
Committee meetings.

**My situation is a little different from your YouTube-based ingestion:**
Cambridge School Committee meetings are hosted on a Cablecast server,
not YouTube. We use MediaScribe for live captioning, which produces SCC
files that end up attached to our Cablecast VOD records. We also have
seven-language translations. So the transcript and caption infrastructure
is already there — the question is building the structured layer on top.

I'm planning to build the Cambridge version using WordPress on DreamHost
with a local Python pipeline that pulls from the Cablecast API, parses
SCC files, and pushes structured data to WordPress. I'm targeting a demo
for the New England Alliance for Community Media Conference on November 17.

**A few questions:**
- Is the Community Highlighter's ingestion layer modular enough to swap
  in a Cablecast source, or would Cambridge need a separate adapter?
- A lot of MassAccess member stations use Cablecast. If we built a
  Cablecast adapter together, it would potentially unlock the tool for a
  significant chunk of the Massachusetts PEG ecosystem. Is that something
  you'd be interested in collaborating on?
- Would you have any interest in co-presenting at the NEACM conference
  on November 17 — either in person or remotely? It could be a good
  opportunity to introduce the Community AI Project to the New England
  community media network.

I'm happy to share my full project specification if it would be useful.
And I'm very open to building on what you've already made rather than
reinventing it — the CC BY-SA license is exactly the right call.

Thanks for the work you're doing. It's good to see BIG building this.

Matt
Media Arts Manager, Cambridge Public Schools
Board Member, MassAccess
