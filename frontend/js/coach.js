// AI coach panel (cloned from #coachTemplate): requests coaching for a saved analysis and renders it.
import { el, renderScoreBars, requestJson } from "./common.js";

function fillList(list, items, render) {
  list.textContent = "";
  items.forEach((item) => {
    const li = el("li");
    render(li, item);
    list.appendChild(li);
  });
}

export function createCoachView(container, onSessionExpired) {
  const root = document.getElementById("coachTemplate").content.firstElementChild.cloneNode(true);
  root.classList.add("hidden");
  container.appendChild(root);
  const part = (name) => root.querySelector(`[data-el="${name}"]`);
  let activeId = null;

  function showMessage(title, message, canRetry) {
    part("contentScore").textContent = "-";
    part("coachTitle").textContent = title;
    part("coachMeta").textContent = message;
    part("coachBody").classList.add("hidden");
    part("retryCoachBtn").classList.toggle("hidden", !canRetry);
  }

  function show(coach) {
    root.classList.remove("hidden");
    part("contentScore").textContent = coach.content_score;
    part("coachTitle").textContent = coach.on_topic ? "Here's what I thought" : "This one went off-topic";
    part("coachMeta").textContent = "";
    const meta = coach.meta || {};
    part("coachFooter").textContent = meta.model
      ? `Written by an AI coach (${meta.model} via ${meta.provider}${meta.latency_ms ? `, ${(meta.latency_ms / 1000).toFixed(1)}s` : ""}). It can get things wrong, so trust your own judgement too.`
      : "";
    part("coachSummary").textContent = coach.summary;
    renderScoreBars(part("contentBreakdown"), coach.dimensions, coach.content_scores);

    const { framework } = coach;
    part("frameworkTitle").textContent = `Did you cover the ${framework.name} steps?`;
    const chips = part("frameworkChips");
    chips.textContent = "";
    framework.parts.forEach((item) => {
      const present = framework.present.includes(item);
      chips.appendChild(el("span", present ? "chip chip-present" : "chip chip-missing", `${present ? "✓" : "✗"} ${item}`));
    });

    fillList(part("coachStrengths"), coach.strengths, (li, text) => {
      li.textContent = text;
    });
    fillList(part("coachImprovements"), coach.improvements, (li, item) => {
      li.append(el("b", "", item.issue), el("br"), item.suggestion);
    });
    part("coachTopic").textContent = coach.topic_feedback;
    part("improvedTitle").textContent =
      coach.improved_answer_type === "template" ? "A structure to fill in with your own details" : "How you could say it";
    part("improvedAnswer").textContent = coach.improved_answer;
    part("coachBody").classList.remove("hidden");
    part("retryCoachBtn").classList.add("hidden");
  }

  async function request(analysisId) {
    activeId = analysisId;
    root.classList.remove("hidden");
    showMessage("Listening back to your answer...", "Your coach is going through what you said.", false);
    try {
      const data = await requestJson(`/analyses/${analysisId}/coach`, { method: "POST" });
      if (analysisId === activeId) show(data.coach);
    } catch (error) {
      if (analysisId !== activeId) return;
      if (error.status === 401) {
        onSessionExpired();
        return;
      }
      showMessage("Your coach isn't available right now", error.message, [429, 503, 504].includes(error.status));
    }
  }

  part("retryCoachBtn").addEventListener("click", () => {
    if (activeId) request(activeId);
  });
  part("copyImprovedBtn").addEventListener("click", async () => {
    const button = part("copyImprovedBtn");
    try {
      await navigator.clipboard.writeText(part("improvedAnswer").textContent);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Copy failed";
    }
    setTimeout(() => {
      button.textContent = "Copy";
    }, 1500);
  });

  return {
    request,
    show,
    hide() {
      activeId = null;
      root.classList.add("hidden");
    },
  };
}
