"""
Finds the Cablecast Show ID for Cambridge School Committee.
Run this once to get the ID, then put it in your .env file.

Usage:
    source venv/bin/activate
    python find_show_id.py
"""

import os, requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get('CABLECAST_BASE_URL', '')


print(f"Connecting to Cablecast at {BASE}...\n")

# Try common auth header formats — Cablecast versions vary
for auth_header in [
    {'X-API-Key': KEY},
    {'Authorization': f'Bearer {KEY}'},
    {'X-Cablecast-API-Key': KEY},
]:
    try:
        r = requests.get(
            f"{BASE}/shows",
            headers=auth_header,
            params={'per_page': 100},
            timeout=10
        )
        if r.ok:
            print(f"Auth worked with header: {list(auth_header.keys())[0]}")
            print("Add this to your .env:\n  CABLECAST_AUTH_HEADER=" +
                  list(auth_header.keys())[0])
            break
    except Exception as e:
        continue
else:
    print("Could not authenticate. Check CABLECAST_API_KEY in .env")
    exit(1)

# Parse shows
data = r.json()
shows = data if isinstance(data, list) else data.get('shows', [])

print(f"\nFound {len(shows)} shows. Searching for 'school committee'...\n")

matches = [s for s in shows
           if 'school' in str(s.get('name', '')).lower()
           or 'committee' in str(s.get('name', '')).lower()]

if matches:
    print("Likely matches:")
    for s in matches:
        print(f"  ID: {s.get('id')}  →  {s.get('name')}")
    print("\nPut the correct ID in your .env as SCHOOL_COMMITTEE_SHOW_ID=...")
else:
    print("No matches found. All shows:")
    for s in shows[:30]:
        print(f"  ID: {s.get('id')}  →  {s.get('name')}")
    if len(shows) > 30:
        print(f"  ... and {len(shows) - 30} more")
    print("\nNote the correct ID and add it to your .env")
