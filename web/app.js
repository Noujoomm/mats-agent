/* MATS Agent — voice-first bilingual client.
   Push-to-talk + hands-free (VAD, ~900 ms silence), barge-in, Nemotron ASR via
   /api/transcribe (Web Speech API fallback), SSE token streaming, and
   sentence-by-sentence speech synthesis. */
"use strict";

const $ = (id) => document.getElementById(id);
const el = {
  mic: $("micBtn"), micWrap: document.querySelector(".mic-wrap"), status: $("status"),
  interim: $("interim"), handsFree: $("handsFree"), chips: $("chipList"), thread: $("thread"),
  form: $("composer"), input: $("composerInput"), send: $("sendBtn"), lang: $("langBtn"),
  theme: $("themeBtn"), speak: $("speakBtn"), rtBtn: $("runtimeBtn"), rtDlg: $("runtimeDlg"),
  rtBody: $("rtBody"), rtClose: $("rtClose"), tpl: $("msgTpl"),
};

const SILENCE_MS = 900;          // end of utterance
const NO_SPEECH_MS = 9000;       // give up if nobody speaks
const MAX_UTTERANCE_MS = 20000;
const BARGE_MS = 280;            // sustained voice needed to interrupt the agent

/* ───────────────────────── i18n ───────────────────────── */
const T = {
  ar: {
    tagline: "مساعد صوتي لعمليات حملات الحج", otherLang: "English", switchLang: "Switch to English",
    skip: "انتقل لمربع السؤال", voiceTitle: "الصوت", micLabel: "تحدّث", speakToggle: "قراءة الردود بصوت",
    theme: "الوضع الليلي", runtime: "التشغيل", close: "إغلاق",
    statusIdle: "اضغط وتكلّم", statusListening: "أسمعك…", statusThinking: "أفكّر…",
    statusSpeaking: "أتكلّم — قاطعني متى ما تبي", statusTranscribing: "أحوّل صوتك لنص…",
    statusNoMic: "ما قدرت أفتح المايك — اكتب سؤالك تحت", statusNoSpeech: "ما سمعت شي، جرّب مرة ثانية",
    statusError: "صار خطأ، جرّب مرة ثانية",
    handsFree: "بدون يدين", handsFreeHint: "يسمعك تلقائيًا بعد كل رد، وتقدر تقاطعه بصوتك.",
    tryAsking: "جرّب تسأل", inputLabel: "اكتب سؤالك", placeholder: "اكتب سؤالك…", send: "إرسال",
    sql: "الاستعلام", fbQ: "الجواب صحيح؟", right: "صح", wrong: "غلط",
    fbRight: "تمام، حفظته كمثال موثّق.", fbWrong: "نسيته، وسجّلته درس عشان ما أكرر الغلط.",
    howAnswered: "كيف جاوب", total: "الإجمالي", via: "بالصوت", attempt: "محاولة",
    rows: "صف", capped: "أول {n} صف فقط", sources: "المصادر",
    steps: { route: "التوجيه والسياق", memory: "الذاكرة", sql: "كتابة SQL", guard: "الحارس", web: "بحث الويب",
             answer: "الجواب", remember: "تذكّرت", clarify: "سؤال توضيح", learn: "تعلّمت من خطأ",
             scope: "خارج التخصص" },
    intents: { smalltalk: "دردشة", data: "بيانات", complex: "تحليل", web: "ويب", hybrid: "بيانات + ويب", clarify: "توضيح", out_of_scope: "خارج التخصص" },
    remembered: "تذكّرت", clarifyHint: "اختر أو قلها بصوتك:", facts: "اللي أتذكره عنك",
    noFacts: "ما عندي شي محفوظ عنك. قل مثلًا: «أنا مشرف فوج 7».", forgetFacts: "انسَ كل شي",
    lessons: "دروس من أخطاء سابقة",
    rt: {
      provider: "المزوّد", key: "مفتاح API", models: "النماذج", fast: "سريع: توجيه + إعادة صياغة + جواب",
      fallback: "احتياطي السريع", sqlm: "نص ← SQL", complex: "الأسئلة المعقّدة + التصعيد",
      voice: "الصوت", asr: "تحويل الكلام (ASR)", tts: "صوت الردود", voiceAr: "الصوت العربي",
      voiceEn: "الصوت الإنجليزي", tryVoice: "جرّب", tavily: "بحث Tavily", data: "البيانات",
      campaign: "الحملة", now: "الوقت المحاكى", counts: "الأعداد", memory: "الذاكرة",
      safety: "الأمان", on: "مفعّل", off: "غير مفعّل", browser: "متصفح (Web Speech)",
      fictional: "كل البيانات وهمية لأغراض العرض.",
    },
  },
  en: {
    tagline: "Voice assistant for Hajj campaign operations", otherLang: "عربي", switchLang: "التبديل للعربية",
    skip: "Skip to question box", voiceTitle: "Voice", micLabel: "Talk", speakToggle: "Read replies aloud",
    theme: "Dark mode", runtime: "Runtime", close: "Close",
    statusIdle: "Tap and talk", statusListening: "Listening…", statusThinking: "Thinking…",
    statusSpeaking: "Speaking — interrupt me anytime", statusTranscribing: "Transcribing…",
    statusNoMic: "Couldn't open the microphone — type below", statusNoSpeech: "I didn't hear anything, try again",
    statusError: "Something went wrong, try again",
    handsFree: "Hands-free", handsFreeHint: "Listens again after every reply; you can interrupt by speaking.",
    tryAsking: "Try asking", inputLabel: "Type your question", placeholder: "Type your question…", send: "Send",
    sql: "SQL", fbQ: "Is this right?", right: "Right", wrong: "Wrong",
    fbRight: "Saved as a verified example.", fbWrong: "Forgotten, and saved as a lesson so I don't repeat it.",
    howAnswered: "How it answered", total: "total", via: "by voice", attempt: "attempt",
    rows: "rows", capped: "first {n} rows only", sources: "Sources",
    steps: { route: "Route + context", memory: "Memory", sql: "Write SQL", guard: "Guard", web: "Web search",
             answer: "Answer", remember: "Remembered", clarify: "Clarifying question", learn: "Learned from a mistake",
             scope: "Out of scope" },
    intents: { smalltalk: "smalltalk", data: "data", complex: "complex", web: "web", hybrid: "data + web", clarify: "clarify", out_of_scope: "out of scope" },
    remembered: "Remembered", clarifyHint: "Pick one, or just say it:", facts: "What I remember about you",
    noFacts: "Nothing remembered yet. Try: \u201cI supervise group 7\u201d.", forgetFacts: "Forget everything",
    lessons: "Lessons from past mistakes",
    rt: {
      provider: "Provider", key: "API key", models: "Models", fast: "Fast: route + rewrite + answer",
      fallback: "Fast fallback", sqlm: "Text-to-SQL", complex: "Complex questions + escalation",
      voice: "Voice", asr: "Speech-to-text (ASR)", tts: "Spoken replies", voiceAr: "Arabic voice",
      voiceEn: "English voice", tryVoice: "Try", tavily: "Tavily search", data: "Data",
      campaign: "Campaign", now: "Simulated time", counts: "Counts", memory: "Memory",
      safety: "Safety", on: "on", off: "off", browser: "browser (Web Speech)",
      fictional: "All data is fictional, for demo purposes.",
    },
  },
};

