// ==========================================================================
// Voice Trigger Automation — Dashboard Application Logic
// ==========================================================================

// Determine backend API URL dynamically based on environment
function detectDefaultApiUrl() {
  if (typeof window === "undefined") return "http://localhost:8000";
  // If page loaded over HTTPS or remote domain, always use current origin to prevent mixed content blocking
  if (window.location.protocol === "https:" || !["localhost", "127.0.0.1"].includes(window.location.hostname)) {
    return window.location.origin;
  }
  if (window.location.port === "8000") {
    return window.location.origin;
  }
  return "http://localhost:8000";
}

let currentApiUrl = detectDefaultApiUrl();
const POLL_INTERVAL_MS = 2500;
const TICK_INTERVAL_MS = 200; // Fast ticker for smooth countdown and expiration

// Global Application State
let pollIntervalId = null;
let tickIntervalId = null;
let isMonitoring = true; // Auto-monitor enabled by default
let sessionState = "IDLE"; // IDLE, ACTIVE, COMPLETED, EXPIRED, ERROR
let currentTriggerId = null;
let sessionExpiresAt = null; // Date object
let transcriptSubmitted = false;
let websocketClient = null;
let wsReconnectTimer = null;

// Audio & Speech Recognition State
let mediaStream = null;
let recognition = null;
let isRecognizing = false;
let micPermissionGranted = null; // null = pending, true = granted, false = denied
let accumulatedFinalTranscript = "";
let currentInterimTranscript = "";

// Webhook & Backend Data Store Configuration
const DEFAULT_WEBHOOK_URL = "https://api.agents.snsihub.ai/webhook/memora-chat";
let sttWebhookUrl =
  (window.ENV && window.ENV.AI_WORKFLOW_WEBHOOK_URL) ||
  localStorage.getItem("vta_webhook_url") ||
  DEFAULT_WEBHOOK_URL;

let supabaseUrl =
  (window.ENV && window.ENV.SUPABASE_URL) ||
  localStorage.getItem("vta_supabase_url") ||
  "https://vzxlgygptsdtyiowowfq.supabase.co";

let supabaseAnonKey =
  (window.ENV && window.ENV.SUPABASE_ANON_KEY) ||
  localStorage.getItem("vta_supabase_anon_key") ||
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6eGxneWdwdHNkdHlpb3dvd2ZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNDcyNDQsImV4cCI6MjEwMzgyMzI0NH0.pLgvSOj18ZPbcq6BNSPeQSMMx36HuWrjI_ycyg_J8ec";

let supabaseClient = null;
let activeAuthUser = null;

// DOM Elements
let apiUrlSelect, customApiUrl, monitoringToggleBtn, monitoringToggleLabel;
let authBtn, authBtnLabel, signOutBtn, configModalBtn;
let monitoringBanner, monitoringBannerText, micPermissionStatus, lastEventTime;
let backendStatusPill, backendStatusLabel, backendEndpointBox;
let sessionStatusBadge, triggerStatePill, triggerStateLabel;
let countdownDisplay, noActiveSessionPlaceholder, activeSessionDetails, activeSessionId, activeSessionExpires, quickStartTimerBtn;
let wordCountBadge, copyTranscriptBtn, transcriptBox, transcriptPlaceholder, transcriptFinal, transcriptInterim;
let test10sBtn, test30sBtn, test1mBtn, testResetBtn;
let authModal, closeAuthModalBtn, tabSignIn, tabSignUp, authForm, authModalAlert, authEmail, authPassword, authSubmitBtn;
let configModal, closeConfigModalBtn, configForm, configModalAlert, cfgWebhookUrl, cfgSupabaseUrl, cfgSupabaseKey, resetConfigBtn, saveConfigBtn;
let historyHeaderToggle, historyBody, toggleHistoryBtn, toggleHistoryIcon, refreshHistoryBtn, historyCountBadge, historyLoading, historyEmpty, historyList;
let audioFileInput, uploadAudioBtn, audioUploadStatus, audioUploadText;
let mediaRecorder = null;
let recordedAudioChunks = [];
let currentSessionAudioPath = null;
let currentSessionAudioDuration = null;
let recordingStartTime = null;

function cacheElements() {
  apiUrlSelect = document.getElementById("apiUrlSelect");
  customApiUrl = document.getElementById("customApiUrl");
  monitoringToggleBtn = document.getElementById("monitoringToggleBtn");
  monitoringToggleLabel = document.getElementById("monitoringToggleLabel");

  authBtn = document.getElementById("authBtn");
  authBtnLabel = document.getElementById("authBtnLabel");
  signOutBtn = document.getElementById("signOutBtn");
  configModalBtn = document.getElementById("configModalBtn");

  monitoringBanner = document.getElementById("monitoringBanner");
  monitoringBannerText = document.getElementById("monitoringBannerText");
  micPermissionStatus = document.getElementById("micPermissionStatus");
  lastEventTime = document.getElementById("lastEventTime");

  backendStatusPill = document.getElementById("backendStatusPill");
  backendStatusLabel = document.getElementById("backendStatusLabel");
  backendEndpointBox = document.getElementById("backendEndpointBox");

  sessionStatusBadge = document.getElementById("sessionStatusBadge");
  triggerStatePill = document.getElementById("triggerStatePill");
  triggerStateLabel = document.getElementById("triggerStateLabel");

  countdownDisplay = document.getElementById("countdownDisplay");
  noActiveSessionPlaceholder = document.getElementById("noActiveSessionPlaceholder");
  quickStartTimerBtn = document.getElementById("quickStartTimerBtn");
  activeSessionDetails = document.getElementById("activeSessionDetails");
  activeSessionId = document.getElementById("activeSessionId");
  activeSessionExpires = document.getElementById("activeSessionExpires");

  wordCountBadge = document.getElementById("wordCountBadge");
  copyTranscriptBtn = document.getElementById("copyTranscriptBtn");
  transcriptBox = document.getElementById("transcriptBox");
  transcriptPlaceholder = document.getElementById("transcriptPlaceholder");
  transcriptFinal = document.getElementById("transcriptFinal");
  transcriptInterim = document.getElementById("transcriptInterim");

  test10sBtn = document.getElementById("test10sBtn");
  test30sBtn = document.getElementById("test30sBtn");
  test1mBtn = document.getElementById("test1mBtn");
  testResetBtn = document.getElementById("testResetBtn");

  authModal = document.getElementById("authModal");
  closeAuthModalBtn = document.getElementById("closeAuthModalBtn");
  tabSignIn = document.getElementById("tabSignIn");
  tabSignUp = document.getElementById("tabSignUp");
  authForm = document.getElementById("authForm");
  authModalAlert = document.getElementById("authModalAlert");
  authEmail = document.getElementById("authEmail");
  authPassword = document.getElementById("authPassword");
  authSubmitBtn = document.getElementById("authSubmitBtn");

  configModal = document.getElementById("configModal");
  closeConfigModalBtn = document.getElementById("closeConfigModalBtn");
  configForm = document.getElementById("configForm");
  configModalAlert = document.getElementById("configModalAlert");
  cfgWebhookUrl = document.getElementById("cfgWebhookUrl");
  cfgSupabaseUrl = document.getElementById("cfgSupabaseUrl");
  cfgSupabaseKey = document.getElementById("cfgSupabaseKey");
  resetConfigBtn = document.getElementById("resetConfigBtn");
  saveConfigBtn = document.getElementById("saveConfigBtn");

  historyHeaderToggle = document.getElementById("historyHeaderToggle");
  historyBody = document.getElementById("historyBody");
  toggleHistoryBtn = document.getElementById("toggleHistoryBtn");
  toggleHistoryIcon = document.getElementById("toggleHistoryIcon");
  refreshHistoryBtn = document.getElementById("refreshHistoryBtn");
  historyCountBadge = document.getElementById("historyCountBadge");
  historyLoading = document.getElementById("historyLoading");
  historyEmpty = document.getElementById("historyEmpty");
  historyList = document.getElementById("historyList");

  audioFileInput = document.getElementById("audioFileInput");
  uploadAudioBtn = document.getElementById("uploadAudioBtn");
  audioUploadStatus = document.getElementById("audioUploadStatus");
  audioUploadText = document.getElementById("audioUploadText");
}

