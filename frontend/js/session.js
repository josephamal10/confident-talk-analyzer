// Session view: replay a saved recording with its scores, transcript, feedback and AI coaching.
import { formatDateLabel, requestJson } from "./common.js";
import { createCoachView } from "./coach.js";
import { createResultView } from "./results.js";

const $ = (id) => document.getElementById(id);
let resultView = null;
let coachView = null;
let currentId = null;

export async function showSession(id, catalog, onSessionExpired) {
  if (!resultView) {
    resultView = createResultView($("sessionResults"));
    coachView = createCoachView($("sessionCoach"), onSessionExpired);
    $("sessionCoachBtn").addEventListener("click", () => {
      $("sessionCoachBtn").classList.add("hidden");
      coachView.request(currentId);
    });
  }
  currentId = id;
  resultView.hide();
  coachView.hide();
  $("sessionCoachBtn").classList.add("hidden");
  const audio = $("sessionAudio");
  audio.pause();
  audio.classList.add("hidden");
  $("sessionNoAudio").classList.add("hidden");
  $("sessionKicker").textContent = "Loading session...";
  $("sessionTitle").textContent = "";

  let session;
  try {
    session = await requestJson(`/analyses/${id}`);
  } catch (error) {
    if (error.status === 401) return onSessionExpired();
    $("sessionKicker").textContent = error.status === 404 ? "Session not found" : error.message;
    return;
  }
  if (id !== currentId) return;

  const mode = catalog.modes.find((item) => item.id === session.mode) || catalog.modes[0];
  $("sessionKicker").textContent = `${mode.label} · ${formatDateLabel(session.timestamp, true)}`;
  $("sessionTitle").textContent = session.topic || "Free speaking";

  if (session.audio_url) {
    audio.src = session.audio_url;
    audio.classList.remove("hidden");
  } else {
    audio.removeAttribute("src");
    $("sessionNoAudio").classList.remove("hidden");
  }

  resultView.render(session, mode);
  if (session.coach) coachView.show(session.coach);
  else if (session.coach_available) $("sessionCoachBtn").classList.remove("hidden");
}

export function leaveSession() {
  $("sessionAudio").pause();
}
