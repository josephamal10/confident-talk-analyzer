// Small canvas line chart used for score history and the per-talk pace timeline.
import { getThemeValue } from "./common.js";

// options: values, min, max, ticks (y values with grid lines), labels (x labels, same length as
// values or two for first/last), band ([low, high] shaded range), highlight (indexes drawn in red).
export function drawLineChart(canvas, options) {
  const { values = [], min = 0, max = 10, ticks = [], labels = [], band = null, highlight = [], emptyText = "" } = options;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const cssWidth = Math.max(280, Math.floor(canvas.getBoundingClientRect().width || 320));
  const cssHeight = options.height || 220;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  canvas.style.height = `${cssHeight}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const text = getThemeValue("--chart-text", "rgba(148, 163, 184, 0.9)");
  ctx.font = '12px "Space Grotesk", sans-serif';
  if (!values.length) {
    ctx.fillStyle = text;
    ctx.fillText(emptyText, 16, cssHeight / 2);
    return;
  }

  const pad = { left: 40, right: 18, top: 16, bottom: 30 };
  const plotW = cssWidth - pad.left - pad.right;
  const plotH = cssHeight - pad.top - pad.bottom;
  const yAt = (value) => pad.top + ((max - Math.min(max, Math.max(min, value))) / (max - min)) * plotH;
  const xAt = (index) => (values.length === 1 ? pad.left + plotW / 2 : pad.left + (index * plotW) / (values.length - 1));

  if (band) {
    ctx.fillStyle = getThemeValue("--chart-band", "rgba(56, 189, 248, 0.12)");
    ctx.fillRect(pad.left, yAt(band[1]), plotW, yAt(band[0]) - yAt(band[1]));
  }
  ctx.strokeStyle = getThemeValue("--chart-grid", "rgba(148, 163, 184, 0.22)");
  ctx.lineWidth = 1;
  ctx.fillStyle = text;
  ticks.forEach((tick) => {
    const y = yAt(tick);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(cssWidth - pad.right, y);
    ctx.stroke();
    ctx.fillText(String(tick), 6, y + 4);
  });

  ctx.strokeStyle = getThemeValue("--chart-line", "#3b82f6");
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  values.forEach((value, index) => (index ? ctx.lineTo(xAt(index), yAt(value)) : ctx.moveTo(xAt(index), yAt(value))));
  ctx.stroke();

  const highlighted = new Set(highlight);
  values.forEach((value, index) => {
    ctx.fillStyle = highlighted.has(index) ? getThemeValue("--danger", "#ef4444") : getThemeValue("--chart-point", "#38bdf8");
    ctx.beginPath();
    ctx.arc(xAt(index), yAt(value), 4, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = text;
  if (labels.length === values.length && values.length <= 12) {
    labels.forEach((label, index) => {
      const width = ctx.measureText(label).width;
      ctx.fillText(label, Math.min(cssWidth - width - 4, Math.max(4, xAt(index) - width / 2)), cssHeight - 8);
    });
  } else if (labels.length) {
    ctx.fillText(labels[0], pad.left, cssHeight - 8);
    const last = labels[labels.length - 1];
    ctx.fillText(last, cssWidth - pad.right - ctx.measureText(last).width, cssHeight - 8);
  }
}
