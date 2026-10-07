"use strict";

// Real media events drive commercial breaks. The program element stays paused
// at its actual playhead; a second element plays the commercial independently.
(function (root, factory) {
  const Player = factory();
  if (typeof module === "object" && module.exports) module.exports = Player;
  else root.HomeBoundProgramPlayer = Player;
})(typeof window === "undefined" ? globalThis : window, function () {
  return class HomeBoundProgramPlayer {
    constructor(program, advertisement, { report = async () => {}, update = () => {} } = {}) {
      this.program = program;
      this.advertisement = advertisement;
      this.report = report;
      this.update = update;
      this.generation = 0;
      this.session = null;
      this.stream = null;
      this.activeBreak = null;
      this.playedBreaks = new Set();
      this.muted = true;
      this.wantPlay = false;
      this.suspended = false;
      this.phaseQueue = Promise.resolve();
      this.error = "";
      this.cleanupBreak = () => {};
      program.addEventListener("timeupdate", () => this.tick());
      program.addEventListener("ended", () => { if (this.stream) { this.wantPlay = false; this.emit(); } });
      program.addEventListener("error", () => {
        if (!this.stream) return;
        this.wantPlay = false;
        this.error = "The film could not load. Try replaying it.";
        this.emit();
      });
      for (const video of [program, advertisement]) {
        for (const event of ["play", "pause", "waiting", "playing", "loadedmetadata", "timeupdate"]) {
          video.addEventListener(event, () => this.emit());
        }
      }
    }

    get current() { return this.activeBreak ? this.advertisement : this.program; }

    emit() {
      this.update({
        active: Boolean(this.stream),
        commercial: Boolean(this.activeBreak),
        title: this.activeBreak?.title || "",
        remaining: this.activeBreak ? Math.max(0, this.activeBreak.duration - this.advertisement.currentTime) : 0,
        paused: this.current.paused,
        muted: this.muted,
        ended: this.program.ended && !this.activeBreak,
        time: this.program.currentTime || 0,
        duration: this.program.duration || this.stream?.duration || 0,
        error: this.error,
      });
    }

    load(media) {
      if (!media?.stream?.available) { if (this.stream) this.unload(); return; }
      if (media?.playback_id === this.session && this.stream?.src === media.stream?.src) return;
      this.unload();
      this.session = media.playback_id;
      this.stream = media.stream;
      this.program.poster = this.stream.poster;
      this.program.src = this.stream.src;
      this.program.muted = this.advertisement.muted = this.muted;
      this.program.load();
      this.wantPlay = true;
      this.playCurrent();
      this.emit();
    }

    unload() {
      this.generation += 1;
      this.cleanupBreak();
      this.activeBreak = null;
      this.stream = null;
      this.session = null;
      this.wantPlay = false;
      this.error = "";
      this.playedBreaks.clear();
      for (const video of [this.program, this.advertisement]) {
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
      this.emit();
    }

    notifyPhase(phase, generation = this.generation) {
      const session = this.session;
      this.phaseQueue = this.phaseQueue.catch(() => {}).then(async () => {
        if (generation !== this.generation || !session) return;
        await this.report({ playback_id: session, phase });
      }).catch(() => {
        if (generation === this.generation) {
          this.error = "The film is playing. Home notes are temporarily unavailable.";
          this.emit();
        }
      });
      return this.phaseQueue;
    }

    async playCurrent() {
      if (!this.stream || !this.wantPlay || this.suspended) return;
      const generation = this.generation, video = this.current;
      try { await video.play(); }
      catch (_) {
        if (generation !== this.generation || video !== this.current) return;
        this.wantPlay = false;
        this.error = "Press play to continue.";
      }
      if (generation === this.generation) this.emit();
    }

    tick() {
      if (!this.stream || this.activeBreak || !this.wantPlay || this.suspended || this.program.paused) return;
      const cue = this.stream.breaks.find((item, index) => !this.playedBreaks.has(index) && this.program.currentTime >= item.at);
      if (cue) this.startBreak(cue);
    }

    startBreak(cue) {
      const generation = this.generation;
      this.playedBreaks.add(this.stream.breaks.indexOf(cue));
      this.activeBreak = cue;
      this.program.pause();
      this.resumeAt = this.program.currentTime;
      this.advertisement.src = cue.src;
      this.advertisement.muted = this.muted;
      const finish = () => this.finishBreak(generation);
      const failed = () => {
        this.error = "The commercial could not load. Returning to the film.";
        this.finishBreak(generation);
      };
      this.advertisement.addEventListener("ended", finish);
      this.advertisement.addEventListener("error", failed);
      this.cleanupBreak = () => {
        this.advertisement.removeEventListener("ended", finish);
        this.advertisement.removeEventListener("error", failed);
      };
      this.advertisement.load();
      this.notifyPhase("break", generation);
      this.emit();
      this.playCurrent();
    }

    finishBreak(generation) {
      if (generation !== this.generation || !this.activeBreak) return;
      this.cleanupBreak();
      this.activeBreak = null;
      this.advertisement.pause();
      this.program.currentTime = this.resumeAt;
      // Hide personal notes locally before any network round trip can complete.
      this.emit();
      this.notifyPhase("program", generation);
      if (generation === this.generation) this.playCurrent();
    }

    toggle() {
      if (!this.stream) return;
      this.error = "";
      if (this.program.ended && !this.activeBreak) { this.replay(); return; }
      this.wantPlay = !this.wantPlay;
      if (this.wantPlay) this.playCurrent();
      else this.current.pause();
      this.emit();
    }

    setMuted(muted) {
      this.muted = Boolean(muted);
      this.program.muted = this.advertisement.muted = this.muted;
      this.emit();
    }

    replay() {
      if (!this.stream) return;
      this.generation += 1;
      this.cleanupBreak();
      this.advertisement.pause();
      this.activeBreak = null;
      this.playedBreaks.clear();
      this.program.currentTime = 0;
      this.wantPlay = true;
      this.error = "";
      this.notifyPhase("program");
      this.playCurrent();
      this.emit();
    }

    suspend(value) {
      this.suspended = value;
      if (value) this.current.pause();
      else this.playCurrent();
      this.emit();
    }
  };
});