// --------------------------------------------------------------------------
// UI State Formatters & Updaters
// --------------------------------------------------------------------------
function formatTimestamp(isoString) {
  if (!isoString) return "-";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return isoString;
  }
}

function updateEventTime(label = null) {
  if (!lastEventTime) return;
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  lastEventTime.textContent = label ? `${label}: ${time}` : `Last sync: ${time}`;
}

function setBannerState(state, message) {
  if (!monitoringBanner || !monitoringBannerText) return;
  monitoringBanner.className = "status-banner";
  if (state === "active") {
    monitoringBanner.classList.add("banner-active");
  } else if (state === "error") {
    monitoringBanner.classList.add("banner-error");
  } else if (state === "paused") {
    monitoringBanner.classList.add("banner-paused");
  }
  monitoringBannerText.textContent = message;
}

function updateBackendConnectionUI(isOnline) {
  if (!backendStatusPill || !backendStatusLabel) return;
  if (isOnline) {
    backendStatusPill.className = "status-pill status-connected";
    backendStatusLabel.textContent = "Online";
  } else {
    backendStatusPill.className = "status-pill status-offline";
    backendStatusLabel.textContent = "Offline";
  }
  if (backendEndpointBox) {
    backendEndpointBox.textContent = `GET ${currentApiUrl}/trigger/status`;
  }
}

function updateSessionStatusUI(state, triggerActive = false) {
  if (!sessionStatusBadge || !triggerStatePill || !triggerStateLabel) return;

  sessionStatusBadge.textContent = state;
  if (state === "ACTIVE") {
    sessionStatusBadge.className = "status-badge badge-active";
    triggerStatePill.className = "status-pill status-connected";
    triggerStateLabel.textContent = "Trigger Active";
  } else {
    sessionStatusBadge.className = "status-badge badge-idle";
    triggerStatePill.className = "status-pill status-neutral";
    triggerStateLabel.textContent = "Trigger Inactive";
  }
}

function updateMicPermissionUI(state) {
  if (!micPermissionStatus) return;
  if (state === "granted") {
    micPermissionStatus.className = "chip chip-granted";
    micPermissionStatus.textContent = "Mic: Permission Granted";
  } else if (state === "denied") {
    micPermissionStatus.className = "chip chip-denied";
    micPermissionStatus.textContent = "Mic: Permission Denied";
  } else {
    micPermissionStatus.className = "chip chip-neutral";
    micPermissionStatus.textContent = "Mic: Pending Permission";
  }
}

function updateCountdownDigits(remainingSeconds) {
  if (!countdownDisplay) return;
  const secs = Math.max(0, Math.floor(remainingSeconds));
  const m = Math.floor(secs / 60).toString().padStart(2, "0");
  const s = (secs % 60).toString().padStart(2, "0");
  countdownDisplay.textContent = `${m}:${s}`;

  if (sessionState === "ACTIVE" && secs > 0) {
    countdownDisplay.classList.add("active");
  } else {
    countdownDisplay.classList.remove("active");
  }
}

function updateWordCount() {
  if (!wordCountBadge) return;
  const fullText = (accumulatedFinalTranscript + " " + currentInterimTranscript).trim();
  const words = fullText ? fullText.split(/\s+/).filter(Boolean) : [];
  wordCountBadge.textContent = `${words.length} ${words.length === 1 ? "word" : "words"}`;
}

function renderTranscript() {
  if (!transcriptBox) return;
  const hasText = Boolean(accumulatedFinalTranscript || currentInterimTranscript);

  if (hasText) {
    if (transcriptPlaceholder) transcriptPlaceholder.classList.add("hidden");
    if (transcriptFinal) transcriptFinal.textContent = accumulatedFinalTranscript;
    if (transcriptInterim) transcriptInterim.textContent = currentInterimTranscript ? " " + currentInterimTranscript : "";
  } else {
    if (transcriptPlaceholder) transcriptPlaceholder.classList.remove("hidden");
    if (transcriptFinal) transcriptFinal.textContent = "";
    if (transcriptInterim) transcriptInterim.textContent = "";
  }

  if (sessionState === "ACTIVE" && isRecognizing) {
    transcriptBox.classList.add("active-listening");
  } else {
    transcriptBox.classList.remove("active-listening");
  }

  updateWordCount();
  transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

// --------------------------------------------------------------------------
// Microphone & Speech Recognition Engine
// --------------------------------------------------------------------------
async function ensureMicrophonePermission() {
  if (micPermissionGranted === true && mediaStream) return true;
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    micPermissionGranted = true;
    updateMicPermissionUI("granted");
    return true;
  } catch (err) {
    micPermissionGranted = false;
    updateMicPermissionUI("denied");
    console.warn("Microphone access denied:", err.message);
    return false;
  }
}

