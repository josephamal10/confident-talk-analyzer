// Practice modes: each mode's setup panel and the fields sent to /analyze.
import { el, formatClock, pickRandom, requestJson } from "./common.js";
import { currentDeck } from "./deck.js";
import { currentDocument, documentScript } from "./document.js";

const $ = (id) => document.getElementById(id);
const CUSTOM_PASSAGE = "__custom__";
const ROLE_CATEGORY = "__role__";
const GENERAL_CATEGORY = "__general__";
// Role questions come typed; each type is answered with the framework of the matching bank category.
const TYPE_CATEGORY = { behavioral: "behavioral", role: "technical", motivation: "personal" };
// Where each kind of mode gets prompts for the user's job role, and how the role box reads there.
const ROLE_SOURCES = {
  question: {
    endpoint: "/interview/questions",
    key: "questions",
    button: "Get questions for this role",
    intro: "The AI coach will judge your answers as an interviewer for this role.",
    loading: (role) => `Writing interview questions for ${role}...`,
    noun: "questions",
    next: "Next question",
  },
  topic: {
    endpoint: "/jam/topics",
    key: "topics",
    button: "Get JAM topics for this role",
    intro: "Practising for the JAM round of an interview? Add the role to get the kind of topics panels give, and the coach will judge you like that panel.",
    loading: (role) => `Finding interview JAM topics for ${role}...`,
    noun: "JAM topics",
    next: "New topic",
  },
};

let catalog = null;
let mode = null;
let hooks = { requireLogin: () => true, onSessionExpired: () => {} };
const selections = {};
// Prompts written for the user's role, per mode: { role, items }.
const roleSets = {};
const roleStatus = {};

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

function roleSource() {
  return mode.prompt.roles ? ROLE_SOURCES[mode.prompt.kind === "question" ? "question" : "topic"] : null;
}

function roleSet() {
  return roleSets[mode.id] || null;
}

// The "Question type" picker in interview mode; in JAM it switches between role and general topics.
function renderCategoryOptions() {
  const categorySelect = $("questionCategory");
  categorySelect.textContent = "";
  const set = roleSet();
  if (mode.prompt.kind === "question") {
    if (set) categorySelect.appendChild(new Option(`For your role: ${set.role}`, ROLE_CATEGORY));
    catalog.interview.forEach((category) => {
      categorySelect.appendChild(new Option(`${category.label} (${category.framework.name})`, category.id));
    });
  } else if (set) {
    categorySelect.appendChild(new Option(`Interview JAM for: ${set.role}`, ROLE_CATEGORY));
    categorySelect.appendChild(new Option("General JAM topics", GENERAL_CATEGORY));
  }
  categorySelect.value = selection().categoryId;
}

