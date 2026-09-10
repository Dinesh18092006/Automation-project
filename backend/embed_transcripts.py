"""
Embed Transcripts CLI Tool
Generates Google Gemini vector embeddings for transcripts stored in Supabase speech_transcripts.

Usage:
    # Embed all rows currently missing embeddings:
    python embed_transcripts.py

    # Re-embed all rows:
    python embed_transcripts.py --all

    # Embed a specific session:
    python embed_transcripts.py --session TEST_7205

    # Run semantic search test against stored embeddings:
    python embed_transcripts.py --search "project discussion"
"""

import os
import sys
import json
import argparse
import httpx

def load_env():
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    for env_path in [
        os.path.join(cur_dir, ".env"),
        os.path.join(cur_dir, "..", ".env"),
        os.path.join(cur_dir, "..", "frontend", ".env")
    ]:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v

load_env()

DEFAULT_SUPABASE_URL = os.getenv("SUPABASE_URL", "https://vzxlgygptsdtyiowowfq.supabase.co")
DEFAULT_SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6eGxneWdwdHNkdHlpb3dvd2ZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNDcyNDQsImV4cCI6MjEwMzgyMzI0NH0.pLgvSOj18ZPbcq6BNSPeQSMMx36HuWrjI_ycyg_J8ec")
DEFAULT_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "768"))

def get_gemini_embedding(text: str, api_key: str, model: str = DEFAULT_MODEL, dimension: int = DIMENSION) -> list:
    """Generate 768-dim vector embedding using Google Gemini API."""
    if not text or not text.strip():
        return None

    clean_model = model.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:embedContent?key={api_key}"
    payload = {
        "output_dimensionality": dimension,
        "content": {
            "parts": [{"text": text.strip()}]
        }
    }

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("embedding", {}).get("values")
        else:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text}")

def check_embedding_column(supabase_url: str, supabase_key: str) -> bool:
    """Check if the embedding column exists in Supabase."""
    import time
    url = f"{supabase_url.rstrip('/')}/rest/v1/speech_transcripts?select=id,embedding&limit=1"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}"
    }
    for attempt in range(3):
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    return True
                if "embedding" in resp.text:
                    return False
                return True
        except Exception as e:
            if attempt == 2:
                print(f"[Warning] Supabase column check encountered: {e}")
                return False
            time.sleep(1.5)
    return False

def fetch_transcripts(supabase_url: str, supabase_key: str, embed_all: bool = False, session_id: str = None, limit: int = 100):
    base_url = supabase_url.rstrip("/")
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    params = {
        "select": "id,session_id,transcript,created_at",
        "order": "created_at.desc",
        "limit": str(limit)
    }
    if not embed_all:
        params["embedding"] = "is.null"
    if session_id:
        params["session_id"] = f"eq.{session_id}"

    with httpx.Client(timeout=12.0) as client:
        resp = client.get(f"{base_url}/rest/v1/speech_transcripts", headers=headers, params=params)
        if resp.status_code == 200:
            return resp.json()
        elif "embedding" in resp.text:
            raise ValueError("COLUMN_NOT_FOUND")
        else:
            raise RuntimeError(f"Supabase GET failed {resp.status_code}: {resp.text}")

def update_embedding(supabase_url: str, supabase_key: str, row_id: str, embedding: list):
    base_url = supabase_url.rstrip("/")
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    with httpx.Client(timeout=12.0) as client:
        resp = client.patch(
            f"{base_url}/rest/v1/speech_transcripts?id=eq.{row_id}",
            headers=headers,
            json={"embedding": embedding}
        )
        return resp.status_code in (200, 204)