const CHIPS = {
  ar: [
    "مين ما ركب باص منى لعرفات؟",
    "وش وضع باصات فوج 5 لعرفات؟",
    "أي باصات متأخرة وكم التأخير؟",
    "كم حاج ضايع الحين؟",
    "أي فوج أسوأ في الصعود لعرفات؟ وش تنصح؟",
    "كيف الجو في عرفات اليوم؟ وأي أفواج للحين في منى؟",
  ],
  en: [
    "Who hasn't boarded the Mina → Arafat bus?",
    "What's the status of group 5 buses to Arafat?",
    "Which buses are delayed and by how much?",
    "How many pilgrims are missing right now?",
    "Rank the groups by boarding progress to Arafat and recommend what to do",
    "What's the weather in Arafat today, and which groups are still in Mina?",
  ],
};

const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

const clientId = store.get("mats.client", "") || (() => {
  const id = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()) + Math.random().toString(16).slice(2);
  store.set("mats.client", id); return id;
})();
let lang = store.get("mats.lang", (navigator.language || "ar").startsWith("ar") ? "ar" : "en");
let runtime = null;
let history = [];
let state = "idle";            // idle | listening | transcribing | thinking | speaking
let speakOn = store.get("mats.speak", "1") === "1";
const t = (k) => T[lang][k] ?? k;

