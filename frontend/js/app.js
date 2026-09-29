// Analyzer page: sign-in, practice setup, recording, analysis and coaching.
import { formatClock, initializeTheme, postJson, requestJson } from "./common.js";
import { hideCoach, initCoach, requestCoaching } from "./coach.js";
import * as practice from "./practice.js";
import { Recorder, fileNameFor } from "./recorder.js";
import { drawTimeline, renderResults } from "./results.js";

const $ = (id) => document.getElementById(id);
let audioBlob = null;
let practiceReady = false;

// ---------- Sign-in ----------

function setAuthStatus(message, type = "") {
  const status = $("authStatus");
  status.className = "status-line";
  if (type === "error") status.classList.add("status-error");
  if (type === "ok") status.classList.add("status-ok");
  status.textContent = message;
}

function setActiveTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((button, index) => {
    const active = button.dataset.tab === tabName;
    button.classList.toggle("active", active);
    if (active) $("tabGlider").style.transform = `translateX(${index * 100}%)`;
  });
  $("loginForm").classList.toggle("active", tabName === "login");
  $("registerForm").classList.toggle("active", tabName === "register");
  setAuthStatus("");
}

function updatePasswordStrength() {
  const password = $("registerPassword").value;
  const score = [password.length >= 8, /[A-Z]/.test(password), /[0-9]/.test(password), /[^A-Za-z0-9]/.test(password)].filter(Boolean).length;
  const bar = $("strengthBar");
  bar.style.width = ["20%", "35%", "60%", "80%", "100%"][score];
  bar.style.backgroundColor = ["#ef4444", "#f97316", "#f59e0b", "#3b82f6", "#1d4ed8"][score];
  $("strengthLabel").textContent = `Password strength: ${["weak", "fair", "good", "strong", "excellent"][score]}`;
}

