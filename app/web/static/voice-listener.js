"use strict";

// One microphone connection for the conversation. Only speech-containing
// utterances leave the browser; quiet 45-second buffers are discarded locally.
class ContinuousVoiceListener {
  constructor({ onUtterance, onError, onState, onLevel = () => {} }) {
    Object.assign(this, { onUtterance, onError, onState, onLevel });
    this.stream = this.context = this.recorder = this.analyser = this.source = null;
    this.connecting = this.timer = this.limitTimer = null;
    this.connectionGeneration = this.captureGeneration = 0;
    this.listening = false;
  }

  get ready() {
    return this.context?.state === "running" && this.stream?.getAudioTracks().some((track) => track.readyState === "live");
  }

  async connect() {
    // This call also runs directly from Start talking, preserving the gesture.
    this.context?.resume().catch(() => {});
    if (this.connecting) return this.connecting;
    if (this.ready) return true;
    const generation = ++this.connectionGeneration;
    this.connecting = this.open(generation).finally(() => {
      if (generation === this.connectionGeneration) this.connecting = null;
    });
    return this.connecting;
  }

  async open(generation) {
    try {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context || !window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("This browser cannot keep a voice conversation open. You can still type.");
      }
      if (!this.context || this.context.state === "closed") this.context = new Context();
      const context = this.context;
      context.resume().catch(() => {});
      if (!this.stream) {
        this.onState("permission");
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        if (generation !== this.connectionGeneration) {
          stream.getTracks().forEach((track) => track.stop());
          return false;
        }
        this.stream = stream;
        this.source = context.createMediaStreamSource(stream);
        this.analyser = context.createAnalyser();
        this.analyser.fftSize = 2048;
        this.source.connect(this.analyser);
        stream.getAudioTracks().forEach((track) => track.addEventListener("ended", () => {
          if (this.stream === stream) {
            this.disconnect();
            this.onError(new Error("The microphone disconnected. Connect it, then choose Start talking."));
          }
        }));
      }
      // resume() can remain pending until a gesture. Never hang startup on it.
      await Promise.race([context.resume().catch(() => {}), new Promise((resolve) => setTimeout(resolve, 120))]);
      return generation === this.connectionGeneration && Boolean(this.ready);
    } catch (error) {
      if (generation === this.connectionGeneration) {
        this.disconnect();
        this.onError(error);
      }
      return false;
    }
  }

  listen() {
    if (!this.ready || this.recorder) return false;
    this.listening = true;
    const generation = ++this.captureGeneration;
    const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"].find((type) => MediaRecorder.isTypeSupported(type));
    if (!mimeType) {
      this.onError(new Error("Your browser has no supported audio recording format. You can still type."));
      return false;
    }
    let recorder;
    try { recorder = new MediaRecorder(this.stream, { mimeType }); }
    catch (error) { this.onError(error); return false; }
    this.recorder = recorder;
    const detector = new SpeechEndDetector(performance.now());
    const samples = new Float32Array(this.analyser.fftSize);
    let chunks = [], bytes = 0;
    recorder.addEventListener("dataavailable", (event) => {
      if (generation !== this.captureGeneration) return;
      if (event.data.size) { chunks.push(event.data); bytes += event.data.size; }
      if (bytes > 8 * 1024 * 1024) {
        this.suspend();
        this.onError(new Error("That request was too long. Try a shorter sentence."));
      }
    });
    recorder.addEventListener("error", () => {
      if (generation !== this.captureGeneration) return;
      this.suspend();
      this.onError(new Error("The microphone recording stopped unexpectedly. Choose Start talking to reconnect."));
    });
    recorder.addEventListener("stop", () => {
      if (generation !== this.captureGeneration) { chunks = []; return; }
      this.clearTimers();
      this.recorder = null;
      if (!detector.heardSpeech || !bytes) {
        chunks = [];
        if (this.listening) this.listen();
        return;
      }
      this.listening = false;
      const audio = new Blob(chunks, { type: mimeType });
      chunks = [];
      this.onState("transcribing");
      Promise.resolve(this.onUtterance(audio)).catch(this.onError);
    });
    try { recorder.start(500); }
    catch (error) { this.suspend(); this.onError(error); return false; }
    this.timer = setInterval(() => {
      if (generation !== this.captureGeneration || recorder.state !== "recording") return;
      this.analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
      this.onLevel(Math.min(1, rms * 14));
      if (detector.sample(rms, performance.now())) recorder.stop();
    }, 50);
    this.limitTimer = setTimeout(() => {
      if (generation === this.captureGeneration && recorder.state === "recording") recorder.stop();
    }, 45000);
    this.onState("listening");
    return true;
  }

  clearTimers() {
    clearInterval(this.timer);
    clearTimeout(this.limitTimer);
    this.timer = this.limitTimer = null;
    this.onLevel(0);
  }

  suspend() {
    this.listening = false;
    this.captureGeneration += 1;
    this.clearTimers();
    const recorder = this.recorder;
    this.recorder = null;
    if (recorder?.state === "recording") recorder.stop();
  }

  disconnect() {
    this.connectionGeneration += 1;
    this.connecting = null;
    this.suspend();
    const stream = this.stream;
    this.stream = null;
    stream?.getTracks().forEach((track) => track.stop());
    this.source?.disconnect();
    this.analyser?.disconnect();
    if (this.context?.state !== "closed") this.context?.close().catch(() => {});
    this.context = this.source = this.analyser = null;
  }
}
