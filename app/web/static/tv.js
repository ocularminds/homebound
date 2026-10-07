"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { canvas: null, busy: false, poll: null, lastSync: 0, mic: false, voiceGeneration: 0, speech: null, speechUrl: null, speechAbort: null, requestAbort: null, noteKey: "", panelKey: "", connected: false, generatedAt: 0, autoProgram: new URLSearchParams(location.search).get("play") === "park_chase", captions: false };
const node = (tag, className = "", text = "") => { const item = document.createElement(tag); item.className = className; item.textContent = text; return item; };
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#tv-" + name); svg.append(use); svg.setAttribute("aria-hidden", "true"); return svg;
}
function button(label, className, click) { const item = node("button", className, label); item.type = "button"; item.addEventListener("click", click); return item; }
function money(minor, currency = "EUR") { return new Intl.NumberFormat("en", { style: "currency", currency }).format(minor / 100); }
function status(text, error = false) { $("#status").textContent = text; $("#status").dataset.error = String(error); }

async function request(path, body, options = {}) {
  const response = await fetch(path, { method: body === undefined ? "GET" : "POST", credentials: "same-origin", headers: { "X-HomeBound-Client": "web", ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, body: body === undefined ? undefined : JSON.stringify(body), ...options });
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.message || "The home connection is unavailable."); }
  return options.audio ? response.blob() : response.json();
}

function privateNow() {
  state.noteKey = "";
  $("#notes").replaceChildren();
  $("#note-waiting").hidden = true;
  $("#privacy-label").textContent = "Personal notes stay private";
}

function renderNotes(data) {
  // A slow server response must not leave personal notes over the resumed film.
  if (data.media.stream && !player.activeBreak) { privateNow(); return; }
  const key = JSON.stringify(data.notes);
  if (key !== state.noteKey) {
    state.noteKey = key;
    $("#notes").replaceChildren(...data.notes.map((note) => {
      const card = node("article", "note-card");
      const top = node("div", "note-top");
      const recipient = node("div", "note-recipient");
      const name = { mom: "Mom", leo: "Leo", alex: "Alex", household: "Everyone" }[note.recipient];
      recipient.append(node("span", "note-dot", name.slice(0, 1)), node("span", "", "For " + name));
      const dismiss = button("", "note-dismiss", async () => {
        try { render(await request("/api/canvas/dismiss", { note_id: note.id })); }
        catch (error) { privateNow(); status(error.message, true); }
      });
      dismiss.setAttribute("aria-label", "Dismiss note for " + name); dismiss.append(icon("check"));
      top.append(recipient, dismiss);
      const footer = node("div", "note-footer");
      footer.append(node("span", "", "From " + note.sender), node("span", "", note.screening === "demo_fixture" ? "Sample note" : "Saved for today"));
      card.append(top, node("p", "", note.text), footer); return card;
    }));
  }
  $("#note-waiting").hidden = !data.note_waiting;
}

function renderRecipes(data) {
  const grid = node("div", "recipe-grid");
  const recipes = [...data.recipes].sort((a, b) => Number(b.id === data.media.recipe) - Number(a.id === data.media.recipe));
  for (const recipe of recipes) {
    const card = node("article", "recipe-card");
    const inScene = recipe.id === data.media.recipe;
    card.append(node("span", "minutes", `${recipe.minutes} MIN${inScene ? " · ON YOUR SCREEN" : " · ANOTHER IDEA"}`), node("h3", "", recipe.name), node("p", "", recipe.description));
    const label = !recipe.inventory_fresh ? "Pantry needs a fresh check" : recipe.ready ? "You have all the ingredients" : "Missing: " + recipe.ingredients.filter((i) => !i.available).map((i) => i.name).join(", ");
    card.append(node("p", "availability" + (recipe.ready ? "" : " missing"), label));
    const ingredients = node("ul", "ingredients");
    for (const ingredient of recipe.ingredients) {
      const item = node("li", ingredient.available ? "" : "ingredient-missing");
      item.append(ingredient.available ? icon("check") : node("span", "", "+"), node("span", "", ingredient.name)); ingredients.append(item);
    }
    card.append(ingredients);
    if (recipe.inventory_fresh && recipe.missing.includes("olive_oil")) card.append(button("Add olive oil to draft cart", "primary-button", () => action("cart_add", "olive_oil")));
    grid.append(card);
  }
  return grid;
}

