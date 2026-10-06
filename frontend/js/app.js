// Single-page app: views, routes, and the practice flow (setup -> record -> analyze -> coach).
import { SKILL_LABELS, el, formatClock, initializeTheme, requestJson } from "./common.js";
import { getUser, initAuth, loadUser, onAuthChange, requireLogin, sessionExpired, showLogin } from "./auth.js";
import { createCoachView } from "./coach.js";
import { initDeckUpload } from "./deck.js";
import { initDocumentUpload } from "./document.js";
import { initHome } from "./home.js";
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
  if (name !== "practice") recorder.cancel();
  window.scrollTo({ top: 0 });
}

// Home page card look per mode: an icon (SVG path data, 24x24) and a hue for its colour.
const MODE_LOOK = {
  free: { hue: 199, icon: "M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3" },
  interview: { hue: 221, icon: "M3 9h18v11H3zM8 9V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v3M3 14h18" },
  jam: { hue: 262, icon: "M12 8v5l3 2M9 2h6M12 4a9 9 0 1 1 0 18 9 9 0 0 1 0-18z" },
  snap: { hue: 38, icon: "M13 2 4 14h7l-1 8 9-12h-7z" },
  read: { hue: 160, icon: "M4 4h11a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3zM8 9h6M8 13h6" },
  presentation: { hue: 187, icon: "M3 4h18v12H3zM12 16v4M8 20h8M7 12l3-3 2 2 4-4" },
  pitch: { hue: 330, icon: "M12 2c3 3 4 7 3 11l-3 3-3-3c-1-4 0-8 3-11zM9 13l-3 1 1 4 3-2M15 13l3 1-1 4-3-2" },
  debate: { hue: 12, icon: "M4 5h10v7H8l-4 3zM10 15v2h6l4 3V10h-4" },
};

function minutesLabel(seconds) {
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
}

function timeBadge(timer = {}) {
  if (timer.user_duration) return "Any length";
  if (timer.target_choices) return `${minutesLabel(timer.target_choices[0])} – ${minutesLabel(timer.target_choices.at(-1))}`;
  if (timer.prep_seconds) return `${timer.prep_seconds} s prep · ${minutesLabel(timer.target_seconds)}`;
  if (timer.target_seconds) return minutesLabel(timer.target_seconds);
  return timer.limit_seconds ? `Up to ${minutesLabel(timer.limit_seconds)}` : "";
}

function modeIcon(path) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
  shape.setAttribute("d", path);
  svg.appendChild(shape);
  return svg;
}

function renderModeLinks() {
  const grid = $("modeGrid");
  const switcher = $("modeSwitcher");
  grid.textContent = "";
  switcher.textContent = "";
  catalog.modes.forEach((mode, index) => {
    const look = MODE_LOOK[mode.id] || MODE_LOOK.free;
    const card = el("a", "mode-card");
    card.href = `#/practice/${mode.id}`;
    card.style.setProperty("--i", index);
    card.style.setProperty("--hue", look.hue);

    const top = el("span", "mode-card-top");
    const icon = el("span", "mode-card-icon");
    icon.appendChild(modeIcon(look.icon));
    top.append(icon, el("span", "mode-card-time", timeBadge(mode.timer)));

    const skills = el("span", "mode-card-skills");
    mode.skills.slice(0, 3).forEach((skill) => skills.appendChild(el("span", "", SKILL_LABELS[skill])));

    const footer = el("span", "mode-card-go");
    footer.append(el("span", "", "Start practice"), el("span", "mode-card-arrow", "→"));
    if (mode.coached) footer.prepend(el("span", "mode-card-coach", "AI coach"));

    card.append(top, el("span", "mode-card-title", mode.label), el("span", "mode-card-tagline", mode.tagline), skills, footer);
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
initHome();

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
    initDocumentUpload({ requireLogin: () => requireLogin(currentPath()), onSessionExpired, onChange: practice.refreshSetup });
    practiceResults = createResultView($("practiceResults"));
    practiceCoach = createCoachView($("practiceCoach"), onSessionExpired);
    setControls("idle");
    startRouter();
  })
  .catch(() => {
    $("modeGrid").textContent = "Could not load the practice modes. Check that the server is running, then refresh.";
  });
