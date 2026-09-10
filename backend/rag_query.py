"""
RAG Query CLI Tool
Performs Retrieval-Augmented Generation (RAG) using:
  - Vector Embedding: Google Gemini (models/gemini-embedding-001)
  - Vector Search: Supabase pgvector cosine similarity
  - Answer Synthesis: Google Gemini 3.1 Flash Lite (models/gemini-3.1-flash-lite)

Usage:
    python rag_query.py "What did the speaker say about Render?"
    python rag_query.py --interactive
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
DEFAULT_EMBED_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
DEFAULT_GEN_MODEL = os.getenv("GEMINI_GENERATION_MODEL", "models/gemini-3.1-flash-lite")
DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "768"))

def get_embedding(text: str, api_key: str, model: str = DEFAULT_EMBED_MODEL) -> list:
    """Generate 768-dim embedding vector."""
    clean_model = model.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:embedContent?key={api_key}"
    payload = {
        "output_dimensionality": DIMENSION,
        "content": {"parts": [{"text": text.strip()}]}
    }
    with httpx.Client(timeout=12.0) as client:
        resp = client.post(url, json=payload)
        if resp.status_code == 200:
            return resp.json().get("embedding", {}).get("values")
        raise RuntimeError(f"Embedding error ({resp.status_code}): {resp.text}")

def retrieve_transcripts(query: str, query_vector: list, supabase_url: str, supabase_key: str, top_k: int = 5) -> list:
    """Retrieve relevant transcripts via Supabase RPC or fallback."""
    base_url = supabase_url.rstrip("/")
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    # 1. Try vector RPC
    if query_vector:
        try:
            with httpx.Client(timeout=10.0) as client:
                rpc_resp = client.post(
                    f"{base_url}/rest/v1/rpc/match_speech_transcripts",
                    headers=headers,
                    json={
                        "query_embedding": query_vector,
                        "match_threshold": 0.15,
                        "match_count": top_k
                    }
                )
                if rpc_resp.status_code == 200:
                    matches = rpc_resp.json()
                    if matches:
                        return matches
        except Exception:
            pass

    # 2. Fallback: Recent records
    with httpx.Client(timeout=10.0) as client:
        fb_resp = client.get(
            f"{base_url}/rest/v1/speech_transcripts",
            headers=headers,
            params={"select": "id,session_id,transcript,created_at", "order": "created_at.desc", "limit": str(top_k)}
        )
        if fb_resp.status_code == 200:
            return fb_resp.json()
    return []

def generate_answer(query: str, chunks: list, api_key: str, model: str = DEFAULT_GEN_MODEL) -> str:
    """Generate grounded answer using Gemini 3.1 Flash Lite with retries."""
    import time
    clean_model = model.replace("models/", "")
    models_to_try = [clean_model, "gemini-3.1-flash-lite", "gemini-2.5-flash"]
    # De-duplicate while preserving order
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    context_lines = []
    for idx, c in enumerate(chunks, 1):
        sess = c.get("session_id") or "UNKNOWN"
        time_str = c.get("created_at") or ""
        sim = c.get("similarity")
        relevance = f" (relevance: {round(sim*100, 1)}%)" if sim is not None else ""
        text = c.get("transcript") or ""
        context_lines.append(f"[{idx}] Session: {sess}{relevance} | Date: {time_str}\n\"{text}\"")

    context_block = "\n\n".join(context_lines) if context_lines else "(No relevant voice recordings found)"

    prompt = (
        "You are an expert AI assistant answering questions grounded in audio transcripts.\n"
        "Use ONLY the following context transcripts to formulate a factual, clear answer.\n"
        "If quoting or summarizing a specific point, cite the Session ID.\n"
        "If the transcripts do not contain the answer, say so honestly.\n\n"
        f"--- CONTEXT TRANSCRIPTS ---\n{context_block}\n\n"
        f"--- USER QUESTION ---\n{query}\n\n"
        "--- ANSWER ---"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800}
    }

    last_err = None
    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        for attempt in range(2):
            try:
                with httpx.Client(timeout=25.0) as client:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
                        return "No text produced."
                    elif resp.status_code == 503:
                        time.sleep(1.5)
                        continue
                    else:
                        last_err = f"API Error {resp.status_code}: {resp.text}"
            except Exception as ex:
                last_err = str(ex)
                time.sleep(1.0)
    raise RuntimeError(last_err or "Generation failed after retries")

def ask(query: str, supabase_url: str, supabase_key: str, gemini_key: str, gen_model: str):
    print(f"\n[Question]: {query}")
    print("[1/3] Generating vector embedding...")
    try:
        vec = get_embedding(query, gemini_key)
    except Exception as e:
        print(f"Embedding error: {e}")
        vec = None

    print("[2/3] Retrieving matching transcripts from Supabase...")
    chunks = retrieve_transcripts(query, vec, supabase_url, supabase_key)
    print(f"      Found {len(chunks)} source chunk(s)")

    print(f"[3/3] Generating answer with {gen_model}...")
    try:
        ans = generate_answer(query, chunks, gemini_key, model=gen_model)
    except Exception as e:
        print(f"Generation error: {e}")
        return

    print("\n" + "=" * 70)
    print("  GEMINI 3.1 FLASH LITE - RAG ANSWER")
    print("=" * 70)
    print(ans)
    print("\n" + "-" * 70)
    print("Sources referenced:")
    for i, c in enumerate(chunks, 1):
        sim = c.get("similarity")
        score_str = f" [relevance: {round(sim*100, 1)}%]" if sim is not None else ""
        print(f"  {i}. Session: {c.get('session_id')}{score_str} - {c.get('transcript', '')[:70]}...")
    print("=" * 70 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Ask questions about your speech transcripts using RAG")
    parser.add_argument("query", nargs="?", help="The question to ask")
    parser.add_argument("--interactive", "-i", action="store_true", help="Start interactive Q&A mode")
    args = parser.parse_args()

    load_env()
    supabase_url = os.getenv("SUPABASE_URL") or DEFAULT_SUPABASE_URL
    supabase_key = os.getenv("SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY
    gemini_key = os.getenv("GEMINI_API_KEY") or DEFAULT_GEMINI_KEY
    gen_model = os.getenv("GEMINI_GENERATION_MODEL") or DEFAULT_GEN_MODEL

    if args.interactive:
        print("=" * 70)
        print("  GEMINI 3.1 FLASH LITE - INTERACTIVE RAG CHAT")
        print(f"  Connected to Supabase: {supabase_url}")
        print("  Type your question and press Enter. Type 'exit' or 'quit' to end.")
        print("=" * 70)
        while True:
            try:
                q = input("\nYou > ").strip()
                if not q:
                    continue
                if q.lower() in ("exit", "quit", "q"):
                    break
                ask(q, supabase_url, supabase_key, gemini_key, gen_model)
            except (KeyboardInterrupt, EOFError):
                break
        return

    if not args.query:
        parser.print_help()
        sys.exit(0)

    ask(args.query, supabase_url, supabase_key, gemini_key, gen_model)

if __name__ == "__main__":
    main()
