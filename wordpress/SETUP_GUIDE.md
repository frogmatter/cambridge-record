# WordPress Setup Guide
## DreamHost VPS → Cambridge Record

Follow these steps in order. Takes about 45-60 minutes start to finish.

---

## Step 1 — Confirm or upgrade DreamHost to VPS

Shared hosting has PHP memory limits (128MB) that will cause timeouts
when pushing hundreds of segments per meeting. VPS avoids this.

1. Log in at panel.dreamhost.com
2. Go to **Hosting → VPS**
3. If you're on shared hosting, add a VPS. The $10/month tier is fine.
4. If already on VPS, confirm PHP memory limit:
   Go to **Websites → PHP**, find your domain, confirm memory limit ≥ 256MB.
   If lower, edit the php.ini or contact DreamHost support.

---

## Step 2 — Install WordPress

DreamHost has a one-click installer.

1. In the DreamHost panel, go to **WordPress → Install WordPress**
2. Choose your domain (or add a subdomain — e.g. `record.yourdomain.com`)
3. Complete the install wizard
4. Note your WordPress admin URL, username, and password

**Then in WordPress admin (wp-admin):**
- Go to **Settings → Permalinks**
- Select **"Post name"** (e.g. `/meeting/school-committee-2026-01-15/`)
- Click Save. This is required for the REST API to work correctly.

---

## Step 3 — Install the Cambridge Record plugin

The plugin is in the `cambridge-record/` folder in your project zip.

**Option A — Upload via WordPress admin (easiest):**
1. Zip the `cambridge-record/` plugin folder
2. In WP admin: **Plugins → Add New → Upload Plugin**
3. Upload the zip and click **Install Now**
4. Click **Activate Plugin**

**Option B — Upload via SFTP:**
1. Connect to your DreamHost server via SFTP (credentials in panel)
2. Navigate to `/home/[username]/[domain]/wp-content/plugins/`
3. Upload the entire `cambridge-record/` folder there
4. In WP admin: **Plugins → Installed Plugins → Activate "Cambridge Record"**

**Confirm it activated correctly:**
After activation, you should see "Meetings", "Officials", and "Issues"
appear in the WordPress admin left sidebar. If you see those, the plugin
is running.

---

## Step 4 — No other plugins needed

The plugin handles everything in code. Do NOT install:
- ACF (Advanced Custom Fields) — not needed, conflicts with our meta registration
- Custom Post Type UI — not needed, post types are registered in code
- Any other custom field plugin

The only optional plugin worth considering later (not now) is **SearchWP**
if the built-in meta search becomes too slow on large archives.

---

## Step 5 — Generate an Application Password

The pipeline authenticates using WordPress Application Passwords
(a built-in WordPress feature since 5.6, safer than your main password).

1. In WP admin, go to **Users → Profile**
2. Scroll down to **"Application Passwords"**
3. Enter a name: `Cambridge Record Pipeline`
4. Click **"Add New Application Password"**
5. Copy the generated password immediately — it won't be shown again
   Format will be like: `AbCd EfGh IjKl MnOp QrSt UvWx`
   Remove the spaces when putting it in your .env: `AbCdEfGhIjKlMnOpQrStUvWx`

---

## Step 6 — Configure your .env file

In your local project folder (next to `ingest_cablecast.py`), create `.env`:

```
CABLECAST_BASE_URL=https://[your-cablecast-host]/cablecastapi/v1
CABLECAST_API_KEY=[your-api-key]
SCHOOL_COMMITTEE_SHOW_ID=[show-id-from-cablecast-admin]

WP_BASE_URL=https://[your-wordpress-domain]/wp-json/wp/v2
WP_USERNAME=[your-wp-admin-username]
WP_APP_PASSWORD=[application-password-no-spaces]

CPS_MEETINGS_URL=https://www.cpsd.us/school_committee/school_committee_meetings
```

**Finding SCHOOL_COMMITTEE_SHOW_ID:**
In Cablecast admin, navigate to Shows, find "Cambridge School Committee",
and look at the URL — the numeric ID in the URL is what you need.
Or run this quick Python snippet to find it:

```python
import requests, os
from dotenv import load_dotenv
load_dotenv()

r = requests.get(
    f"{os.environ['CABLECAST_BASE_URL']}/shows",
    headers={'X-API-Key': os.environ['CABLECAST_API_KEY']},
    params={'search': 'school committee'}
)
for show in r.json().get('shows', r.json()):
    print(show.get('id'), show.get('name'))
```

---

## Step 7 — Test the API

```bash
cd [your-project-folder]
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python wordpress/test_api.py
```

You should see all checks pass:
```
── 1. Connectivity ─────────────────────────────
  ✓  REST API root is reachable
── 2. Authentication ───────────────────────────
  ✓  Authenticated as: Matt (roles: administrator)
── 3. Custom post type endpoints ───────────────
  ✓  /wp-json/wp/v2/meeting  →  200 OK
  ✓  /wp-json/wp/v2/segment  →  200 OK
  ...
── 5. Write test ────────────────────────────────
  ✓  Created test meeting post (ID: 42)
  ✓  Meta fields round-trip correctly (write → read)
  ✓  Deleted test post 42

  Passed: 22   Failed: 0
  ✓  All checks passed — ready to run the pipeline.
```

If any checks fail, the error message says exactly what to fix.

---

## Step 8 — Manually create your first Official records

Before running the pipeline, add the current School Committee members
by hand in WP admin so votes can be linked to real people.

1. **Officials → Add New**
2. Fill in: Full Name, Title, Term Start, Is Voting Member (check)
3. Save — note the post ID for future reference

Current Cambridge School Committee members (verify against current roster):
- Chair (title: Chair)
- Vice Chair (title: Vice Chair)
- 5 Members (title: Member)
- Superintendent (title: Superintendent, is_voting_member: false)

---

## You're ready for Phase 2

Once `test_api.py` shows all green:
→ Run `python ingest_cablecast.py` to start pulling meetings from Cablecast.
   Start with `--limit 1` to test on a single meeting before the full run.

See `PIPELINE_SPEC.md` for the full ingestion code.
