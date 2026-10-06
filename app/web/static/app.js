"use strict";

const $ = (selector) => document.querySelector(selector);
const ui = {
  title: $("#stage-title"), description: $("#stage-description"), heard: $("#heard-text"),
  input: $("#message"), mic: $("#mic-button"), send: $("#send-button"),
  voiceToggle: $("#voice-toggle"), voiceStatus: $("#voice-status"), notice: $("#notice"),
  conversation: $("#conversation"), activity: $("#activity-list"), start: $("#start-talking"),
};
const emptyActivity = ui.activity.cloneNode(true);
const state = {
  config: null, turns: [], activity: [], pending: new Set(), dialogue: null,
  busy: false, starting: false, micEnabled: true, speechEnabled: true,
  typing: false, mode: "connecting", showGreeting: true, greeted: false,
  pendingMessage: null, pollTimer: null, voiceGeneration: 0, transcriptionAbort: null,
  audio: null, audioUrls: new Map(), speechGeneration: 0, speechAbort: null,
  playing: false, finishAudio: null, pendingPlayback: null,
};

function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#i-" + name);
  svg.setAttribute("aria-hidden", "true");
  svg.append(use);
  return svg;
}
function notice(message = "") {
  ui.notice.textContent = message;
  ui.notice.hidden = !message;
}
async function request(path, body, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: body === undefined ? "GET" : "POST", credentials: "same-origin",
      headers: { "X-HomeBound-Client": "web", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body), ...options,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("The home connection was interrupted. Check the action history before asking again.");
  }
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    const error = new Error(result.message || "The home service couldn't complete that request.");
    error.code = result.error;
    throw error;
  }
  return options.audio ? response.blob() : response.json();
}

function renderStage(mode = state.mode) {
  state.mode = mode;
  document.body.dataset.state = mode;
  const latest = state.turns.at(-1);
  const showTurn = !state.showGreeting && latest;
  const pending = Boolean(state.pendingMessage);
  document.body.dataset.hasTurn = String(Boolean(showTurn || pending));
  ui.heard.hidden = !(pending || showTurn);
  ui.heard.textContent = pending ? "“" + state.pendingMessage + "”" : showTurn ? "“" + latest.message + "”" : "";
  ui.title.textContent = pending ? "Let me check that." : showTurn ? latest.reply : state.config?.greeting.greeting || "Make yourself at home.";
  ui.description.textContent = pending ? "" : showTurn ? latest.follow_up || "" : state.config?.greeting.prompt || "What else can I help with?";
  ui.description.hidden = !ui.description.textContent;
  const labels = {
    connecting: "Getting ready", permission: "Allow microphone access",
    listening: "Listening · just talk", transcribing: "Hearing your request",
    thinking: "One moment", preparing: "Getting your reply", speaking: "Alexa is speaking",
    muted: "Microphone off", ready: "Ready when you are", typing: "You can type below",
    interaction: "Tap once to start talking",
  };
  ui.voiceStatus.textContent = labels[mode] || labels.ready;
  $("#suggestions").hidden = Boolean(showTurn || pending || state.typing);
  const outcomeHolder = $("#current-outcome");
  outcomeHolder.replaceChildren();
  if (showTurn && !pending && latest.trace?.length) {
    const entry = latest.trace.filter((item) => item.invoked).at(-1) || latest.trace.at(-1);
    outcomeHolder.append(badge(entry));
    const details = el("button", "text-button", "View details");
    details.type = "button";
    details.addEventListener("click", () => openDialog("home-dialog"));
    outcomeHolder.append(details);
  }
}

