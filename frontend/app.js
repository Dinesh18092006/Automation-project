const BACKEND_URL = "https://automation-project-d95s.onrender.com";

let checking = false;
let statusTimer = null;

let recognition = null;
let microphoneRunning = false;

let currentTriggerId = null;


// -------------------------------------
// HTML elements
// -------------------------------------

const statusElement = document.getElementById("status");
const micStatusElement = document.getElementById("micStatus");
const micIconElement = document.getElementById("micIcon");
const transcriptElement = document.getElementById("transcript");

const startButton = document.getElementById("startButton");
const stopButton = document.getElementById("stopButton");


// -------------------------------------
// Check trigger status
// -------------------------------------

async function checkTriggerStatus() {

    try {

        const response = await fetch(
            `${BACKEND_URL}/trigger/status`
        );

        if (!response.ok) {
            throw new Error("Backend returned an error");
        }

        const data = await response.json();

        console.log("Trigger status:", data);

        if (data.active === true) {

            currentTriggerId = data.trigger_id;

            updateTriggerUI(true);

            startMicrophone();

        } else {

            currentTriggerId = null;

            updateTriggerUI(false);

            stopMicrophone();
        }

    } catch (error) {

        console.error("Status check failed:", error);

        statusElement.textContent = "Backend connection failed";
        statusElement.className = "status inactive";
    }
}


// -------------------------------------
// Start checking backend
// -------------------------------------

function startChecking() {

    if (checking) {
        return;
    }

    checking = true;

    console.log("Started checking trigger status");

    checkTriggerStatus();

    statusTimer = setInterval(
        checkTriggerStatus,
        3000
    );
}


// -------------------------------------
// Stop checking backend
// -------------------------------------

function stopChecking() {

    checking = false;

    if (statusTimer !== null) {

        clearInterval(statusTimer);

        statusTimer = null;
    }

    stopMicrophone();

    console.log("Stopped checking trigger status");
}


// -------------------------------------
// Update trigger UI
// -------------------------------------

function updateTriggerUI(active) {

    if (active) {

        statusElement.textContent =
            "Trigger ACTIVE";

        statusElement.className =
            "status active";

    } else {

        statusElement.textContent =
            "Trigger INACTIVE";

        statusElement.className =
            "status inactive";
    }
}


// -------------------------------------
// Create speech recognition
// -------------------------------------

function createSpeechRecognition() {

    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    if (!SpeechRecognition) {

        alert(
            "Speech recognition is not supported in this browser. Please use Google Chrome."
        );

        return null;
    }

    const recognition =
        new SpeechRecognition();

    recognition.continuous = true;

    recognition.interimResults = true;

    recognition.lang = "en-IN";


    recognition.onstart = function () {

        microphoneRunning = true;

        micIconElement.textContent = "🎙️";

        micStatusElement.textContent =
            "Microphone is ON";

        console.log("Microphone started");
    };


    recognition.onresult = function (event) {

        let finalText = "";

        for (
            let i = event.resultIndex;
            i < event.results.length;
            i++
        ) {

            const result = event.results[i];

            if (result.isFinal) {

                finalText +=
                    result[0].transcript;
            }
        }

        finalText = finalText.trim();

        if (finalText.length > 0) {

            console.log(
                "Speech detected:",
                finalText
            );

            transcriptElement.textContent =
                finalText;

            sendTranscript(finalText);
        }
    };


    recognition.onerror = function (event) {

        console.error(
            "Speech recognition error:",
            event.error
        );
    };


    recognition.onend = function () {

        microphoneRunning = false;

        console.log(
            "Speech recognition ended"
        );

        /*
         * If the trigger is still active,
         * restart the microphone.
         */

        if (checking && currentTriggerId !== null) {

            setTimeout(() => {

                if (
                    checking &&
                    currentTriggerId !== null &&
                    !microphoneRunning
                ) {

                    startMicrophone();
                }

            }, 500);
        }
    };


    return recognition;
}


// -------------------------------------
// Start microphone
// -------------------------------------

function startMicrophone() {

    if (microphoneRunning) {
        return;
    }

    if (!checking) {
        return;
    }

    if (currentTriggerId === null) {
        return;
    }

    if (!recognition) {

        recognition =
            createSpeechRecognition();
    }

    if (!recognition) {
        return;
    }

    try {

        recognition.start();

    } catch (error) {

        console.log(
            "Microphone start:",
            error.message
        );
    }
}


// -------------------------------------
// Stop microphone
// -------------------------------------

function stopMicrophone() {

    currentTriggerId = null;

    if (recognition) {

        try {
            recognition.stop();
        } catch (error) {
            console.log(error);
        }
    }

    microphoneRunning = false;

    micIconElement.textContent = "🎙️";

    micStatusElement.textContent =
        "Microphone is OFF";
}


// -------------------------------------
// Send transcript to backend
// -------------------------------------

async function sendTranscript(text) {

    if (!currentTriggerId) {

        console.log(
            "No active trigger. Transcript not sent."
        );

        return;
    }

    try {

        const response = await fetch(
            `${BACKEND_URL}/trigger/result`,
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    trigger_id:
                        currentTriggerId,

                    transcript: text
                })
            }
        );

        const data =
            await response.json();

        console.log(
            "Transcript response:",
            data
        );

    } catch (error) {

        console.error(
            "Failed to send transcript:",
            error
        );
    }
}


// -------------------------------------
// Buttons
// -------------------------------------

startButton.addEventListener(
    "click",
    startChecking
);

stopButton.addEventListener(
    "click",
    stopChecking
);