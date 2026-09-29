// Single-page app: views, routes, and the practice flow (setup -> record -> analyze -> coach).
import { SKILL_LABELS, el, formatClock, initializeTheme, requestJson } from "./common.js";
import { getUser, initAuth, loadUser, onAuthChange, requireLogin, sessionExpired, showLogin } from "./auth.js";
import { createCoachView } from "./coach.js";
import { initDeckUpload } from "./deck.js";
import { initDocumentUpload } from "./document.js";
import { completeLoader, hideLoader, setStage, showLoader } from "./loader.js";
import * as practice from "./practice.js";
import { drawChart as drawProgressChart, showProgress } from "./progress.js";
import { Recorder, fileNameFor } from "./recorder.js";
import { createResultView, redrawCharts } from "./results.js";
import { currentPath, fallback, navigate, route, startRouter } from "./router.js";
import { leaveSession, showSession } from "./session.js";

const $ = (id) => document.getElementById(id);
const VIEWS = ["home", "login", "practice", "progress", "session"];
const NAV_FOR_VIEW = { home: "home", practice: "home", progress: "progress", session: "progress" };
// Which practice buttons are visible in each state of the flow.
const CONTROLS = {
  idle: ["startBtn"],
  prep: ["skipPrepBtn", "restartBtn"],
  recording: ["stopAnalyzeBtn", "restartBtn"],
  analyzing: [],
  done: ["againBtn"],
  failed: ["againBtn", "retryAnalyzeBtn"],
};
let catalog = null;
let practiceResults = null;
let practiceCoach = null;
let audioBlob = null;
let activeLimit = null;
let activePrep = 0;

const onSessionExpired = () => sessionExpired(currentPath());

// ---------- Views ----------

function showView(name) {
  VIEWS.forEach((view) => {
    const section = $(`view-${view}`);
    const active = view === name;
    section.classList.toggle("hidden", !active);
    if (active) {
      section.classList.remove("view-enter");
      void section.offsetWidth; // restart the enter animation
      section.classList.add("view-enter");
    }
  });
  document.querySelectorAll("[data-nav]").forEach((link) => link.classList.toggle("active", link.dataset.nav === NAV_FOR_VIEW[name]));
  if (name !== "session") leaveSession();
  if (name !== "practice" && recorder.state !== "idle") recorder.cancel();
  window.scrollTo({ top: 0 });
}

function renderModeLinks() {
  const grid = $("modeGrid");
  const switcher = $("modeSwitcher");
  grid.textContent = "";
  switcher.textContent = "";
  catalog.modes.forEach((mode, index) => {
    const card = el("a", "mode-card");
    card.href = `#/practice/${mode.id}`;
    card.style.setProperty("--i", index);
    card.append(
      el("span", "mode-card-title", mode.label),
      el("span", "mode-card-tagline", mode.tagline),
      el("span", "mode-card-skills", mode.skills.slice(0, 3).map((skill) => SKILL_LABELS[skill]).join(" · "))
    );
    grid.appendChild(card);

    const pill = el("a", "mode-pill", mode.label);
    pill.href = `#/practice/${mode.id}`;
    pill.dataset.mode = mode.id;
    switcher.appendChild(pill);
  });
}

// ---------- Practice ----------

function setStatus(message, isError = false) {
  $("status").textContent = message;
  $("status").classList.toggle("status-error", isError);
}

function setControls(state) {
  Object.values(CONTROLS).flat().forEach((id) => $(id).classList.add("hidden"));
  CONTROLS[state].forEach((id) => $(id).classList.remove("hidden"));
  practice.setLocked(state === "prep" || state === "recording" || state === "analyzing");
}

function setPlayer(blob) {
  const audio = $("practiceAudio");
  if (audio.src) URL.revokeObjectURL(audio.src);
  if (blob) audio.src = URL.createObjectURL(blob);
  else audio.removeAttribute("src");
  $("practicePlayer").classList.toggle("hidden", !blob);
}

function resetAttempt() {
  audioBlob = null;
  setPlayer(null);
  $("stage").classList.add("hidden");
  practiceResults.hide();
  practiceCoach.hide();
}