function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn("SpeechRecognition not supported in this browser.");
    return null;
  }

  const rec = new SpeechRecognition();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "en-IN";

  rec.onstart = () => {
    isRecognizing = true;
    renderTranscript();
  };

  rec.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const res = event.results[i];
      const text = res[0].transcript;
      if (res.isFinal) {
        accumulatedFinalTranscript = (accumulatedFinalTranscript ? accumulatedFinalTranscript + " " : "") + text.trim();
        dispatchPartialTranscriptToWebhook(accumulatedFinalTranscript);
      } else {
        interim += text;
      }
    }
    currentInterimTranscript = interim.trim();
    renderTranscript();
  };

  rec.onerror = (event) => {
    console.warn("Speech recognition error:", event.error);
    if (event.error === "not-allowed") {
      micPermissionGranted = false;
      updateMicPermissionUI("denied");
    }
  };

  rec.onend = () => {
    isRecognizing = false;
    // Auto-restart if session is still active
    if (sessionState === "ACTIVE" && isMonitoring) {
      try {
        rec.start();
      } catch (_) {}
    } else {
      renderTranscript();
    }
  };

  return rec;
}

async function startListening() {
  const granted = await ensureMicrophonePermission();
  if (!granted) return;

  // 1. Start SpeechRecognition
  if (!recognition) {
    recognition = initSpeechRecognition();
  }

  if (recognition && !isRecognizing) {
    try {
      recognition.start();
    } catch (err) {
      if (err.name !== "InvalidStateError") {
        console.warn("Recognition start warning:", err);
      }
    }
  }

  // 2. Start MediaRecorder for Raw Audio Capture
  try {
    if (window.MediaRecorder && mediaStream) {
      recordedAudioChunks = [];
      const options = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? { mimeType: "audio/webm;codecs=opus" }
        : (MediaRecorder.isTypeSupported("audio/webm") ? { mimeType: "audio/webm" } : {});

      mediaRecorder = new MediaRecorder(mediaStream, options);
      recordingStartTime = Date.now();

      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          recordedAudioChunks.push(e.data);
        }
      };

      mediaRecorder.onstop = async () => {
        if (recordedAudioChunks.length > 0 && currentTriggerId) {
          const mimeType = mediaRecorder.mimeType || "audio/webm";
          const audioBlob = new Blob(recordedAudioChunks, { type: mimeType });
          const durationSec = recordingStartTime ? Math.round((Date.now() - recordingStartTime) / 1000) : null;
          await uploadRecordedAudioToSupabase(currentTriggerId, audioBlob, durationSec);
        }
      };

      mediaRecorder.start(1000); // Collect in 1s chunks
    }
  } catch (recErr) {
    console.warn("MediaRecorder start warning:", recErr);
  }
}

function stopListening() {
  if (recognition && isRecognizing) {
    try {
      recognition.stop();
    } catch (err) {
      console.warn("Recognition stop error:", err);
    }
  }
  isRecognizing = false;

  // Stop MediaRecorder if running
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    try {
      mediaRecorder.stop();
    } catch (mErr) {
      console.warn("MediaRecorder stop error:", mErr);
    }
  }

  renderTranscript();
}

// --------------------------------------------------------------------------
// Real-Time WebSocket Connection (/trigger/ws)
// --------------------------------------------------------------------------
function initWebSocket() {
  if (!currentApiUrl) return;
  if (websocketClient) {
    try { websocketClient.close(); } catch (_) {}
    websocketClient = null;
  }

  const cleanUrl = currentApiUrl.replace(/\/+$/, "");
  const wsProtocol = cleanUrl.startsWith("https") ? "wss:" : "ws:";
  const host = cleanUrl.replace(/^https?:\/\//, "");
  const wsUrl = `${wsProtocol}//${host}/trigger/ws`;

  try {
    websocketClient = new WebSocket(wsUrl);

    websocketClient.onopen = () => {
      updateEventTime("WS connected");
    };

    websocketClient.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === "TRIGGER_STARTED") {
          activateSession(msg);
        } else if (msg.event === "TRIGGER_RESET" || msg.event === "TRIGGER_COMPLETED") {
          pollBackendStatus();
        }
      } catch (e) {
        console.warn("WS message parse error:", e);
      }
    };

    websocketClient.onclose = () => {
      websocketClient = null;
      if (isMonitoring) {
        if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
        wsReconnectTimer = setTimeout(initWebSocket, 5000);
      }
    };

    websocketClient.onerror = () => {
      // Polling handles fallback gracefully
    };
  } catch (err) {
    console.warn("WebSocket init error:", err);
  }
}

// --------------------------------------------------------------------------
// Polling Backend Status (GET /trigger/status)
// --------------------------------------------------------------------------
async function pollBackendStatus() {
  if (!isMonitoring) return;

  const url = `${currentApiUrl}/trigger/status`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 4000);

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { "Accept": "application/json" },
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    updateBackendConnectionUI(true);
    setBannerState("active", "Monitoring Active • Auto-polling & WebSocket stream live");
    updateEventTime();

    // Evaluate Transition to ACTIVE
    if (data.active && data.trigger_id) {
      if (sessionState === "ACTIVE" && data.remaining_seconds != null) {
        const expectedExpires = new Date(Date.now() + data.remaining_seconds * 1000);
        if (!sessionExpiresAt || Math.abs(sessionExpiresAt.getTime() - expectedExpires.getTime()) > 2000) {
          sessionExpiresAt = expectedExpires;
        }
      }
      await activateSession(data);
    } else {
      // If was active, handle completion
      if (sessionState === "ACTIVE") {
        sessionState = data.status || "IDLE";
        stopListening();
        if (!transcriptSubmitted && currentTriggerId) {
          submitFinalTranscript(currentTriggerId);
        }
      }

      updateSessionStatusUI(data.status || "IDLE", false);

      if (data.status === "COMPLETED" || data.status === "EXPIRED") {
        updateCountdownDigits(0);
        if (data.transcript && !accumulatedFinalTranscript) {
          accumulatedFinalTranscript = data.transcript;
          renderTranscript();
        }
      } else if (data.status === "IDLE") {
        currentTriggerId = null;
        sessionExpiresAt = null;
        updateCountdownDigits(0);
        if (noActiveSessionPlaceholder) noActiveSessionPlaceholder.classList.remove("hidden");
        if (activeSessionDetails) activeSessionDetails.classList.add("hidden");
      }
    }
  } catch (error) {
    // If request failed and we are on HTTPS or remote host but currentApiUrl is still localhost, auto-switch to window.location.origin and retry
    if (window.location.protocol === "https:" && currentApiUrl !== window.location.origin) {
      console.warn(`[API Fallback] ${currentApiUrl} unreachable over HTTPS (${error.message}). Auto-switching to ${window.location.origin}`);
      currentApiUrl = window.location.origin;
      if (apiUrlSelect) apiUrlSelect.value = currentApiUrl;
      if (backendEndpointBox) backendEndpointBox.textContent = `GET ${currentApiUrl}/trigger/status`;
      initWebSocket();
      setTimeout(pollBackendStatus, 500);
      return;
    }

    updateBackendConnectionUI(false);
    setBannerState("error", `Monitoring Error • Unable to reach backend (${error.name === "AbortError" ? "Timeout" : error.message})`);
    updateEventTime("Offline");
  }
}