function applyLang() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-label]").forEach((n) => {
    n.setAttribute("aria-label", t(n.dataset.i18nLabel)); n.title = t(n.dataset.i18nLabel);
  });
  document.querySelectorAll("[data-i18n-ph]").forEach((n) => { n.placeholder = t(n.dataset.i18nPh); });
  renderChips();
  setState(state);
  if (el.rtDlg.open) renderRuntime();
}

function renderChips() {
  el.chips.replaceChildren(...CHIPS[lang].map((q, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "chip"; b.dir = "auto";
    if (i === 4) b.innerHTML = `<span class="tag">Ultra</span>`;
    if (i === 5) b.innerHTML = `<span class="tag">Tavily</span>`;
    b.append(q);
    b.addEventListener("click", () => ask(q, false));
    return b;
  }));
}

/* ───────────────────────── state ───────────────────────── */
const STATUS_KEY = { idle: "statusIdle", listening: "statusListening", transcribing: "statusTranscribing",
  thinking: "statusThinking", speaking: "statusSpeaking" };

function setState(s, msgKey) {
  state = s;
  document.body.dataset.state = s;
  el.mic.setAttribute("aria-pressed", String(s !== "idle"));
  el.status.textContent = t(msgKey || STATUS_KEY[s]);
  el.send.disabled = s === "thinking";
}

/* ───────────────────────── audio input ───────────────────────── */
const audio = { stream: null, ctx: null, analyser: null, buf: null, floor: 0.01, raf: 0 };

async function ensureMic() {
  if (audio.stream) return true;
  try {
    audio.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch { setState("idle", "statusNoMic"); return false; }
  audio.ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = audio.ctx.createMediaStreamSource(audio.stream);
  audio.analyser = audio.ctx.createAnalyser();
  audio.analyser.fftSize = 1024;
  audio.buf = new Float32Array(audio.analyser.fftSize);
  src.connect(audio.analyser);
  meterLoop();
  return true;
}

function level() {
  if (!audio.analyser) return 0;
  audio.analyser.getFloatTimeDomainData(audio.buf);
  let sum = 0;
  for (const v of audio.buf) sum += v * v;
  return Math.sqrt(sum / audio.buf.length);
}

/* One animation loop drives the level ring, the VAD and barge-in detection. */
const vad = { active: false, onEnd: null, speech: false, lastVoice: 0, started: 0 };
let bargeSince = 0;

function meterLoop() {
  const now = performance.now();
  const rms = level();
  if (state === "idle" || state === "thinking") audio.floor = audio.floor * 0.95 + rms * 0.05;
  const listenTh = Math.max(0.015, audio.floor * 3);
  const visible = state === "listening" ? Math.min(1, rms / 0.12) : 0;
  el.micWrap.style.setProperty("--level", visible.toFixed(3));

  if (vad.active) {
    if (rms > listenTh) { if (!vad.speech) vad.speech = true; vad.lastVoice = now; }
    const silentFor = now - vad.lastVoice;
    if ((vad.speech && silentFor > SILENCE_MS) || now - vad.started > MAX_UTTERANCE_MS) endVad(true);
    else if (!vad.speech && now - vad.started > NO_SPEECH_MS) endVad(false);
  }

  // Barge-in: sustained voice above a (higher) threshold while the agent talks.
  if ((state === "speaking" || state === "thinking") && el.handsFree.checked) {
    const bargeTh = Math.max(0.06, audio.floor * 6);
    if (rms > bargeTh) {
      if (!bargeSince) bargeSince = now;
      else if (now - bargeSince > BARGE_MS) { bargeSince = 0; bargeIn(); }
    } else bargeSince = 0;
  } else bargeSince = 0;
  audio.raf = requestAnimationFrame(meterLoop);
}

function startVad(onEnd) {
  Object.assign(vad, { active: true, onEnd, speech: false, started: performance.now(), lastVoice: performance.now() });
}
function endVad(hadSpeech) {
  if (!vad.active) return;
  vad.active = false;
  const cb = vad.onEnd; vad.onEnd = null;
  cb && cb(hadSpeech);
}

/* ───────────────────────── listening ───────────────────────── */
let recorder = null;
let recognition = null;

async function startListening() {
  if (!(await ensureMic())) return;
  if (audio.ctx.state === "suspended") await audio.ctx.resume();
  stopSpeaking();
  el.interim.textContent = "";
  setState("listening");
  if (runtime?.asr?.enabled && window.MediaRecorder) listenWithAsr();
  else listenWithWebSpeech();
}

function listenWithAsr() {
  const chunks = [];
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
  recorder = new MediaRecorder(audio.stream, mime ? { mimeType: mime } : undefined);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    const rec = recorder; recorder = null;
    if (!rec._keep) return;
    setState("transcribing");
    const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
    const fd = new FormData();
    fd.append("file", blob, blob.type.includes("mp4") ? "speech.mp4" : "speech.webm");
    fd.append("language", lang);
    try {
      const r = await fetch("/api/transcribe", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const { text } = await r.json();
      if (text) ask(text, true); else afterTurn("statusNoSpeech");
    } catch (e) {
      console.warn("ASR failed, falling back to Web Speech", e);
      runtime.asr.enabled = false;
      setState("idle", "statusError");
    }
  };
  recorder.start(250);
  startVad((hadSpeech) => {
    if (!recorder) return;
    recorder._keep = hadSpeech;
    recorder.stop();
    if (!hadSpeech) afterTurn("statusNoSpeech");
  });
}

function listenWithWebSpeech() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { setState("idle", "statusNoMic"); el.input.focus(); return; }
  recognition = new SR();
  recognition.lang = lang === "ar" ? "ar-SA" : "en-US";
  recognition.interimResults = true;
  recognition.continuous = true;
  let finalText = "";
  recognition.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
    }
    el.interim.textContent = (finalText + " " + interim).trim();
    vad.lastVoice = performance.now(); vad.speech = true;
  };
  recognition.onerror = (e) => { if (e.error === "not-allowed") setState("idle", "statusNoMic"); };
  recognition.onend = () => {
    recognition = null;
    endVad(false);
    const text = (finalText || el.interim.textContent).trim();
    if (state !== "listening") return;
    if (text) ask(text, true); else afterTurn("statusNoSpeech");
  };
  recognition.start();
  startVad(() => { try { recognition && recognition.stop(); } catch { /* already stopped */ } });
}

