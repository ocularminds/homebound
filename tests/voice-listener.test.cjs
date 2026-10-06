const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const source = ["voice-activity.js", "voice-listener.js"].map((file) =>
  readFileSync(join(__dirname, "../app/web/static/", file), "utf8")
).join("\n");

function environment({ pendingPermission = false, audioBlocked = false } = {}) {
  let time = 0, level = 0, microphoneCalls = 0, resolvePermission;
  const timers = new Map(), intervals = new Map(), recordings = [], utterances = [], errors = [];
  class Track extends EventTarget {
    readyState = "live";
    stop() { this.readyState = "ended"; }
  }
  const track = new Track();
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  class Context {
    state = audioBlocked ? "suspended" : "running";
    resume() { return this.state === "suspended" ? new Promise(() => {}) : Promise.resolve(); }
    close() { this.state = "closed"; return Promise.resolve(); }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createAnalyser() { return { fftSize: 2048, getFloatTimeDomainData(samples) { samples.fill(level); }, disconnect() {} }; }
  }
  class Recorder extends EventTarget {
    static isTypeSupported() { return true; }
    state = "inactive";
    constructor(_stream, { mimeType }) { super(); this.mimeType = mimeType; recordings.push(this); }
    start() { this.state = "recording"; }
    stop() {
      this.state = "inactive";
      queueMicrotask(() => {
        const data = new Event("dataavailable");
        data.data = new Blob(["test audio"], { type: this.mimeType });
        this.dispatchEvent(data);
        this.dispatchEvent(new Event("stop"));
      });
    }
  }
  const Listener = runInNewContext(source + "\nContinuousVoiceListener;", {
    window: { AudioContext: Context, MediaRecorder: Recorder }, MediaRecorder: Recorder,
    navigator: { mediaDevices: { getUserMedia() {
      microphoneCalls += 1;
      return pendingPermission ? new Promise((resolve) => { resolvePermission = resolve; }) : Promise.resolve(stream);
    } } },
    Blob, Float32Array, performance: { now: () => time },
    setInterval(callback) { const id = {}; intervals.set(id, callback); return id; },
    clearInterval(id) { intervals.delete(id); },
    setTimeout(callback, duration) {
      if (duration === 120) return setTimeout(callback, 0);
      const id = {}; timers.set(id, { callback, duration }); return id;
    },
    clearTimeout(id) { timers.delete(id); },
  });
  const listener = new Listener({ onUtterance: (audio) => utterances.push(audio), onError: (error) => errors.push(error), onState() {} });
  return {
    listener, recordings, utterances, errors, track, timers, intervals,
    calls: () => microphoneCalls,
    grant: () => resolvePermission(stream),
    async feed(milliseconds, rms) {
      level = rms;
      for (let elapsed = 0; elapsed < milliseconds; elapsed += 50) {
        time += 50;
        for (const callback of [...intervals.values()]) callback();
        await Promise.resolve();
      }
    },
    async limit() {
      const timer = [...timers.values()].find((item) => item.duration === 45000);
      timer.callback();
      await Promise.resolve(); await Promise.resolve();
    },
  };
}

test("quiet buffers rotate locally without speech requests or reacquiring the microphone", async () => {
  const env = environment();
  assert.equal(await env.listener.connect(), true);
  assert.equal(env.listener.listen(), true);
  await env.limit();
  await env.limit();
  assert.equal(env.recordings.length, 3);
  assert.equal(env.utterances.length, 0);
  assert.equal(env.calls(), 1);
  env.listener.disconnect();
  assert.equal(env.track.readyState, "ended");
  assert.equal(env.timers.size + env.intervals.size, 0);
});

test("two speech turns reuse the stream and pause capture while the assistant replies", async () => {
  const env = environment();
  await env.listener.connect();
  env.listener.listen();
  await env.feed(750, .06);
  await env.feed(1600, 0);
  assert.equal(env.utterances.length, 1);
  assert.equal(env.listener.recorder, null);
  assert.equal(env.track.readyState, "live");
  // Loud speaker output while suspended cannot start a recording or another request.
  await env.feed(3000, .1);
  assert.equal(env.utterances.length, 1);
  env.listener.listen();
  await env.feed(700, .05);
  await env.feed(1600, 0);
  assert.equal(env.utterances.length, 2);
  assert.equal(env.calls(), 1);
  env.listener.disconnect();
  assert.equal(env.errors.length, 0);
});

test("muting a speech buffer discards it even when the recorder stop event arrives later", async () => {
  const env = environment();
  await env.listener.connect();
  env.listener.listen();
  await env.feed(1000, .06);
  env.listener.disconnect();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(env.utterances.length, 0);
  assert.equal(env.track.readyState, "ended");
  assert.equal(env.timers.size + env.intervals.size, 0);
});

test("muting while permission is pending stops the late-arriving stream", async () => {
  const env = environment({ pendingPermission: true });
  const connecting = env.listener.connect();
  env.listener.disconnect();
  env.grant();
  assert.equal(await connecting, false);
  assert.equal(env.track.readyState, "ended");
  assert.equal(env.listener.recorder, null);
});

test("a blocked AudioContext returns for a gesture instead of hanging startup", async () => {
  const env = environment({ audioBlocked: true });
  assert.equal(await env.listener.connect(), false);
  assert.equal(env.listener.listen(), false);
  env.listener.context.state = "running";
  assert.equal(await env.listener.connect(), true);
  assert.equal(env.listener.listen(), true);
  assert.equal(env.calls(), 1);
  env.listener.disconnect();
});