// --------------------------------------------------------------------------
// Session Activation & Countdown Ticker
// --------------------------------------------------------------------------
async function activateSession(data) {
  const isNewActive = (sessionState !== "ACTIVE" || currentTriggerId !== data.trigger_id);
  if (!isNewActive) return;

  currentTriggerId = data.trigger_id;
  sessionState = "ACTIVE";
  transcriptSubmitted = false;

  // Clear previous session transcript for new incoming trigger session
  accumulatedFinalTranscript = "";
  currentInterimTranscript = "";
  renderTranscript();

  if (data.remaining_seconds != null && data.remaining_seconds > 0) {
    sessionExpiresAt = new Date(Date.now() + data.remaining_seconds * 1000);
  } else if (data.expires_at) {
    sessionExpiresAt = new Date(data.expires_at);
  } else {
    sessionExpiresAt = new Date(Date.now() + 60000);
  }

  updateSessionStatusUI("ACTIVE", true);

  if (noActiveSessionPlaceholder) noActiveSessionPlaceholder.classList.add("hidden");
  if (activeSessionDetails) {
    activeSessionDetails.classList.remove("hidden");
    if (activeSessionId) activeSessionId.textContent = data.trigger_id || "-";
    if (activeSessionExpires) activeSessionExpires.textContent = formatTimestamp(data.expires_at || sessionExpiresAt.toISOString());
  }

  updateEventTime(`Trigger '${data.trigger_id}' started`);

  // Start speech capture immediately
  await startListening();
}

function startTickTimer() {
  if (tickIntervalId !== null) clearInterval(tickIntervalId);
  tickIntervalId = setInterval(() => {
    if (sessionState === "ACTIVE" && sessionExpiresAt) {
      const remainingMs = sessionExpiresAt.getTime() - Date.now();
      const remainingSec = Math.max(0, remainingMs / 1000);
      updateCountdownDigits(remainingSec);

      if (remainingSec <= 0) {
        // Session expired
        sessionState = "EXPIRED";
        updateSessionStatusUI("EXPIRED", false);
        stopListening();
        if (!transcriptSubmitted && currentTriggerId) {
          submitFinalTranscript(currentTriggerId);
        }
      }
    }
  }, TICK_INTERVAL_MS);
}

