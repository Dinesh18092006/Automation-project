/* ============================================================
   Voice Trigger Automation — Frontend Logic
   Architecture:
     1. Poll /trigger/status every 5 s
     2. When active → start Web Speech API (SpeechRecognition)
     3. On final transcript → pre-submit guard → POST /trigger/result
     4. When expired → stop recognition, update UI
   ============================================================ */

'use strict';

// ─────────────────────────────────────────────
// CONFIGURATION
// ─────────────────────────────────────────────
const CONFIG = {
  POLL_MS:       5000,   // Status poll interval
  RETRY_MS:      3000,   // Recognition restart delay after onend
  SPEECH_LANG:  'en-US',
  MAX_LOG_ITEMS: 100,    // Prevent unbounded DOM growth
};

// ─────────────────────────────────────────────
// APPLICATION STATE
// ─────────────────────────────────────────────
const state = {
  active:          false,
  triggerId:       null,
  sessionToken:    null,
  expiresAt:       null,     // Date object (UTC)
  secondsRemaining: 0,
};

let recognition      = null;
let isListening      = false;
let countdownTimer   = null;   // setInterval handle for client-side countdown
let pollTimer        = null;   // setInterval handle for status poll
let restartTimeout   = null;   // setTimeout handle for recognition restart
let logEntryCount    = 0;

// ─────────────────────────────────────────────
// BROWSER SUPPORT CHECK
// ─────────────────────────────────────────────
function checkBrowserSupport() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    document.getElementById('chrome-warning').classList.remove('hidden');
    return false;
  }
  return true;
}

const speechSupported = checkBrowserSupport();

// ─────────────────────────────────────────────
// STATUS POLLING  (Layer 2 expiry: on-read)
// ─────────────────────────────────────────────
async function pollStatus() {
  try {
    const res  = await fetch('/trigger/status');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const wasActive = state.active;

    // Update local state
    state.active           = data.active;
    state.triggerId        = data.trigger_id;
    state.sessionToken     = data.session_token;
    state.expiresAt        = data.expires_at ? new Date(data.expires_at) : null;
    state.secondsRemaining = typeof data.seconds_remaining === 'number'
                             ? data.seconds_remaining : 0;

    // Render UI
    renderStatus(data);

    // Handle state transitions
    if (!wasActive && state.active) {
      // Trigger just became active
      logEntry('✅ Voice session started.', 'system');
      startListening();
    } else if (wasActive && !state.active) {
      // Trigger just expired
      stopListening();
      logEntry('⏰ Session expired. Voice trigger is now inactive.', 'system');
    }

    // Sync countdown from authoritative server value
    if (state.active) {
      syncCountdown(state.secondsRemaining);
    }

    setConnectionStatus(true);

  } catch (err) {
    console.error('[poll] Error:', err);
    setConnectionStatus(false);
  }
}

// ─────────────────────────────────────────────
// UI RENDERING
// ─────────────────────────────────────────────
function renderStatus(data) {
  const label    = document.getElementById('status-label');
  const dot      = document.getElementById('status-dot');
  const ring     = document.getElementById('pulse-ring');
  const meta     = document.getElementById('session-meta');

  if (data.active) {
    label.textContent = 'ACTIVE';
    label.className   = 'status-label active';
    dot.className     = 'status-dot active';
    ring.className    = 'pulse-ring active';
    meta.textContent  = `Session: ${data.trigger_id || '—'}`;
  } else {
    label.textContent = 'INACTIVE';
    label.className   = 'status-label inactive';
    dot.className     = 'status-dot';
    ring.className    = 'pulse-ring';
    meta.textContent  = data.trigger_id
      ? `Last session: ${data.trigger_id}`
      : 'Waiting for trigger…';
    // Reset countdown
    document.getElementById('countdown-display').textContent = '--:--';
    document.getElementById('countdown-display').classList.remove('expiring');
  }

  // Session info table
  document.getElementById('info-trigger-id').textContent = data.trigger_id || '—';
  document.getElementById('info-started').textContent    = data.started_at
    ? formatDateTime(new Date(data.started_at)) : '—';
  document.getElementById('info-expires').textContent    = data.expires_at
    ? formatDateTime(new Date(data.expires_at)) : '—';
  document.getElementById('info-token').textContent      = data.session_token
    ? truncate(data.session_token, 18) : '—';
}

