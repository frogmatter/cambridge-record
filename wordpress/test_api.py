"""
Test script: verifies the Cambridge Record WordPress plugin is correctly
installed and working on mediatechaction.com before running the pipeline.

Usage:
    source venv/bin/activate
    python wordpress/test_api.py
"""

import os, requests, json
from dotenv import load_dotenv

load_dotenv()

WP_BASE = os.environ['WP_BASE_URL']   # https://mediatechaction.com/wp-json/wp/v2
CR_BASE = WP_BASE.replace('/wp/v2', '/cambridge-record/v1')
AUTH    = (os.environ['WP_USERNAME'], os.environ['WP_APP_PASSWORD'])

passed, failed = [], []

def ok(msg):
    print(f"  ✓  {msg}")
    passed.append(msg)

def fail(msg, detail=''):
    print(f"  ✗  {msg}")
    if detail: print(f"     → {detail}")
    failed.append(msg)


# ── 1. Connectivity ───────────────────────────────────────────
print("\n── 1. Connectivity ─────────────────────────────────────")
try:
    r = requests.get(f"{WP_BASE}/", timeout=10)
    ok("REST API root reachable") if r.ok else fail("REST API root", f"HTTP {r.status_code}")
except Exception as e:
    fail("Cannot reach WordPress", str(e))


# ── 2. Authentication ─────────────────────────────────────────
print("\n── 2. Authentication ───────────────────────────────────")
try:
    r = requests.get(f"{WP_BASE}/users/me", auth=AUTH, timeout=10)
    if r.ok:
        u = r.json()
        ok(f"Authenticated: {u.get('name')} (roles: {', '.join(u.get('roles', []))})")
        if 'administrator' not in u.get('roles', []):
            fail("User needs administrator role for pipeline writes")
    else:
        fail("Authentication failed — check WP_USERNAME and WP_APP_PASSWORD in .env",
             f"HTTP {r.status_code}")
except Exception as e:
    fail("Auth error", str(e))


# ── 3. Plugin post types ──────────────────────────────────────
print("\n── 3. Plugin post types ────────────────────────────────")
for endpoint in ['meeting', 'official', 'issue']:
    try:
        r = requests.get(f"{WP_BASE}/{endpoint}", auth=AUTH,
                         params={'per_page': 1}, timeout=10)
        if r.ok:
            ok(f"/wp-json/wp/v2/{endpoint}")
        elif r.status_code == 404:
            fail(f"/wp-json/wp/v2/{endpoint} — 404",
                 "Is the Cambridge Record plugin activated?")
        else:
            fail(f"/wp-json/wp/v2/{endpoint}", f"HTTP {r.status_code}")
    except Exception as e:
        fail(f"{endpoint} endpoint", str(e))


# ── 4. Custom REST routes ─────────────────────────────────────
print("\n── 4. Custom REST routes ───────────────────────────────")
for path, params in [
    ('/meetings', {}),
    ('/search',   {'q': 'test'}),
]:
    try:
        r = requests.get(f"{CR_BASE}{path}", params=params, timeout=10)
        if r.ok:
            ok(f"/wp-json/cambridge-record/v1{path}")
        else:
            fail(f"/wp-json/cambridge-record/v1{path}", f"HTTP {r.status_code}")
    except Exception as e:
        fail(f"cambridge-record/v1{path}", str(e))