function productImage(product) { const img = node("img"); img.src = "/static/product-" + (product.art === "jacket" ? "jacket" : "oil") + ".svg"; img.alt = product.name + " illustration"; return img; }
function renderProducts(data) {
  const group = node("div");
  for (const product of data.products) {
    const item = node("article", "product"); const copy = node("div");
    copy.append(node("h3", "", product.name), node("p", "", product.detail), node("p", "price", money(product.price_minor, product.currency)), button("Add to draft cart", "primary-button", () => action("cart_add", product.id)), node("span", "small-label", "Demo catalog · illustrative price"));
    item.append(productImage(product), copy); group.append(item);
  }
  if (!data.products.length) group.append(node("p", "empty-cart", "There are no item matches for this scene yet."));
  return group;
}

function renderCart(data) {
  const group = node("div");
  if (!data.cart.items.length) group.append(node("p", "empty-cart", "Nothing here just yet. Ask about the cooking show or the jacket in the movie."));
  for (const product of data.cart.items) {
    const line = node("article", "cart-line"), copy = node("div");
    copy.append(node("h3", "", product.name), node("p", "", "Quantity " + product.quantity));
    line.append(productImage(product), copy, node("strong", "", money(product.price_minor * product.quantity))); group.append(line);
  }
  const total = node("div", "cart-total"); total.append(node("span", "", "Illustrative total"), node("span", "", money(data.cart.total_minor))); group.append(total);
  group.append(node("p", "cart-info", "Amazon Pay isn't connected. This is a draft cart with demo items and prices. No order or payment will be submitted."));
  if (data.cart.items.length) group.append(button("Clear draft cart", "secondary-button", () => action("cart_clear")));
  return group;
}

function renderRoom(data) {
  const group = node("div"), steps = node("ol", "room-plan");
  for (const step of data.plan) { const item = node("li"); item.append(icon("check"), node("span", "", step.label)); steps.append(item); }
  const lights = node("div", "room-lights");
  for (const [name, value] of [["TV area", data.room.tv_area], ["Reading lamp", data.room.reading_lamp]]) { const item = node("div", "light-setting", name); item.append(node("strong", "", value + "%")); lights.append(item); }
  group.append(steps, lights, node("p", "cart-info", "Room preview · Physical TV and lighting controls need a connected adapter and authorization through Decionis."), button("Restore previous room", "secondary-button", () => action("restore"))); return group;
}

function renderPanel(data) {
  const labels = { recipes: ["FROM THE SCREEN TO YOUR TABLE", "A little inspiration for dinner."], shopping: ["INSPIRED BY THIS SCENE", "Something caught your eye."], cart: ["SAVED FOR A CLOSER LOOK", "Your draft cart."], room: ["THE ROOM, IN HARMONY", "Make room for a good book."] };
  const key = JSON.stringify([data.panel, data.recipes, data.products, data.cart, data.room, data.plan, data.media.recipe]);
  $("#panel").hidden = !labels[data.panel]; document.body.dataset.panel = String(Boolean(labels[data.panel]));
  if (key === state.panelKey) return;
  state.panelKey = key;
  if (!labels[data.panel]) { $("#panel-content").replaceChildren(); return; }
  $("#panel-eyebrow").textContent = labels[data.panel][0]; $("#panel-title").textContent = labels[data.panel][1];
  const content = { recipes: renderRecipes, shopping: renderProducts, cart: renderCart, room: renderRoom }[data.panel](data);
  $("#panel-content").replaceChildren(content);
}

