// Renders an /analyze response: scores, annotated transcript and the mode-specific panels.
import { SKILL_LABELS, el, formatClock, formatDuration, renderScoreBars } from "./common.js";
import { drawLineChart } from "./charts.js";

const $ = (id) => document.getElementById(id);
let lastTimeline = null;

function describeLevel(value) {
  if (value >= 0.55) return "high";
  if (value >= 0.4) return "medium";
  return "low";
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export function renderResults(result, mode) {
  // Reveal first: charts size themselves from the visible layout.
  $("resultPanel").classList.remove("hidden");
  const metrics = result.metrics || {};
  $("score").textContent = result.score ?? "-";
  $("delivery").textContent = result.delivery || "-";
  const meta = [
    `${formatDuration(result.minutes, result.seconds)} (${Math.round(metrics.speaking_span || 0)}s speaking)`,
    `${metrics.wpm ?? "-"} WPM`,
    plural(metrics.filler_count ?? 0, "filler"),
  ];
  if (metrics.hedge_count) meta.push(plural(metrics.hedge_count, "hedge"));
  if (metrics.target_seconds) meta.push(`target ${formatClock(metrics.target_seconds)}`);
  $("resultMeta").textContent = meta.join(" · ");

  renderScoreBars($("breakdown"), mode.skills.map((skill) => [skill, SKILL_LABELS[skill]]), result.sub_scores);

  const tone = result.vocal_tone;
  $("vocalTone").textContent = tone
    ? `Energy ${describeLevel(tone.arousal)} · Assertiveness ${describeLevel(tone.dominance)} · Positivity ${describeLevel(tone.valence)}`
    : "Not available (emotion model not installed)";

  const match = result.topic_match;
  $("topicLine").classList.toggle("hidden", mode.prompt.kind === "passage");
  $("topicRelated").textContent = match
    ? `${match.related ? "Yes" : "No"} (semantic similarity ${match.similarity.toFixed(2)})`
    : "No topic provided";

  renderTranscript(result);
  $("feedback").textContent = result.feedback || "-";
  renderReferee(result.referee);
  renderReading(result.reading);
  renderTimeline(result);
}

function renderTranscript(result) {
  const container = $("transcription");
  container.textContent = "";
  const words = result.words || [];
  if (!words.length) {
    container.textContent = result.transcription || "-";
    return;
  }

  const language = result.language || {};
  const hedges = new Set((language.hedges || []).flatMap((item) => item.indexes));
  const stutters = new Set((language.stutters || []).flatMap((item) => item.indexes));
  const repeats = new Set((language.repeated || []).flatMap((item) => item.indexes.slice(2)));
  const unclear = new Set(result.unclear_indexes || []);
  const rising = new Set(result.uptalk?.rising_indexes || []);
  const pausesBefore = new Map(
    (result.pauses || []).filter((pause) => pause.kind === "hesitation").map((pause) => [pause.before_word, pause])
  );
  const used = new Set();

  words.forEach((word, index) => {
    const pause = pausesBefore.get(index);
    if (pause) {
      const chip = el("span", "pause-chip", `${pause.duration.toFixed(1)}s`);
      chip.title = "Hesitation pause";
      container.append(chip, " ");
      used.add("pause");
    }
    const span = el("span", "", word.text);
    const kind = word.filler ? "filler" : stutters.has(index) ? "stutter" : hedges.has(index) ? "hedge" : repeats.has(index) ? "repeat" : "";
    if (kind) {
      span.classList.add(kind);
      used.add(kind);
    }
    if (unclear.has(index)) {
      span.classList.add("unclear");
      span.title = "The recogniser was unsure about this word";
      used.add("unclear");
    }
    container.appendChild(span);
    if (rising.has(index)) {
      const marker = el("span", "rise-marker", "↗");
      marker.title = "Pitch rose at the end of this statement (experimental)";
      container.appendChild(marker);
      used.add("rise");
    }
    container.append(" ");
  });

  document.querySelectorAll("#legend [data-kind]").forEach((item) => {
    item.classList.toggle("hidden", !used.has(item.dataset.kind));
  });
  $("legend").classList.toggle("hidden", used.size === 0);
}

function renderReferee(referee) {
  $("refereePanel").classList.toggle("hidden", !referee);
  if (!referee) return;
  const { hesitation, repetition, deviation } = referee.counts;
  const total = hesitation + repetition + deviation;
  $("refereeSummary").textContent = total
    ? `You would have been challenged ${total} time${total === 1 ? "" : "s"}: ${hesitation} hesitation, ${repetition} repetition, ${deviation} deviation. Clean run before the first challenge: ${referee.clean_seconds}s.`
    : "No challenges: a clean minute with no hesitation, repetition or deviation!";
  if (!referee.deviation_checked) $("refereeSummary").textContent += " (Deviation check unavailable.)";

  const list = $("refereeEvents");
  list.textContent = "";
  referee.events.forEach((event) => {
    const item = el("li", `referee-event referee-${event.type}`);
    item.append(el("span", "event-time", formatClock(event.time)), el("span", "event-type", event.type), el("span", "", event.detail));
    list.appendChild(item);
  });
}

function renderReading(reading) {
  $("readingPanel").classList.toggle("hidden", !reading);
  if (!reading) return;
  const { counts } = reading;
  const parts = [
    `${Math.round(reading.accuracy * 100)}% read correctly`,
    `${counts.missed} skipped`,
    `${counts.misread} misread`,
    `${counts.added} added`,
  ];
  if (reading.sentence_pause_rate != null) parts.push(`paused at ${Math.round(reading.sentence_pause_rate * 100)}% of full stops`);
  $("readingSummary").textContent = parts.join(" · ");

  const script = $("readingScript");
  script.textContent = "";
  reading.tokens.forEach((token) => {
    const span = el("span", `read-${token.status}`, token.text);
    if (token.status === "misread") span.title = `You said "${token.said}"`;
    if (token.status === "missed") span.title = "Skipped";
    script.append(span, " ");
  });
  $("readingAdded").textContent = reading.added.length ? `Words you added: ${reading.added.join(", ")}` : "";
}

function renderTimeline(result) {
  const timeline = result.timeline || [];
  const show = timeline.length >= 3;
  $("timelinePanel").classList.toggle("hidden", !show);
  lastTimeline = show ? { timeline, range: result.metrics?.wpm_range } : null;
  if (!show) return;
  drawTimeline();

  const notes = [];
  const trends = result.trends;
  if (trends) {
    const pace = Math.round(trends.pace_change * 100);
    notes.push(pace >= 0 ? `Pace rose ${pace}% from start to finish.` : `Pace fell ${-pace}% from start to finish.`);
    notes.push(trends.energy_change_db <= -3 ? "Energy dropped towards the end." : "Energy stayed steady.");
  }
  if (timeline.some((segment) => segment.fillers)) notes.push("Red dots mark stretches with filler words.");
  $("timelineNotes").textContent = notes.join(" ");
}

export function drawTimeline() {
  if (!lastTimeline) return;
  const { timeline, range } = lastTimeline;
  const values = timeline.map((segment) => segment.wpm);
  drawLineChart($("timelineChart"), {
    values,
    min: 0,
    max: Math.max(220, ...values),
    ticks: [0, 50, 100, 150, 200],
    band: range,
    labels: timeline.map((segment) => formatClock(segment.start)),
    highlight: timeline.map((segment, index) => (segment.fillers ? index : -1)).filter((index) => index >= 0),
    height: 200,
  });
}