function setConnectionStatus(connected) {
  const el    = document.getElementById('connection-status');
  const label = document.getElementById('connection-label');
  el.className    = `connection-status ${connected ? 'connected' : 'disconnected'}`;
  label.textContent = connected ? 'Connected' : 'Disconnected';
}

function setMicUI(active) {
  const card   = document.getElementById('mic-card');
  const waves  = document.getElementById('mic-waves');
  const status = document.getElementById('mic-status');

  if (active) {
    card.classList.add('active');
    waves.classList.add('active');
    status.textContent = 'Listening…';
  } else {
    card.classList.remove('active');
    waves.classList.remove('active');
    status.textContent = 'Microphone inactive';
  }
}

// ─────────────────────────────────────────────
// COUNTDOWN TIMER (client-side, between polls)
// ─────────────────────────────────────────────
function syncCountdown(seconds) {
  clearInterval(countdownTimer);
  let remaining = Math.max(0, seconds);

  function tick() {
    const el = document.getElementById('countdown-display');
    if (!state.active || remaining <= 0) {
      el.textContent = '--:--';
      el.classList.remove('expiring');
      clearInterval(countdownTimer);
      return;
    }
    const m = String(Math.floor(remaining / 60)).padStart(2, '0');
    const s = String(remaining % 60).padStart(2, '0');
    el.textContent = `${m}:${s}`;
    el.classList.toggle('expiring', remaining <= 60);
    remaining--;
  }

  tick(); // immediate render
  countdownTimer = setInterval(tick, 1000);
}

// ─────────────────────────────────────────────
// SPEECH RECOGNITION
// ─────────────────────────────────────────────
function buildRecognition() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) return null;

  const rec = new SpeechRec();
  rec.continuous      = true;   // Keep listening until we explicitly stop
  rec.interimResults  = false;  // Only process final, committed results
  rec.lang            = CONFIG.SPEECH_LANG;

  rec.onstart = () => {
    isListening = true;
    setMicUI(true);
    console.log('[speech] Recognition started');
  };

  rec.onresult = async (event) => {
    // Iterate over any new final results
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        const transcript = event.results[i][0].transcript.trim();
        if (transcript) {
          await submitTranscript(transcript);
        }
      }
    }
  };

  rec.onend = () => {
    isListening = false;
    console.log('[speech] Recognition ended');

    // Auto-restart if the session is still active
    if (state.active) {
      clearTimeout(restartTimeout);
      restartTimeout = setTimeout(() => {
        if (state.active && recognition) {
          try { recognition.start(); }
          catch (e) { console.warn('[speech] Restart failed:', e); }
        }
      }, CONFIG.RETRY_MS);
    } else {
      setMicUI(false);
    }
  };

  rec.onerror = (event) => {
    const err = event.error;
    console.error('[speech] Error:', err);

    if (err === 'no-speech') {
      // Normal — user paused; recognition will fire onend and restart
      return;
    }
    if (err === 'audio-capture') {
      logEntry('❌ Microphone not found. Check device connection.', 'error');
      stopListening();
    } else if (err === 'not-allowed') {
      logEntry('❌ Microphone permission denied. Allow access in browser settings.', 'error');
      stopListening();
    } else if (err === 'network') {
      logEntry('⚠️ Speech API network error. Will retry.', 'warning');
      // onend will fire and trigger restart
    } else {
      logEntry(`⚠️ Speech error: ${err}`, 'warning');
    }
  };

  return rec;
}

function startListening() {
  if (isListening || !speechSupported) {
    if (!speechSupported) {
      logEntry('❌ Chrome required for speech recognition.', 'error');
    }
    return;
  }

  recognition = buildRecognition();
  if (!recognition) return;

  try {
    recognition.start();
  } catch (e) {
    console.error('[speech] Could not start:', e);
    logEntry('❌ Could not start microphone.', 'error');
  }
}

