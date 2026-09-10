-- ============================================================================
-- Voice Trigger Automation: Speech-to-Text Transcripts Schema
-- ============================================================================
-- Execute this script in your Supabase project's SQL Editor:
-- https://supabase.com/dashboard/project/_/sql

-- 1. Create the speech_transcripts table
CREATE TABLE IF NOT EXISTS public.speech_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    language_code TEXT DEFAULT 'en-IN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Indexes for fast lookups by session_id and created_at
CREATE INDEX IF NOT EXISTS idx_speech_transcripts_session_id 
ON public.speech_transcripts(session_id);

CREATE INDEX IF NOT EXISTS idx_speech_transcripts_created_at 
ON public.speech_transcripts(created_at DESC);

-- Composite index for fast session-ordered queries
CREATE INDEX IF NOT EXISTS idx_speech_transcripts_session_created 
ON public.speech_transcripts(session_id, created_at DESC);

-- 3. Enable Row Level Security (RLS)
ALTER TABLE public.speech_transcripts ENABLE ROW LEVEL SECURITY;

-- 4. RLS Policy: Allow insert from anon and authenticated roles
DROP POLICY IF EXISTS "Allow insert speech_transcripts" ON public.speech_transcripts;
CREATE POLICY "Allow insert speech_transcripts"
ON public.speech_transcripts
FOR INSERT
TO anon, authenticated
WITH CHECK (true);

-- 5. RLS Policy: Allow select from anon and authenticated roles
DROP POLICY IF EXISTS "Allow select speech_transcripts" ON public.speech_transcripts;
CREATE POLICY "Allow select speech_transcripts"
ON public.speech_transcripts
FOR SELECT
TO anon, authenticated
USING (true);

-- 6. Grant permissions
GRANT ALL ON TABLE public.speech_transcripts TO anon, authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