async function loadRolePrompts() {
  const source = roleSource();
  const role = $("roleInput").value.trim();
  if (!role) {
    $("roleStatus").textContent = "Type or pick the role you're preparing for first.";
    return;
  }
  if (!hooks.requireLogin()) return;
  const button = $("roleQuestionsBtn");
  const forMode = mode;
  button.disabled = true;
  $("roleStatus").textContent = source.loading(role);
  try {
    const data = await requestJson(source.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    const items = data[source.key];
    roleSets[forMode.id] = { role: data.role, items };
    const chosen = selections[forMode.id];
    chosen.categoryId = ROLE_CATEGORY;
    chosen.promptId = items[0].id;
    roleStatus[forMode.id] =
      data.source === "ai"
        ? `${items.length} ${source.noun} for ${data.role}${data.cached ? " (saved from an earlier request)" : ""}. Use ${source.next} to go through them.`
        : `Showing general ${source.noun} for ${data.role}; the AI writer isn't available right now.`;
    if (mode === forMode) renderSetup();
  } catch (error) {
    if (error.status === 401) hooks.onSessionExpired();
    else $("roleStatus").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

export function initPractice(options = {}) {
  hooks = { ...hooks, ...options };
  const roleOptions = $("roleOptions");
  roleOptions.textContent = "";
  catalog.roles.forEach((role) => roleOptions.appendChild(new Option(role)));
  $("roleQuestionsBtn").addEventListener("click", loadRolePrompts);

  const categorySelect = $("questionCategory");
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

  const styleSelect = $("readingStyle");
  styleSelect.textContent = "";
  const styles = [...catalog.passage_styles].sort((a, b) => (b.id === "custom") - (a.id === "custom"));
  styles.forEach((style) => {
    const label = style.id === "custom" ? "Everyday reading" : style.label;
    styleSelect.appendChild(new Option(`${label} (${style.wpm_range[0]}-${style.wpm_range[1]} words a minute)`, style.id));
  });
  styleSelect.addEventListener("change", () => {
    selection().readingStyle = styleSelect.value;
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
      categoryId: mode.prompt.kind === "question" ? catalog.interview[0].id : GENERAL_CATEGORY,
      readingStyle: "custom",
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
  if (isRolePrompt()) return roleSet().items;
  if (mode.prompt.kind === "question") {
    return catalog.interview.find((category) => category.id === selection().categoryId).questions;
  }
  return catalog.banks[mode.prompt.bank] || [];
}

// Whether the current prompt was written for the user's role (so it isn't in the server's bank).
function usingDocument() {
  return mode.prompt.kind === "passage" && Boolean(currentDocument());
}

// Re-renders the set-up panel (e.g. after a document is uploaded or removed).
export function refreshSetup() {
  if (mode) renderSetup();
}

function isRolePrompt() {
  return Boolean(mode.prompt.roles && roleSet() && selection().categoryId === ROLE_CATEGORY);
}

function currentPrompt() {
  return bankItems().find((item) => item.id === selection().promptId);
}

function currentFramework() {
  if (mode.prompt.kind === "question") {
    const categoryId = isRolePrompt() ? TYPE_CATEGORY[currentPrompt()?.type] || "personal" : selection().categoryId;
    return catalog.interview.find((category) => category.id === categoryId).framework;
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
  const source = roleSource();
  $("roleBlock").classList.toggle("hidden", !source);
  if (source) {
    $("roleQuestionsBtn").textContent = source.button;
    $("roleStatus").textContent = roleStatus[mode.id] || source.intro;
  }
  $("questionBlock").classList.toggle("hidden", !(prompt.kind === "question" || (source && roleSet())));
  $("questionCategoryLabel").textContent = prompt.kind === "question" ? "Question type" : "Topics";
  if (prompt.kind === "question" || source) renderCategoryOptions();
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
    // An uploaded document replaces the passage until it's removed.
    const fromDocument = usingDocument();
    const custom = !fromDocument && chosen.passageId === CUSTOM_PASSAGE;
    $("passageChooser").classList.toggle("hidden", fromDocument);
    $("customScript").classList.toggle("hidden", !custom);
    $("passagePreview").classList.toggle("hidden", custom || fromDocument);
    $("passagePreview").textContent = custom || fromDocument ? "" : catalog.passages.find((p) => p.id === chosen.passageId).text;
    $("readingStyleBlock").classList.toggle("hidden", !(custom || fromDocument));
    $("readingStyle").value = chosen.readingStyle;
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
  if (isRolePrompt() && mode.prompt.kind === "question") {
    return `${currentPrompt()?.type_label || "Role"} question for ${roleSet().role}. ${framework?.description || ""}`;
  }
  if (isRolePrompt()) {
    const kind = currentPrompt()?.type === "general" ? "A common interview JAM topic" : `A topic linked to the ${roleSet().role} role`;
    return `${kind}. Keep talking for the whole minute: no hesitation, no repetition, no going off-topic.`;
  }
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
    if (usingDocument()) {
      return {
        title: `Read from ${currentDocument().filename}`,
        text: "Read any part you like, as much as you like. The analysis finds where you read from.",
        script: documentScript(),
        long: true,
      };
    }
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
  if (mode.prompt.roles) {
    const role = $("roleInput").value.trim();
    if (role) fields.role = role;
    if (!custom && isRolePrompt()) {
      // Prompts written for the role aren't in the server's bank, so send the text (and a question's type).
      delete fields.prompt_id;
      fields.custom_prompt = currentPrompt().text;
      if (mode.prompt.kind === "question") fields.question_type = currentPrompt().type;
    }
  }
  if (mode.prompt.kind === "passage") {
    if (usingDocument()) fields.document_id = String(currentDocument().id);
    else if (chosen.passageId === CUSTOM_PASSAGE) fields.custom_script = $("customScript").value.trim();
    else fields.prompt_id = chosen.passageId;
    if (usingDocument() || chosen.passageId === CUSTOM_PASSAGE) fields.reading_style = chosen.readingStyle;
  }
  if (mode.prompt.sides) fields.side = chosen.side;
  if (mode.prompt.notes) fields.notes = $("notesInput").value.trim();
  if (mode.timer.target_choices) fields.target_seconds = String(chosen.target);
  if (mode.prompt.slides && currentDeck()) fields.deck_id = String(currentDeck().id);
  return fields;
}