function render(data) {
  if (document.hidden) { privateNow(); return; }
  if (state.canvas && data.revision < state.canvas.revision) return;
  if (data.generated_at && data.generated_at < state.generatedAt) return;
  state.generatedAt = data.generated_at || 0;
  state.lastSync = performance.now(); state.connected = true;
  const config = state.canvas || {};
  state.canvas = { ...data, voice_configured: data.voice_configured ?? config.voice_configured, home_timezone: data.home_timezone || config.home_timezone };
  player.load(data.media);
  const videoReady = Boolean(data.programs?.park_chase?.available);
  $("#watch-cartoon").disabled = !videoReady;
  $("#cartoon-availability").textContent = videoReady ? "Play the cartoon · notes during commercials" : "Film being prepared";
  if (state.autoProgram && videoReady) {
    state.autoProgram = false;
    if (data.media.id !== "park_chase") signal("scene", "park_chase");
  }
  const track = $("#program-track");
  if (data.media.stream && track.getAttribute("src") !== data.media.stream.captions) track.src = data.media.stream.captions;
  $("#scene-background").dataset.art = data.media.art;
  $("#program-category").textContent = data.media.category;
  $("#program-title").textContent = data.media.title;
  $("#program-subtitle").textContent = data.media.subtitle;
  $("#program-mode").textContent = data.media.stream ? data.media.stream.available ? "Original animated short" : "Film being prepared" : "Illustrated media preview";
  $("#caption-status").hidden = !data.media.captions; $("#muted-status").hidden = !data.media.muted;
  $("#audience").dataset.private = String(data.audience.private);
  $("#audience-label").textContent = data.audience.guest ? "A guest is here" : data.audience.names.length ? data.audience.names.join(" & ") + " · living room" : "Living room · audience unknown";
  $("#privacy-label").textContent = data.audience.private || data.audience.people.length !== 1 ? "Personal notes stay private" : "Notes for the right person, at the right moment";
  const cartCount = data.cart.items.reduce((sum, item) => sum + item.quantity, 0);
  $("#cart-count").textContent = cartCount;
  $("#cart-button").setAttribute("aria-label", `Review draft cart, ${cartCount} ${cartCount === 1 ? "item" : "items"}`);
  $("#dashboard").hidden = !data.media.dashboard; document.body.dataset.dashboard = String(data.media.dashboard);
  $("#dashboard-toggle").textContent = data.auto_dashboard ? "Turn break dashboard off" : "Turn break dashboard on";
  $("#screening-mode").textContent = { local_demo_screening: "Local demo screening · AWS Guardrails not configured", bedrock_guardrails: "Amazon Bedrock Guardrails · published version", guardrails_required: "Waiting for Bedrock Guardrails · new notes held" }[data.capabilities.screening];
  const cloud = data.capabilities;
  $("#cloud-mode").textContent = cloud.agentcore === "configured" || cloud.eventbridge === "configured"
    ? `${cloud.agentcore === "configured" ? "AgentCore planner configured" : "Direct Bedrock planning"} · ${cloud.eventbridge === "configured" ? "SQS receiver configured" : "local events"}`
    : "Deployment adapters included; not deployed";
  $("#agent-trace").replaceChildren(...data.trace.map((entry) => node("li", "", entry.agent + ": " + entry.outcome)));
  renderNotes(data); renderPanel(data); updateClock();
}

const filmTime = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
const player = new HomeBoundProgramPlayer($("#program-video"), $("#commercial-video"), {
  report: async (transition) => {
    try { render(await request("/api/canvas/playback", { request_id: crypto.randomUUID(), ...transition }, { signal: AbortSignal.timeout(3500) })); }
    catch (error) { privateNow(); throw error; }
  },
  update: (playback) => {
    document.body.dataset.video = String(playback.active);
    document.body.dataset.commercial = String(playback.commercial);
    $("#video-screen").hidden = !playback.active;
    $("#program-video").hidden = playback.commercial;
    $("#commercial-video").hidden = !playback.commercial;
    $("#playback-controls").hidden = !playback.active;
    $("#commercial-badge").hidden = !playback.commercial;
    $("#commercial-countdown").textContent = playback.paused ? `Paused · ${Math.ceil(playback.remaining)}s remaining` : `Film returns in ${Math.ceil(playback.remaining)}s`;
    $("#film-play").textContent = playback.ended ? "Play again" : playback.paused ? "Play" : "Pause";
    const playingWhat = playback.commercial ? "commercial" : "film";
    $("#film-play").setAttribute("aria-label", playback.ended ? "Replay film" : `${playback.paused ? "Play" : "Pause"} ${playingWhat}`);
    $("#film-sound").textContent = playback.muted ? "Sound on" : "Mute";
    $("#film-sound").setAttribute("aria-label", playback.muted ? "Turn film sound on" : "Mute film sound");
    $("#film-progress").max = playback.duration || 60;
    $("#film-progress").value = playback.time;
    $("#film-time").textContent = `${filmTime(playback.time)} / ${filmTime(playback.duration)}`;
    $("#film-break-label").textContent = playback.commercial ? "Your notes, while the film takes a break" : "Two short commercial breaks";
    if (playback.active && !playback.commercial) privateNow();
    if (playback.error) status(playback.error, true);
  },
});
$("#program-video").volume = $("#commercial-video").volume = 0.7;
$("#film-play").addEventListener("click", () => player.toggle());
$("#film-sound").addEventListener("click", () => player.setMuted(!player.muted));
$("#film-replay").addEventListener("click", () => player.replay());
$("#film-captions").addEventListener("click", () => {
  state.captions = !state.captions;
  for (const track of $("#program-video").textTracks) track.mode = state.captions ? "showing" : "hidden";
  $("#film-captions").setAttribute("aria-pressed", String(state.captions));
});

