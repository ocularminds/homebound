const assert = require("node:assert/strict");
const test = require("node:test");
const Player = require("../app/web/static/program-player.js");

class Video extends EventTarget {
  constructor() {
    super(); this.src = ""; this.currentTime = 0; this.duration = 60;
    this.paused = true; this.ended = false; this.loads = 0; this.listeners = new Map();
  }
  addEventListener(name, fn, options) {
    this.listeners.set(name, [...(this.listeners.get(name) || []), fn]);
    super.addEventListener(name, fn, options);
  }
  removeEventListener(name, fn) {
    this.listeners.set(name, (this.listeners.get(name) || []).filter((item) => item !== fn));
    super.removeEventListener(name, fn);
  }
  removeAttribute(name) { if (name === "src") this.src = ""; }
  load() { this.currentTime = 0; this.ended = false; this.loads += 1; }
  play() { this.paused = false; this.dispatchEvent(new Event("play")); return Promise.resolve(); }
  pause() { this.paused = true; this.dispatchEvent(new Event("pause")); }
  advance(time) { this.currentTime = time; this.dispatchEvent(new Event("timeupdate")); }
  finish() { this.ended = true; this.paused = true; this.dispatchEvent(new Event("ended")); }
}
const media = (id = "current-program") => ({
  playback_id: id,
  stream: {
    available: true, src: "/static/media/film.mp4", poster: "/static/media/poster.jpg", duration: 60,
    breaks: [
      { at: 20, src: "/static/media/ad-one.mp4", duration: 6, title: "Movie night" },
      { at: 42, src: "/static/media/ad-two.mp4", duration: 6, title: "Popcorn" },
    ],
  },
});
const settle = () => new Promise(setImmediate);
function setup(report) {
  const program = new Video(), ad = new Video(), phases = [], views = [];
  const player = new Player(program, ad, {
    report: report || (async (value) => phases.push(value)),
    update: (value) => views.push(value),
  });
  player.load(media());
  return { player, program, ad, phases, views };
}

test("both commercials pause the film and resume its actual saved playhead", async () => {
  const { program, ad, player, phases } = setup();
  program.advance(20.125);
  await settle();
  assert.equal(program.paused, true);
  assert.equal(ad.paused, false);
  assert.equal(ad.src, "/static/media/ad-one.mp4");
  assert.deepEqual(phases, [{ playback_id: "current-program", phase: "break" }]);
  ad.advance(6); ad.finish();
  await settle();
  assert.equal(program.currentTime, 20.125);
  assert.equal(program.paused, false);
  assert.equal(player.activeBreak, null);
  program.advance(20.375);
  assert.equal(player.activeBreak, null);
  program.advance(42.25);
  assert.equal(ad.src, "/static/media/ad-two.mp4");
  await settle();
  ad.advance(6); ad.finish();
  await settle();
  assert.equal(program.currentTime, 42.25);
  assert.deepEqual(phases.map((item) => item.phase), ["break", "program", "break", "program"]);
});

test("pausing an ad freezes it so the viewer can read notes", async () => {
  const { program, ad, player, views } = setup();
  program.advance(20); ad.advance(2);
  player.toggle();
  assert.equal(ad.paused, true);
  assert.equal(program.paused, true);
  assert.equal(views.at(-1).remaining, 4);
  player.toggle();
  assert.equal(ad.paused, false);
  assert.equal(program.currentTime, 20);
  ad.finish(); await settle();
  assert.equal(program.paused, false);
});

test("a late ended callback from an old commercial cannot finish a new session's ad", async () => {
  const { program, ad, player, phases } = setup();
  program.advance(20);
  const oldEnded = ad.listeners.get("ended")[0];
  await settle();
  player.load(media("replacement-program"));
  program.advance(20);
  await settle();
  oldEnded();
  await settle();
  assert.equal(player.activeBreak.title, "Movie night");
  assert.equal(program.paused, true);
  assert.equal(phases.at(-1).playback_id, "replacement-program");
  assert.equal(phases.at(-1).phase, "break");
});

test("a missing commercial returns to the film without replaying the failed cue", async () => {
  const { program, ad, player, phases } = setup();
  program.advance(20.25); await settle();
  ad.dispatchEvent(new Event("error")); await settle();
  assert.equal(program.paused, false);
  assert.equal(program.currentTime, 20.25);
  assert.equal(phases.at(-1).phase, "program");
  program.advance(21);
  assert.equal(player.activeBreak, null);
});

test("notes hide immediately and the film resumes even if the server is unavailable", async () => {
  let rejectReport;
  const { program, ad, views } = setup(() => new Promise((_, reject) => { rejectReport = reject; }));
  program.advance(20); await settle();
  ad.finish();
  assert.equal(views.at(-1).commercial, false);
  assert.equal(program.paused, false);
  rejectReport(new Error("offline"));
  await settle();
  rejectReport(new Error("offline"));
  await settle();
  assert.equal(program.paused, false);
});

test("polling the same session does not reload a film or commercial", () => {
  const { program, ad, player } = setup();
  program.advance(20.2); ad.advance(3);
  const loads = [program.loads, ad.loads];
  player.load(media());
  assert.deepEqual([program.loads, ad.loads], loads);
  assert.equal(program.currentTime, 20.2);
  assert.equal(ad.currentTime, 3);
});

test("a hidden tab suspends its current video and resumes the same position", () => {
  const { program, ad, player } = setup();
  program.advance(20); ad.advance(2.5);
  player.suspend(true);
  assert.equal(ad.paused, true);
  player.suspend(false);
  assert.equal(ad.paused, false);
  assert.equal(ad.currentTime, 2.5);
  assert.equal(program.currentTime, 20);
});

test("replay resets both commercial cues and preserves the sound preference", async () => {
  const { program, ad, player } = setup();
  player.setMuted(false);
  program.advance(20); await settle();
  player.replay();
  assert.equal(program.currentTime, 0);
  assert.equal(program.muted, false);
  assert.equal(ad.muted, false);
  program.advance(20); await settle();
  assert.equal(player.activeBreak.title, "Movie night");
});

test("unfinished media never starts a broken stream", () => {
  const { player, program } = setup();
  const pending = media("pending"); pending.stream.available = false;
  player.load(pending);
  assert.equal(program.src, "");
  assert.equal(program.paused, true);
  assert.equal(player.stream, null);
});

test("switching to an illustrated scene stops both video elements", () => {
  const { player, program, ad } = setup();
  program.advance(20);
  player.load({ playback_id: "coast" });
  assert.equal(program.paused, true);
  assert.equal(ad.paused, true);
  assert.equal(player.activeBreak, null);
  assert.equal(ad.src, "");
});
