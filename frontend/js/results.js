// Renders an analysis (live or saved) into a results panel cloned from #resultTemplate.
import { SKILL_LABELS, el, formatClock, formatDuration, renderScoreBars } from "./common.js";
import { drawLineChart } from "./charts.js";

const views = new Set();

function describeLevel(value) {
  if (value >= 0.55) return "high";
  if (value >= 0.4) return "medium";
  return "low";
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export function createResultView(container) {
  const root = document.getElementById("resultTemplate").content.firstElementChild.cloneNode(true);
  root.classList.add("hidden");
  container.appendChild(root);
  const part = (name) => root.querySelector(`[data-el="${name}"]`);
  let timeline = null;

  function renderTranscript(result) {
    const container = part("transcription");
    container.textContent = "";
    const words = result.words || [];
    if (!words.length) {
      container.textContent = result.transcription || "-";
      part("legend").classList.add("hidden");
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

    root.querySelectorAll('[data-el="legend"] [data-kind]').forEach((item) => {
      item.classList.toggle("hidden", !used.has(item.dataset.kind));
    });
    part("legend").classList.toggle("hidden", used.size === 0);
  }

  function renderReferee(referee) {
    part("refereePanel").classList.toggle("hidden", !referee);
    if (!referee) return;
    const { hesitation, repetition, deviation } = referee.counts;
    const total = hesitation + repetition + deviation;
    part("refereeSummary").textContent = total
      ? `A JAM referee would have stopped you ${plural(total, "time")} (${hesitation} for hesitating, ${repetition} for repeating yourself, ${deviation} for going off-topic). You got ${referee.clean_seconds}s in before the first challenge.`
      : "Not a single challenge: no hesitating, no repeating yourself and no going off-topic. That's a clean minute.";
    if (!referee.deviation_checked) part("refereeSummary").textContent += " (The off-topic check isn't available right now.)";

    const list = part("refereeEvents");
    list.textContent = "";
    referee.events.forEach((event) => {
      const item = el("li", `referee-event referee-${event.type}`);
      item.append(el("span", "event-time", formatClock(event.time)), el("span", "event-type", event.type), el("span", "", event.detail));
      list.appendChild(item);
    });
  }

  function renderReading(reading, context) {
    part("readingPanel").classList.toggle("hidden", !reading);
    if (!reading) return;
    const { counts } = reading;
    const match = reading.match;
    part("readingMatch").className = `reading-match${match ? ` match-${match.verdict}` : ""}`;
    part("readingMatch").textContent = match ? match.message : "";

    const doc = context?.document;
    const section = reading.section;
    part("readingSection").textContent = !doc
      ? ""
      : section
        ? `You read about ${Math.max(1, Math.round(section.share * 100))}% of ${doc.filename}, from "${section.first_words.replace(/[.,;:!?]+$/, "")}..." to "...${section.last_words}"`
        : `Nothing you said matched ${doc.filename} word for word, so there's no word-by-word check this time.`;
    const aligned = reading.tokens.length > 0;
    part("readingScript").classList.toggle("hidden", !aligned);
    part("readingLegend").classList.toggle("hidden", !aligned);
    part("readingSummary").classList.toggle("hidden", !aligned);
    const parts = [
      `${Math.round(reading.accuracy * 100)}% read correctly`,
      `${counts.missed} skipped`,
      `${counts.misread} misread`,
      `${counts.added} added`,
    ];
    if (reading.sentence_pause_rate != null) parts.push(`paused at ${Math.round(reading.sentence_pause_rate * 100)}% of full stops`);
    part("readingSummary").textContent = parts.join(" · ");

    const script = part("readingScript");
    script.textContent = "";
    reading.tokens.forEach((token) => {
      const span = el("span", `read-${token.status}`, token.text);
      if (token.status === "misread") span.title = `You said "${token.said}"`;
      if (token.status === "missed") span.title = "Skipped";
      script.append(span, " ");
    });
    part("readingAdded").textContent = reading.added.length ? `Words you added: ${reading.added.join(", ")}` : "";
  }

  function renderSlides(match, deck) {
    part("slidesPanel").classList.toggle("hidden", !deck);
    if (!deck) return;
    if (!match) {
      part("slidesSummary").textContent = `Presented with ${deck.filename} (${plural(deck.slide_count, "slide")}). Slide matching is unavailable right now.`;
      part("slidesList").textContent = "";
      part("offSlides").textContent = "";
      return;
    }
    const covered = match.slides.filter((slide) => slide.covered).length;
    part("slidesSummary").textContent =
      `You talked about ${covered} of ${plural(match.slides.length, "slide")} in ${deck.filename} ` +
      `(${Math.round(match.coverage * 100)}%). Talk-to-slides similarity: ${match.speech_deck_similarity.toFixed(2)}.`;
    const list = part("slidesList");
    list.textContent = "";
    match.slides.forEach((slide) => {
      const item = el("li", slide.covered ? "slide-covered" : "slide-missed");
      item.append(
        el("span", "slide-mark", slide.covered ? "✓" : "✗"),
        el("span", "", slide.title),
        el("span", "result-meta", slide.covered ? `from ${formatClock(slide.first_mentioned)}` : "not discussed")
      );
      list.appendChild(item);
    });
    part("offSlides").textContent = match.off_slide_sentences.length
      ? `Said without a matching slide: "${match.off_slide_sentences.join('", "')}"`
      : "";
  }

  function drawTimeline() {
    if (!timeline || root.classList.contains("hidden")) return;
    const values = timeline.segments.map((segment) => segment.wpm);
    drawLineChart(part("timelineChart"), {
      values,
      min: 0,
      max: Math.max(220, ...values),
      ticks: [0, 50, 100, 150, 200],
      band: timeline.range,
      labels: timeline.segments.map((segment) => formatClock(segment.start)),
      highlight: timeline.segments.map((segment, index) => (segment.fillers ? index : -1)).filter((index) => index >= 0),
      height: 200,
    });
  }

  function renderTimeline(result) {
    const segments = result.timeline || [];
    const show = segments.length >= 3;
    part("timelinePanel").classList.toggle("hidden", !show);
    timeline = show ? { segments, range: result.metrics?.wpm_range } : null;
    if (!show) return;
    drawTimeline();
    const notes = [];
    if (result.trends) {
      const pace = Math.round(result.trends.pace_change * 100);
      notes.push(pace >= 0 ? `Pace rose ${pace}% from start to finish.` : `Pace fell ${-pace}% from start to finish.`);
      notes.push(result.trends.energy_change_db <= -3 ? "Energy dropped towards the end." : "Energy stayed steady.");
    }
    if (segments.some((segment) => segment.fillers)) notes.push("Red dots mark stretches with filler words.");
    part("timelineNotes").textContent = notes.join(" ");
  }

  function render(result, mode) {
    // Reveal first: charts size themselves from the visible layout.
    root.classList.remove("hidden");
    const metrics = result.metrics || {};
    part("score").textContent = result.score ?? "-";
    part("delivery").textContent = result.delivery || "-";
    const meta = [
      `${formatDuration(result.minutes, result.seconds)} (${Math.round(metrics.speaking_span || 0)}s speaking)`,
      `${metrics.wpm ?? "-"} WPM`,
      plural(metrics.filler_count ?? 0, "filler"),
    ];
    if (metrics.hedge_count) meta.push(plural(metrics.hedge_count, "hedge"));
    if (metrics.target_seconds) meta.push(`target ${formatClock(metrics.target_seconds)}`);
    part("resultMeta").textContent = meta.join(" · ");

    part("breakdown").classList.toggle("hidden", !result.sub_scores);
    if (result.sub_scores) {
      renderScoreBars(part("breakdown"), mode.skills.map((skill) => [skill, SKILL_LABELS[skill]]), result.sub_scores);
    }

    const tone = result.vocal_tone;
    part("vocalTone").parentElement.classList.toggle("hidden", !tone && !result.sub_scores);
    part("vocalTone").textContent = tone
      ? `Energy ${describeLevel(tone.arousal)} · Assertiveness ${describeLevel(tone.dominance)} · Positivity ${describeLevel(tone.valence)}`
      : "Not available (emotion model not installed)";

    const match = result.topic_match;
    part("topicLine").classList.toggle("hidden", mode.prompt.kind === "passage" || !result.sub_scores);
    part("topicRelated").textContent = match
      ? `${match.related ? "Yes" : "No"} (semantic similarity ${match.similarity.toFixed(2)})`
      : "No topic provided";

    renderTranscript(result);
    part("feedback").textContent = result.feedback || "-";
    renderReferee(result.referee);
    renderReading(result.reading, result.context);
    renderSlides(result.slides_match, result.context?.deck);
    renderTimeline(result);
  }

  const view = {
    root,
    render,
    hide: () => root.classList.add("hidden"),
    redraw: drawTimeline,
  };
  views.add(view);
  return view;
}

export function redrawCharts() {
  views.forEach((view) => view.redraw());
}
