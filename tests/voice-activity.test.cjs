const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const source = readFileSync(join(__dirname, "../app/web/static/voice-activity.js"), "utf8");
const SpeechEndDetector = runInNewContext(`${source}\nSpeechEndDetector;`);

function feed(detector, from, to, level) {
  let result = null;
  for (let time = from; time <= to; time += 50) result = detector.sample(level, time) || result;
  return result;
}

test("speech finishes once after a 1.5-second pause", () => {
  const detector = new SpeechEndDetector(0);
  assert.equal(feed(detector, 0, 1000, 0.06), null);
  assert.equal(feed(detector, 1050, 2450, 0.001), null);
  assert.equal(detector.sample(0.001, 2500), "silence");
  assert.equal(detector.sample(0.001, 2550), null);
});

test("a brief hesitation does not submit mid-sentence", () => {
  const detector = new SpeechEndDetector(0);
  assert.equal(feed(detector, 0, 600, 0.06), null);
  assert.equal(feed(detector, 650, 1800, 0.001), null);
  assert.equal(feed(detector, 1850, 2700, 0.04), null);
  assert.equal(feed(detector, 2750, 4150, 0.001), null);
  assert.equal(detector.sample(0.001, 4200), "silence");
});

test("silence and a short microphone click do not count as speech", () => {
  const detector = new SpeechEndDetector(0);
  assert.equal(feed(detector, 0, 100, 0.1), null);
  assert.equal(feed(detector, 150, 10000, 0.001), null);
  assert.equal(detector.heardSpeech, false);
});

test("a delayed audio sample cannot make one spike count as speech", () => {
  const detector = new SpeechEndDetector(0);
  assert.equal(detector.sample(0.1, 5000), null);
  assert.equal(feed(detector, 5050, 10000, 0), null);
  assert.equal(detector.heardSpeech, false);
});

test("both continuous speech and silence retain the 45-second limit", () => {
  for (const level of [0, 0.1]) {
    const detector = new SpeechEndDetector(0);
    assert.equal(feed(detector, 0, 44950, level), null);
    assert.equal(detector.sample(level, 45000), "limit");
  }
});