function stopListening(submit = true) {
  if (vad.active) { if (submit) endVad(true); else vad.active = false; }
  if (!submit) {
    if (recorder) { recorder._keep = false; recorder.stop(); }
    if (recognition) { recognition.onend = null; recognition.abort(); recognition = null; }
  }
}

/* ───────────────────────── speaking ─────────────────────────
   Neural server voice (/api/tts, streamed MP3, next sentence prefetched while the
   current one plays) when configured; otherwise the best browser voice available. */
const tts = { queue: 0, buffer: "", streamDone: true, gen: 0, audio: [], playing: null, serverFailed: false };

/* Make text sound right when spoken: phones, arrows, pilgrim numbers. */
function speechText(text, code) {
  return text.replace(/[*_#`>|]/g, " ")
    .replace(/\+?966-(5\d{2})-(\d{3})-(\d{4})/g, "0$1 $2 $3")
    .replace(/→|->/g, code === "ar" ? " إلى " : " to ")
    .replace(/\bP-0*(\d+)/g, code === "ar" ? "رقم $1" : "number $1")
    .replace(/\s+/g, " ").trim();
}

function voiceScore(v, code) {
  const L = v.lang.replace("_", "-").toLowerCase(), n = v.name.toLowerCase();
  let s = 0;
  if (code === "ar") {
    if (!L.startsWith("ar")) return -1;
    if (L === "ar-sa") s += 4; else if (/^ar-(ae|kw|qa|bh|om)/.test(L)) s += 2;
  } else {
    if (!L.startsWith("en")) return -1;
    if (L === "en-us") s += 3; else if (L === "en-gb") s += 2;
  }
  if (/natural|neural/.test(n)) s += 8;          // Edge: "Microsoft Hamed Online (Natural)"
  if (/premium|enhanced|siri/.test(n)) s += 6;   // macOS/iOS downloadable voices
  if (/google/.test(n)) s += 5;
  if (!v.localService) s += 1;
  return s;
}

function browserVoices(code) {
  if (!("speechSynthesis" in window)) return [];
  return speechSynthesis.getVoices().map((v) => [voiceScore(v, code), v])
    .filter(([sc]) => sc >= 0).sort((a, b) => b[0] - a[0]).map(([, v]) => v);
}

function pickVoice(code) {
  const saved = store.get(`mats.voice.${code}`, "");
  const list = browserVoices(code);
  return list.find((v) => v.name === saved) || list[0] || null;
}

const useServerTts = () => runtime?.tts?.provider && runtime.tts.provider !== "browser" && !tts.serverFailed;

function serverVoice(code) {
  const opts = runtime?.tts?.voices?.[code] || [];
  const saved = store.get(`mats.voice.${code}`, "");
  return (opts.find((o) => o.id === saved) || opts[0] || {}).id || "";
}

function speakBrowser(clean, code, onDone) {
  if (!("speechSynthesis" in window)) { onDone(); return; }
  const u = new SpeechSynthesisUtterance(clean);
  u.lang = code === "ar" ? "ar-SA" : "en-US";
  const v = pickVoice(code);
  if (v) u.voice = v;
  u.rate = code === "ar" ? 0.98 : 1.03;
  u.onend = u.onerror = onDone;
  speechSynthesis.speak(u);
}

function playNext() {
  if (tts.playing || !tts.audio.length) return;
  const it = tts.audio.shift();
  if (it.gen !== tts.gen) { playNext(); return; }
  tts.playing = it;
  it.a.play().catch(() => it.fail());
}

function speakSentence(text, code) {
  const clean = speechText(text, code);
  if (!clean || !speakOn) return;
  tts.queue++;
  if (state === "thinking") setState("speaking");
  const gen = tts.gen;           // anything from before a barge-in must not count
  const done = () => { if (gen !== tts.gen) return; tts.queue--; maybeFinishedSpeaking(); };
  if (!useServerTts()) { speakBrowser(clean, code, done); return; }

  const a = new Audio(`/api/tts?lang=${code}&voice=${encodeURIComponent(serverVoice(code))}`
                      + `&text=${encodeURIComponent(clean)}`);
  a.preload = "auto";            // starts fetching now, so the next sentence is ready in time
  const it = { a, gen, fail: null };
  let finished = false;
  const finish = () => { if (finished) return; finished = true; if (tts.playing === it) tts.playing = null; done(); playNext(); };
  it.fail = () => {              // server voice failed: say this sentence with the browser
    if (finished || gen !== tts.gen) return;
    finished = true; tts.serverFailed = true;
    if (tts.playing === it) tts.playing = null;
    speakBrowser(clean, code, () => { done(); playNext(); });
  };
  a.onended = finish;
  a.onerror = () => it.fail();
  tts.audio.push(it);
  playNext();
}

function feedSpeech(chunk, sentLang) {
  tts.buffer += chunk;
  const re = /^(.*?[.!?؟…\n]+)(\s|$)/s;
  let m;
  while ((m = tts.buffer.match(re)) && m[1].trim().length > 1) {
    speakSentence(m[1], sentLang);
    tts.buffer = tts.buffer.slice(m[0].length);
  }
}

function flushSpeech(sentLang) {
  if (tts.buffer.trim()) speakSentence(tts.buffer, sentLang);
  tts.buffer = "";
  tts.streamDone = true;
  maybeFinishedSpeaking();
}

function stopSpeaking() {
  tts.gen++; tts.buffer = ""; tts.queue = 0; tts.streamDone = true;
  if (tts.playing) { tts.playing.a.pause(); tts.playing.a.removeAttribute("src"); }
  tts.audio.forEach((it) => it.a.removeAttribute("src"));
  tts.audio = []; tts.playing = null;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

function maybeFinishedSpeaking() {
  if (tts.queue <= 0 && tts.streamDone && (state === "speaking" || state === "thinking")) afterTurn();
}

function afterTurn(msgKey) {
  setState("idle", msgKey);
  if (el.handsFree.checked) setTimeout(() => { if (state === "idle" && el.handsFree.checked) startListening(); }, msgKey ? 1200 : 350);
}

/* ───────────────────────── barge-in ───────────────────────── */
let controller = null;
let currentMsg = null;

function bargeIn() {
  if (controller) controller.abort();
  controller = null;
  stopSpeaking();
  if (currentMsg) currentMsg.classList.add("interrupted");
  startListening();
}

/* ───────────────────────── chat ───────────────────────── */
function addUser(text, byVoice) {
  const d = document.createElement("div");
  d.className = "msg user"; d.dir = "auto"; d.textContent = text;
  if (byVoice) { const s = document.createElement("span"); s.className = "via"; s.textContent = "🎙 " + t("via"); d.prepend(s); }
  el.thread.append(d);
}

function newBotMsg() {
  const node = el.tpl.content.firstElementChild.cloneNode(true);
  node.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  el.thread.append(node);
  return node;
}

async function ask(text, byVoice) {
  text = (text || "").trim();
  if (!text) return;
  if (state !== "idle" && state !== "listening" && state !== "transcribing") bargeIn();
  stopListening(false);
  el.interim.textContent = "";
  addUser(text, byVoice);
  const msg = newBotMsg();
  currentMsg = msg;
  msg.scrollIntoView({ behavior: "smooth", block: "start" });
  setState("thinking");
  tts.streamDone = false; tts.buffer = "";

  const ctl = new AbortController();
  controller = ctl;
  const ans = msg.querySelector(".answer");
  let answerLang = lang, done = null, intent = null;
  const steps = [];

  try {
    const r = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: ctl.signal,
      body: JSON.stringify({ message: text, history: history.slice(-8), lang, client_id: clientId }),
    });
    if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        switch (ev.type) {
          case "intent": intent = ev; answerLang = ev.lang; renderMeta(msg, ev); break;
          case "trace": steps.push(ev); renderTrace(msg, steps); break;
          case "sql": renderSql(msg, ev); break;
          case "table": renderTable(msg, ev); break;
          case "sources": renderSources(msg, ev.sources); break;
          case "clarify": renderClarify(msg, ev); break;
          case "remembered": renderRemembered(msg, ev.fact); break;
          case "token": ans.textContent += ev.text; feedSpeech(ev.text, answerLang); break;
          case "done": done = ev; break;
          case "error": throw new Error(ev.message);
        }
      }
    }
  } catch (e) {
    if (ctl.signal.aborted) return;          // barge-in: a new turn already started
    ans.innerHTML = `<span class="error-msg"></span>`;
    ans.firstChild.textContent = t("statusError") + ` (${e.message})`;
    stopSpeaking(); setState("idle", "statusError");
    return;
  } finally {
    if (controller === ctl) controller = null;
  }
  if (done) {
    ans.textContent = done.answer;
    renderTrace(msg, steps, done.total_ms);
    if (done.sql) wireFeedback(msg, done.question, done.sql);
    history.push({ role: "user", content: done.question || text },
                 { role: "assistant", content: done.answer, context: done.context || null });
  }
  if (speakOn) flushSpeech(answerLang); else { tts.streamDone = true; afterTurn(); }
}

