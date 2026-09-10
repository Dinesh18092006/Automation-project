-- ==============================================================================
-- Supabase Vector Embeddings Migration for speech_transcripts Table
-- Model: Google Gemini (gemini-embedding-001 / output_dimensionality: 768)
--
-- Instructions:
-- 1. Open Supabase Dashboard: https://supabase.com/dashboard/project/vzxlgygptsdtyiowowfq/sql
-- 2. Paste this entire script into the SQL Editor and click "Run".
-- ==============================================================================

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Add embedding column to speech_transcripts (768 dimensions for Gemini)
ALTER TABLE public.speech_transcripts 
ADD COLUMN IF NOT EXISTS embedding vector(768);

-- 3. Create HNSW Index for ultra-fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_speech_transcripts_embedding 
ON public.speech_transcripts 
USING hnsw (embedding vector_cosine_ops);

-- 4. Update Row Level Security (RLS) policies to allow updating embedding column
DROP POLICY IF EXISTS "Allow update speech_transcripts" ON public.speech_transcripts;
CREATE POLICY "Allow update speech_transcripts"
ON public.speech_transcripts
FOR UPDATE
TO anon, authenticated
USING (true)
WITH CHECK (true);

-- Ensure anon and authenticated have permissions
GRANT ALL ON TABLE public.speech_transcripts TO anon, authenticated;

-- 5. Helper Function for Semantic Similarity Search
-- Usage: supabase.rpc('match_speech_transcripts', { query_embedding: [...], match_threshold: 0.5, match_count: 5 })
CREATE OR REPLACE FUNCTION public.match_speech_transcripts(
    query_embedding vector(768),
    match_threshold float DEFAULT 0.2,
    match_count int DEFAULT 10
)
RETURNS TABLE (
    id uuid,
    session_id text,
    transcript text,
    language_code text,
    created_at timestamptz,
    audio_file_path text,
    audio_duration_seconds numeric,
    similarity float
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $func$
BEGIN
    RETURN QUERY
    SELECT
        st.id,
        st.session_id,
        st.transcript,
        st.language_code,
        st.created_at,
        st.audio_file_path,
        st.audio_duration_seconds,
        1 - (st.embedding <=> query_embedding) AS similarity
    FROM public.speech_transcripts st
    WHERE st.embedding IS NOT NULL
      AND 1 - (st.embedding <=> query_embedding) > match_threshold
    ORDER BY st.embedding <=> query_embedding
    LIMIT match_count;
END $func$;

GRANT EXECUTE ON FUNCTION public.match_speech_transcripts(vector(768), float, int) TO anon, authenticated;
