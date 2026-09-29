// Helpers shared by the analyzer and tracker pages.
export const API_BASE = "";
const THEME_STORAGE_KEY = "cta_theme";

export async function requestJson(url, options = {}) {
  const response = await fetch(`${API_BASE}${url}`, options);

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

export function postJson(url, payload) {
  return requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getThemeValue(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function applyTheme(theme, toggle) {
  const resolved = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", resolved);
  if (toggle) toggle.textContent = resolved === "light" ? "Dark Theme" : "Light Theme";
}

// Applies the saved (or system) theme and wires the toggle button; onChange redraws charts.
export function initializeTheme(toggle, onChange = () => {}) {
  let saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved !== "light" && saved !== "dark") {
    saved = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  applyTheme(saved, toggle);
  toggle?.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    localStorage.setItem(THEME_STORAGE_KEY, next);
    applyTheme(next, toggle);
    onChange();
  });
}

export function formatClock(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function formatDuration(minutes, seconds) {
  const total = Math.max(0, (Number.parseInt(minutes, 10) || 0) * 60 + (Number.parseInt(seconds, 10) || 0));
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
}

export function formatDateLabel(timestamp, withTime = false) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  const options = withTime
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { month: "short", day: "numeric" };
  return date.toLocaleString(undefined, options);
}

// Creates an element with an optional class and text content.
export function el(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== "") element.textContent = text;
  return element;
}

export function pickRandom(items, avoid) {
  const pool = items.length > 1 ? items.filter((item) => item !== avoid) : items;
  return pool[Math.floor(Math.random() * pool.length)];
}

export const SKILL_LABELS = {
  pace: "Pace",
  fluency: "Fluency",
  pauses: "Pausing",
  expressiveness: "Expressiveness",
  vocal_confidence: "Vocal confidence",
  language: "Confident language",
  accuracy: "Reading accuracy",
  phrasing: "Phrasing",
  timing: "Timing",
  variety: "Word variety",
};

// Draws score bars (0-10) into a container, in the order of `labels`.
export function renderScoreBars(container, labels, scores) {
  container.textContent = "";
  labels.forEach(([key, label]) => {
    const value = scores?.[key];
    const row = el("div", "breakdown-row");
    const track = el("div", "breakdown-track");
    const bar = el("div", "breakdown-bar");
    bar.style.width = value == null ? "0%" : `${value * 10}%`;
    track.appendChild(bar);
    row.append(el("span", "", label), track, el("span", "breakdown-value", value == null ? "n/a" : value.toFixed(1)));
    container.appendChild(row);
  });
}
