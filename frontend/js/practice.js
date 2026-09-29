// Practice modes: each mode's setup panel and the fields sent to /analyze.
import { el, formatClock, pickRandom, requestJson } from "./common.js";
import { currentDeck } from "./deck.js";

const $ = (id) => document.getElementById(id);
const CUSTOM_PASSAGE = "__custom__";

let catalog = null;
let mode = null;
const selections = {};

export async function loadCatalog() {
  if (!catalog) catalog = await requestJson("/modes");
  return catalog;
}

export function getCatalog() {
  return catalog;
}

export function currentMode() {
  return mode;
}

export function findMode(id) {
  return catalog.modes.find((item) => item.id === id) || null;
}

export function initPractice() {
  const categorySelect = $("questionCategory");
  categorySelect.textContent = "";
  catalog.interview.forEach((category) => {
    categorySelect.appendChild(new Option(`${category.label} (${category.framework.name})`, category.id));
  });
  categorySelect.addEventListener("change", () => {
    selection().categoryId = categorySelect.value;
    selection().promptId = pickRandom(bankItems()).id;
    renderSetup();
  });

  const passageSelect = $("passageSelect");
  passageSelect.textContent = "";
  const groups = {};
  catalog.passages.forEach((passage) => {
    if (!groups[passage.style_label]) {
      groups[passage.style_label] = document.createElement("optgroup");
      groups[passage.style_label].label = passage.style_label;
      passageSelect.appendChild(groups[passage.style_label]);
    }
    groups[passage.style_label].appendChild(new Option(passage.title, passage.id));
  });
  passageSelect.appendChild(new Option("Use my own text", CUSTOM_PASSAGE));
  passageSelect.addEventListener("change", () => {
    selection().passageId = passageSelect.value;
    renderSetup();
  });

  $("nextPromptBtn").addEventListener("click", () => {
    const current = bankItems().find((item) => item.id === selection().promptId);
    selection().promptId = pickRandom(bankItems(), current).id;
    renderSetup();
  });
  $("suggestBtn").addEventListener("click", () => {
    $("promptInput").value = pickRandom(catalog.banks.topics.map((item) => item.text), $("promptInput").value);
  });
  document.querySelectorAll("#sideButtons button").forEach((button) => {
    button.addEventListener("click", () => {
      selection().side = button.dataset.side;
      renderSetup();
    });
  });
}

function selection() {
  if (!selections[mode.id]) {
    const timer = mode.timer;
    selections[mode.id] = {
      categoryId: catalog.interview[0].id,
      side: Math.random() < 0.5 ? "for" : "against",
      target: timer.target_seconds ?? null,
      prep: timer.prep_seconds ?? 0,
      passageId: catalog.passages[0].id,
      promptId: null,
    };
  }
  return selections[mode.id];
}

function bankItems() {
  if (mode.prompt.kind === "question") {
    return catalog.interview.find((category) => category.id === selection().categoryId).questions;
  }
  return catalog.banks[mode.prompt.bank] || [];
}

function currentPrompt() {
  return bankItems().find((item) => item.id === selection().promptId);
}

function currentFramework() {
  if (mode.prompt.kind === "question") {
    return catalog.interview.find((category) => category.id === selection().categoryId).framework;
  }
  return mode.framework;
}

export function selectMode(id) {
  const next = findMode(id) || catalog.modes[0];
  const changed = next !== mode;
  mode = next;
  const chosen = selection();
  if (mode.prompt.style === "card" && !chosen.promptId) chosen.promptId = pickRandom(bankItems()).id;
  if (changed) {
    $("promptInput").value = "";
    $("customPromptInput").value = "";
  }
  renderSetup();
  return changed;
}

function renderChoices(containerId, choices, selected, format, onPick) {
  const container = $(containerId);
  container.textContent = "";
  choices.forEach((value) => {
    const button = el("button", value === selected ? "active" : "", format(value));
    button.type = "button";
    button.addEventListener("click", () => onPick(value));
    container.appendChild(button);
  });
}

