// Progress page: stats, focus areas, skill trends and session history, filterable by mode.
import { el, formatDateLabel, formatDuration, initializeTheme, postJson, requestJson } from "./common.js";
import { drawLineChart } from "./charts.js";

const $ = (id) => document.getElementById(id);
let history = [];
let modeLabels = {};
let activeMode = null;

function filtered() {
  return activeMode ? history.filter((entry) => (entry.mode || "free") === activeMode) : history;
}

function renderFilter(summary) {
  const container = $("modeFilter");
  container.textContent = "";
  const options = [{ id: null, label: "All modes", count: summary.total_sessions }, ...summary.modes.filter((mode) => mode.count)];
  options.forEach((option) => {
    const button = el("button", option.id === activeMode ? "active" : "", `${option.label} (${option.count})`);
    button.type = "button";
    button.addEventListener("click", () => {
      activeMode = option.id;
      loadProgress();
    });
    container.appendChild(button);
  });
}

function renderSkills(skills) {
  const container = $("skillList");
  container.textContent = "";
  if (!skills.length) {
    container.appendChild(el("p", "result-meta", "Skill scores appear after your first analysis with the new modes."));
    return;
  }
  skills.forEach((skill) => {
    const row = el("div", "breakdown-row skill-row");
    const track = el("div", "breakdown-track");
    const bar = el("div", "breakdown-bar");
    bar.style.width = `${skill.recent * 10}%`;
    track.appendChild(bar);
    const change = skill.change;
    const trend = el("span", `trend ${change > 0 ? "trend-up" : change < 0 ? "trend-down" : ""}`);
    trend.textContent = change == null ? "" : `${change > 0 ? "↑ +" : change < 0 ? "↓ " : ""}${change === 0 ? "±0" : change}`;
    trend.title = change == null ? "" : `Previous 5 sessions: ${skill.previous}/10`;
    row.append(el("span", "", skill.label), track, el("span", "breakdown-value", skill.recent.toFixed(1)), trend);
    container.appendChild(row);
  });
}

function renderFocus(summary) {
  const list = $("focusList");
  list.textContent = "";
  if (!summary.focus.length) {
    list.appendChild(el("li", "", summary.sessions ? "No weak spots right now. Keep practising to stay sharp." : "Record a session to find your focus areas."));
  }
  summary.focus.forEach((item) => {
    const li = el("li");
    li.append(el("b", "", `${item.label} (${item.average}/10)`), el("br"), item.reason);
    list.appendChild(li);
  });
  $("suggestionText").textContent = `Next: ${summary.suggestion.label}. ${summary.suggestion.reason}`;
  $("suggestionLink").href = `/?mode=${encodeURIComponent(summary.suggestion.mode)}`;
  $("suggestionLink").textContent = `Practise ${summary.suggestion.label}`;
}

function renderHistory() {
  const entries = filtered();
  const list = $("historyList");
  list.textContent = "";
  if (!entries.length) {
    $("historySummary").textContent = "No sessions yet. Go back and record your first one.";
  } else {
    const first = Number(entries[0].score) || 0;
    const latest = Number(entries[entries.length - 1].score) || 0;
    const delta = +(latest - first).toFixed(1);
    $("historySummary").textContent = `Trend since your first session: ${delta > 0 ? "+" : ""}${delta}`;
  }
  entries
    .slice(-10)
    .reverse()
    .forEach((entry) => {
      const item = el("div", "history-item");
      const mode = modeLabels[entry.mode || "free"] || "Free practice";
      item.append(
        el("p", "", `${formatDateLabel(entry.timestamp, true)} · ${mode} · ${entry.score}/10 · ${entry.delivery}`),
        el(
          "p",
          "meta",
          `${entry.topic ? `${entry.topic} · ` : ""}${formatDuration(entry.minutes, entry.seconds)} · ${entry.wpm} WPM · ` +
            `${entry.filler_count} filler${entry.filler_count === 1 ? "" : "s"}`
        )
      );
      list.appendChild(item);
    });
  drawChart();
}

function drawChart() {
  const entries = filtered();
  drawLineChart($("progressChart"), {
    values: entries.map((entry) => Number(entry.score) || 0),
    min: 0,
    max: 10,
    ticks: [0, 2, 4, 6, 8, 10],
    labels: entries.map((entry) => formatDateLabel(entry.timestamp)),
    height: 240,
    emptyText: "No sessions yet. Analyze your speech to build your progress graph.",
  });
}

async function loadProgress() {
  try {
    const query = activeMode ? `?mode=${encodeURIComponent(activeMode)}` : "";
    const summary = await requestJson(`/progress${query}`);
    modeLabels = Object.fromEntries(summary.modes.map((mode) => [mode.id, mode.label]));
    $("statSessions").textContent = summary.sessions;
    $("statLatest").textContent = summary.latest_score ?? "-";
    $("statBest").textContent = summary.best?.score ?? "-";
    $("statStreak").textContent = summary.streak;
    renderFilter(summary);
    renderFocus(summary);
    renderSkills(summary.skills);
    renderHistory();
  } catch (error) {
    if (error.status === 401) window.location.href = "/";
    else $("historySummary").textContent = error.message || "Unable to load your progress right now.";
  }
}

async function bootstrap() {
  let user;
  try {
    user = (await requestJson("/me")).user;
  } catch {
    window.location.href = "/";
    return;
  }
  $("trackerUser").textContent = `${user.name || "Speaker"}'s progress`;
  history = (await requestJson("/history")).history;
  history.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  loadProgress();
}

$("backBtn").addEventListener("click", () => {
  window.location.href = "/";
});
$("logoutBtn").addEventListener("click", async () => {
  try {
    await postJson("/logout", {});
  } catch {
    // Return to the login screen even if the request failed.
  }
  window.location.href = "/";
});
window.addEventListener("resize", drawChart);

initializeTheme($("themeToggle"), drawChart);
bootstrap();