function updateControls() {
  ui.input.readOnly = state.busy;
  ui.send.disabled = state.busy || !state.config;
  ui.start.disabled = state.busy || state.starting || !state.config?.voice_configured;
  ui.mic.disabled = !state.config?.voice_configured;
  ui.mic.setAttribute("aria-pressed", String(state.micEnabled));
  ui.mic.setAttribute("aria-label", state.micEnabled ? "Mute microphone" : "Enable microphone");
  ui.mic.querySelector("span").textContent = state.micEnabled ? "Mic on" : "Mic off";
  ui.mic.querySelector("use").setAttribute("href", state.micEnabled ? "#i-mic" : "#i-muted");
  ui.voiceToggle.setAttribute("aria-pressed", String(state.speechEnabled));
  ui.voiceToggle.textContent = state.speechEnabled ? "Spoken replies on" : "Spoken replies off";
  ui.voiceToggle.disabled = !state.config?.voice_configured;
  $("#type-button").disabled = state.busy;
  $("#clear-chat").disabled = state.busy;
  document.querySelectorAll("[data-prompt], .resume-button").forEach((button) => { button.disabled = state.busy; });
}
function renderContext(dialogue, captured = null) {
  state.dialogue = dialogue || state.dialogue;
  const context = state.dialogue || {};
  const parts = [];
  if (context.visitor === "delivery" || captured?.actor === "delivery-agent") parts.push("Delivery");
  else if (context.visitor) parts.push(context.visitor === "resident" ? "Someone at home" : "Guest");
  if (context.speaker) parts.push(context.speaker === "child" ? "Child at home" : "Adult at home");
  const expected = context.expected ?? captured?.delivery_expected;
  const recognized = context.recognized ?? captured?.courier_recognized;
  if (typeof expected === "boolean") parts.push(expected ? "Expected" : "Unexpected");
  if (typeof recognized === "boolean") parts.push(recognized ? "Recognized in simulation" : "Not recognized");
  if (context.simulated_time) parts.push(context.simulated_time + " demo time");
  $("#context-label").textContent = parts.slice(0, 2).join(" · ") || "Your home. Just ask.";
  $("#context-details").textContent = parts.length ? parts.join(" · ") + ". These are conversation claims for the simulated home." : "No household context has been provided yet. Alexa will ask when it is needed.";
}

function outcome(entry) {
  const result = entry.result || {};
  if (!entry.invoked) return { label: "NOT SUBMITTED", kind: "unknown" };
  if (result.decision === "ESCALATE") return { label: "APPROVAL NEEDED", kind: "hold" };
  if (result.decision === "BLOCK") return { label: "BLOCKED", kind: "block" };
  if (result.decision === "ALLOW" && result.execution === "PERFORMED") return { label: "ALLOWED · EXECUTED", kind: "allow" };
  if (result.decision === "ALLOW") return { label: "ALLOWED · NOT EXECUTED", kind: "hold" };
  return { label: result.decision === "AUTHORITY_UNAVAILABLE" ? "AUTHORITY UNAVAILABLE" : "RESULT UNKNOWN", kind: "unknown" };
}

function badge(entry) {
  const status = outcome(entry);
  return el("span", `decision-badge ${status.kind}`, status.label);
}

function renderConversation() {
  ui.conversation.replaceChildren();
  for (const turn of state.turns) {
    const row = el("article", "turn");
    const user = el("div", "user-message");
    user.append(el("p", "", turn.message));
    const reply = el("div", "assistant-message");
    reply.append(el("span", "alexa-mini"), el("p", "", turn.reply));
    row.append(user, reply);
    const meta = el("div", "reply-meta");
    if (turn.trace?.length) meta.append(badge(turn.trace.filter((entry) => entry.invoked).slice(-1)[0] || turn.trace[turn.trace.length - 1]));
    if (turn.id && state.config.voice_configured) {
      const speak = el("button", "", "Read reply");
      speak.type = "button";
      speak.prepend(icon("sound"));
      speak.addEventListener("click", () => playReply(turn.id));
      meta.append(speak);
    }
    row.append(meta);
    if (turn.warning) row.append(el("p", "reply-warning", turn.warning));
    ui.conversation.append(row);
  }
  if (state.pendingMessage) {
    const row = el("article", "turn");
    const user = el("div", "user-message");
    user.append(el("p", "", state.pendingMessage));
    row.append(user);
    ui.conversation.append(row);
  }
  ui.conversation.scrollTop = ui.conversation.scrollHeight;
}