function renderSetup() {
  const chosen = selection();
  const { prompt, timer } = mode;
  $("setupTitle").textContent = mode.label;
  $("setupTagline").textContent = mode.tagline;

  const isText = prompt.style === "text";
  const isCard = prompt.style === "card";
  const isPassage = prompt.kind === "passage";
  $("promptTextBlock").classList.toggle("hidden", !isText);
  $("promptInputLabel").textContent = prompt.label;
  $("questionBlock").classList.toggle("hidden", prompt.kind !== "question");
  $("questionCategory").value = chosen.categoryId;
  $("promptCard").classList.toggle("hidden", !isCard);
  $("customBlock").classList.toggle("hidden", !(isCard && (prompt.custom || prompt.kind === "question")));
  $("sideBlock").classList.toggle("hidden", !prompt.sides);
  $("passageBlock").classList.toggle("hidden", !isPassage);
  $("notesBlock").classList.toggle("hidden", !prompt.notes);
  $("slidesBlock").classList.toggle("hidden", !prompt.slides);

  if (isCard) {
    const framework = currentFramework();
    $("promptCardKicker").textContent = framework ? `${framework.name}: ${framework.parts.join(" → ")}` : prompt.label;
    $("promptCardText").textContent = prompt.reveal_on_start
      ? "Your topic stays hidden until you press Start."
      : currentPrompt()?.text || "";
    $("promptCardHint").textContent = cardHint(framework);
    $("nextPromptBtn").classList.toggle("hidden", Boolean(prompt.reveal_on_start));
    $("nextPromptBtn").textContent = prompt.kind === "question" ? "Next question" : `New ${prompt.kind === "motion" ? "motion" : "topic"}`;
    $("customPromptLabel").textContent = prompt.kind === "question" ? "Or type your own question" : "Or type your own";
  }
  if (prompt.sides) {
    document.querySelectorAll("#sideButtons button").forEach((button) => {
      button.classList.toggle("active", button.dataset.side === chosen.side);
    });
  }
  if (isPassage) {
    $("passageSelect").value = chosen.passageId;
    const custom = chosen.passageId === CUSTOM_PASSAGE;
    $("customScript").classList.toggle("hidden", !custom);
    $("passagePreview").classList.toggle("hidden", custom);
    $("passagePreview").textContent = custom ? "" : catalog.passages.find((p) => p.id === chosen.passageId).text;
  }

  $("durationBlock").classList.toggle("hidden", !timer.user_duration);
  $("targetBlock").classList.toggle("hidden", !timer.target_choices);
  if (timer.target_choices) {
    renderChoices("targetButtons", timer.target_choices, chosen.target, formatClock, (value) => {
      chosen.target = value;
      renderSetup();
    });
  }
  $("prepBlock").classList.toggle("hidden", !timer.prep_choices);
  if (timer.prep_choices) {
    renderChoices("prepButtons", timer.prep_choices, chosen.prep, (value) => `${value}s`, (value) => {
      chosen.prep = value;
      renderSetup();
    });
  }
  $("timerNote").textContent = timerNote();
}

function cardHint(framework) {
  if (mode.id === "jam") return "Keep talking for the whole minute: no hesitation, no repetition, no going off-topic.";
  if (mode.id === "snap") return `You get ${selection().prep} seconds to think, then speak.`;
  if (mode.id === "debate") return `You're arguing ${selection().side.toUpperCase()} the motion.`;
  return framework?.description || "";
}

function timerNote() {
  const { prepSeconds, limitSeconds, targetSeconds } = timerSettings();
  if (mode.timer.user_duration) return "";
  const parts = [];
  if (prepSeconds) parts.push(`${prepSeconds}s to think`);
  if (targetSeconds && targetSeconds === limitSeconds) {
    parts.push(`speak for exactly ${formatClock(targetSeconds)}; recording stops automatically`);
  } else if (targetSeconds) {
    parts.push(`aim for ${formatClock(targetSeconds)}; recording stops at ${formatClock(limitSeconds)}`);
  } else if (limitSeconds) {
    parts.push(`recording stops at ${formatClock(limitSeconds)}`);
  }
  const text = parts.join(", then ");
  return text.charAt(0).toUpperCase() + text.slice(1) + ".";
}