async function refresh() {
  try { render(await request("/api/canvas", undefined, { signal: AbortSignal.timeout(3500) })); }
  catch (error) { state.connected = false; privateNow(); if (error.name !== "AbortError") status("Home connection unavailable. Personal notes are hidden.", true); }
}
async function poll() { if (!document.hidden) await refresh(); state.poll = setTimeout(poll, 750); }
function updateClock() { $("#clock").textContent = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: state.canvas?.home_timezone || "Europe/Stockholm" }).format(new Date()); }

function resumeListening() { if (state.mic && !state.busy && !state.speech && !document.hidden && !document.querySelector("dialog[open]")) listener.listen(); }
function stopSpeech() {
  state.speechAbort?.abort(); state.speechAbort = null;
  state.speech?.pause(); state.speech = null;
  if (state.speechUrl) URL.revokeObjectURL(state.speechUrl); state.speechUrl = null;
}
async function playReply(identifier, generation) {
  const controller = new AbortController(); state.speechAbort = controller;
  const ownsSpeech = () => state.speechAbort === controller;
  try {
    const blob = await request("/api/voice/speak", { request_id: identifier }, { audio: true, signal: controller.signal });
    if (!ownsSpeech() || !state.mic || generation !== state.voiceGeneration || document.hidden) return;
    state.speechUrl = URL.createObjectURL(blob); const audio = state.speech = new Audio(state.speechUrl);
    audio.addEventListener("ended", () => { if (state.speech === audio) { stopSpeech(); resumeListening(); } }, { once: true });
    audio.addEventListener("error", () => { if (ownsSpeech()) { stopSpeech(); resumeListening(); } }, { once: true });
    await audio.play();
  } catch (error) { if (!ownsSpeech()) return; stopSpeech(); if (error.name !== "AbortError") status("Your reply is on screen. Tap the microphone to enable audio."); resumeListening(); }
}
function setBusy(busy) { state.busy = busy; $("#send").disabled = busy; $("#ask").setAttribute("aria-busy", String(busy)); }
async function send(message) {
  message = message.trim(); if (!message || state.busy) return;
  listener.suspend(); stopSpeech(); setBusy(true); status("Finding the right thing for this moment…");
  const identifier = crypto.randomUUID(), generation = state.voiceGeneration;
  let turn;
  try {
    turn = await request("/api/chat", { request_id: identifier, message, scenario_id: "canvas" });
    $("#ask").value = ""; status(turn.reply); await refresh();
  } catch (error) { status(error.message, true); }
  finally { setBusy(false); }
  if (turn && state.mic && generation === state.voiceGeneration) await playReply(turn.id, generation);
  else resumeListening();
}

async function action(intent, product = "unknown") {
  if (state.busy) return;
  listener.suspend(); stopSpeech();
  setBusy(true);
  try { const data = await request("/api/canvas/action", { request_id: crypto.randomUUID(), intent, product }); render(data.canvas); status(data.reply); }
  catch (error) { status(error.message, true); }
  finally { setBusy(false); resumeListening(); }
}
async function signal(kind, value) {
  try { const data = await request("/api/canvas/simulate", { request_id: crypto.randomUUID(), kind, value }); render(data); $("#demo-dialog").close(); status(kind === "presence" ? "Demo audience updated. The canvas has adapted." : "Demo signal received. The canvas has adapted."); }
  catch (error) { status(error.message, true); }
}

