"""
Cambridge Record — HLS Caption Fetcher
Fetches per-cue WebVTT captions from Cablecast's HLS subtitle segments.

How it works:
  1. Fetch captions.en.m3u8 to get the list of ~1577 VTT segment files
  2. Fetch all VTT segments concurrently using a thread pool
  3. Parse each segment's cues (which have real millisecond timestamps)
  4. Merge into one sorted list of caption cues

Usage (from ingest_cablecast.py):
    from fetch_captions import fetch_hls_captions
    segments = fetch_hls_captions(folder_url, lang='en')
"""

import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

log = logging.getLogger(__name__)

# Number of parallel HTTP requests for VTT segments.
# 20 is conservative — the Cablecast CDN (CloudFront) handles this fine.
FETCH_WORKERS = 20

# Regex to parse a VTT timestamp: 00:36:41.901
TS_RE = re.compile(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})')

# Strip VTT positioning tags like <c>, <00:00:05.000><c>text</c>
TAG_RE = re.compile(r'<[^>]+>')


def _ts_to_seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _parse_vtt_segment(text, segment_number):
    """
    Parse one 10-second VTT segment file.
    Returns list of {start_seconds, end_seconds, text}.
    Timestamps inside the file are already absolute (not relative to segment).
    """
    cues = []
    blocks = text.strip().split('\n\n')

    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue

        # Find the timing line (contains -->)
        timing_line = None
        timing_idx = None
        for i, line in enumerate(lines):
            if '-->' in line:
                timing_line = line
                timing_idx = i
                break

        if timing_line is None:
            continue  # WEBVTT header or empty block

        # Parse start --> end
        times = TS_RE.findall(timing_line)
        if len(times) < 2:
            continue

        start = _ts_to_seconds(*times[0])
        end   = _ts_to_seconds(*times[1])

        # Collect text lines after the timing line
        text_lines = lines[timing_idx + 1:]
        raw_text = ' '.join(text_lines)
        clean_text = TAG_RE.sub('', raw_text).strip()

        if clean_text:
            cues.append({
                'start_seconds': round(start, 3),
                'end_seconds':   round(end, 3),
                'text':          clean_text,
            })

    return cues


def _fetch_segment(args):
    """Fetch and parse one VTT segment. Returns (segment_number, cues)."""
    segment_number, url, session = args
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        cues = _parse_vtt_segment(r.text, segment_number)
        return segment_number, cues
    except Exception as e:
        log.warning(f'  Segment {segment_number:05d} failed: {e}')
        return segment_number, []


def fetch_hls_captions(folder_url, lang='en'):
    """
    Fetch all VTT caption cues for a given language by reading the HLS
    subtitle manifest and downloading all segment files.

    Args:
        folder_url: Base URL of the VOD folder, e.g.
                    https://reflect-.../store-4/11522-SC091526-v2
        lang:       Language code, e.g. 'en', 'am', 'ar'

    Returns:
        List of dicts: {index, start_seconds, end_seconds, text, is_vote}
        Sorted by start_seconds. Returns [] if captions unavailable.
    """
    manifest_url = f'{folder_url}/captions.{lang}.m3u8'
    log.info(f'  Fetching caption manifest: {manifest_url}')

    try:
        r = requests.get(manifest_url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning(f'  Could not fetch caption manifest for lang={lang}: {e}')
        return []

    # Parse segment filenames from the manifest
    # Lines like: subtitles/captions.en.00000.vtt?duration=10
    segment_lines = [
        line.strip()
        for line in r.text.splitlines()
        if line.strip() and not line.startswith('#')
    ]

    if not segment_lines:
        log.warning('  Caption manifest is empty')
        return []

    log.info(f'  Found {len(segment_lines)} caption segments')

    # Build full URLs for each segment
    # segment_lines contain relative paths like: subtitles/captions.en.00000.vtt?duration=10
    segment_tasks = []
    for i, seg_path in enumerate(segment_lines):
        # Strip the ?duration=N query parameter — not needed for fetching
        clean_path = seg_path.split('?')[0]
        url = f'{folder_url}/{clean_path}'
        segment_tasks.append((i, url))

    # Fetch all segments concurrently
    all_cues = []
    adapter = requests.adapters.HTTPAdapter(pool_connections=FETCH_WORKERS, pool_maxsize=FETCH_WORKERS)
    session = requests.Session()
    session.mount('https://', adapter)

    log.info(f'  Downloading {len(segment_tasks)} VTT segments '
             f'({FETCH_WORKERS} parallel workers)...')

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_segment, (num, url, session)): num
            for num, url in segment_tasks
        }

        completed = 0
        for future in as_completed(futures):
            segment_number, cues = future.result()
            all_cues.extend(cues)
            completed += 1
            if completed % 200 == 0:
                log.info(f'    {completed}/{len(segment_tasks)} segments fetched...')

    session.close()

    # Sort all cues by start time (concurrent fetching may disorder them)
    all_cues.sort(key=lambda c: c['start_seconds'])

    # Deduplicate: VTT segments overlap slightly at boundaries,
    # so the same cue text at the same timestamp can appear twice.
    deduped = []
    seen = set()
    for cue in all_cues:
        key = (round(cue['start_seconds'], 1), cue['text'][:40])
        if key not in seen:
            seen.add(key)
            deduped.append(cue)

    log.info(f'  Parsed {len(deduped)} caption cues '
             f'(after deduplication from {len(all_cues)} raw cues)')

    # Build final segment list with index and is_vote flag
    segments = []
    for i, cue in enumerate(deduped):
        segments.append({
            'index':         i,
            'start_seconds': cue['start_seconds'],
            'end_seconds':   cue['end_seconds'],
            'text':          cue['text'],
            'is_vote':       False,  # set by flag_votes() in ingest_cablecast.py
        })

    return segments
