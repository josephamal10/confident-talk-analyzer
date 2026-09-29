// Microphone recording with an optional preparation countdown and an auto-stop time limit.
const TICK_MS = 100;

export class Recorder {
  // onPrep(remainingSeconds), onTick(elapsedSeconds), onStart(), onStop(blob, elapsedSeconds)
  constructor({ onPrep, onTick, onStart, onStop }) {
    this.handlers = { onPrep, onTick, onStart, onStop };
    this.state = "idle";
  }

  // Asks for the microphone first, so the permission prompt appears before any countdown.
  async start({ prepSeconds = 0, limitSeconds = null } = {}) {
    if (this.state !== "idle" || this.starting) return;
    this.starting = true;
    this.cancelled = false;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } finally {
      this.starting = false;
    }
    // Cancelled while the browser was still asking for the microphone.
    if (this.cancelled) {
      this.cancelled = false;
      this.releaseMicrophone();
      this.handlers.onStop?.(null, 0);
      return;
    }
    this.limitSeconds = limitSeconds;
    if (prepSeconds > 0) {
      this.state = "prep";
      const prepEnds = performance.now() + prepSeconds * 1000;
      this.handlers.onPrep?.(prepSeconds);
      this.timer = setInterval(() => {
        const remaining = (prepEnds - performance.now()) / 1000;
        if (remaining <= 0) {
          clearInterval(this.timer);
          this.beginRecording();
        } else {
          this.handlers.onPrep?.(remaining);
        }
      }, TICK_MS);
    } else {
      this.beginRecording();
    }
  }

  beginRecording() {
    this.state = "recording";
    this.discard = false;
    this.chunks = [];
    this.mediaRecorder = new MediaRecorder(this.stream);
    this.mediaRecorder.ondataavailable = (event) => this.chunks.push(event.data);
    this.mediaRecorder.onstop = () => this.finish();
    this.mediaRecorder.start();
    this.startedAt = performance.now();
    this.handlers.onStart?.();
    this.timer = setInterval(() => {
      const elapsed = this.elapsed();
      this.handlers.onTick?.(elapsed);
      if (this.limitSeconds && elapsed >= this.limitSeconds) this.stop();
    }, TICK_MS);
  }

  elapsed() {
    return this.startedAt ? (performance.now() - this.startedAt) / 1000 : 0;
  }

  // Ends the thinking-time countdown early and starts recording now.
  skipPrep() {
    if (this.state !== "prep") return;
    clearInterval(this.timer);
    this.beginRecording();
  }

  // Stopping during the countdown cancels without recording anything.
  stop() {
    clearInterval(this.timer);
    if (this.state === "prep") {
      this.discard = false;
      this.releaseMicrophone();
      this.state = "idle";
      this.handlers.onStop?.(null, 0);
    } else if (this.state === "recording") {
      this.state = "stopping";
      this.elapsedAtStop = this.elapsed();
      this.mediaRecorder.stop();
    }
  }

  // Stops and throws the recording away (onStop receives no blob).
  cancel() {
    if (this.starting) {
      this.cancelled = true;
      return;
    }
    if (this.state === "idle") return;
    this.discard = true;
    this.stop();
  }

  finish() {
    const type = this.mediaRecorder.mimeType || "audio/webm";
    const blob = this.discard ? null : new Blob(this.chunks, { type });
    this.discard = false;
    this.releaseMicrophone();
    this.state = "idle";
    this.startedAt = null;
    this.handlers.onStop?.(blob, this.elapsedAtStop);
  }

  releaseMicrophone() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}

export function fileNameFor(blob) {
  if (blob.type.includes("ogg")) return "recording.ogg";
  if (blob.type.includes("mp4") || blob.type.includes("aac")) return "recording.mp4";
  return "recording.webm";
}