def semantic_search(query: str, supabase_url: str, supabase_key: str, gemini_key: str, top_k: int = 5):
    print(f"\n[Semantic Search] Generating embedding for query: '{query}'...")
    try:
        query_vector = get_gemini_embedding(query, gemini_key)
    except Exception as e:
        print(f"Failed to generate query embedding: {e}")
        return

    base_url = supabase_url.rstrip("/")
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "query_embedding": query_vector,
        "match_threshold": 0.1,
        "match_count": top_k
    }

    with httpx.Client(timeout=12.0) as client:
        resp = client.post(f"{base_url}/rest/v1/rpc/match_speech_transcripts", headers=headers, json=payload)
        if resp.status_code == 200:
            results = resp.json()
            print(f"\nFound {len(results)} match(es):\n")
            for i, r in enumerate(results, 1):
                sim = round(r.get("similarity", 0) * 100, 1)
                print(f"[{i}] Similarity: {sim}% | Session: {r.get('session_id')}")
                print(f"    Transcript: {r.get('transcript')}")
                print("-" * 60)
        else:
            print(f"Search RPC failed ({resp.status_code}): {resp.text}")
            print("\n>> Make sure you have executed backend/add_vector_embeddings.sql in Supabase SQL Editor!")

def main():
    parser = argparse.ArgumentParser(description="Embed Supabase transcripts using Gemini API")
    parser.add_argument("--all", action="store_true", help="Re-embed all rows even if embedding exists")
    parser.add_argument("--session", type=str, default=None, help="Filter by session ID")
    parser.add_argument("--limit", type=int, default=100, help="Max rows to process (default: 100)")
    parser.add_argument("--search", type=str, default=None, help="Perform semantic search on transcripts")
    args = parser.parse_args()

    load_env()

    supabase_url = os.getenv("SUPABASE_URL") or DEFAULT_SUPABASE_URL
    supabase_key = os.getenv("SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY
    gemini_key = os.getenv("GEMINI_API_KEY") or DEFAULT_GEMINI_KEY
    model = os.getenv("GEMINI_EMBEDDING_MODEL") or DEFAULT_MODEL

    if args.search:
        semantic_search(args.search, supabase_url, supabase_key, gemini_key)
        return

    print("=" * 70)
    print("  GEMINI TRANSCRIPT VECTOR EMBEDDER")
    print(f"  Supabase: {supabase_url}")
    print(f"  Model   : {model} ({DIMENSION} dimensions)")
    print(f"  Mode    : {'Re-embed ALL rows' if args.all else 'Embed missing rows only'}")
    print("=" * 70)

    # Check if embedding column exists in Supabase
    if not check_embedding_column(supabase_url, supabase_key):
        print("\n" + "!" * 70)
        print("  [ACTION REQUIRED] The 'embedding' column does not exist in Supabase yet!")
        print("  Please execute the SQL script in your Supabase SQL Editor first:")
        print("  Script path: backend/add_vector_embeddings.sql")
        print("  Supabase SQL Editor: https://supabase.com/dashboard/project/vzxlgygptsdtyiowowfq/sql")
        print("!" * 70 + "\n")
        sys.exit(1)

    print("\nFetching transcripts from Supabase...")
    try:
        rows = fetch_transcripts(supabase_url, supabase_key, embed_all=args.all, session_id=args.session, limit=args.limit)
    except Exception as e:
        print(f"[Error]: {e}")
        sys.exit(1)

    valid_rows = [r for r in rows if r.get("transcript") and r.get("transcript").strip()]
    print(f"Found {len(valid_rows)} transcript(s) to embed.\n")

    if not valid_rows:
        print("All rows already have embeddings, or no transcripts found.")
        return

    success = 0
    failed = 0

    for idx, row in enumerate(valid_rows, 1):
        row_id = row["id"]
        sess = row.get("session_id", "UNKNOWN")
        text = row.get("transcript", "").strip()
        print(f"[{idx}/{len(valid_rows)}] Embedding session '{sess}' (ID: {row_id[:8]}...)")
        print(f"      Text: {text[:65]}...")

        try:
            vector = get_gemini_embedding(text, gemini_key, model=model)
            if not vector or len(vector) != DIMENSION:
                print(f"      [FAILED] Invalid vector (dim={len(vector) if vector else 0})")
                failed += 1
                continue

            update_embedding(supabase_url, supabase_key, row_id, vector)
            print(f"      [SUCCESS] Stored {len(vector)}-dim vector in Supabase.")
            success += 1
        except Exception as err:
            print(f"      [FAILED] {err}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"  Embedding Completed: {success} succeeded, {failed} failed")
    print("=" * 70)

if __name__ == "__main__":
    main()