function renderActivity() {
  ui.activity.replaceChildren();
  const entries = state.activity.flatMap((turn) => (turn.trace || []).map((trace) => ({ turn, trace }))).reverse();
  if (!entries.length) ui.activity.append(emptyActivity.firstElementChild.cloneNode(true));
  for (const { turn, trace } of entries) {
    const item = el("details", "activity-item");
    const summary = el("summary");
    const label = el("span", "activity-title");
    const names = { unlockDoor: "Side gate request", disarmSystem: "Home security request", viewStream: "Camera access request", resumeEscalation: "Approval check" };
    label.append(el("strong", "", names[trace.name] || "Home action request"));
    const scene = state.config.scenarios.find((s) => s.id === turn.scenario_id);
    label.append(el("small", "", scene?.title || "From your conversation"));
    summary.append(label, badge(trace));
    const detail = el("div", "evidence-details");
    const result = trace.result || {};
    detail.append(el("p", "", trace.invoked ? (trace.result ? "HomeBound MCP returned this action result." : "The MCP call was attempted; no result was received.") : "Stopped before MCP invocation."));
    const evidence = result.dossier_evidence;
    detail.append(el("p", "", evidence?.verified && evidence.trust_anchor === "DECIONIS_OFFICIAL" ? "Dossier verification: verified against the official Decionis trust anchor." : "Dossier verification: no verified proof reported for this request."));
    for (const [field, title] of [["decision", "Authority decision"], ["execution", "Execution"], ["correlation_id", "Correlation"], ["dossier_id", "Dossier"], ["grant_id", "Grant"], ["escalation_expires_at", "Approval expires"]]) {
      if (result[field]) {
        const line = el("p", "", `${title}: `);
        line.append(el("code", "", result[field]));
        detail.append(line);
      }
    }
    if (trace.reason) detail.append(el("p", "", `Request check: ${trace.reason}`));
    if (result.reason_codes?.length) detail.append(el("p", "", `Reason: ${result.reason_codes.join(", ")}`));
    detail.append(el("p", "", "Captured request"), el("pre", "", JSON.stringify({ tool: trace.name, arguments: trace.arguments }, null, 2)));
    item.append(summary, detail);
    ui.activity.append(item);
  }
  $("#export-history").disabled = !entries.length;
}

function renderPending() {
  const holder = $("#pending-requests");
  holder.replaceChildren();
  for (const correlation of state.pending) {
    const row = el("div", "pending-request");
    row.append(el("span", "", "Complete this request in Decionis Presence, then check its approval."));
    const button = el("button", "resume-button", "Check approval");
    button.type = "button";
    button.addEventListener("click", () => checkApproval(correlation));
    row.append(button);
    holder.append(row);
  }
}

function renderDevices(snapshot) {
  const devices = snapshot?.state;
  const fields = [
    ["#gate-state", devices?.door_locked?.side_gate, "Locked", "Unlocked"],
    ["#security-state", devices?.security_system_armed?.home_security, "Armed", "Disarmed"],
    ["#camera-state", devices?.camera_stream_available?.front_door, "Simulated stream available", "Simulated stream unavailable"],
  ];
  fields.forEach(([selector, value, yes, no]) => {
    $(selector).textContent = typeof value === "boolean" ? (value ? yes : no) : "State not yet reported";
    $(selector).classList.toggle("reported", typeof value === "boolean");
  });
  $("#snapshot-label").textContent = devices ? "Last execution snapshot · simulated" : "Waiting for an execution report";
}