function idleMessage() {
  return getUser() ? "Set things up, then press Start recording when you're ready." : "Press Start recording to log in and begin.";
}

function openPractice(modeId) {
  showView("practice");
  const changed = practice.selectMode(modeId);
  if (changed) {
    resetAttempt();
    setControls("idle");
    setStatus(idleMessage());
  }
  document.querySelectorAll(".mode-pill").forEach((pill) => pill.classList.toggle("active", pill.dataset.mode === practice.currentMode().id));
}

function showStage() {
  const content = practice.stageContent();
  $("stage").classList.remove("hidden");
  $("stageTitle").textContent = content.title;
  $("stagePrompt").textContent = content.text || "";
  $("stagePrompt").classList.toggle("hidden", !content.text);
  $("teleprompter").textContent = content.script || "";
  $("teleprompter").classList.toggle("hidden", !content.script);
  $("teleprompter").classList.toggle("teleprompter-long", Boolean(content.long));
  $("teleprompter").scrollTop = 0;
  const slides = $("stageSlides");
  slides.textContent = "";
  (content.slides || []).forEach((title) => slides.appendChild(el("li", "", title)));
  slides.classList.toggle("hidden", !content.slides);
  $("timerBlock").classList.remove("hidden");
}

function updateTimer(label, seconds, fraction) {
  $("timerLabel").textContent = label;
  $("timerDisplay").textContent = formatClock(seconds);
  $("timerBar").style.width = `${Math.min(100, Math.max(0, fraction * 100))}%`;
}

const recorder = new Recorder({
  onPrep(remaining) {
    $("stageKicker").textContent = "Get ready";
    updateTimer("Thinking time", Math.ceil(remaining), 1 - remaining / activePrep);
  },
  onStart() {
    $("stageKicker").textContent = "Recording";
    $("stage").classList.add("recording");
    setControls("recording");
    setStatus("Recording... press Stop & analyze when you're done.");
  },
  onTick(elapsed) {
    if (activeLimit) updateTimer("Time left", Math.ceil(activeLimit - elapsed), elapsed / activeLimit);
    else updateTimer("Elapsed", elapsed, 0);
  },
  onStop(blob, elapsed) {
    $("stage").classList.remove("recording");
    $("timerBlock").classList.add("hidden");
    $("stageKicker").textContent = "Your prompt";
    if (!blob) {
      setControls("idle");
      $("stage").classList.add("hidden");
      setStatus("That take was thrown away. Take a moment, then press Start recording when you're ready.");
      return;
    }
    audioBlob = blob;
    setPlayer(blob);
    const reachedLimit = activeLimit && elapsed >= activeLimit - 0.2;
    analyzeRecording(reachedLimit ? "Time's up! " : "");
  },
});

