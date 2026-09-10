"""
CLI Tool to retrieve and view transcripts stored in Supabase.
Requires no external dependencies (uses standard library only).

Usage:
    python view_transcripts.py
    python view_transcripts.py --limit 10
    python view_transcripts.py --session TEST_7205
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.parse
from datetime import datetime

DEFAULT_SUPABASE_URL = "https://vzxlgygptsdtyiowowfq.supabase.co"
DEFAULT_SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6eGxneWdwdHNkdHlpb3dvd2ZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNDcyNDQsImV4cCI6MjEwMzgyMzI0NH0.pLgvSOj18ZPbcq6BNSPeQSMMx36HuWrjI_ycyg_J8ec"

def load_env_file(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key not in os.environ:
                    os.environ[key] = val

def fetch_transcripts(url, key, limit=20, session_id=None):
    base_url = url.rstrip("/")
    query_params = {
        "select": "*",
        "order": "created_at.desc",
        "limit": str(limit)
    }
    if session_id:
        query_params["session_id"] = f"eq.{session_id}"

    endpoint = f"{base_url}/rest/v1/speech_transcripts?{urllib.parse.urlencode(query_params)}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(endpoint, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data, "speech_transcripts"
    except urllib.error.HTTPError as e:
        # Fallback to voice_transcripts if speech_transcripts fails
        try:
            vt_endpoint = f"{base_url}/rest/v1/voice_transcripts?select=*&order=created_at.desc&limit={limit}"
            vt_req = urllib.request.Request(vt_endpoint, headers=headers)
            with urllib.request.urlopen(vt_req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data, "voice_transcripts"
        except Exception:
            raise e

def format_timestamp(ts):
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts

def main():
    parser = argparse.ArgumentParser(description="View transcripts retrieved from Supabase")
    parser.add_argument("--limit", type=int, default=20, help="Number of records to fetch (default: 20)")
    parser.add_argument("--session", type=str, default=None, help="Filter by specific session/trigger ID")
    parser.add_argument("--json", action="store_true", help="Output raw JSON format")
    args = parser.parse_args()

    # Load from environment or .env files
    current_dir = os.path.dirname(os.path.abspath(__file__))
    load_env_file(os.path.join(current_dir, ".env"))
    load_env_file(os.path.join(current_dir, "..", ".env"))
    load_env_file(os.path.join(current_dir, "..", "backend", ".env"))
    load_env_file(os.path.join(current_dir, "..", "frontend", ".env"))

    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL
    supabase_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY

    print("=" * 70)
    print("  SUPABASE TRANSCRIPT RETRIEVER")
    print(f"  Target URL: {supabase_url}")
    if args.session:
        print(f"  Filter: session_id = '{args.session}'")
    print("=" * 70)

    try:
        records, table = fetch_transcripts(supabase_url, supabase_key, limit=args.limit, session_id=args.session)
    except Exception as e:
        print(f"\n[ERROR] Failed to retrieve data from Supabase: {e}")
        sys.exit(1)

    if args.json:
        print(json.dumps(records, indent=2))
        return

    print(f"\nFound {len(records)} record(s) from table '{table}':\n")
    if not records:
        print("  (No transcript records found)")
        return

    for i, r in enumerate(records, 1):
        sess = r.get("session_id") or r.get("trigger_id") or "UNKNOWN"
        created = format_timestamp(r.get("created_at"))
        audio = r.get("audio_file_path") or "None"
        dur = r.get("audio_duration_seconds")
        dur_str = f" ({dur}s)" if dur else ""
        transcript = r.get("transcript") or "(Empty transcript)"

        print(f"[{i}] Session ID : {sess}")
        print(f"    Date/Time  : {created}")
        print(f"    Audio File : {audio}{dur_str}")
        print(f"    Transcript : {transcript}")
        print("-" * 70)

if __name__ == "__main__":
    main()
