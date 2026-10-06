"use strict";

// Detect an utterance ending without retaining audio or making a network call.
class SpeechEndDetector {
  constructor(startedAt) {
    this.startedAt = startedAt;
    this.lastSampleAt = startedAt;
    this.lastVoiceAt = null;
    this.voicedMilliseconds = 0;
    this.heardSpeech = false;
    this.ended = false;
  }

  sample(rms, now) {
    if (this.ended) return null;
    const elapsed = Math.min(100, Math.max(0, now - this.lastSampleAt));
    this.lastSampleAt = now;
    if (Number.isFinite(rms) && rms >= 0.012) {
      this.voicedMilliseconds += elapsed;
      this.lastVoiceAt = now;
      if (this.voicedMilliseconds >= 250) this.heardSpeech = true;
    } else if (!this.heardSpeech && this.lastVoiceAt !== null && now - this.lastVoiceAt > 200) {
      this.voicedMilliseconds = 0;
      this.lastVoiceAt = null;
    }
    const reason = now - this.startedAt >= 45000 ? "limit"
      : this.heardSpeech && now - this.lastVoiceAt >= 1500 ? "silence" : null;
    if (reason) this.ended = true;
    return reason;
  }
}