// Back to the set-up with the Start button, so there's time to get ready (or pick a new prompt) first.
function readyForAnotherTake() {
  resetAttempt();
  setControls("idle");
  setStatus("Ready for another go. Take a moment, then press Start recording when you're ready.");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function startPractice() {
  if (!requireLogin(currentPath())) return;
  const problem = practice.validate();
  if (problem) {
    setStatus(problem, true);
    return;
  }
  practice.prepareAttempt();
  const { prepSeconds, limitSeconds } = practice.timerSettings();
  activeLimit = limitSeconds;
  activePrep = prepSeconds;
  resetAttempt();
  setControls(prepSeconds ? "prep" : "recording");
  showStage();
  updateTimer(prepSeconds ? "Thinking time" : "Time left", prepSeconds || limitSeconds || 0, 0);
  setStatus(prepSeconds ? "Think about your answer. Recording starts automatically." : "Starting...");
  try {
    await recorder.start({ prepSeconds, limitSeconds });
  } catch {
    setControls("idle");
    $("stage").classList.add("hidden");
    setStatus("Microphone access was denied. Allow it in your browser and try again.", true);
  }
}

// Reads the newline-delimited JSON progress stream from /analyze?stream=1.
async function streamAnalysis(formData) {
  const response = await fetch("/analyze?stream=1", { method: "POST", body: formData });
  if (!response.ok) {
    let message = "Analysis failed. Please try again.";
    try {
      message = (await response.json()).error || message;
    } catch {
      // Not JSON (e.g. a proxy error page).
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const event = JSON.parse(line);
      if (event.stage) setStage(event.stage);
      if (event.result) return event.result;
      if (event.error) {
        const error = new Error(event.error);
        error.status = event.status;
        throw error;
      }
    }
    if (done) throw new Error("The analysis ended unexpectedly. Please try again.");
  }
}

async function analyzeRecording(prefix = "") {
  if (!audioBlob) return;
  setControls("analyzing");
  setStatus(`${prefix}Analyzing your speech...`);
  showLoader(audioBlob);
  try {
    const formData = new FormData();
    formData.append("audio", audioBlob, fileNameFor(audioBlob));
    Object.entries(practice.formFields()).forEach(([key, value]) => formData.append(key, value));
    const result = await streamAnalysis(formData);
    await completeLoader();
    practiceResults.render(result, practice.currentMode());
    setControls("done");
    setStatus("Done! This session is saved to My progress, where you can replay it any time.");
    if (result.coach_available) practiceCoach.request(result.id);
    else practiceCoach.hide();
    $("practicePlayer").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    hideLoader();
    if (error.status === 401) return onSessionExpired();
    // A recording with no usable speech can't be fixed by retrying; anything else might be temporary.
    const retryable = ![400, 422].includes(error.status);
    setControls("failed");
    $("retryAnalyzeBtn").classList.toggle("hidden", !retryable);
    setStatus(error.message, true);
  }
}

// ---------- Routes ----------

route("/", () => showView("home"));
route("/login", (_params, query) => {
  if (getUser()) return navigate(query.get("next") || "/");
  showLogin(query);
  showView("login");
});
route("/practice/:mode", ({ mode }) => openPractice(mode));
route("/progress", () => {
  if (!requireLogin("/progress")) return;
  showView("progress");
  showProgress(getUser(), onSessionExpired);
});
route("/session/:id", ({ id }) => {
  if (!requireLogin(`/session/${id}`)) return;
  showView("session");
  showSession(Number(id), catalog, onSessionExpired);
});
fallback(() => navigate("/"));

onAuthChange((user) => {
  if (!user && ["/progress", "/session"].some((prefix) => currentPath().startsWith(prefix))) navigate("/");
  if (!$("view-practice").classList.contains("hidden") && recorder.state === "idle" && !audioBlob) setStatus(idleMessage());
});

// ---------- Start-up ----------

document.querySelectorAll("[data-scroll]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    $(link.dataset.scroll).scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
$("startBtn").addEventListener("click", startPractice);
$("skipPrepBtn").addEventListener("click", () => recorder.skipPrep());
$("stopAnalyzeBtn").addEventListener("click", () => recorder.stop());
$("restartBtn").addEventListener("click", () => recorder.cancel());
$("againBtn").addEventListener("click", readyForAnotherTake);
$("retryAnalyzeBtn").addEventListener("click", () => analyzeRecording());
window.addEventListener("resize", () => {
  redrawCharts();
  drawProgressChart();
});

initializeTheme($("themeToggle"), () => {
  redrawCharts();
  drawProgressChart();
});
initAuth();

// Old links used /?mode=jam; send them to the practice view instead.
const legacyMode = new URLSearchParams(window.location.search).get("mode");
if (legacyMode) {
  window.history.replaceState(null, "", `${window.location.pathname}#/practice/${encodeURIComponent(legacyMode)}`);
}

Promise.all([loadUser(), practice.loadCatalog()])
  .then(([, loaded]) => {
    catalog = loaded;
    renderModeLinks();
    practice.initPractice({ requireLogin: () => requireLogin(currentPath()), onSessionExpired });
    initDeckUpload({
      getTopicAndTarget: practice.presentationContext,
      requireLogin: () => requireLogin(currentPath()),
      onSessionExpired,
    });
    initDocumentUpload({ requireLogin: () => requireLogin(currentPath()), onSessionExpired });
    practiceResults = createResultView($("practiceResults"));
    practiceCoach = createCoachView($("practiceCoach"), onSessionExpired);
    setControls("idle");
    startRouter();
  })
  .catch(() => {
    $("modeGrid").textContent = "Could not load the practice modes. Check that the server is running, then refresh.";
  });
