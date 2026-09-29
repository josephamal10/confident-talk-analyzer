// Reference documents for read-aloud: upload a file, see quick read-aloud checks, then read any part of it.
import { el, formatClock, requestJson } from "./common.js";

const $ = (id) => document.getElementById(id);
const INTRO =
  "Upload a PDF, Word, PowerPoint or text file. Read any part of it aloud and the analysis finds where you read from and checks it word by word.";
let current = null;
let hooks = {};

export function currentDocument() {
  return current;
}

// The document as the reader sees it on screen, one paragraph per block.
export function documentScript() {
  return current ? current.paragraphs.join("\n\n") : "";
}

function setStatus(message, isError = false) {
  $("documentStatus").textContent = message;
  $("documentStatus").classList.toggle("status-error", isError);
}

function clearDocument() {
  current = null;
  $("documentInput").value = "";
  $("documentPanel").classList.add("hidden");
  $("removeDocumentBtn").classList.add("hidden");
  setStatus(INTRO);
}

function render() {
  const { checks } = current;
  $("documentSummary").textContent = [
    current.filename,
    `${checks.word_count.toLocaleString()} words`,
    `${checks.paragraph_count} paragraph${checks.paragraph_count === 1 ? "" : "s"}`,
    `about ${formatClock(checks.reading_seconds)} to read it all`,
  ].join(" · ");

  const notes = $("documentNotes");
  notes.textContent = "";
  const add = (text, kind = "info") => notes.appendChild(el("li", `deck-issue deck-${kind}`, text));
  if (current.truncated) add(`It's a long file, so only the first ${checks.word_count.toLocaleString()} words were kept.`, "warn");
  if (checks.readability_label) {
    const level = { Easy: "easy to read", Standard: "a standard read", "Fairly hard": "fairly hard going", Hard: "hard going" }[checks.readability_label];
    add(`Reading level: ${level}${checks.average_sentence_words ? `, with ${checks.average_sentence_words} words per sentence on average` : ""}.`);
  }
  if (checks.long_sentence_count) {
    add(
      `${checks.long_sentence_count} sentence${checks.long_sentence_count === 1 ? " is" : "s are"} over 30 words, like "${checks.long_sentence_example}" Plan where you'll take a breath.`,
      "warn"
    );
  }
  if (checks.watch_words.length) add(`Watch out for: ${checks.watch_words.join(", ")}. Figures and abbreviations are easy to stumble on.`);

  const preview = $("documentPreview");
  preview.textContent = "";
  current.paragraphs.forEach((paragraph) => preview.appendChild(el("p", "", paragraph)));
  $("documentPanel").classList.remove("hidden");
  $("removeDocumentBtn").classList.remove("hidden");
}

async function upload(file) {
  if (!hooks.requireLogin()) {
    $("documentInput").value = "";
    return;
  }
  const form = new FormData();
  form.append("document", file, file.name);
  setStatus(`Reading ${file.name}...`);
  try {
    current = await requestJson("/documents", { method: "POST", body: form });
    setStatus("Ready. It'll be on screen while you read, so you can read straight from it.");
    render();
  } catch (error) {
    if (error.status === 401) return hooks.onSessionExpired();
    current = null;
    $("documentPanel").classList.add("hidden");
    setStatus(error.message, true);
  }
}

export function initDocumentUpload(options) {
  hooks = options;
  setStatus(INTRO);
  $("documentInput").addEventListener("change", () => {
    const file = $("documentInput").files[0];
    if (file) upload(file);
  });
  $("removeDocumentBtn").addEventListener("click", clearDocument);
}
