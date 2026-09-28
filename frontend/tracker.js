const API_BASE = "";

const trackerUser = document.getElementById("trackerUser");
const historySummary = document.getElementById("historySummary");
const historyList = document.getElementById("historyList");
const progressChart = document.getElementById("progressChart");
const backBtn = document.getElementById("backBtn");
const logoutBtn = document.getElementById("logoutBtn");
const themeToggle = document.getElementById("themeToggle");

let historyCache = [];
const THEME_STORAGE_KEY = "cta_theme";

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

function formatDateLabel(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(minutes, seconds) {
  const safeMinutes = Math.max(0, Number.parseInt(minutes, 10) || 0);
  const safeSeconds = Math.max(0, Number.parseInt(seconds, 10) || 0);
  const totalSeconds = (safeMinutes * 60) + safeSeconds;
  const normalizedMinutes = Math.floor(totalSeconds / 60);
  const normalizedSeconds = totalSeconds % 60;
  return `${normalizedMinutes}m ${String(normalizedSeconds).padStart(2, "0")}s`;
}

function drawProgressChart(entries) {
  const canvas = progressChart;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const cssWidth = Math.max(320, Math.floor(canvas.getBoundingClientRect().width || 320));
  const cssHeight = 260;
  const dpr = window.devicePixelRatio || 1;

  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  if (!entries.length) {
    ctx.fillStyle = getThemeValue("--chart-text", "rgba(148, 163, 184, 0.9)");
    ctx.font = '15px "Space Grotesk", sans-serif';
    ctx.fillText("No sessions found. Analyze your speech to generate progress data.", 20, 132);
    return;
  }

  const padding = { left: 44, right: 20, top: 20, bottom: 34 };
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
  const firstLabel = formatDateLabel(entries[0].timestamp).split(",")[0];
  const lastLabel = formatDateLabel(entries[entries.length - 1].timestamp).split(",")[0];
  ctx.fillText(firstLabel, padding.left, cssHeight - 10);
  ctx.fillText(lastLabel, cssWidth - padding.right - 70, cssHeight - 10);
}

function renderHistory(entries) {
  historyCache = entries;
  historyList.textContent = "";

  if (!entries.length) {
    historySummary.textContent = "No history yet. Go back and run your first analysis.";
    drawProgressChart([]);
    return;
  }

  const firstScore = Number(entries[0].score) || 0;
  const latestScore = Number(entries[entries.length - 1].score) || 0;
  const delta = +(latestScore - firstScore).toFixed(1);
  const trend = delta > 0 ? `+${delta}` : `${delta}`;

  historySummary.textContent =
    `Total sessions: ${entries.length} | Latest score: ${latestScore}/10 | Trend: ${trend}`;

  entries
    .slice(-10)
    .reverse()
    .forEach((entry) => {
      const item = document.createElement("div");
      item.className = "history-item";

      const title = document.createElement("p");
      title.textContent = `${formatDateLabel(entry.timestamp)} - Score ${entry.score}/10 - ${entry.emotion}`;

      const meta = document.createElement("p");
      meta.className = "meta";
      meta.textContent = `Duration: ${formatDuration(entry.minutes, entry.seconds)} | WPM: ${entry.wpm} | Fillers: ${entry.filler_count} | Topic: ${entry.topic || "General"}`;

      item.append(title, meta);
      historyList.appendChild(item);
    });

  drawProgressChart(entries);
}

async function loadHistory() {
  try {
    const result = await requestJson(`${API_BASE}/history`);
    const entries = Array.isArray(result.history) ? result.history : [];
    entries.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    renderHistory(entries);
  } catch (error) {
    if (error.status === 401) {
      window.location.href = "/";
      return;
    }
    historySummary.textContent = error.message || "Unable to load history right now.";
    drawProgressChart([]);
  }
}

async function bootstrap() {
  let user;
  try {
    user = (await requestJson(`${API_BASE}/me`)).user;
  } catch {
    window.location.href = "/";
    return;
  }

  trackerUser.textContent = `${user.name || "Speaker"} - Progress Overview`;
  loadHistory();
}

backBtn.addEventListener("click", () => {
  window.location.href = "/";
});

logoutBtn.addEventListener("click", async () => {
  try {
    await requestJson(`${API_BASE}/logout`, { method: "POST" });
  } catch {
    // Return to the login screen even if the request failed.
  }
  window.location.href = "/";
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

window.addEventListener("resize", () => drawProgressChart(historyCache));

initializeTheme();
bootstrap();