/* ───────────────────────── rendering ───────────────────────── */
function renderMeta(msg, ev) {
  const meta = msg.querySelector(".meta");
  meta.innerHTML = "";
  const b = document.createElement("span");
  b.className = "badge intent"; b.textContent = T[lang].intents[ev.intent] || ev.intent;
  meta.append(b);
}

function renderClarify(msg, ev) {
  if (!ev.options.length) return;     // a plain question: the user just answers it
  const box = document.createElement("div");
  box.className = "clarify";
  const hint = document.createElement("span");
  hint.className = "clarify-hint"; hint.textContent = t("clarifyHint");
  box.append(hint, ...ev.options.map((o) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "chip"; b.dir = "auto"; b.textContent = o;
    b.addEventListener("click", () => ask(o, false));
    return b;
  }));
  msg.querySelector(".meta").after(box);
}

function renderRemembered(msg, fact) {
  const b = document.createElement("span");
  b.className = "badge remembered"; b.dir = "auto";
  b.textContent = `🧠 ${t("remembered")}: ${fact}`;
  msg.querySelector(".meta").append(b);
}

function renderSql(msg, ev) {
  const box = msg.querySelector(".sql-box");
  box.hidden = false;
  box.querySelector("code").textContent = ev.sql;
  box.querySelector(".sql-meta").textContent = `· ${t("attempt")} ${ev.attempt} · ${ev.model}`;
}

