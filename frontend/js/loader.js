// Full-screen "analyzing" overlay: the user's own waveform with a scanning sweep, the real analysis
// stages ticking off as the server reports them, and rotating speaking tips.
import { el } from "./common.js";

const $ = (id) => document.getElementById(id);
const BAR_COUNT = 56;
export const STAGES = [
  ["upload", "Uploading your recording"],
  ["decode", "Listening for your voice"],
  ["transcribe", "Transcribing every word"],
  ["prosody", "Measuring pace, pauses and pitch"],
  ["tone", "Reading your vocal tone"],
  ["score", "Scoring and writing feedback"],
];
const TIPS = [
  "A one-second silent pause sounds far more confident than \"um\".",
  "Most confident speakers land between 120 and 160 words per minute.",
  "Stress one key word per sentence and your pitch varies naturally.",
  "Start with your main point, then back it up. Listeners remember the first line.",
  "\"I think\" and \"maybe\" soften your message. State it, then explain it.",
  "Let your voice fall at the end of a statement so it doesn't sound like a question.",
  "Breathe out before you start: a steady first sentence sets the tone.",
];
const MIN_VISIBLE_MS = 1600;
const DONE_PAUSE_MS = 450;
let tipTimer = null;
let clockTimer = null;
let shownAt = 0;

// Heights (0-1) of the recording's loudness, sampled into BAR_COUNT bars.
async function waveformPeaks(blob) {
  try {
    const context = new AudioContext();
    const audio = await context.decodeAudioData(await blob.arrayBuffer());
    context.close();
    const samples = audio.getChannelData(0);
    const size = Math.floor(samples.length / BAR_COUNT);
    const peaks = Array.from({ length: BAR_COUNT }, (_, bar) => {
      let sum = 0;
      for (let i = bar * size; i < (bar + 1) * size; i += 16) sum += samples[i] * samples[i];
      return Math.sqrt(sum / (size / 16));
    });
    // The floor keeps a silent or very quiet take looking flat instead of stretching noise to full height.
    const loudest = Math.max(...peaks, 0.01);
    return peaks.map((peak) => Math.max(0.08, peak / loudest));
  } catch {
    return Array.from({ length: BAR_COUNT }, (_, i) => 0.25 + 0.55 * Math.abs(Math.sin(i * 0.45)));
  }
}

async function drawWave(blob) {
  const wave = $("loaderWave");
  wave.textContent = "";
  (await waveformPeaks(blob)).forEach((height, index) => {
    const bar = el("span", "wave-bar");
    bar.style.setProperty("--h", height.toFixed(3));
    bar.style.setProperty("--i", index);
    wave.appendChild(bar);
  });
}

export function showLoader(blob) {
  const list = $("loaderStages");
  list.textContent = "";
  STAGES.forEach(([id, label]) => {
    const item = el("li", "loader-stage", label);
    item.dataset.stage = id;
    list.appendChild(item);
  });
  setStage("upload");
  drawWave(blob);

  let tip = Math.floor(Math.random() * TIPS.length);
  $("loaderTip").textContent = TIPS[tip];
  clearInterval(tipTimer);
  tipTimer = setInterval(() => {
    tip = (tip + 1) % TIPS.length;
    $("loaderTip").classList.remove("tip-in");
    void $("loaderTip").offsetWidth;
    $("loaderTip").textContent = TIPS[tip];
    $("loaderTip").classList.add("tip-in");
  }, 4500);

  shownAt = Date.now();
  $("loaderClock").textContent = "0s";
  clearInterval(clockTimer);
  clockTimer = setInterval(() => {
    $("loaderClock").textContent = `${Math.round((Date.now() - shownAt) / 1000)}s`;
  }, 500);

  $("loader").classList.remove("hidden");
  document.body.classList.add("no-scroll");
}

// Marks every stage before `stageId` done and `stageId` active.
export function setStage(stageId) {
  const order = STAGES.map(([id]) => id);
  const current = order.indexOf(stageId);
  if (current < 0) return;
  document.querySelectorAll("#loaderStages .loader-stage").forEach((item) => {
    const position = order.indexOf(item.dataset.stage);
    item.classList.toggle("done", position < current);
    item.classList.toggle("active", position === current);
  });
}

// Ticks every stage off and holds the overlay a moment, so a fast analysis doesn't just flicker.
export async function completeLoader() {
  document.querySelectorAll("#loaderStages .loader-stage").forEach((item) => {
    item.classList.remove("active");
    item.classList.add("done");
  });
  const wait = Math.max(DONE_PAUSE_MS, MIN_VISIBLE_MS - (Date.now() - shownAt));
  await new Promise((resolve) => setTimeout(resolve, wait));
  hideLoader();
}

export function hideLoader() {
  clearInterval(tipTimer);
  clearInterval(clockTimer);
  $("loader").classList.add("hidden");
  document.body.classList.remove("no-scroll");
}
