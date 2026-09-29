const API_BASE = "";

let mediaRecorder;
let audioChunks = [];
let audioBlob;
let currentUser = null;
let historyCache = [];
let recordingTimeoutId = null;

const authShell = document.getElementById("authShell");
const appShell = document.getElementById("appShell");
const authStatus = document.getElementById("authStatus");
const welcomeUser = document.getElementById("welcomeUser");

const tabButtons = document.querySelectorAll(".tab-btn");
const tabGlider = document.getElementById("tabGlider");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");

const registerPassword = document.getElementById("registerPassword");
const strengthBar = document.getElementById("strengthBar");
const strengthLabel = document.getElementById("strengthLabel");

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const analyzeBtn = document.getElementById("analyzeBtn");
const statusText = document.getElementById("status");
const logoutBtn = document.getElementById("logoutBtn");
const trackerBtn = document.getElementById("trackerBtn");
const historyPanel = document.getElementById("historyPanel");
const historySummary = document.getElementById("historySummary");
const historyList = document.getElementById("historyList");
const progressChart = document.getElementById("progressChart");
const minutesInput = document.getElementById("minutes");
const secondsInput = document.getElementById("seconds");
const themeToggle = document.getElementById("themeToggle");

const THEME_STORAGE_KEY = "cta_theme";
const SUB_SCORE_LABELS = {
  pace: "Pace",
  fluency: "Fluency",
  pauses: "Pausing",
  expressiveness: "Expressiveness",
  vocal_confidence: "Vocal confidence",
};
const CONTENT_SCORE_LABELS = {
  structure: "Structure",
  clarity: "Clarity",
  relevance: "Relevance",
  depth: "Depth",
};

let practiceMode = "topic";
let questionBank = null;
let currentQuestion = null;
let lastAnalysisId = null;

