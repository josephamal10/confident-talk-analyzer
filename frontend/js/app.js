// Single-page app: views, routes, and the practice flow (setup -> record -> analyze -> coach).
import { SKILL_LABELS, el, formatClock, initializeTheme, requestJson } from "./common.js";
import { getUser, initAuth, loadUser, onAuthChange, requireLogin, sessionExpired, showLogin } from "./auth.js";
import { createCoachView } from "./coach.js";
import { initDeckUpload } from "./deck.js";
import * as practice from "./practice.js";
import { drawChart as drawProgressChart, showProgress } from "./progress.js";
import { Recorder, fileNameFor } from "./recorder.js";
import { createResultView, redrawCharts } from "./results.js";
import { currentPath, fallback, navigate, route, startRouter } from "./router.js";
import { leaveSession, showSession } from "./session.js";

const $ = (id) => document.getElementById(id);
const VIEWS = ["home", "login", "practice", "progress", "session"];
const NAV_FOR_VIEW = { home: "home", practice: "home", progress: "progress", session: "progress" };
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
  if (name !== "practice" && recorder.state !== "idle") recorder.stop();
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

function setStatus(message) {
  $("status").textContent = message;
}

function resetAttempt() {
  audioBlob = null;
  $("analyzeBtn").disabled = true;
  const preview = $("audioPreview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.removeAttribute("src");
  preview.classList.add("hidden");
  $("stage").classList.add("hidden");
  practiceResults.hide();
  practiceCoach.hide();
}

function openPractice(modeId) {
  showView("practice");
  const changed = practice.selectMode(modeId);
  if (changed) resetAttempt();
  document.querySelectorAll(".mode-pill").forEach((pill) => pill.classList.toggle("active", pill.dataset.mode === practice.currentMode().id));
  if (recorder.state === "idle" && !audioBlob) {
    setStatus(getUser() ? "Set things up, then press Start when you're ready." : "Press Start to log in and begin recording.");
  }
}

function showStage() {
  const content = practice.stageContent();
  $("stage").classList.remove("hidden");
  $("stageTitle").textContent = content.title;
  $("stagePrompt").textContent = content.text || "";
  $("stagePrompt").classList.toggle("hidden", !content.text);
  $("teleprompter").textContent = content.script || "";
  $("teleprompter").classList.toggle("hidden", !content.script);
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
  if (!requireLogin(currentPath())) return;
  const problem = practice.validate();
  if (problem) {
    setStatus(problem);
    return;
  }
  practice.prepareAttempt();
  const { prepSeconds, limitSeconds } = practice.timerSettings();
  activeLimit = limitSeconds;
  activePrep = prepSeconds;
  resetAttempt();
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
    practiceResults.render(result, practice.currentMode());
    setStatus("Analysis complete. It's saved to My progress, where you can replay it any time.");
    if (result.coach_available) practiceCoach.request(result.id);
    else practiceCoach.hide();
    practiceResults.root.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (error.status === 401) return onSessionExpired();
    setStatus(error.message);
  } finally {
    $("analyzeBtn").disabled = !audioBlob;
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
  if (!$("view-practice").classList.contains("hidden") && recorder.state === "idle" && !audioBlob) {
    setStatus(user ? "Set things up, then press Start when you're ready." : "Press Start to log in and begin recording.");
  }
});

// ---------- Start-up ----------

document.querySelectorAll("[data-scroll]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    $(link.dataset.scroll).scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
$("startBtn").addEventListener("click", startPractice);
$("stopBtn").addEventListener("click", () => recorder.stop());
$("analyzeBtn").addEventListener("click", analyzeRecording);
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
    practice.initPractice();
    initDeckUpload({
      getTopicAndTarget: practice.presentationContext,
      requireLogin: () => requireLogin(currentPath()),
      onSessionExpired,
    });
    practiceResults = createResultView($("practiceResults"));
    practiceCoach = createCoachView($("practiceCoach"), onSessionExpired);
    startRouter();
  })
  .catch(() => {
    $("modeGrid").textContent = "Could not load the practice modes. Check that the server is running, then refresh.";
  });