function renderTable(msg, ev) {
  const wrap = msg.querySelector(".table-wrap");
  wrap.hidden = false;
  const table = document.createElement("table");
  const thead = table.createTHead().insertRow();
  ev.columns.forEach((c) => { const th = document.createElement("th"); th.textContent = c; thead.append(th); });
  const tb = table.createTBody();
  ev.rows.slice(0, 100).forEach((row) => {
    const tr = tb.insertRow();
    row.forEach((v) => {
      const td = tr.insertCell();
      td.textContent = v === null ? "—" : String(v);
      td.dir = "auto";
      if (typeof v === "number") td.className = "num";
    });
  });
  const note = document.createElement("div");
  note.className = "table-note";
  note.textContent = `${ev.rows.length} ${t("rows")}` + (ev.truncated || ev.rows.length > 100
    ? ` · ${t("capped").replace("{n}", Math.min(100, ev.rows.length))}` : "");
  wrap.replaceChildren(table, note);
}

function renderSources(msg, sources) {
  const box = msg.querySelector(".sources");
  if (!sources.length) return;
  box.hidden = false;
  const label = document.createElement("span");
  label.className = "src-label"; label.textContent = `${t("sources")} · Tavily`;
  box.replaceChildren(label, ...sources.map((s) => {
    const a = document.createElement("a");
    a.href = s.url; a.target = "_blank"; a.rel = "noopener"; a.textContent = s.title || s.url; a.dir = "auto";
    return a;
  }));
}