function acceptTurn(turn) {
  state.pendingMessage = null;
  state.showGreeting = false;
  if (!state.turns.some((item) => item.id === turn.id)) state.turns.push(turn);
  state.turns = state.turns.slice(-12);
  if (turn.trace?.length && !state.activity.some((item) => item.id === turn.id)) state.activity.push(turn);
  state.activity = state.activity.slice(-32);
  for (const entry of turn.trace || []) {
    const result = entry.result || {};
    if (result.decision === "ESCALATE" && result.correlation_id) state.pending.add(result.correlation_id);
    if (["ALLOW", "BLOCK"].includes(result.decision) && result.correlation_id) state.pending.delete(result.correlation_id);
  }
  renderConversation(); renderActivity(); renderPending(); renderDevices(turn.device_state);
  renderContext(turn.dialogue, turn.captured_context);
  renderStage();
}
function applyBootstrap(data) {
  state.config = data;
  state.turns = data.turns;
  state.activity = data.activity;
  state.pending = new Set(data.pending);
  renderConversation(); renderActivity(); renderPending(); renderDevices(data.device_state);
  renderContext(data.dialogue);
  updateControls();
}

function dialogOpen() { return Boolean(document.querySelector("dialog[open]")); }
function resumeListening() {
  if (state.busy || state.playing || state.starting || dialogOpen()) return;
  if (state.typing) { renderStage("typing"); return; }
  if (!state.micEnabled) { renderStage("muted"); return; }
  if (!listener.listen()) {
    ui.start.hidden = false;
    renderStage("interaction");
  } else ui.start.hidden = true;
  updateControls();
}
function pauseListening() {
  state.micEnabled = false;
  state.voiceGeneration += 1;
  state.transcriptionAbort?.abort();
  listener.disconnect();
  ui.start.hidden = !state.config?.voice_configured;
  if (!state.busy && !state.playing) renderStage("muted");
  updateControls();
}
function voiceError(error) {
  pauseListening();
  notice(error.name === "NotAllowedError"
    ? "Allow microphone access in your browser, then choose Start talking. You can also type."
    : error.name === "NotFoundError"
    ? "No microphone was found. Connect one or use Type."
    : error.message);
}
const listener = new ContinuousVoiceListener({
  onUtterance: transcribeUtterance,
  onError: voiceError,
  onState: (mode) => { renderStage(mode); updateControls(); },
  onLevel: (level) => document.body.style.setProperty("--voice-level", String(level)),
});

async function startTalking() {
  if (!state.config?.voice_configured || state.busy) return;
  state.micEnabled = true;
  state.starting = true;
  state.typing = false;
  $("#chat-form").hidden = true;
  $("#type-button").setAttribute("aria-expanded", "false");
  notice();
  updateControls();
  const ready = await listener.connect();
  state.starting = false;
  updateControls();
  if (!state.micEnabled || state.busy) return;
  if (!ready) {
    ui.start.hidden = false;
    renderStage("interaction");
    return;
  }
  ui.start.hidden = true;
  if (state.pendingPlayback) await playSpeech(state.pendingPlayback.id, state.pendingPlayback.greeting);
  else if (!state.greeted && state.speechEnabled) await playSpeech("greeting", true);
  else resumeListening();
}

