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

-- ============================================================================
-- 9. SNS Workbench Speech Transcripts Schema (speech_transcripts)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.speech_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    language_code TEXT DEFAULT 'en',
    ai_response TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_speech_transcripts_session_id 
ON public.speech_transcripts(session_id);

CREATE INDEX IF NOT EXISTS idx_speech_transcripts_created_at 
ON public.speech_transcripts(created_at DESC);

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

GRANT ALL ON TABLE public.speech_transcripts TO anon, authenticated;