function userDurationSeconds() {
  const minutes = Math.max(0, Number.parseInt($("minutes").value, 10) || 0);
  const seconds = Math.max(0, Number.parseInt($("seconds").value, 10) || 0);
  return minutes * 60 + seconds;
}

// Same rules as modes.resolve_timer on the server.
export function timerSettings() {
  const timer = mode.timer;
  if (timer.user_duration) return { prepSeconds: 0, limitSeconds: userDurationSeconds() || null, targetSeconds: null };
  const chosen = selection();
  const targetSeconds = timer.target_choices ? chosen.target : timer.target_seconds ?? null;
  let limitSeconds = timer.limit_seconds ?? null;
  if (!limitSeconds && targetSeconds && timer.limit_factor) limitSeconds = Math.round(targetSeconds * timer.limit_factor);
  return { prepSeconds: timer.prep_choices ? chosen.prep : timer.prep_seconds || 0, limitSeconds, targetSeconds };
}

function customPrompt() {
  const field = mode.prompt.style === "text" ? $("promptInput") : $("customPromptInput");
  return field.value.trim();
}

// Topic and target used for the slide checks in presentation mode.
export function presentationContext() {
  return { topic: customPrompt(), targetSeconds: timerSettings().targetSeconds };
}

// What to show on the stage while preparing and recording.
export function stageContent() {
  if (mode.prompt.kind === "passage") {
    const chosen = selection();
    const script = chosen.passageId === CUSTOM_PASSAGE
      ? $("customScript").value.trim()
      : catalog.passages.find((p) => p.id === chosen.passageId).text;
    return { title: "Read this aloud", script };
  }
  const text = customPrompt() || (mode.prompt.style === "card" ? currentPrompt()?.text : "") || "";
  const side = mode.prompt.sides ? ` (you're arguing ${selection().side.toUpperCase()})` : "";
  const deck = mode.prompt.slides ? currentDeck() : null;
  return {
    title: mode.prompt.label,
    text: text ? `${text}${side}` : "Speak about anything you like.",
    slides: deck ? deck.slides.map((slide) => slide.title || `Slide ${slide.number}`) : null,
  };
}

// Surprise-topic modes (snap talk) draw a fresh hidden topic for every attempt.
export function prepareAttempt() {
  if (mode.prompt.reveal_on_start) {
    const current = currentPrompt();
    selection().promptId = pickRandom(bankItems(), current).id;
  }
}

export function setLocked(locked) {
  document.querySelectorAll("#modeSwitcher a, #setupPanel input, #setupPanel select, #setupPanel textarea, #setupPanel button").forEach(
    (element) => {
      element.classList.toggle("locked", locked);
      if (element.tagName !== "A") element.disabled = locked;
    }
  );
}

export function validate() {
  if (mode.prompt.kind === "passage" && !stageContent().script) return "Paste the text you want to practise reading.";
  if (mode.timer.user_duration && !userDurationSeconds()) return "Set a duration above 0 seconds.";
  return null;
}

export function formFields() {
  const chosen = selection();
  const fields = { mode: mode.id };
  const custom = customPrompt();
  if (custom) fields.custom_prompt = custom;
  if (mode.prompt.style === "card" && !custom) fields.prompt_id = chosen.promptId;
  if (mode.prompt.kind === "passage") {
    if (chosen.passageId === CUSTOM_PASSAGE) fields.custom_script = $("customScript").value.trim();
    else fields.prompt_id = chosen.passageId;
  }
  if (mode.prompt.sides) fields.side = chosen.side;
  if (mode.prompt.notes) fields.notes = $("notesInput").value.trim();
  if (mode.timer.target_choices) fields.target_seconds = String(chosen.target);
  if (mode.prompt.slides && currentDeck()) fields.deck_id = String(currentDeck().id);
  return fields;
}
