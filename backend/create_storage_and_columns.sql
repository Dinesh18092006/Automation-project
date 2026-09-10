-- ============================================================================
-- Supabase Storage: voice-recordings Bucket & Policies (TASK 1)
-- & speech_transcripts Schema Update (TASK 2)
-- ============================================================================
-- Run this in your Supabase SQL Editor:
-- https://supabase.com/dashboard/project/vzxlgygptsdtyiowowfq/sql

-- ----------------------------------------------------------------------------
-- 1. Create the private Storage Bucket 'voice-recordings'
-- ----------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'voice-recordings',
    'voice-recordings',
    false, -- Private bucket: access via signed URLs only
    26214400, -- 25 MB in bytes
    ARRAY[
        'audio/mpeg',
        'audio/mp3',
        'audio/wav',
        'audio/x-wav',
        'audio/webm',
        'audio/ogg',
        'audio/m4a',
        'audio/x-m4a',
        'audio/mp4'
    ]
)
ON CONFLICT (id) DO UPDATE SET
    public = false,
    file_size_limit = 26214400,
    allowed_mime_types = ARRAY[
        'audio/mpeg',
        'audio/mp3',
        'audio/wav',
        'audio/x-wav',
        'audio/webm',
        'audio/ogg',
        'audio/m4a',
        'audio/x-m4a',
        'audio/mp4'
    ];

-- ----------------------------------------------------------------------------
-- 2. Storage RLS Policies for 'voice-recordings' bucket
-- ----------------------------------------------------------------------------
-- Allow anon & authenticated users to upload audio files
DROP POLICY IF EXISTS "Allow upload to voice-recordings" ON storage.objects;
CREATE POLICY "Allow upload to voice-recordings"
ON storage.objects
FOR INSERT
TO anon, authenticated
WITH CHECK (bucket_id = 'voice-recordings');

-- Allow anon & authenticated users to read/download audio files (e.g. for generating signed URLs)
DROP POLICY IF EXISTS "Allow read voice-recordings" ON storage.objects;
CREATE POLICY "Allow read voice-recordings"
ON storage.objects
FOR SELECT
TO anon, authenticated
USING (bucket_id = 'voice-recordings');

-- ----------------------------------------------------------------------------
-- 3. Update speech_transcripts Table Schema (TASK 2)
-- ----------------------------------------------------------------------------
ALTER TABLE public.speech_transcripts 
ADD COLUMN IF NOT EXISTS audio_file_path TEXT,
ADD COLUMN IF NOT EXISTS audio_duration_seconds NUMERIC;

-- Policy to allow updates (e.g. linking audio_file_path to existing transcript row)
DROP POLICY IF EXISTS "Allow update speech_transcripts" ON public.speech_transcripts;
CREATE POLICY "Allow update speech_transcripts"
ON public.speech_transcripts
FOR UPDATE
TO anon, authenticated
USING (true)
WITH CHECK (true);