// --------------------------------------------------------------------------
// Transcript Dispatch & Backend Sync
// --------------------------------------------------------------------------
async function submitFinalTranscript(triggerId) {
  transcriptSubmitted = true;
  const fullText = (accumulatedFinalTranscript + " " + currentInterimTranscript).trim();

  try {
    const payload = {
      trigger_id: triggerId,
      transcript: fullText,
      language_code: "en-IN",
    };

    // 1. Send to Local Backend
    await fetch(`${currentApiUrl}/trigger/transcript`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    // 2. Dispatch to STT Webhook / Data Store
    dispatchPartialTranscriptToWebhook(fullText, true);

    // 3. Task 3: Redundant / Fallback Client-side Save to Supabase speech_transcripts
    saveTranscriptToSupabaseFallback(triggerId, fullText, "en-IN", currentSessionAudioPath, currentSessionAudioDuration);

    updateEventTime(`Transcript submitted (${triggerId})`);
  } catch (err) {
    console.warn("Failed to submit transcript:", err);
  }
}

// --------------------------------------------------------------------------
// Supabase Audio Storage Uploads (Task 3)
// --------------------------------------------------------------------------
function updateUploadProgress(show, text = "") {
  if (!audioUploadStatus || !audioUploadText) return;
  if (show) {
    audioUploadStatus.classList.remove("hidden");
    audioUploadText.textContent = text;
  } else {
    audioUploadStatus.classList.add("hidden");
  }
}

async function uploadAudioBlobToStorage(sessionId, audioBlob, extension = "webm", mimeType = "audio/webm") {
  if (!sessionId || !audioBlob) return null;

  // Max 25 MB validation (26,214,400 bytes)
  const MAX_SIZE = 25 * 1024 * 1024;
  if (audioBlob.size > MAX_SIZE) {
    alert("Audio file exceeds the maximum 25MB limit.");
    return null;
  }

  const timestamp = Date.now();
  const filePath = `${sessionId}/${timestamp}.${extension}`;
  updateUploadProgress(true, "Uploading audio...");

  try {
    // 1. Try Supabase Client
    if (supabaseClient) {
      const { data, error } = await supabaseClient.storage
        .from("voice-recordings")
        .upload(filePath, audioBlob, {
          contentType: mimeType,
          upsert: true
        });

      if (error) {
        console.warn("[Supabase Storage Upload Error]:", error.message);
        updateUploadProgress(false);
        return null;
      }
      updateUploadProgress(true, "Audio stored!");
      setTimeout(() => updateUploadProgress(false), 2000);
      return filePath;
    }

    // 2. Direct REST Upload Fallback
    if (supabaseUrl && supabaseAnonKey) {
      const uploadUrl = `${supabaseUrl}/storage/v1/object/voice-recordings/${filePath}`;
      const res = await fetch(uploadUrl, {
        method: "POST",
        headers: {
          "apikey": supabaseAnonKey,
          "Authorization": `Bearer ${supabaseAnonKey}`,
          "Content-Type": mimeType,
          "x-upsert": "true"
        },
        body: audioBlob
      });

      if (!res.ok) {
        const errText = await res.text();
        console.warn("[Supabase Storage REST Error]:", res.status, errText);
        updateUploadProgress(false);
        return null;
      }

      updateUploadProgress(true, "Audio stored!");
      setTimeout(() => updateUploadProgress(false), 2000);
      return filePath;
    }
  } catch (err) {
    console.warn("[Supabase Storage Upload Exception]:", err);
  }

  updateUploadProgress(false);
  return null;
}

async function uploadRecordedAudioToSupabase(sessionId, audioBlob, durationSeconds = null) {
  const ext = (audioBlob.type && audioBlob.type.includes("mp4")) ? "m4a" : "webm";
  const path = await uploadAudioBlobToStorage(sessionId, audioBlob, ext, audioBlob.type || "audio/webm");
  if (path) {
    currentSessionAudioPath = path;
    currentSessionAudioDuration = durationSeconds;
    console.log(`[Audio Storage]: Recorded session audio saved to '${path}'`);

    // If transcript was already saved, link audio path to that row
    if (supabaseClient) {
      supabaseClient
        .from("speech_transcripts")
        .update({ audio_file_path: path, audio_duration_seconds: durationSeconds })
        .eq("session_id", sessionId)
        .then(() => setTimeout(loadTranscriptHistory, 1200))
        .catch(() => {});
    }
  }
}

async function handleCustomAudioFileUpload(file) {
  if (!file) return;

  // Validate format
  const validExtensions = ["mp3", "wav", "m4a", "webm", "ogg"];
  const fileExt = file.name.split(".").pop().toLowerCase();
  if (!validExtensions.includes(fileExt) && !file.type.startsWith("audio/")) {
    alert(`Unsupported audio format (.${fileExt}). Please select MP3, WAV, M4A, WebM, or OGG.`);
    return;
  }

  // Validate size
  if (file.size > 25 * 1024 * 1024) {
    alert("Audio file is too large! Maximum allowed size is 25MB.");
    return;
  }

  const sessionId = currentTriggerId || `UPLOAD_${Date.now().toString().slice(-6)}`;
  updateUploadProgress(true, `Uploading ${file.name}...`);

  try {
    const storagePath = await uploadAudioBlobToStorage(sessionId, file, fileExt, file.type || `audio/${fileExt}`);
    if (storagePath) {
      currentSessionAudioPath = storagePath;
      updateEventTime(`Audio uploaded (${file.name})`);

      // Forward audio to Workbench Webhook proxy
      dispatchAudioFileToWebhook(file, sessionId, storagePath);

      // Save initial row in speech_transcripts linking audio file
      saveTranscriptToSupabaseFallback(
        sessionId,
        `[Audio file uploaded: ${file.name}]`,
        "en-IN",
        storagePath,
        null
      );
    }
  } catch (err) {
    alert(`Audio upload failed: ${err.message || err}`);
    updateUploadProgress(false);
  }
}

async function dispatchAudioFileToWebhook(file, sessionId, storagePath) {
  if (!sttWebhookUrl) return;
  try {
    const formData = new FormData();
    formData.append("file", file, file.name);
    formData.append("session_id", sessionId);
    formData.append("audio_file_path", storagePath);

    fetch("/api/workbench/audio-webhook", {
      method: "POST",
      headers: { "x-target-webhook-url": sttWebhookUrl },
      body: formData
    }).catch(err => console.warn("Webhook audio forward warning:", err));
  } catch (_) {}
}

async function saveTranscriptToSupabaseFallback(sessionId, transcriptText, languageCode = "en-IN", audioPath = null, audioDuration = null) {
  if (!transcriptText || !sessionId) return;
  try {
    const record = {
      session_id: sessionId,
      transcript: transcriptText,
      language_code: languageCode
    };
    if (audioPath || currentSessionAudioPath) {
      record.audio_file_path = audioPath || currentSessionAudioPath;
    }
    if (audioDuration !== null || currentSessionAudioDuration !== null) {
      record.audio_duration_seconds = audioDuration !== null ? audioDuration : currentSessionAudioDuration;
    }

    // Check if Supabase client is initialized
    if (supabaseClient) {
      const { error } = await supabaseClient
        .from("speech_transcripts")
        .insert([record]);
      if (error) {
        console.warn("[Supabase Fallback Save Warning]:", error.message);
      } else {
        console.log("[Supabase Fallback Save]: Successfully saved to speech_transcripts");
        setTimeout(loadTranscriptHistory, 1200);
      }
    } else if (supabaseUrl && supabaseAnonKey) {
      // Direct REST fallback if client instance not ready
      fetch(`${supabaseUrl}/rest/v1/speech_transcripts`, {
        method: "POST",
        headers: {
          "apikey": supabaseAnonKey,
          "Authorization": `Bearer ${supabaseAnonKey}`,
          "Content-Type": "application/json",
          "Prefer": "return=minimal"
        },
        body: JSON.stringify(record)
      }).then(r => {
        if (!r.ok) console.warn("[Supabase Fallback REST Warning]: status", r.status);
        else setTimeout(loadTranscriptHistory, 1200);
      }).catch(err => console.warn("[Supabase Fallback REST Exception]:", err));
    }
  } catch (err) {
    console.warn("[Supabase Fallback Save Warning]:", err);
  }
}

// --------------------------------------------------------------------------
// Task 4: Transcript History Fetching & Rendering
// --------------------------------------------------------------------------
function formatRelativeTime(dateString) {
  if (!dateString) return "just now";
  try {
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return dateString;
    const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
    if (diffSec < 10) return "just now";
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 30) return `${diffDay}d ago`;
    return d.toLocaleDateString();
  } catch {
    return dateString;
  }
}

async function loadTranscriptHistory() {
  if (!historyList) return;
  if (historyLoading) historyLoading.classList.remove("hidden");
  if (historyEmpty) historyEmpty.classList.add("hidden");
  if (historyList) historyList.classList.add("hidden");

  let rows = [];

  // Try 1: Supabase JS Client directly
  if (supabaseClient) {
    try {
      const { data, error } = await supabaseClient
        .from("speech_transcripts")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(20);
      if (!error && Array.isArray(data) && data.length > 0) {
        rows = data;
      } else if (error) {
        console.warn("[History Supabase Client]:", error.message);
      }
    } catch (e) {
      console.warn("[History Supabase Client Exception]:", e);
    }
  }

  // Try 2: Direct Supabase REST API
  if (rows.length === 0 && supabaseUrl && supabaseAnonKey) {
    try {
      const res = await fetch(`${supabaseUrl}/rest/v1/speech_transcripts?select=*&order=created_at.desc&limit=20`, {
        headers: {
          "apikey": supabaseAnonKey,
          "Authorization": `Bearer ${supabaseAnonKey}`
        }
      });
      if (res.ok) {
        const json = await res.json();
        if (Array.isArray(json) && json.length > 0) {
          rows = json;
        }
      }
    } catch (_) {}
  }

  // Try 3: Backend History Proxy API (includes voice_transcripts fallback)
  if (rows.length === 0) {
    try {
      const res = await fetch(`${currentApiUrl}/api/transcripts/history?limit=20`);
      if (res.ok) {
        const json = await res.json();
        if (json && Array.isArray(json.transcripts)) {
          rows = json.transcripts;
        }
      }
    } catch (_) {}
  }

  renderHistoryItems(rows);
}