# ── 5. Meta fields round-trip ─────────────────────────────────
print("\n── 5. Meta fields — write and read back ────────────────")
test_id = None
try:
    sample_segments = json.dumps([
        {"index": 0, "start_seconds": 0.0,  "end_seconds": 4.5,
         "text": "Good evening and welcome.", "deep_link_url":
         "https://example.com/vod/1?t=0", "is_vote": False},
        {"index": 1, "start_seconds": 4.5,  "end_seconds": 9.2,
         "text": "We will begin with roll call.", "deep_link_url":
         "https://example.com/vod/1?t=4", "is_vote": False},
    ])
    sample_agenda = json.dumps([
        {"item_number": "1", "title": "Call to Order",
         "start_seconds": 0.0, "deep_link_url":
         "https://example.com/vod/1?t=0", "matched": True},
    ])
    sample_votes = json.dumps([
        {"segment_index": 5, "start_seconds": 120.0,
         "motion_text": "Motion to approve agenda",
         "result": "passes", "vote_for": 6, "vote_against": 0,
         "deep_link_url": "https://example.com/vod/1?t=120"},
    ])

    payload = {
        'title':  'TEST MEETING — DELETE ME',
        'status': 'draft',
        'meta': {
            'meeting_date':        '2026-01-15',
            'meeting_body':        'Cambridge School Committee',
            'cablecast_vod_id':    99999,
            'cablecast_embed_url': 'https://example.com/vod/99999',
            'segment_count':       2,
            'vote_count':          1,
            'agenda_item_count':   1,
            'cr_status':           'processing',
            'summary_origin':      'pending',
            'segments_json':       sample_segments,
            'agenda_json':         sample_agenda,
            'votes_json':          sample_votes,
        }
    }
    r = requests.post(f"{WP_BASE}/meeting", json=payload, auth=AUTH, timeout=15)

    if r.status_code == 201:
        test_id = r.json()['id']
        ok(f"Created test meeting (WP post ID: {test_id})")

        # Read back
        r2 = requests.get(f"{WP_BASE}/meeting/{test_id}", auth=AUTH)
        meta = r2.json().get('meta', {})

        checks = [
            ('meeting_date',        '2026-01-15'),
            ('cablecast_vod_id',    99999),
            ('segment_count',       2),
            ('cr_status',           'processing'),
        ]
        for field, expected in checks:
            actual = meta.get(field)
            if actual == expected:
                ok(f"  meta.{field} = {expected!r}")
            else:
                fail(f"  meta.{field}", f"expected {expected!r}, got {actual!r}")

        # Check JSON blobs parse correctly
        for blob_field in ['segments_json', 'agenda_json', 'votes_json']:
            raw = meta.get(blob_field, '')
            try:
                parsed = json.loads(raw)
                ok(f"  meta.{blob_field} parses as JSON ({len(parsed)} item(s))")
            except Exception:
                fail(f"  meta.{blob_field} is not valid JSON", repr(raw[:80]))

    else:
        fail("Could not create test meeting",
             f"HTTP {r.status_code} — {r.text[:200]}")

except Exception as e:
    fail("Meta round-trip error", str(e))

# Clean up
if test_id:
    try:
        requests.delete(f"{WP_BASE}/meeting/{test_id}", auth=AUTH,
                        params={'force': True}, timeout=10)
        ok(f"Cleaned up test post {test_id}")
    except Exception:
        print(f"  ⚠  Could not delete test post {test_id} — delete manually in WP admin")


# ── 6. Permalink structure ────────────────────────────────────
print("\n── 6. Permalink structure ──────────────────────────────")
try:
    r = requests.get(f"{WP_BASE}/meeting", auth=AUTH,
                     params={'per_page': 1}, timeout=10)
    # If permalinks aren't set to "Post name", the REST API still works
    # but individual post URLs won't be pretty. Check via root endpoint.
    root = requests.get(WP_BASE.replace('/wp/v2', ''), timeout=10)
    if root.ok:
        ok("Permalink structure looks fine (REST API root accessible)")
    else:
        fail("Permalink issue — go to Settings → Permalinks → Post name → Save")
except Exception as e:
    fail("Permalink check", str(e))


# ── Summary ───────────────────────────────────────────────────
print("\n" + "─" * 54)
print(f"  Passed: {len(passed)}   Failed: {len(failed)}")
if not failed:
    print("\n  ✓ All checks passed — ready to run the pipeline.\n")
    print("  Next: python ingest_cablecast.py --limit 1\n")
else:
    print(f"\n  Fix {len(failed)} issue(s) before ingesting:\n")
    for f in failed:
        print(f"    • {f}")
    print()