function stopListening() {
  clearTimeout(restartTimeout);
  if (recognition) {
    try { recognition.stop(); } catch (_) { /* ignore */ }
    recognition = null;
  }
  isListening = false;
  setMicUI(false);
  clearInterval(countdownTimer);
  document.getElementById('countdown-display').textContent = '--:--';
  document.getElementById('countdown-display').classList.remove('expiring');
}

// ─────────────────────────────────────────────
// TRANSCRIPT SUBMISSION
// Layer 4 (client guard) + actual POST
// ─────────────────────────────────────────────
async function submitTranscript(transcript) {
  // ── Layer 4: Pre-submit expiry guard ──
  // Re-check status right before posting to catch last-second expiry
  let guardData;
  try {
    const guardRes = await fetch('/trigger/status');
    guardData       = await guardRes.json();
  } catch (err) {
    logEntry('⚠️ Could not verify session before submission. Transcript held.', 'warning');
    return;
  }

  if (!guardData.active) {
    logEntry('⚠️ Session expired just before submission. Transcript discarded.', 'warning');
    // Sync state so we stop listening
    state.active = false;
    renderStatus(guardData);
    stopListening();
    return;
  }

  // Refresh token in case a new session started since last poll
  state.sessionToken = guardData.session_token;
  state.triggerId    = guardData.trigger_id;

  // ── POST to backend ──
  try {
    const res = await fetch('/trigger/result', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trigger_id:    state.triggerId,
        transcript:    transcript,
        session_token: state.sessionToken,
      }),
    });

    if (res.ok) {
      // Successful submission — log transcript text
      logEntry(transcript, 'transcript');

    } else if (res.status === 403) {
      let detail = 'Session expired or rejected by server.';
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      logEntry(`⚠️ ${detail} Transcript discarded.`, 'warning');
      state.active = false;
      stopListening();
      // Trigger a poll immediately so the UI syncs
      pollStatus();

    } else {
      logEntry(`❌ Server error (HTTP ${res.status}). Transcript not sent.`, 'error');
    }

  } catch (err) {
    console.error('[submit] Network error:', err);
    logEntry('❌ Network error. Could not submit transcript.', 'error');
  }
}

// ─────────────────────────────────────────────
// TRANSCRIPT LOG
// ─────────────────────────────────────────────
function logEntry(text, type = 'transcript') {
  const body  = document.getElementById('log-body');
  const empty = document.getElementById('log-empty');

  // Hide empty state
  if (empty) empty.style.display = 'none';

  // Prune old entries to avoid unbounded DOM growth
  logEntryCount++;
  if (logEntryCount > CONFIG.MAX_LOG_ITEMS) {
    const oldest = body.querySelector('.log-entry');
    if (oldest) oldest.remove();
  }

  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;

  const now     = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  entry.innerHTML = `
    <span class="log-time">${escapeHTML(timeStr)}</span>
    <span class="log-text">${escapeHTML(text)}</span>
  `;

  body.appendChild(entry);
  body.scrollTop = body.scrollHeight;
}

// Exposed to HTML onclick
function clearLog() {
  const body = document.getElementById('log-body');
  body.innerHTML = `
    <div class="log-empty" id="log-empty">
      No transcripts yet.<br />Trigger a voice session to begin.
    </div>
  `;
  logEntryCount = 0;
}

// ─────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────
function formatDateTime(date) {
  if (!(date instanceof Date) || isNaN(date)) return '—';
  return date.toLocaleTimeString([], {
    hour:   '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function truncate(str, len) {
  return str && str.length > len ? str.slice(0, len) + '…' : str;
}

function escapeHTML(str) {
  return String(str)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}

// ─────────────────────────────────────────────
// INITIALISE
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Immediate first poll so the UI reflects current server state fast
  pollStatus();

  // Then poll on the regular interval
  pollTimer = setInterval(pollStatus, CONFIG.POLL_MS);
});
