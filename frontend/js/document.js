// Reference documents for read-aloud: upload a file, see quick read-aloud checks, then read any part of it.
import { el, formatClock, requestJson } from "./common.js";

const $ = (id) => document.getElementById(id);
const INTRO =
  "Have your own article, script or notes? PDF, Word, PowerPoint and text files all work. Read any part of it and the analysis finds where you read from and checks it word by word.";
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
  $("documentPickLabel").textContent = "Upload a document";
  setStatus(INTRO);
  hooks.onChange?.();
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
  $("documentPickLabel").textContent = "Upload a different document";
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
    setStatus("Ready. You'll read from this instead of a passage, and it stays on screen while you read. Remove it to pick a passage again.");
    render();
  } catch (error) {
    if (error.status === 401) return hooks.onSessionExpired();
    // A failed replacement keeps the document that was already loaded.
    setStatus(current ? `${error.message} Still using ${current.filename}.` : error.message, true);
  } finally {
    $("documentInput").value = "";
    hooks.onChange?.();
  }
}

export function initDocumentUpload(options) {
  hooks = options;
  setStatus(INTRO);
  $("documentPickBtn").addEventListener("click", () => $("documentInput").click());
  $("documentInput").addEventListener("change", () => {
    const file = $("documentInput").files[0];
    if (file) upload(file);
  });
  $("removeDocumentBtn").addEventListener("click", clearDocument);
}