function renderTrace(msg, steps, totalMs) {
  const ol = msg.querySelector(".steps");
  ol.replaceChildren(...steps.map((s) => {
    const li = document.createElement("li");
    li.className = `step ${s.status}`;
    li.innerHTML = `<span class="dot" aria-hidden="true"></span><span class="name"></span><span class="ms"></span>`;
    li.querySelector(".name").textContent = T[lang].steps[s.step] || s.step;
    li.querySelector(".ms").textContent = `${s.ms} ms`;
    if (s.model) { const m = document.createElement("span"); m.className = "model"; m.textContent = s.model; li.append(m); }
    if (s.detail) { const d = document.createElement("span"); d.className = "detail"; d.textContent = s.detail; d.dir = "auto"; li.append(d); }
    return li;
  }));
  if (totalMs != null) {
    msg.querySelector(".trace-total").textContent = `· ${t("total")} ${(totalMs / 1000).toFixed(1)} s`;
    const meta = msg.querySelector(".meta");
    const b = document.createElement("span");
    b.className = "badge"; b.textContent = `${(totalMs / 1000).toFixed(1)} s`;
    meta.append(b);
    const models = [...new Set(steps.map((s) => s.model).filter((m) => m && m.includes("/")))];
    models.forEach((m) => { const x = document.createElement("span"); x.className = "badge"; x.textContent = m.split("/").pop(); meta.append(x); });
  }
}

function wireFeedback(msg, question, sql) {
  const box = msg.querySelector(".feedback");
  box.hidden = false;
  box.querySelectorAll(".fb").forEach((b) => b.addEventListener("click", async () => {
    const verdict = b.dataset.v;
    const out = box.querySelector(".fb-msg");
    try {
      const r = await fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, sql, verdict }) });
      if (!r.ok) throw new Error((await r.json()).detail);
      box.querySelectorAll(".fb").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      out.textContent = verdict === "right" ? t("fbRight") : t("fbWrong");
    } catch (e) { out.textContent = e.message; }
  }));
}

/* ───────────────────────── runtime panel ───────────────────────── */
let mem = null;
async function loadRuntime() {
  try { runtime = await (await fetch("/api/runtime")).json(); } catch { runtime = null; }
  try { mem = await (await fetch(`/api/memory?client_id=${encodeURIComponent(clientId)}`)).json(); } catch { mem = null; }
}

function voiceOptions(code) {
  const esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const saved = store.get(`mats.voice.${code}`, "");
  if (useServerTts()) {
    const opts = runtime.tts.voices[code] || [];
    return opts.map((o, i) => `<option value="${esc(o.id)}" ${o.id === saved || (!saved && i === 0) ? "selected" : ""}>${esc(o.label)}</option>`).join("");
  }
  const list = browserVoices(code), best = pickVoice(code);
  if (!list.length) return `<option>—</option>`;
  return list.map((v) => `<option value="${esc(v.name)}" ${best && v.name === best.name ? "selected" : ""}>${esc(v.name)} (${esc(v.lang)})</option>`).join("");
}