function getThemeValue(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function applyTheme(theme) {
  const resolved = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", resolved);
  if (themeToggle) {
    themeToggle.textContent = resolved === "light" ? "Dark Theme" : "Light Theme";
  }
}

function initializeTheme() {
  let saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved !== "light" && saved !== "dark") {
    saved = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  applyTheme(saved);
}

function setAuthStatus(message, type = "") {
  authStatus.className = "status-line";
  if (type === "error") authStatus.classList.add("status-error");
  if (type === "ok") authStatus.classList.add("status-ok");
  authStatus.textContent = message;
}

function setActiveTab(tabName) {
  tabButtons.forEach((btn, index) => {
    const isActive = btn.dataset.tab === tabName;
    btn.classList.toggle("active", isActive);
    if (isActive) {
      tabGlider.style.transform = `translateX(${index * 100}%)`;
    }
  });

  loginForm.classList.toggle("active", tabName === "login");
  registerForm.classList.toggle("active", tabName === "register");
  setAuthStatus("");
}

function scorePassword(password) {
  let score = 0;
  if (password.length >= 8) score += 1;
  if (/[A-Z]/.test(password)) score += 1;
  if (/[0-9]/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  return score;
}

function updatePasswordStrength() {
  const score = scorePassword(registerPassword.value);
  const widths = ["20%", "35%", "60%", "80%", "100%"];
  const labels = ["weak", "fair", "good", "strong", "excellent"];
  const colors = ["#ef4444", "#f97316", "#f59e0b", "#3b82f6", "#1d4ed8"];

  strengthBar.style.width = widths[score];
  strengthBar.style.backgroundColor = colors[score];
  strengthLabel.textContent = `Password strength: ${labels[score]}`;
}

function hideTrackerPanel() {
  historyPanel.classList.add("hidden");
  trackerBtn.textContent = "My Speech Tracker";
}

function showTrackerPanel() {
  historyPanel.classList.remove("hidden");
  trackerBtn.textContent = "Hide Speech Tracker";
  requestAnimationFrame(() => drawProgressChart(historyCache));
}

function showApp(user) {
  currentUser = user;
  welcomeUser.textContent = user?.name || "Speaker";
  authShell.classList.add("hidden");
  appShell.classList.remove("hidden");
  statusText.textContent = "Click start to record";
  hideTrackerPanel();
  loadUserHistory();
  loadQuestionBank();
}

function showAuth() {
  currentUser = null;
  historyCache = [];
  renderHistory([]);
  hideTrackerPanel();
  appShell.classList.add("hidden");
  authShell.classList.remove("hidden");
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);

  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    const error = new Error(data.error || "Request failed.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function postJson(url, payload) {
  return requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function handleSessionExpired() {
  showAuth();
  setAuthStatus("Your session has expired. Please log in again.", "error");
}

function formatDateLabel(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatDuration(minutes, seconds) {
  const safeMinutes = Math.max(0, Number.parseInt(minutes, 10) || 0);
  const safeSeconds = Math.max(0, Number.parseInt(seconds, 10) || 0);
  const totalSeconds = (safeMinutes * 60) + safeSeconds;
  const normalizedMinutes = Math.floor(totalSeconds / 60);
  const normalizedSeconds = totalSeconds % 60;
  return `${normalizedMinutes}m ${String(normalizedSeconds).padStart(2, "0")}s`;
}

function getSelectedDurationSeconds() {
  const inputMinutes = Math.max(0, Number.parseInt(minutesInput.value, 10) || 0);
  const inputSeconds = Math.max(0, Number.parseInt(secondsInput.value, 10) || 0);
  const totalSeconds = (inputMinutes * 60) + inputSeconds;
  minutesInput.value = String(Math.floor(totalSeconds / 60));
  secondsInput.value = String(totalSeconds % 60);
  return totalSeconds;
}

function describeLevel(value) {
  if (value >= 0.55) return "high";
  if (value >= 0.4) return "medium";
  return "low";
}

function pickRandom(items, avoid) {
  const pool = items.length > 1 ? items.filter((item) => item !== avoid) : items;
  return pool[Math.floor(Math.random() * pool.length)];
}

function selectedCategory() {
  const categoryId = document.getElementById("questionCategory").value;
  return questionBank?.categories.find((category) => category.id === categoryId);
}

function showNextQuestion() {
  const category = selectedCategory();
  if (!category) return;
  currentQuestion = pickRandom(category.questions, currentQuestion);
  document.getElementById("questionText").textContent = currentQuestion.text;
  document.getElementById("questionFramework").textContent =
    `${category.framework.name}: ${category.framework.parts.join(" → ")}`;
  document.getElementById("questionHint").textContent = category.framework.description;
}

async function loadQuestionBank() {
  if (questionBank) return;
  try {
    questionBank = await requestJson(`${API_BASE}/questions`);
  } catch {
    document.getElementById("questionText").textContent = "Could not load interview questions.";
    return;
  }
  const select = document.getElementById("questionCategory");
  select.textContent = "";
  questionBank.categories.forEach((category) => {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = `${category.label} (${category.framework.name})`;
    select.appendChild(option);
  });
  showNextQuestion();
}

function setPracticeMode(mode) {
  practiceMode = mode;
  document.querySelectorAll(".mode-btn").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.getElementById("topicPanel").classList.toggle("hidden", mode !== "topic");
  document.getElementById("interviewPanel").classList.toggle("hidden", mode !== "interview");
}

function renderScoreBars(containerId, labels, scores) {
  const container = document.getElementById(containerId);
  container.textContent = "";
  Object.entries(labels).forEach(([key, label]) => {
    const value = scores?.[key];
    const row = document.createElement("div");
    row.className = "breakdown-row";

    const name = document.createElement("span");
    name.textContent = label;

    const track = document.createElement("div");
    track.className = "breakdown-track";
    const bar = document.createElement("div");
    bar.className = "breakdown-bar";
    bar.style.width = value == null ? "0%" : `${value * 10}%`;
    track.appendChild(bar);

    const number = document.createElement("span");
    number.className = "breakdown-value";
    number.textContent = value == null ? "n/a" : value.toFixed(1);

    row.append(name, track, number);
    container.appendChild(row);
  });
}

function renderTranscript(result) {
  const container = document.getElementById("transcription");
  container.textContent = "";
  if (!Array.isArray(result.words) || !result.words.length) {
    container.textContent = result.transcription || "-";
    return;
  }

  const pausesBefore = new Map(
    (result.pauses || []).filter((pause) => pause.kind === "hesitation").map((pause) => [pause.before_word, pause])
  );
  result.words.forEach((word, index) => {
    const pause = pausesBefore.get(index);
    if (pause) {
      const chip = document.createElement("span");
      chip.className = "pause-chip";
      chip.title = "Hesitation pause";
      chip.textContent = `${pause.duration.toFixed(1)}s`;
      container.append(chip, " ");
    }
    const span = document.createElement("span");
    span.textContent = word.text;
    if (word.filler) span.className = "filler";
    container.append(span, " ");
  });
}

function renderResult(result) {
  const metrics = result.metrics || {};
  document.getElementById("score").textContent = result.score ?? "-";
  document.getElementById("delivery").textContent = result.delivery || "-";
  document.getElementById("resultMeta").textContent = [
    `${formatDuration(result.minutes, result.seconds)} (${Math.round(metrics.speaking_span || 0)}s speaking)`,
    `${metrics.wpm ?? "-"} WPM`,
    `${metrics.filler_count ?? 0} fillers`,
    `${metrics.hesitation_pause_count ?? 0} hesitation pauses`,
  ].join(" · ");

  renderScoreBars("breakdown", SUB_SCORE_LABELS, result.sub_scores);

  const tone = result.vocal_tone;
  document.getElementById("vocalTone").textContent = tone
    ? `Energy ${describeLevel(tone.arousal)} · Assertiveness ${describeLevel(tone.dominance)} · Positivity ${describeLevel(tone.valence)}`
    : "Not available (emotion model not installed)";

  const match = result.topic_match;
  document.getElementById("topicRelated").textContent = match
    ? `${match.related ? "Yes" : "No"} (semantic similarity ${match.similarity.toFixed(2)})`
    : "No topic provided";

  renderTranscript(result);
  document.getElementById("feedback").textContent = result.feedback || "-";
  document.getElementById("resultPanel").classList.remove("hidden");
}

function fillList(listId, items, renderItem) {
  const list = document.getElementById(listId);
  list.textContent = "";
  items.forEach((item) => {
    const li = document.createElement("li");
    renderItem(li, item);
    list.appendChild(li);
  });
}

function renderCoach(coachResult) {
  document.getElementById("contentScore").textContent = coachResult.content_score;
  document.getElementById("coachTitle").textContent = coachResult.on_topic ? "Content review" : "Content review: off-topic";
  const meta = coachResult.meta || {};
  document.getElementById("coachMeta").textContent =
    meta.model ? `Generated by ${meta.model} via ${meta.provider}${meta.latency_ms ? ` in ${(meta.latency_ms / 1000).toFixed(1)}s` : ""}` : "";
  document.getElementById("coachSummary").textContent = coachResult.summary;
  renderScoreBars("contentBreakdown", CONTENT_SCORE_LABELS, coachResult.content_scores);

  const framework = coachResult.framework;
  document.getElementById("frameworkTitle").textContent = `${framework.name} check`;
  const chips = document.getElementById("frameworkChips");
  chips.textContent = "";
  framework.parts.forEach((part) => {
    const chip = document.createElement("span");
    const present = framework.present.includes(part);
    chip.className = present ? "chip chip-present" : "chip chip-missing";
    chip.textContent = `${present ? "✓" : "✗"} ${part}`;
    chips.appendChild(chip);
  });

  fillList("coachStrengths", coachResult.strengths, (li, text) => {
    li.textContent = text;
  });
  fillList("coachImprovements", coachResult.improvements, (li, item) => {
    const issue = document.createElement("b");
    issue.textContent = item.issue;
    li.append(issue, document.createElement("br"), item.suggestion);
  });
  document.getElementById("coachTopic").textContent = coachResult.topic_feedback;
  document.getElementById("improvedTitle").textContent =
    coachResult.improved_answer_type === "template"
      ? "A structure to follow (fill in your own details)"
      : "A stronger version of your answer";
  document.getElementById("improvedAnswer").textContent = coachResult.improved_answer;
  document.getElementById("coachBody").classList.remove("hidden");
}

function showCoachMessage(title, message, canRetry) {
  document.getElementById("contentScore").textContent = "-";
  document.getElementById("coachTitle").textContent = title;
  document.getElementById("coachMeta").textContent = message;
  document.getElementById("coachBody").classList.add("hidden");
  document.getElementById("retryCoachBtn").classList.toggle("hidden", !canRetry);
}

async function requestCoaching(analysisId) {
  const panel = document.getElementById("coachPanel");
  panel.classList.remove("hidden");
  showCoachMessage("Reviewing your answer...", "The AI coach is reading your transcript.", false);
  try {
    const data = await requestJson(`${API_BASE}/analyses/${analysisId}/coach`, { method: "POST" });
    if (analysisId !== lastAnalysisId) return;
    renderCoach(data.coach);
  } catch (error) {
    if (analysisId !== lastAnalysisId) return;
    if (error.status === 401) {
      handleSessionExpired();
      return;
    }
    const retryable = [429, 503, 504].includes(error.status);
    showCoachMessage("AI coach unavailable", error.message, retryable);
  }
}

function drawProgressChart(entries) {
  const canvas = progressChart;
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const cssWidth = Math.max(320, Math.floor(canvas.getBoundingClientRect().width || 320));
  const cssHeight = 240;
  const dpr = window.devicePixelRatio || 1;

  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  if (!entries.length) {
    ctx.fillStyle = getThemeValue("--chart-text", "rgba(148, 163, 184, 0.9)");
    ctx.font = '15px "Space Grotesk", sans-serif';
    ctx.fillText("No sessions yet. Run analysis to build your progress graph.", 20, 124);
    return;
  }

  const padding = { left: 42, right: 20, top: 20, bottom: 34 };
  const plotW = cssWidth - padding.left - padding.right;
  const plotH = cssHeight - padding.top - padding.bottom;
  const scores = entries.map((entry) => Number(entry.score) || 0);
  const maxScore = 10;
  const minScore = 0;

  ctx.strokeStyle = getThemeValue("--chart-grid", "rgba(148, 163, 184, 0.22)");
  ctx.fillStyle = getThemeValue("--chart-text", "rgba(148, 163, 184, 0.9)");
  ctx.font = '12px "Space Grotesk", sans-serif';

  for (let tick = minScore; tick <= maxScore; tick += 2) {
    const y = padding.top + ((maxScore - tick) / (maxScore - minScore)) * plotH;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(cssWidth - padding.right, y);
    ctx.stroke();
    ctx.fillText(String(tick), 12, y + 4);
  }

  const xAt = (index) => {
    if (scores.length === 1) return padding.left + plotW / 2;
    return padding.left + (index * plotW) / (scores.length - 1);
  };

  const yAt = (score) => padding.top + ((maxScore - score) / (maxScore - minScore)) * plotH;

  ctx.strokeStyle = getThemeValue("--chart-line", "#3b82f6");
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  scores.forEach((score, index) => {
    const x = xAt(index);
    const y = yAt(score);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = getThemeValue("--chart-point", "#38bdf8");
  scores.forEach((score, index) => {
    const x = xAt(index);
    const y = yAt(score);
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = getThemeValue("--chart-text", "rgba(148, 163, 184, 0.95)");
  const firstLabel = formatDateLabel(entries[0].timestamp);
  const lastLabel = formatDateLabel(entries[entries.length - 1].timestamp);
  ctx.fillText(firstLabel, padding.left, cssHeight - 10);
  ctx.fillText(lastLabel, cssWidth - padding.right - 62, cssHeight - 10);
}

function renderHistory(entries) {
  historyList.textContent = "";
  historyCache = entries;

  if (!entries.length) {
    historySummary.textContent = "No history yet. Complete your first analysis.";
    drawProgressChart([]);
    return;
  }

  const firstScore = Number(entries[0].score) || 0;
  const latest = entries[entries.length - 1];
  const latestScore = Number(latest.score) || 0;
  const delta = +(latestScore - firstScore).toFixed(1);
  const trend = delta > 0 ? `+${delta}` : `${delta}`;

  historySummary.textContent =
    `Sessions: ${entries.length} | Latest score: ${latestScore}/10 | Overall trend: ${trend}`;

  entries
    .slice(-5)
    .reverse()
    .forEach((entry) => {
      const item = document.createElement("div");
      item.className = "history-item";

      const title = document.createElement("p");
      title.textContent = `${formatDateLabel(entry.timestamp)} - Score ${entry.score}/10 - ${entry.delivery}`;

      const meta = document.createElement("p");
      meta.className = "meta";
      meta.textContent = `Duration: ${formatDuration(entry.minutes, entry.seconds)} | WPM: ${entry.wpm} | Fillers: ${entry.filler_count} | Topic: ${entry.topic || "General"}`;

      item.append(title, meta);
      historyList.appendChild(item);
    });

  drawProgressChart(entries);
}

async function loadUserHistory() {
  if (!currentUser?.email) {
    renderHistory([]);
    return;
  }

  try {
    const result = await requestJson(`${API_BASE}/history`);
    const entries = Array.isArray(result.history) ? result.history : [];
    entries.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    renderHistory(entries);
  } catch (error) {
    if (error.status === 401) {
      handleSessionExpired();
      return;
    }
    historySummary.textContent = "Unable to load history right now.";
    drawProgressChart([]);
  }
}

tabButtons.forEach((button) => {
  button.addEventListener("click", () => setActiveTab(button.dataset.tab));
});

document.querySelectorAll(".ghost-icon").forEach((button) => {
  button.addEventListener("click", () => {
    const targetId = button.dataset.toggle;
    const input = document.getElementById(targetId);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Hide" : "Show";
  });
});

registerPassword.addEventListener("input", updatePasswordStrength);

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("loginEmail").value.trim();
  const password = document.getElementById("loginPassword").value;

  const loginSubmit = document.getElementById("loginSubmit");
  loginSubmit.disabled = true;
  loginSubmit.textContent = "Signing In...";
  setAuthStatus("Authenticating...");

  try {
    const result = await postJson(`${API_BASE}/login`, { email, password });
    setAuthStatus(result.message, "ok");
    showApp(result.user);
  } catch (error) {
    setAuthStatus(error.message, "error");
  } finally {
    loginSubmit.disabled = false;
    loginSubmit.textContent = "Sign In";
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = document.getElementById("registerName").value.trim();
  const email = document.getElementById("registerEmail").value.trim();
  const password = document.getElementById("registerPassword").value;

  const registerSubmit = document.getElementById("registerSubmit");
  registerSubmit.disabled = true;
  registerSubmit.textContent = "Creating...";
  setAuthStatus("Creating your account...");

  try {
    const result = await postJson(`${API_BASE}/register`, { name, email, password });
    setAuthStatus(`${result.message} Please log in.`, "ok");
    registerForm.reset();
    updatePasswordStrength();
    setActiveTab("login");
    document.getElementById("loginEmail").value = email;
  } catch (error) {
    setAuthStatus(error.message, "error");
  } finally {
    registerSubmit.disabled = false;
    registerSubmit.textContent = "Create Account";
  }
});

logoutBtn.addEventListener("click", async () => {
  try {
    await postJson(`${API_BASE}/logout`, {});
  } catch {
    // The server session is gone either way; still return to the login screen.
  }
  showAuth();
});

trackerBtn.addEventListener("click", () => {
  window.location.href = "/tracker";
});

if (themeToggle) {
  themeToggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    const nextTheme = currentTheme === "light" ? "dark" : "light";
    localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    applyTheme(nextTheme);
    drawProgressChart(historyCache);
  });
}

startBtn.addEventListener("click", async () => {
  const selectedDurationSeconds = getSelectedDurationSeconds();
  if (selectedDurationSeconds <= 0) {
    statusText.textContent = "Set duration above 0 seconds.";
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.start();

    audioChunks = [];
    audioBlob = null;
    analyzeBtn.disabled = true;
    statusText.textContent = "Recording in progress...";
    mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
    mediaRecorder.onstop = () => {
      audioBlob = new Blob(audioChunks, { type: "audio/webm" });
      mediaRecorder.stream.getTracks().forEach((track) => track.stop());
      analyzeBtn.disabled = false;
      if (recordingTimeoutId) {
        clearTimeout(recordingTimeoutId);
        recordingTimeoutId = null;
      }
    };
    if (recordingTimeoutId) clearTimeout(recordingTimeoutId);
    recordingTimeoutId = setTimeout(() => {
      if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
        statusText.textContent = "Recording stopped at selected duration.";
        startBtn.disabled = false;
        stopBtn.disabled = true;
      }
    }, selectedDurationSeconds * 1000);

    startBtn.disabled = true;
    stopBtn.disabled = false;
  } catch (error) {
    if (recordingTimeoutId) {
      clearTimeout(recordingTimeoutId);
      recordingTimeoutId = null;
    }
    statusText.textContent = "Microphone access denied.";
  }
});

stopBtn.addEventListener("click", () => {
  if (!mediaRecorder || mediaRecorder.state !== "recording") {
    return;
  }
  if (recordingTimeoutId) {
    clearTimeout(recordingTimeoutId);
    recordingTimeoutId = null;
  }

  mediaRecorder.stop();
  statusText.textContent = "Recording stopped.";

  startBtn.disabled = false;
  stopBtn.disabled = true;
});

analyzeBtn.addEventListener("click", async () => {
  if (!audioBlob) return;

  statusText.textContent = "Analyzing speech...";
  analyzeBtn.disabled = true;

  try {
    const formData = new FormData();
    formData.append("audio", audioBlob, "recording.webm");
    formData.append("mode", practiceMode);
    if (practiceMode === "interview" && currentQuestion) {
      formData.append("question_id", currentQuestion.id);
    } else {
      formData.append("topic", document.getElementById("topic").value.trim());
    }

    const result = await requestJson(`${API_BASE}/analyze`, {
      method: "POST",
      body: formData,
    });

    lastAnalysisId = result.id;
    renderResult(result);
    statusText.textContent = "Analysis complete.";
    if (result.coach_available) {
      requestCoaching(result.id);
    } else {
      document.getElementById("coachPanel").classList.add("hidden");
    }
    await loadUserHistory();
  } catch (error) {
    if (error.status === 401) {
      handleSessionExpired();
      return;
    }
    statusText.textContent = error.message;
  } finally {
    analyzeBtn.disabled = false;
  }
});

document.querySelectorAll(".mode-btn").forEach((button) => {
  button.addEventListener("click", () => setPracticeMode(button.dataset.mode));
});

document.getElementById("questionCategory").addEventListener("change", showNextQuestion);
document.getElementById("nextQuestionBtn").addEventListener("click", showNextQuestion);

document.getElementById("suggestTopicBtn").addEventListener("click", async () => {
  await loadQuestionBank();
  if (!questionBank?.topics?.length) return;
  const topicInput = document.getElementById("topic");
  topicInput.value = pickRandom(questionBank.topics, topicInput.value);
});

document.getElementById("retryCoachBtn").addEventListener("click", () => {
  if (lastAnalysisId) requestCoaching(lastAnalysisId);
});

document.getElementById("copyImprovedBtn").addEventListener("click", async () => {
  const button = document.getElementById("copyImprovedBtn");
  try {
    await navigator.clipboard.writeText(document.getElementById("improvedAnswer").textContent);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy failed";
  }
  setTimeout(() => {
    button.textContent = "Copy";
  }, 1500);
});

async function restoreSession() {
  try {
    const result = await requestJson(`${API_BASE}/me`);
    showApp(result.user);
  } catch {
    // Not logged in; the login form is already showing.
  }
}

restoreSession();

window.addEventListener("resize", () => drawProgressChart(historyCache));

initializeTheme();
updatePasswordStrength();
renderHistory([]);
