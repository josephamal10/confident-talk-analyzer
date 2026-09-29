// Slide deck upload for presentation mode: instant checks and an optional AI review of the slides.
import { el, formatClock, renderScoreBars, requestJson } from "./common.js";

const $ = (id) => document.getElementById(id);
let deck = null;
let hooks = {};

export function currentDeck() {
  return deck;
}

function setStatus(message, isError = false) {
  $("deckStatus").textContent = message;
  $("deckStatus").classList.toggle("status-error", isError);
}

function clearDeck() {
  deck = null;
  $("deckInput").value = "";
  $("deckPanel").classList.add("hidden");
  $("removeDeckBtn").classList.add("hidden");
  $("deckReview").classList.add("hidden");
  setStatus("Upload your deck to get instant slide feedback and check that your talk follows it.");
}

function renderDeck() {
  const { checks } = deck;
  const total = deck.slides.length;
  const content = checks.content_slide_count ?? total;
  const summary = [
    `${deck.filename}`,
    `${total} slide${total === 1 ? "" : "s"}${content !== total ? ` (${content} content)` : ""}`,
    `${checks.total_words} words on slides`,
  ];
  if (checks.recommended_range && deck.target_seconds) {
    summary.push(`aim for ${checks.recommended_range[0]}-${checks.recommended_range[1]} content slides for ${formatClock(deck.target_seconds)}`);
  }
  if (checks.topic_similarity != null) summary.push(`fit to topic ${checks.topic_similarity.toFixed(2)}`);
  $("deckSummary").textContent = summary.join(" · ");

  const flagged = new Set(checks.issues.filter((issue) => issue.slide).map((issue) => issue.slide));
  const list = $("deckSlides");
  list.textContent = "";
  deck.slides.forEach((slide) => {
    const item = el("li", flagged.has(slide.number) ? "slide-flagged" : "");
    item.append(
      el("span", "", slide.title || "(no title)"),
      el("span", "result-meta", ` ${slide.word_count} word${slide.word_count === 1 ? "" : "s"}`)
    );
    list.appendChild(item);
  });

  const issues = $("deckIssues");
  issues.textContent = "";
  if (!checks.issues.length) issues.appendChild(el("li", "deck-ok", "No problems found by the quick checks."));
  checks.issues.forEach((issue) => {
    const item = el("li", `deck-issue deck-${issue.severity}`);
    item.append(el("b", "", issue.slide ? `Slide ${issue.slide}: ` : "Deck: "), issue.message);
    issues.appendChild(item);
  });

  $("reviewDeckBtn").classList.toggle("hidden", !deck.review_available);
  $("deckPanel").classList.remove("hidden");
  $("removeDeckBtn").classList.remove("hidden");
  if (deck.review) renderReview(deck.review);
  else $("deckReview").classList.add("hidden");
}

function fill(listId, items, render) {
  const list = $(listId);
  list.textContent = "";
  items.forEach((item) => {
    const li = el("li");
    render(li, item);
    list.appendChild(li);
  });
}

function renderReview(review) {
  $("deckScore").textContent = review.score;
  $("deckReviewSummary").textContent = review.summary;
  renderScoreBars($("deckBreakdown"), review.dimensions, review.scores);
  fill("deckStrengths", review.strengths, (li, text) => {
    li.textContent = text;
  });
  fill("deckFixes", review.slide_feedback, (li, item) => {
    li.append(el("b", "", `Slide ${item.slide}: ${item.issue}`), el("br"), item.suggestion);
  });
  $("deckMissingTitle").classList.toggle("hidden", !review.missing_points.length);
  fill("deckMissing", review.missing_points, (li, text) => {
    li.textContent = text;
  });
  fill("deckOutline", review.suggested_outline, (li, text) => {
    li.textContent = text;
  });
  $("deckReview").classList.remove("hidden");
}

async function upload(file) {
  if (!hooks.requireLogin()) {
    $("deckInput").value = "";
    return;
  }
  const { topic, targetSeconds } = hooks.getTopicAndTarget();
  const form = new FormData();
  form.append("deck", file, file.name);
  form.append("topic", topic);
  if (targetSeconds) form.append("target_seconds", String(targetSeconds));
  setStatus(`Reading ${file.name}...`);
  try {
    deck = await requestJson("/decks", { method: "POST", body: form });
    setStatus("Slides ready. They'll appear on screen while you present, and your talk will be checked against them.");
    renderDeck();
  } catch (error) {
    if (error.status === 401) return hooks.onSessionExpired();
    deck = null;
    $("deckPanel").classList.add("hidden");
    setStatus(error.message, true);
  }
}

async function review() {
  const button = $("reviewDeckBtn");
  const { topic, targetSeconds } = hooks.getTopicAndTarget();
  button.disabled = true;
  button.textContent = "Reviewing your slides...";
  try {
    deck = await requestJson(`/decks/${deck.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, target_seconds: targetSeconds }),
    });
    renderDeck();
  } catch (error) {
    if (error.status === 401) return hooks.onSessionExpired();
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Review my slides with AI";
  }
}

export function initDeckUpload(options) {
  hooks = options;
  $("deckInput").addEventListener("change", () => {
    const file = $("deckInput").files[0];
    if (file) upload(file);
  });
  $("removeDeckBtn").addEventListener("click", clearDeck);
  $("reviewDeckBtn").addEventListener("click", review);
}