function renderRuntime() {
  const R = T[lang].rt;
  if (!runtime) { el.rtBody.textContent = t("statusError"); return; }
  const pill = (on, txt) => `<span class="pill ${on ? "on" : "off"}">${txt ?? (on ? R.on : R.off)}</span>`;
  const row = (k, v) => `<div class="rt-row"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const m = runtime.models, c = runtime.counts;
  el.rtBody.innerHTML = `
    <h3>${R.models} · NVIDIA Nemotron</h3>
    ${row(R.provider, `${esc(runtime.provider)}<br>${esc(runtime.base_url)}`)}
    ${row(R.key, pill(runtime.api_key_set))}
    ${row(R.fast, esc(m.fast))}
    ${row(R.fallback, esc(m.fast_fallback))}
    ${row(R.sqlm, esc(m.sql))}
    ${row(R.complex, esc(m.complex))}
    <h3>${R.voice}</h3>
    ${row(R.asr, runtime.asr.enabled ? `${pill(true)} ${esc(runtime.asr.model)}` : `${pill(false)} → ${R.browser}`)}
    ${row(R.tavily, pill(runtime.tavily))}
    ${row(R.tts, useServerTts() ? `${pill(true, runtime.tts.provider)} neural` : `${pill(false, R.browser)}`)}
    ${["ar", "en"].map((code) => row(code === "ar" ? R.voiceAr : R.voiceEn,
      `<span class="voice-pick"><select data-voice="${code}" aria-label="${code === "ar" ? R.voiceAr : R.voiceEn}">${voiceOptions(code)}</select>
       <button type="button" class="fb" data-try="${code}">${R.tryVoice}</button></span>`)).join("")}
    <h3>${R.data}</h3>
    ${row(R.campaign, esc(lang === "ar" ? runtime.campaign.name_ar : runtime.campaign.name_en))}
    ${row(R.now, esc(runtime.simulated_now))}
    ${row(R.counts, Object.entries(c).map(([k, v]) => `${k}: ${v}`).join(" · "))}
    ${row(R.memory, `${runtime.memory.examples} / verified ${runtime.memory.verified}`)}
    ${row(t("lessons"), String(mem?.lessons ?? 0))}
    <h3>${t("facts")}</h3>
    ${(mem?.facts?.length ? `<ul class="facts">${mem.facts.map((f) => `<li dir="auto">${esc(f)}</li>`).join("")}</ul>
       <button type="button" class="fb wrong" id="forgetFacts">${t("forgetFacts")}</button>`
      : `<p class="hint">${t("noFacts")}</p>`)}
    ${row(R.safety, `SELECT-only · mode=ro · authorizer · ${runtime.safety.timeout_s}s · ≤${runtime.safety.max_rows} rows`)}
    <p class="hint">${R.fictional}</p>`;
  el.rtBody.querySelectorAll("select[data-voice]").forEach((sel) => sel.addEventListener("change", () => {
    store.set(`mats.voice.${sel.dataset.voice}`, sel.value);
  }));
  el.rtBody.querySelectorAll("[data-try]").forEach((b) => b.addEventListener("click", () => {
    stopSpeaking();
    speakSentence(b.dataset.try === "ar" ? "هلا والله! أنا مساعدك في الحملة، اسألني عن الباصات والأفواج."
                                          : "Hi! I'm your campaign assistant. Ask me about buses and groups.", b.dataset.try);
  }));
  const fb = $("forgetFacts");
  if (fb) fb.addEventListener("click", async () => {
    await fetch(`/api/memory/facts?client_id=${encodeURIComponent(clientId)}`, { method: "DELETE" });
    await loadRuntime(); renderRuntime();
  });
}

/* ───────────────────────── wiring ───────────────────────── */
el.mic.addEventListener("click", () => {
  if (state === "listening") stopListening(true);
  else if (state === "speaking" || state === "thinking") bargeIn();
  else if (state === "idle") startListening();
});
el.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = el.input.value; el.input.value = "";
  ask(q, false);
});
el.lang.addEventListener("click", () => { lang = lang === "ar" ? "en" : "ar"; store.set("mats.lang", lang); applyLang(); });
el.theme.addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  store.set("mats.theme", document.documentElement.dataset.theme);
});
el.speak.setAttribute("aria-pressed", String(speakOn));
el.speak.addEventListener("click", () => {
  speakOn = !speakOn; store.set("mats.speak", speakOn ? "1" : "0");
  el.speak.setAttribute("aria-pressed", String(speakOn));
  if (!speakOn) { stopSpeaking(); if (state === "speaking") afterTurn(); }
});
el.handsFree.addEventListener("change", () => {
  store.set("mats.handsfree", el.handsFree.checked ? "1" : "0");
  if (el.handsFree.checked && state === "idle") startListening();
});
el.rtBtn.addEventListener("click", async () => { await loadRuntime(); renderRuntime(); el.rtDlg.showModal(); });
el.rtClose.addEventListener("click", () => el.rtDlg.close());
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state !== "idle" && !el.rtDlg.open) { stopListening(false); if (controller) controller.abort(); stopSpeaking(); setState("idle"); }
});
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => { if (el.rtDlg.open) renderRuntime(); };

const savedTheme = store.get("mats.theme", "");
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
applyLang();
loadRuntime();