async function showApp(user) {
  $("welcomeUser").textContent = user?.name || "Speaker";
  $("authShell").classList.add("hidden");
  $("appShell").classList.remove("hidden");
  if (!practiceReady) {
    try {
      await practice.loadCatalog();
      practice.initPractice(onModeChange);
      practiceReady = true;
    } catch {
      setStatus("Could not load practice modes. Refresh the page to try again.");
      return;
    }
    // The progress page links here with ?mode=... to suggest what to practise next.
    const requested = new URLSearchParams(window.location.search).get("mode");
    if (requested) {
      practice.selectMode(requested);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }
  setStatus("Pick a mode, then press Start.");
}

function showAuth() {
  $("appShell").classList.add("hidden");
  $("authShell").classList.remove("hidden");
}

function handleSessionExpired() {
  showAuth();
  setAuthStatus("Your session has expired. Please log in again.", "error");
}

// ---------- Recording ----------

function setStatus(message) {
  $("status").textContent = message;
}

function onModeChange() {
  $("stage").classList.add("hidden");
  $("resultPanel").classList.add("hidden");
  hideCoach();
  resetRecording();
}

function resetRecording() {
  audioBlob = null;
  $("analyzeBtn").disabled = true;
  const preview = $("audioPreview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.removeAttribute("src");
  preview.classList.add("hidden");
}

function showStage() {
  const content = practice.stageContent();
  $("stage").classList.remove("hidden");
  $("stageTitle").textContent = content.title;
  $("stagePrompt").textContent = content.text || "";
  $("stagePrompt").classList.toggle("hidden", !content.text);
  $("teleprompter").textContent = content.script || "";
  $("teleprompter").classList.toggle("hidden", !content.script);
  $("timerBlock").classList.remove("hidden");
}

function updateTimer(label, seconds, fraction) {
  $("timerLabel").textContent = label;
  $("timerDisplay").textContent = formatClock(seconds);
  $("timerBar").style.width = `${Math.min(100, Math.max(0, fraction * 100))}%`;
}

let activeLimit = null;
let activePrep = 0;

const recorder = new Recorder({
  onPrep(remaining) {
    $("stageKicker").textContent = "Get ready";
    updateTimer("Thinking time", Math.ceil(remaining), 1 - remaining / activePrep);
  },
  onStart() {
    $("stageKicker").textContent = "Recording";
    $("stage").classList.add("recording");
    setStatus("Recording... press Stop when you're done.");
  },
  onTick(elapsed) {
    if (activeLimit) updateTimer("Time left", Math.ceil(activeLimit - elapsed), elapsed / activeLimit);
    else updateTimer("Elapsed", elapsed, 0);
  },
  onStop(blob, elapsed) {
    $("stage").classList.remove("recording");
    $("timerBlock").classList.add("hidden");
    $("stageKicker").textContent = "Your prompt";
    $("startBtn").disabled = false;
    $("stopBtn").disabled = true;
    practice.setLocked(false);
    if (!blob) {
      setStatus("Cancelled before recording started.");
      return;
    }
    audioBlob = blob;
    const preview = $("audioPreview");
    preview.src = URL.createObjectURL(blob);
    preview.classList.remove("hidden");
    $("analyzeBtn").disabled = false;
    const reachedLimit = activeLimit && elapsed >= activeLimit - 0.2;
    setStatus(`${reachedLimit ? "Time's up" : "Recording stopped"} (${formatClock(elapsed)}). Listen back or press Analyze.`);
  },
});

async function startPractice() {
  const problem = practice.validate();
  if (problem) {
    setStatus(problem);
    return;
  }
  practice.prepareAttempt();
  const { prepSeconds, limitSeconds } = practice.timerSettings();
  activeLimit = limitSeconds;
  activePrep = prepSeconds;
  resetRecording();
  $("resultPanel").classList.add("hidden");
  hideCoach();
  $("startBtn").disabled = true;
  $("stopBtn").disabled = false;
  practice.setLocked(true);
  showStage();
  updateTimer(prepSeconds ? "Thinking time" : "Time left", prepSeconds || limitSeconds || 0, 0);
  setStatus(prepSeconds ? "Think about your answer. Recording starts automatically." : "Starting...");
  try {
    await recorder.start({ prepSeconds, limitSeconds });
  } catch {
    $("startBtn").disabled = false;
    $("stopBtn").disabled = true;
    practice.setLocked(false);
    $("stage").classList.add("hidden");
    setStatus("Microphone access was denied. Allow it in your browser and try again.");
  }
}

async function analyzeRecording() {
  if (!audioBlob) return;
  setStatus("Analyzing your speech...");
  $("analyzeBtn").disabled = true;
  try {
    const formData = new FormData();
    formData.append("audio", audioBlob, fileNameFor(audioBlob));
    Object.entries(practice.formFields()).forEach(([key, value]) => formData.append(key, value));
    const result = await requestJson("/analyze", { method: "POST", body: formData });
    renderResults(result, practice.currentMode());
    setStatus("Analysis complete.");
    if (result.coach_available) requestCoaching(result.id, handleSessionExpired);
    else hideCoach();
    $("resultPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (error.status === 401) {
      handleSessionExpired();
      return;
    }
    setStatus(error.message);
  } finally {
    $("analyzeBtn").disabled = !audioBlob;
  }
}

// ---------- Wiring ----------

document.querySelectorAll(".tab-btn").forEach((button) => button.addEventListener("click", () => setActiveTab(button.dataset.tab)));
document.querySelectorAll(".ghost-icon").forEach((button) => {
  button.addEventListener("click", () => {
    const input = $(button.dataset.toggle);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Hide" : "Show";
  });
});
$("registerPassword").addEventListener("input", updatePasswordStrength);

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("loginSubmit");
  button.disabled = true;
  button.textContent = "Signing In...";
  setAuthStatus("Authenticating...");
  try {
    const result = await postJson("/login", { email: $("loginEmail").value.trim(), password: $("loginPassword").value });
    setAuthStatus(result.message, "ok");
    showApp(result.user);
  } catch (error) {
    setAuthStatus(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Sign In";
  }
});

$("registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("registerSubmit");
  const email = $("registerEmail").value.trim();
  button.disabled = true;
  button.textContent = "Creating...";
  setAuthStatus("Creating your account...");
  try {
    const result = await postJson("/register", { name: $("registerName").value.trim(), email, password: $("registerPassword").value });
    setAuthStatus(`${result.message} Please log in.`, "ok");
    $("registerForm").reset();
    updatePasswordStrength();
    setActiveTab("login");
    $("loginEmail").value = email;
  } catch (error) {
    setAuthStatus(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Create Account";
  }
});

$("logoutBtn").addEventListener("click", async () => {
  try {
    await postJson("/logout", {});
  } catch {
    // The server session is gone either way; still return to the login screen.
  }
  showAuth();
});

$("trackerBtn").addEventListener("click", () => {
  window.location.href = "/tracker";
});
$("startBtn").addEventListener("click", startPractice);
$("stopBtn").addEventListener("click", () => recorder.stop());
$("analyzeBtn").addEventListener("click", analyzeRecording);
window.addEventListener("resize", drawTimeline);

initializeTheme($("themeToggle"), drawTimeline);
initCoach(handleSessionExpired);
updatePasswordStrength();

requestJson("/me")
  .then((result) => showApp(result.user))
  .catch(() => {
    // Not logged in; the login form is already showing.
  });