function mute() {
  state.mic = false; state.voiceGeneration += 1; state.requestAbort?.abort(); listener.disconnect(); stopSpeech();
  $("#mic").setAttribute("aria-pressed", "false"); $("#mic").setAttribute("aria-label", "Turn microphone on");
}
const listener = new ContinuousVoiceListener({
  onState: (value) => { if (value === "listening") status("Listening. Ask about this moment."); if (value === "transcribing") status("Hearing your request…"); },
  onError: (error) => { mute(); status(error.message, true); },
  onUtterance: async (audio) => {
    const generation = state.voiceGeneration; state.requestAbort = new AbortController();
    try {
      const response = await fetch("/api/voice/transcribe", { method: "POST", credentials: "same-origin", headers: { "Content-Type": audio.type, "X-HomeBound-Client": "web" }, body: audio, signal: state.requestAbort.signal });
      if (!response.ok) throw new Error("I couldn't hear that request. Try again.");
      const data = await response.json();
      if (generation === state.voiceGeneration && state.mic && data.transcript) await send(data.transcript);
    } catch (error) { if (error.name !== "AbortError") status(error.message, true); }
    finally { resumeListening(); }
  },
});
$("#mic").addEventListener("click", async () => {
  if (state.mic) { mute(); status("Microphone off. You can still ask from the Alexa screen."); return; }
  if (!state.canvas?.voice_configured) { status("Configure Deepgram to use voice. You can still type.", true); return; }
  state.mic = true; const generation = ++state.voiceGeneration;
  if (await listener.connect() && generation === state.voiceGeneration && state.mic) {
    $("#mic").setAttribute("aria-pressed", "true"); $("#mic").setAttribute("aria-label", "Turn microphone off"); resumeListening();
  } else { mute(); status("Tap the microphone again to start talking."); }
});

$("#ask-form").addEventListener("submit", (event) => { event.preventDefault(); send($("#ask").value); });
$("#note-form").addEventListener("submit", (event) => { event.preventDefault(); const text = $("#note-text").value.trim(); if (!text) return; const recipient = $("#note-recipient").value; $("#note-dialog").close(); send("Tell " + recipient + " " + text); });
$("#panel-close").addEventListener("click", () => action("dismiss"));
document.querySelectorAll("[data-action]").forEach((item) => item.addEventListener("click", () => action(item.dataset.action)));
document.querySelectorAll("[data-signal]").forEach((item) => item.addEventListener("click", () => signal(item.dataset.signal, item.dataset.value)));
$("#pantry-restock").addEventListener("click", () => signal("inventory", ["pasta", "lemon", "parmesan", "tomato", "basil", "bread", "olive_oil"]));
$("#pantry-missing").addEventListener("click", () => signal("inventory", ["pasta", "lemon", "parmesan", "tomato", "basil", "bread"]));
for (const [control, dialog] of [["note-open", "note-dialog"], ["demo-open", "demo-dialog"], ["about-open", "about-dialog"]]) {
  $("#" + control).addEventListener("click", () => { listener.suspend(); $("#" + dialog).showModal(); });
  $("#" + dialog).addEventListener("close", resumeListening);
}
document.querySelectorAll(".close-dialog").forEach((item) => item.addEventListener("click", () => item.closest("dialog").close()));

// Directional remote navigation follows the screen geometry, not DOM order.
document.addEventListener("keydown", (event) => {
  if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
  const active = document.activeElement;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(active?.tagName)) return;
  const root = document.querySelector("dialog[open]") || document;
  const candidates = [...root.querySelectorAll("button:not(:disabled), a[href], input, select, textarea")].filter((item) => item.getClientRects().length && item !== active);
  const origin = active?.getBoundingClientRect(); if (!origin || !candidates.length) return;
  const x = origin.x + origin.width / 2, y = origin.y + origin.height / 2;
  const horizontal = event.key === "ArrowLeft" || event.key === "ArrowRight";
  const direction = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
  const scored = candidates.map((item) => {
    const r = item.getBoundingClientRect(), dx = r.x + r.width / 2 - x, dy = r.y + r.height / 2 - y;
    const along = (horizontal ? dx : dy) * direction, across = Math.abs(horizontal ? dy : dx);
    return { item, score: along > 1 ? along + across * 3 : Infinity };
  }).sort((a, b) => a.score - b.score);
  if (Number.isFinite(scored[0]?.score)) { event.preventDefault(); scored[0].item.focus(); }
});
document.addEventListener("visibilitychange", () => {
  player.suspend(document.hidden);
  if (document.hidden) { privateNow(); listener.suspend(); stopSpeech(); }
  else { refresh(); resumeListening(); }
});
window.addEventListener("pagehide", () => { clearTimeout(state.poll); mute(); privateNow(); player.suspend(true); });
window.addEventListener("pageshow", (event) => { if (event.persisted) { clearTimeout(state.poll); privateNow(); player.suspend(document.hidden); poll(); } });
setInterval(() => { updateClock(); if (state.lastSync && performance.now() - state.lastSync > 3000) privateNow(); }, 1000);
poll();