function renderHistoryItems(items) {
  if (historyLoading) historyLoading.classList.add("hidden");
  if (!historyList || !historyEmpty) return;

  if (!items || items.length === 0) {
    historyEmpty.classList.remove("hidden");
    historyList.classList.add("hidden");
    if (historyCountBadge) historyCountBadge.textContent = "0 saved";
    return;
  }

  historyEmpty.classList.add("hidden");
  historyList.classList.remove("hidden");
  if (historyCountBadge) historyCountBadge.textContent = `${items.length} saved`;

  historyList.innerHTML = "";
  items.forEach((item) => {
    const el = document.createElement("div");
    el.className = "history-item";

    const relativeTime = formatRelativeTime(item.created_at);
    const sid = item.session_id || item.trigger_id || "SESSION";
    const lang = item.language_code || "en-IN";
    const text = item.transcript || "";
    const isLong = text.length > 120;

    const hasAudio = Boolean(item.audio_file_path);
    const audioPath = item.audio_file_path || "";

    el.innerHTML = `
      <div class="history-item-top">
        <span class="history-item-id">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          ${escapeHtml(sid)}
        </span>
        <div class="history-item-meta">
          ${hasAudio ? `
            <button class="btn-play-audio" type="button" title="Play recording" data-audio-path="${escapeHtml(audioPath)}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
              <span>Play Audio</span>
            </button>
          ` : ''}
          <span class="history-lang-badge">${escapeHtml(lang)}</span>
          <span class="history-time" title="${item.created_at || ''}">${relativeTime}</span>
        </div>
      </div>
      <p class="history-item-text ${isLong ? 'collapsed' : ''}">${escapeHtml(text)}</p>
      ${isLong ? '<span class="history-expand-hint">Click to expand</span>' : ''}
      <div class="history-audio-player-container hidden"></div>
    `;

    // Audio Playback Handler
    if (hasAudio) {
      const playBtn = el.querySelector(".btn-play-audio");
      const playerBox = el.querySelector(".history-audio-player-container");
      if (playBtn && playerBox) {
        playBtn.addEventListener("click", async (ev) => {
          ev.stopPropagation(); // Don't trigger text expand
          await playSignedAudio(audioPath, playerBox, playBtn);
        });
      }
    }

    if (isLong) {
      el.addEventListener("click", () => {
        const p = el.querySelector(".history-item-text");
        const hint = el.querySelector(".history-expand-hint");
        if (p) {
          const isCollapsed = p.classList.toggle("collapsed");
          if (hint) hint.textContent = isCollapsed ? "Click to expand" : "Click to collapse";
        }
      });
    }

    historyList.appendChild(el);
  });
}

// --------------------------------------------------------------------------
// Task 4: Signed URL Generation & Inline Audio Playback
// --------------------------------------------------------------------------
async function playSignedAudio(audioFilePath, container, buttonEl) {
  if (!audioFilePath || !container) return;

  // Toggle close if already open
  if (!container.classList.contains("hidden") && container.innerHTML) {
    container.classList.add("hidden");
    container.innerHTML = "";
    if (buttonEl) {
      buttonEl.innerHTML = `
        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
        <span>Play Audio</span>
      `;
    }
    return;
  }

  container.classList.remove("hidden");
  container.innerHTML = `<span style="font-size: 0.72rem; color: var(--text-muted);">Generating secure audio stream...</span>`;

  try {
    let signedUrl = null;

    // 1. Try Supabase Client
    if (supabaseClient) {
      const { data, error } = await supabaseClient.storage
        .from("voice-recordings")
        .createSignedUrl(audioFilePath, 60); // 60 seconds validity
      if (!error && data && data.signedUrl) {
        signedUrl = data.signedUrl;
      } else if (error) {
        console.warn("[Signed URL Client Warning]:", error.message);
      }
    }

    // 2. Direct REST Fallback
    if (!signedUrl && supabaseUrl && supabaseAnonKey) {
      const signUrl = `${supabaseUrl}/storage/v1/object/sign/voice-recordings/${audioFilePath}`;
      const res = await fetch(signUrl, {
        method: "POST",
        headers: {
          "apikey": supabaseAnonKey,
          "Authorization": `Bearer ${supabaseAnonKey}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ expiresIn: 60 })
      });
      if (res.ok) {
        const json = await res.json();
        if (json && json.signedURL) {
          signedUrl = json.signedURL.startsWith("http")
            ? json.signedURL
            : `${supabaseUrl}/storage/v1${json.signedURL}`;
        }
      }
    }

    if (!signedUrl) {
      container.innerHTML = `<span style="font-size: 0.72rem; color: #fb7185;">Could not generate audio access URL.</span>`;
      return;
    }

    container.innerHTML = `
      <audio controls autoplay preload="auto" src="${signedUrl}">
        Your browser does not support the audio element.
      </audio>
    `;

    if (buttonEl) {
      buttonEl.innerHTML = `
        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="4" width="4" height="16"></rect>
          <rect x="14" y="4" width="4" height="16"></rect>
        </svg>
        <span>Close Player</span>
      `;
    }
  } catch (err) {
    container.innerHTML = `<span style="font-size: 0.72rem; color: #fb7185;">Playback error: ${escapeHtml(err.message || err)}</span>`;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function dispatchPartialTranscriptToWebhook(text, isFinal = false) {
  if (!sttWebhookUrl || !text) return;
  try {
    fetch(sttWebhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentTriggerId || `sess_${Date.now()}`,
        transcript: text,
        is_final: isFinal,
        timestamp: new Date().toISOString(),
      }),
    }).catch(() => {});
  } catch (_) {}
}

// --------------------------------------------------------------------------
// Monitoring Lifecycle Controls (Single Toggle Button)
// --------------------------------------------------------------------------
function startMonitoring() {
  if (isMonitoring && pollIntervalId) return;
  isMonitoring = true;

  if (monitoringToggleBtn && monitoringToggleLabel) {
    monitoringToggleBtn.className = "btn btn-toggle-monitoring active";
    monitoringToggleLabel.textContent = "Monitoring Active";
  }

  setBannerState("active", "Monitoring Active • Auto-polling & WebSocket stream live");
  initWebSocket();
  pollBackendStatus();
  startTickTimer();

  if (pollIntervalId !== null) clearInterval(pollIntervalId);
  pollIntervalId = setInterval(pollBackendStatus, POLL_INTERVAL_MS);
}

function stopMonitoring() {
  isMonitoring = false;

  if (pollIntervalId !== null) {
    clearInterval(pollIntervalId);
    pollIntervalId = null;
  }
  if (tickIntervalId !== null) {
    clearInterval(tickIntervalId);
    tickIntervalId = null;
  }

  if (websocketClient) {
    try { websocketClient.close(); } catch (_) {}
    websocketClient = null;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }

  if (monitoringToggleBtn && monitoringToggleLabel) {
    monitoringToggleBtn.className = "btn btn-toggle-monitoring paused";
    monitoringToggleLabel.textContent = "Resume Monitoring";
  }

  stopListening();
  setBannerState("paused", "Monitoring Paused • Click toggle to resume");
  updateEventTime("Monitoring paused");
}

function toggleMonitoring() {
  if (isMonitoring) {
    stopMonitoring();
  } else {
    startMonitoring();
  }
}

// --------------------------------------------------------------------------
// Simulation Triggers (For Immediate Testing)
// --------------------------------------------------------------------------
async function runTestTrigger(durationSeconds, label) {
  if (!isMonitoring) startMonitoring();

  const triggerId = `TEST_${Date.now().toString().slice(-4)}`;
  try {
    const res = await fetch(`${currentApiUrl}/trigger/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trigger_id: triggerId,
        duration_seconds: durationSeconds,
      }),
    });

    if (res.ok) {
      pollBackendStatus();
    }
  } catch (err) {
    console.warn("Test trigger error:", err);
  }
}