function stopSpeech(resume = true) {
  state.speechGeneration += 1;
  state.speechAbort?.abort();
  state.speechAbort = null;
  if (state.audio) { state.audio.pause(); state.audio.currentTime = 0; state.audio = null; }
  const done = state.finishAudio;
  state.finishAudio = null;
  state.playing = false;
  done?.();
  $("#stop-audio").hidden = true;
  if (resume) resumeListening();
}
async function playSpeech(identifier, greeting = false) {
  if (!state.config?.voice_configured || state.busy) return;
  listener.suspend();
  stopSpeech(false);
  const generation = state.speechGeneration;
  state.pendingPlayback = null;
  state.playing = true;
  renderStage("preparing");
  $("#stop-audio").hidden = false;
  try {
    const key = greeting ? "greeting-" + state.config.greeting.period : identifier;
    let url = state.audioUrls.get(key);
    if (!url) {
      state.speechAbort = new AbortController();
      const blob = await request(greeting ? "/api/voice/greeting" : "/api/voice/speak", greeting ? {} : { request_id: identifier }, { signal: state.speechAbort.signal, audio: true });
      if (generation !== state.speechGeneration) return;
      url = URL.createObjectURL(blob);
      state.audioUrls.set(key, url);
      while (state.audioUrls.size > 8) {
        const oldest = state.audioUrls.keys().next().value;
        URL.revokeObjectURL(state.audioUrls.get(oldest));
        state.audioUrls.delete(oldest);
      }
    }
    if (generation !== state.speechGeneration) return;
    const audio = state.audio = new Audio(url);
    const ended = new Promise((resolve) => {
      state.finishAudio = resolve;
      audio.addEventListener("ended", resolve, { once: true });
      audio.addEventListener("error", () => {
        notice("I couldn't play that reply. You can read it on screen.");
        resolve();
      }, { once: true });
    });
    await audio.play();
    if (generation !== state.speechGeneration) { audio.pause(); return; }
    if (greeting) state.greeted = true;
    renderStage("speaking");
    await ended;
  } catch (error) {
    if (generation !== state.speechGeneration || error.name === "AbortError") return;
    if (error.name === "NotAllowedError") {
      state.pendingPlayback = { id: identifier, greeting };
      ui.start.hidden = false;
      notice("Your browser needs one tap to enable voice. Choose Start talking.");
    } else notice(error.message);
  } finally {
    if (generation === state.speechGeneration) {
      state.audio = null;
      state.finishAudio = null;
      state.playing = false;
      $("#stop-audio").hidden = true;
      if (state.pendingPlayback) renderStage("interaction");
      else resumeListening();
    }
  }
}
async function playReply(identifier) { await playSpeech(identifier); }

async function transcribeUtterance(audio) {
  if (state.busy || !state.micEnabled) return;
  const generation = state.voiceGeneration;
  state.busy = true;
  state.transcriptionAbort = new AbortController();
  renderStage("transcribing");
  updateControls();
  let transcript;
  try {
    const result = await request("/api/voice/transcribe", audio, {
      headers: { "X-HomeBound-Client": "web", "Content-Type": audio.type },
      body: audio, signal: state.transcriptionAbort.signal,
    });
    transcript = result.transcript;
  } catch (error) {
    if (error.name !== "AbortError" && error.code !== "NO_SPEECH") {
      pauseListening();
      notice(error.message);
    }
  } finally {
    state.busy = false;
    state.transcriptionAbort = null;
    updateControls();
  }
  if (transcript && generation === state.voiceGeneration && state.micEnabled) await submitMessage(transcript);
  else resumeListening();
}

async function submitMessage(message) {
  message = message.trim();
  if (!message || state.busy || !state.config) return;
  listener.suspend();
  stopSpeech(false);
  notice();
  state.greeted = true;
  state.showGreeting = false;
  state.typing = false;
  $("#chat-form").hidden = true;
  $("#type-button").setAttribute("aria-expanded", "false");
  const identifier = crypto.randomUUID();
  state.pendingMessage = message;
  ui.input.value = "";
  state.busy = true;
  renderConversation(); renderStage("thinking"); updateControls();
  let turn;
  try {
    turn = await request("/api/chat", { request_id: identifier, message });
    acceptTurn(turn);
  } catch (error) {
    notice(error.message);
    state.pendingMessage = null;
    pauseListening();
    await refreshAfterFailure();
    if (!state.pollTimer && !state.turns.some((item) => item.id === identifier)) {
      ui.input.value = message;
      setTyping(true);
    }
  } finally {
    if (!state.pollTimer) state.busy = false;
    renderConversation(); updateControls();
  }
  if (turn && state.speechEnabled) await playReply(turn.id);
  else resumeListening();
}
async function checkApproval(correlation) {
  if (state.busy) return;
  listener.suspend(); stopSpeech(false); notice();
  state.busy = true;
  renderStage("thinking"); updateControls();
  let turn;
  try {
    turn = await request("/api/resume", { request_id: crypto.randomUUID(), correlation_id: correlation });
    acceptTurn(turn);
  } catch (error) { notice(error.message); await refreshAfterFailure(); }
  finally { if (!state.pollTimer) state.busy = false; updateControls(); }
  if (turn && state.speechEnabled) await playReply(turn.id);
  else resumeListening();
}
async function refreshAfterFailure() {
  try {
    const data = await request("/api/bootstrap");
    applyBootstrap(data);
    if (data.busy) {
      state.busy = true;
      clearTimeout(state.pollTimer);
      state.pollTimer = setTimeout(async () => {
        state.pollTimer = null;
        await refreshAfterFailure();
        if (!state.pollTimer) { state.busy = false; renderStage("ready"); updateControls(); }
      }, 3000);
    }
  } catch { /* Preserve the original error. Never resubmit an action automatically. */ }
}

