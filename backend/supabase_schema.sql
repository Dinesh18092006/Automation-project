-- ============================================================================
-- OrgMind / SNS Workbench: Enterprise Memory AI Chat History Schema
-- ============================================================================
-- Execute this script in your Supabase project's SQL Editor:
-- https://supabase.com/dashboard/project/_/sql

-- 1. Create the chat_histories table
CREATE TABLE IF NOT EXISTS public.chat_histories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Indexes for fast retrieval by user and conversation ordered by time
CREATE INDEX IF NOT EXISTS idx_chat_histories_user_conv 
ON public.chat_histories(user_id, conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_chat_histories_created_at 
ON public.chat_histories(created_at DESC);

-- 3. Enable Row Level Security (RLS) to ensure user memory isolation
ALTER TABLE public.chat_histories ENABLE ROW LEVEL SECURITY;

-- 4. RLS Policy: Users can only read their own conversation history
DROP POLICY IF EXISTS "Users can read own chat history" ON public.chat_histories;
CREATE POLICY "Users can read own chat history"
ON public.chat_histories
FOR SELECT
TO authenticated
USING (auth.uid() = user_id);

-- 5. RLS Policy: Users can only insert messages into their own conversation history
DROP POLICY IF EXISTS "Users can insert own chat history" ON public.chat_histories;
CREATE POLICY "Users can insert own chat history"
ON public.chat_histories
FOR INSERT
TO authenticated
WITH CHECK (auth.uid() = user_id);

-- 6. RLS Policy: Users can delete their own conversation history
DROP POLICY IF EXISTS "Users can delete own chat history" ON public.chat_histories;
CREATE POLICY "Users can delete own chat history"
ON public.chat_histories
FOR DELETE
TO authenticated
USING (auth.uid() = user_id);

-- 7. Grant access to authenticated users
GRANT ALL ON TABLE public.chat_histories TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;

-- ============================================================================
-- 8. Voice Recording STT Persistence Schema (voice_transcripts)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.voice_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    duration_seconds INTEGER,
    source TEXT DEFAULT 'voice_pipeline',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_voice_transcripts_trigger_id 
ON public.voice_transcripts(trigger_id);

CREATE INDEX IF NOT EXISTS idx_voice_transcripts_created_at 
ON public.voice_transcripts(created_at DESC);

ALTER TABLE public.voice_transcripts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow insert voice_transcripts" ON public.voice_transcripts;
CREATE POLICY "Allow insert voice_transcripts"
ON public.voice_transcripts
FOR INSERT
TO anon, authenticated
WITH CHECK (true);

DROP POLICY IF EXISTS "Allow select voice_transcripts" ON public.voice_transcripts;
CREATE POLICY "Allow select voice_transcripts"
ON public.voice_transcripts
FOR SELECT
TO anon, authenticated
USING (true);

GRANT ALL ON TABLE public.voice_transcripts TO anon, authenticated;

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 9. SNS Workbench Speech Transcripts Schema (speech_transcripts)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.speech_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    language_code TEXT DEFAULT 'en-IN',
    ai_response TEXT,
    audio_file_path TEXT,
    audio_duration_seconds INTEGER,
    embedding VECTOR(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ensure embedding column exists if table was already created
ALTER TABLE public.speech_transcripts 
ADD COLUMN IF NOT EXISTS embedding VECTOR(768);

CREATE INDEX IF NOT EXISTS idx_speech_transcripts_session_id 
ON public.speech_transcripts(session_id);

CREATE INDEX IF NOT EXISTS idx_speech_transcripts_created_at 
ON public.speech_transcripts(created_at DESC);

-- HNSW Vector Index for ultra-fast semantic similarity search
CREATE INDEX IF NOT EXISTS idx_speech_transcripts_embedding 
ON public.speech_transcripts 
USING hnsw (embedding vector_cosine_ops);

ALTER TABLE public.speech_transcripts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow insert speech_transcripts" ON public.speech_transcripts;
CREATE POLICY "Allow insert speech_transcripts"
ON public.speech_transcripts
FOR INSERT
TO anon, authenticated
WITH CHECK (true);

DROP POLICY IF EXISTS "Allow select speech_transcripts" ON public.speech_transcripts;
CREATE POLICY "Allow select speech_transcripts"
ON public.speech_transcripts
FOR SELECT
TO anon, authenticated
USING (true);

DROP POLICY IF EXISTS "Allow update speech_transcripts" ON public.speech_transcripts;
CREATE POLICY "Allow update speech_transcripts"
ON public.speech_transcripts
FOR UPDATE
TO anon, authenticated
USING (true)
WITH CHECK (true);

GRANT ALL ON TABLE public.speech_transcripts TO anon, authenticated;

-- Helper Function for Semantic Similarity Search
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