async function resetBackendState() {
  try {
    const res = await fetch(`${currentApiUrl}/trigger/reset`, { method: "POST" });
    if (res.ok) {
      sessionState = "IDLE";
      currentTriggerId = null;
      sessionExpiresAt = null;
      accumulatedFinalTranscript = "";
      currentInterimTranscript = "";
      renderTranscript();
      stopListening();
      pollBackendStatus();
    }
  } catch (err) {
    console.warn("Reset error:", err);
  }
}

// --------------------------------------------------------------------------
// Auth & Config Modals
// --------------------------------------------------------------------------
let hasAutoTriggeredForUser = false;

async function autoStartSessionOnLogin(user, durationSeconds = 60) {
  if (!user) return;
  console.log(`[Auto-Trigger] User authenticated: ${user.email}. Automatically initiating timer session (${durationSeconds}s)...`);

  if (!isMonitoring) {
    startMonitoring();
  }

  // If already in an active session, do not re-trigger
  if (sessionState === "ACTIVE") {
    console.log("[Auto-Trigger] Voice session is already ACTIVE; timer running.");
    return;
  }

  const userPrefix = (user.email ? user.email.split("@")[0] : "user").replace(/[^a-zA-Z0-9_]/g, "");
  const triggerId = `USER_${userPrefix.toUpperCase()}_${Date.now().toString().slice(-4)}`;

  try {
    const res = await fetch(`${currentApiUrl}/trigger/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trigger_id: triggerId,
        duration_seconds: durationSeconds,
      }),
    });

    if (res.ok) {
      updateEventTime(`Auto-started session for ${user.email.split("@")[0]}`);
      pollBackendStatus();
    } else {
      const err = await res.json().catch(() => ({}));
      console.warn("[Auto-Trigger] Could not start session:", err);
    }
  } catch (err) {
    console.warn("[Auto-Trigger] Start trigger error:", err);
  }
}

function initSupabase() {
  if (!window.supabase) return;
  try {
    supabaseClient = window.supabase.createClient(supabaseUrl, supabaseAnonKey);
    supabaseClient.auth.onAuthStateChange((event, session) => {
      const prevUser = activeAuthUser;
      activeAuthUser = session ? session.user : null;
      if (activeAuthUser) {
        if (authBtnLabel) authBtnLabel.textContent = activeAuthUser.email.split("@")[0];
        if (signOutBtn) signOutBtn.classList.remove("hidden");

        // Automatically start the voice session & timer when user logs in
        if (event === "SIGNED_IN" || (!prevUser && (event === "INITIAL_SESSION" || !hasAutoTriggeredForUser))) {
          hasAutoTriggeredForUser = true;
          setTimeout(() => {
            if (activeAuthUser && sessionState !== "ACTIVE") {
              autoStartSessionOnLogin(activeAuthUser, 60);
            }
          }, 600);
        }
      } else {
        hasAutoTriggeredForUser = false;
        if (authBtnLabel) authBtnLabel.textContent = "Sign In";
        if (signOutBtn) signOutBtn.classList.add("hidden");
        if (event === "SIGNED_OUT") {
          resetBackendState();
        }
      }
    });

    supabaseClient.auth.getSession().then(({ data }) => {
      if (data && data.session && data.session.user) {
        activeAuthUser = data.session.user;
        if (authBtnLabel) authBtnLabel.textContent = activeAuthUser.email.split("@")[0];
        if (signOutBtn) signOutBtn.classList.remove("hidden");

        // Restore and auto-start timer for authenticated user
        if (!hasAutoTriggeredForUser) {
          hasAutoTriggeredForUser = true;
          setTimeout(() => {
            if (activeAuthUser && sessionState !== "ACTIVE") {
              autoStartSessionOnLogin(activeAuthUser, 60);
            }
          }, 800);
        }
      }
    });
  } catch (_) {}
}

function showAuthModal(mode = "signin") {
  if (authModal) authModal.classList.remove("hidden");
  if (authModalAlert) authModalAlert.classList.add("hidden");
  if (mode === "signup") {
    tabSignIn.classList.remove("active");
    tabSignUp.classList.add("active");
    authSubmitBtn.textContent = "Create Account";
  } else {
    tabSignIn.classList.add("active");
    tabSignUp.classList.remove("active");
    authSubmitBtn.textContent = "Sign In";
  }
}

function hideAuthModal() {
  if (authModal) authModal.classList.add("hidden");
}

function showConfigModal() {
  if (cfgWebhookUrl) cfgWebhookUrl.value = sttWebhookUrl;
  if (cfgSupabaseUrl) cfgSupabaseUrl.value = supabaseUrl;
  if (cfgSupabaseKey) cfgSupabaseKey.value = supabaseAnonKey;
  if (configModalAlert) configModalAlert.classList.add("hidden");
  if (configModal) configModal.classList.remove("hidden");
}

function hideConfigModal() {
  if (configModal) configModal.classList.add("hidden");
}

// --------------------------------------------------------------------------
// Setup All Event Listeners
// --------------------------------------------------------------------------
function setupEventListeners() {
  cacheElements();

  // Single Monitoring Toggle Button
  if (monitoringToggleBtn) {
    monitoringToggleBtn.addEventListener("click", toggleMonitoring);
  }

  // Target Backend Selector
  if (apiUrlSelect) {
    apiUrlSelect.addEventListener("change", (e) => {
      if (e.target.value === "custom") {
        if (customApiUrl) customApiUrl.classList.remove("hidden");
        currentApiUrl = (customApiUrl && customApiUrl.value.trim()) || currentApiUrl;
      } else {
        if (customApiUrl) customApiUrl.classList.add("hidden");
        currentApiUrl = e.target.value;
      }
      if (backendEndpointBox) backendEndpointBox.textContent = `GET ${currentApiUrl}/trigger/status`;
      if (isMonitoring) {
        initWebSocket();
        pollBackendStatus();
      }
    });
  }

  if (customApiUrl) {
    customApiUrl.addEventListener("input", (e) => {
      const val = e.target.value.trim();
      if (val) {
        currentApiUrl = val.replace(/\/+$/, "");
        if (backendEndpointBox) backendEndpointBox.textContent = `GET ${currentApiUrl}/trigger/status`;
      }
    });
  }

  // Copy Transcript Button
  if (copyTranscriptBtn) {
    copyTranscriptBtn.addEventListener("click", async () => {
      const fullText = (accumulatedFinalTranscript + " " + currentInterimTranscript).trim();
      if (!fullText) return;
      try {
        await navigator.clipboard.writeText(fullText);
        const span = copyTranscriptBtn.querySelector("span");
        if (span) {
          const orig = span.textContent;
          span.textContent = "Copied!";
          setTimeout(() => { span.textContent = orig; }, 1600);
        }
      } catch (err) {
        console.warn("Copy error:", err);
      }
    });
  }

  // Simulation test buttons
  if (test10sBtn) test10sBtn.addEventListener("click", () => runTestTrigger(10, "10s"));
  if (test30sBtn) test30sBtn.addEventListener("click", () => runTestTrigger(30, "30s"));
  if (test1mBtn) test1mBtn.addEventListener("click", () => runTestTrigger(60, "1m"));
  if (quickStartTimerBtn) quickStartTimerBtn.addEventListener("click", () => runTestTrigger(60, "1m"));
  if (testResetBtn) testResetBtn.addEventListener("click", resetBackendState);

  // Modals
  if (authBtn) authBtn.addEventListener("click", () => showAuthModal("signin"));
  if (signOutBtn) signOutBtn.addEventListener("click", () => {
    hasAutoTriggeredForUser = false;
    if (supabaseClient) supabaseClient.auth.signOut();
    resetBackendState();
  });
  if (closeAuthModalBtn) closeAuthModalBtn.addEventListener("click", hideAuthModal);
  if (tabSignIn) tabSignIn.addEventListener("click", () => showAuthModal("signin"));
  if (tabSignUp) tabSignUp.addEventListener("click", () => showAuthModal("signup"));

  if (authForm) {
    authForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!supabaseClient) return;
      const email = authEmail.value.trim();
      const password = authPassword.value;
      authSubmitBtn.disabled = true;

      try {
        if (tabSignUp.classList.contains("active")) {
          const { data, error } = await supabaseClient.auth.signUp({ email, password });
          if (error) throw error;
          authModalAlert.className = "modal-alert success";
          authModalAlert.textContent = "Account created successfully!";
          if (data && data.user) {
            hasAutoTriggeredForUser = true;
            autoStartSessionOnLogin(data.user, 60);
          }
          setTimeout(hideAuthModal, 800);
        } else {
          const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
          if (error) throw error;
          authModalAlert.className = "modal-alert success";
          authModalAlert.textContent = "Signed in successfully! Starting voice session timer...";
          if (data && data.user) {
            hasAutoTriggeredForUser = true;
            autoStartSessionOnLogin(data.user, 60);
          }
          setTimeout(hideAuthModal, 800);
        }
      } catch (err) {
        authModalAlert.className = "modal-alert error";
        authModalAlert.textContent = err.message || "Authentication error";
      } finally {
        authSubmitBtn.disabled = false;
        authModalAlert.classList.remove("hidden");
      }
    });
  }

  if (configModalBtn) configModalBtn.addEventListener("click", showConfigModal);
  if (closeConfigModalBtn) closeConfigModalBtn.addEventListener("click", hideConfigModal);

  if (configForm) {
    configForm.addEventListener("submit", (e) => {
      e.preventDefault();
      sttWebhookUrl = cfgWebhookUrl.value.trim();
      supabaseUrl = cfgSupabaseUrl.value.trim();
      supabaseAnonKey = cfgSupabaseKey.value.trim();

      localStorage.setItem("vta_webhook_url", sttWebhookUrl);
      localStorage.setItem("vta_supabase_url", supabaseUrl);
      localStorage.setItem("vta_supabase_anon_key", supabaseAnonKey);

      initSupabase();
      if (configModalAlert) {
        configModalAlert.className = "modal-alert success";
        configModalAlert.textContent = "Settings saved!";
        configModalAlert.classList.remove("hidden");
      }
      setTimeout(hideConfigModal, 800);
    });
  }

  if (resetConfigBtn) {
    resetConfigBtn.addEventListener("click", () => {
      localStorage.removeItem("vta_webhook_url");
      localStorage.removeItem("vta_supabase_url");
      localStorage.removeItem("vta_supabase_anon_key");
      sttWebhookUrl = DEFAULT_WEBHOOK_URL;
      cfgWebhookUrl.value = DEFAULT_WEBHOOK_URL;
    });
  }

  // Close modals on backdrop click
  if (authModal) {
    authModal.addEventListener("click", (e) => { if (e.target === authModal) hideAuthModal(); });
  }
  if (configModal) {
    configModal.addEventListener("click", (e) => { if (e.target === configModal) hideConfigModal(); });
  }

  // Task 4: Transcript History Event Listeners
  if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      loadTranscriptHistory();
    });
  }

  const toggleHistoryAction = () => {
    if (!historyBody) return;
    const isHidden = historyBody.classList.toggle("hidden");
    if (toggleHistoryIcon) {
      toggleHistoryIcon.innerHTML = isHidden ? "&#9654;" : "&#9660;";
    }
  };

  if (toggleHistoryBtn) {
    toggleHistoryBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleHistoryAction();
    });
  }

  if (historyHeaderToggle) {
    historyHeaderToggle.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      toggleHistoryAction();
    });
  }

  // Task 3: Audio File Upload Listeners
  if (uploadAudioBtn && audioFileInput) {
    uploadAudioBtn.addEventListener("click", () => {
      audioFileInput.click();
    });
    audioFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        handleCustomAudioFileUpload(e.target.files[0]);
        audioFileInput.value = "";
      }
    });
  }
}

// --------------------------------------------------------------------------
// Initialization on Page Load
// --------------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  cacheElements();

  currentApiUrl = detectDefaultApiUrl();
  if (apiUrlSelect) {
    let match = Array.from(apiUrlSelect.options).find(o => o.value === currentApiUrl);
    if (!match) {
      match = document.createElement("option");
      match.value = currentApiUrl;
      match.textContent = `Current Server (${window.location.hostname})`;
      apiUrlSelect.insertBefore(match, apiUrlSelect.firstChild);
    }
    apiUrlSelect.value = currentApiUrl;
  }
  if (backendEndpointBox) {
    backendEndpointBox.textContent = `GET ${currentApiUrl}/trigger/status`;
  }

  setupEventListeners();
  initSupabase();

  // Load Transcript History on startup
  loadTranscriptHistory();

  // AUTOMATIC TRIGGER LIFECYCLE:
  // Connect to backend and start monitoring stream
  startMonitoring();
});