function setTyping(enabled) {
  state.typing = enabled;
  $("#chat-form").hidden = !enabled;
  $("#type-button").setAttribute("aria-expanded", String(enabled));
  if (enabled) {
    listener.suspend(); stopSpeech(false);
    renderStage("typing");
    ui.input.focus({ preventScroll: true });
  } else resumeListening();
}
function openDialog(id) {
  listener.suspend();
  stopSpeech(false);
  $("#" + id).showModal();
  renderStage("ready");
}
$("#chat-form").addEventListener("submit", (event) => { event.preventDefault(); submitMessage(ui.input.value); });
$("#type-button").addEventListener("click", () => setTyping(!state.typing));
ui.mic.addEventListener("click", () => state.micEnabled ? pauseListening() : startTalking());
ui.start.addEventListener("click", startTalking);
$("#stop-audio").addEventListener("click", () => { state.greeted = true; state.pendingPlayback = null; stopSpeech(); });
$("#open-home").addEventListener("click", () => openDialog("home-dialog"));
$("#open-conversation").addEventListener("click", () => openDialog("conversation-dialog"));
document.querySelectorAll(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("close", resumeListening));
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => submitMessage(button.dataset.prompt)));
ui.voiceToggle.addEventListener("click", () => {
  state.speechEnabled = !state.speechEnabled;
  if (!state.speechEnabled) { state.pendingPlayback = null; stopSpeech(); }
  updateControls();
});
$("#clear-chat").addEventListener("click", async () => {
  if (state.busy) return;
  listener.suspend(); stopSpeech(false);
  try {
    await request("/api/clear", {});
    state.turns = [];
    state.showGreeting = true;
    state.greeted = false;
    state.pendingPlayback = null;
    state.dialogue = null;
    renderContext(null);
    notice(); renderConversation(); renderStage("ready");
    $("#conversation-dialog").close();
    if (state.speechEnabled) await playSpeech("greeting", true);
    else resumeListening();
  } catch (error) { notice(error.message); }
});
$("#export-history").addEventListener("click", () => {
  const record = { source: "HomeBound Alexa-style web simulator", exported_at: new Date().toISOString(), activity: state.activity };
  const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: "application/json" }));
  const anchor = el("a");
  anchor.href = url; anchor.download = "homebound-action-record.json"; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener("pagehide", () => {
  pauseListening(); stopSpeech(false); clearTimeout(state.pollTimer);
  state.audioUrls.forEach((url) => URL.revokeObjectURL(url));
  state.audioUrls.clear();
});

async function initialize() {
  updateControls();
  try {
    const data = await request("/api/bootstrap");
    state.speechEnabled = data.voice_configured;
    state.micEnabled = data.voice_configured;
    applyBootstrap(data);
    const clock = () => {
      const now = new Date();
      $("#home-time").textContent = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: data.home_timezone }).format(now);
      $("#home-date").textContent = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: data.home_timezone }).format(now);
    };
    clock(); setInterval(clock, 60000);
    $("#connection-details").textContent = "Home timezone: " + data.home_timezone + ". Deepgram supplies speech; Bedrock interprets your requests. The home clock is used unless you explicitly ask for a simulated demo time.";
    renderStage("ready");
    if (!data.voice_configured) {
      notice("Voice is not configured. You can still use Type.");
      return;
    }
    if (data.busy) { await refreshAfterFailure(); return; }
    await startTalking();
  } catch (error) {
    notice(error.message);
    renderStage("muted");
  }
}
initialize();
