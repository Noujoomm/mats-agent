# MATS Agent: Devpost submission

## Project name
MATS Agent

## Elevator pitch (≤200 chars)
Talk to your Hajj operations data in Saudi Arabic or English. A real-time voice agent with barge-in, routed across NVIDIA Nemotron models on Nebius Token Factory, read-only by design.

## Track
Best Apps and Agents (also entering Best Use of Tavily)

---

## About the project

### Inspiration
During the Hajj, a single campaign moves thousands of pilgrims from Mina to Arafat in a few hours. The supervisors who run that movement are standing next to buses, phone in one hand, crowd in front of them. Their questions are simple:
- "Who hasn't boarded?"
- "Is group 5's bus delayed?"
- "How many are still missing?"

But the answers are locked in a database that needs SQL. They also speak Saudi dialect ("مين ما ركب؟", "كم واحد ضايع؟"), not formal Arabic, and many staff speak English. We wanted an assistant they could simply *talk to*, that answers out loud in seconds and shows its work so it can be trusted.

### What it does
MATS Agent is a bilingual (Arabic/English) real-time voice agent over a campaign's operations database.
- **Voice-first.** Push-to-talk, or *Hands-free* mode: voice activity detection ends your turn after about 900 ms of silence, and the agent listens again after replying. **Barge-in** works: talk over it and it stops speaking, aborts the stream and listens.
- **Understands context, remembers you, learns, and asks when unsure.**
  - It resolves follow-ups, pronouns and references to earlier answers ("the first one's phone?", "and his group's supervisor?") against the data behind those answers.
  - It remembers facts you tell it ("I supervise group 14"), so "my group" works later.
  - It turns its own repaired mistakes and every **Wrong** into lessons for similar questions.
  - When a key detail is missing ("group 5's buses", but from where to where?), it asks with tappable options instead of guessing.
- **Stays in its lane.** It only answers pilgrim guidance and campaign operations, and politely declines everything else before any model work. Religious rulings are referred to the campaign's religious guide, and web search is hard-limited to the holy sites.
- **Understands dialect and follow-ups.** It normalizes Arabic spelling variants and digits and uses a Saudi dialect glossary (ما ركب = not boarded, ضايع = missing, فوج = group). Follow-ups like "وفوج ٥؟" ("and group 5?") are rewritten into full questions.
- **Answers from data, out loud.** It writes SQL, runs it safely, and streams a spoken answer of at most 3 sentences, sentence by sentence, in the language of the question.
- **Shows its work.** Every answer shows the SQL, the result table, and a "How it answered" trace with each step, the Nemotron model that ran it, its milliseconds and the total latency.
- **Reasons when needed.** Rankings, comparisons and "what should we do?" questions go to Nemotron Ultra, which writes the SQL and gives a concrete recommendation.
- **Knows the outside world.** Weather in Arafat, traffic and official announcements come from Tavily, merged with database results, with sources shown.
- **Learns.** Successful question→SQL pairs become few-shot examples. **Right** verifies a pair; **Wrong** makes it forget.
- **Safe.** It is read-only by construction, with three independent layers.

All demo data is a fully fictional "MATS Demo Campaign": 20 groups, 2,000 pilgrims and 40 buses, with the clock frozen mid-movement to Arafat and 7 pilgrims missing.

### How we built it
- **Model routing on Nebius Token Factory.** Every LLM call is a runtime call to Token Factory's OpenAI-compatible API:
  - **Nemotron 3.5 Lightning** (fallback Nemotron 3 Nano 30B-A3B) for intent routing, follow-up rewriting and the streamed spoken answer
  - **Nemotron 3 Super 120B-A12B** for text-to-SQL with error-feedback repair
  - **Nemotron 3 Ultra 550B-A55B** for complex questions, and as the escalation target when Super fails twice

  Model IDs are environment variables, and `scripts/check_models.py` lists and pings them.
- **Speech.**
  - **Nemotron 3.5 ASR** (`nemotron-3.5-asr-streaming-0.6b`), which NVIDIA fine-tuned on SDAIA's SADA dataset for Najdi/Hijazi speech, served by our own FastAPI + NeMo + ffmpeg container on a **Nebius Serverless GPU endpoint** (L40S) behind token auth, with an OpenAI-compatible `/v1/audio/transcriptions` route. The backend proxies audio to it and falls back to the browser's Web Speech API when it isn't configured.
  - Speech synthesis uses the browser (ar-SA / en-US), sentence by sentence as tokens stream over SSE.
- **Agent pipeline** (Python, FastAPI): route + rewrite → memory retrieval (character-trigram similarity on normalized Arabic) → SQL → guard → answer, with every step emitting a trace event. A streaming filter strips `<think>` traces, even when tags are split across chunks.
- **Safety:**
  1. a static check (one SELECT/WITH; write/DDL keywords blocked outside string literals)
  2. SQLite opened with `mode=ro`
  3. a SQLite authorizer that only allows reads, a 3-second progress-handler budget and a row cap
- **Frontend.** Vanilla JS with no build step, mobile-first, RTL/LTR, dark mode and visible focus. The Web Audio API drives a live level ring, VAD and barge-in detection.
- **Tests.** An offline pytest suite with a scripted fake LLM covers:
  - guard injection cases
  - repair → escalate to Ultra
  - complex → Ultra
  - follow-ups
  - hybrid Tavily
  - seed examples
  - mock data shape
  - the SSE endpoint

### Challenges we ran into
- **Barge-in without echo.** The agent's own voice can trigger "user is speaking". We used echo cancellation, an adaptive noise floor, and a higher, sustained threshold (~280 ms) for barge-in than for normal listening.
- **Streaming and reasoning traces.** `<think>` tags arrive split across chunks, sometimes as an orphan `</think>`. We wrote a small state machine that holds back partial tags without delaying the first spoken word.
- **Dialect.** "ما ركب" is not in any SQL tutorial. Combining normalization, a domain glossary and retrieved examples did far more than prompt wording alone.
- **Latency budget for voice.** One JSON call for routing and rewriting together, the fast model for speech, and Ultra only where reasoning matters, so simple questions still feel conversational.
- **A learning loop that can learn mistakes.** A web+database question once produced SQL that "succeeded" (rows came back) but invented a weather column. Auto-saving it taught the agent to repeat the mistake. Now verified pairs (seeds, or answers marked **Right**) clearly outrank auto-saved ones, and mixed web+DB answers are never auto-saved.
- **Mixed questions.** For hybrid questions, Super tried to answer the weather part from the database. Telling it explicitly that the web covers that part, and running Tavily in parallel with the SQL step (with an English query and social media excluded), took these answers from ~8 s to ~3–5 s with official weather sources.
- **Fully fictional but realistic data.** We froze a "simulated now" mid-movement so trip states, missing pilgrims and incidents tell a coherent operational story.

### Accomplishments that we're proud of
- A real spoken conversation in Saudi dialect with barge-in, over live structured data.
- A transparent trace that shows which Nemotron model did what, and how long each step took.
- Self-repair that actually works: a failed query is fed back to Super with the error, and then escalated to Ultra.
- Three safety layers that hold even if the model is tricked into writing `DROP TABLE`.

### What we learned
- Routing beats "one big model": a fast Nemotron for conversation and a big one for reasoning gives both speed and quality.
- For voice, *time to first sentence* matters more than total latency, so streaming plus sentence-level TTS changes how the product feels.
- Showing the SQL and the trace builds trust faster than any accuracy claim.

### What's next
- Streaming ASR partials over WebSocket for even faster turn-taking.
- Nemotron-based TTS for a native Saudi voice.
- Proactive alerts ("group 14's bus is 40 minutes late; call the supervisor?").
- Role-based access and audit logs for real deployments, plus offline-first mode for the holy sites.

---

## Built with
`nvidia-nemotron` · `nemotron-3.5-lightning` · `nemotron-3-super` · `nemotron-3-ultra` · `nemotron-asr` · `nebius-token-factory` · `nebius-serverless` · `nvidia-nemo` · `tavily` · `python` · `fastapi` · `sqlite` · `server-sent-events` · `web-audio-api` · `web-speech-api` · `javascript` · `docker` · `pytest` · `edge-tts (optional neural Arabic voice)`

---

## Feedback on Token Factory, Nemotron and NVIDIA ASR

**Nebius Token Factory**
- *What worked:* the OpenAI-compatible API meant zero new SDK. Switching between three Nemotron sizes per step is a one-string change, which made model routing trivial to build and to A/B test.
- *Model discovery:* model IDs mix casing and separators (`Nemotron-3_5-Lightning` vs `nemotron-3-super-120b-a12b`). We wrote `check_models.py` just to find the exact IDs. Case-insensitive aliases, or a `nemotron-*-latest` alias per size, would remove a whole class of 404s.
- *Reasoning control:* the way to turn thinking on or off differs by model (system prompt flags vs `chat_template_kwargs`). A single documented request parameter (e.g. `reasoning: off|low|high`) across all Nemotron models, plus a separate `reasoning_content` field in streams instead of inline `<think>` tags, would make streaming to voice much simpler.
- *Latency transparency:* per-model time-to-first-token and tokens/s on the model page (p50/p95) would let builders pick models for voice budgets without benchmarking first.
- *Errors:* a structured error code for "model not available in your region/tier" vs "unknown model" would let clients fall back automatically and correctly.

**Nemotron models** (observed while building)
- *Thinking control works, but must be explicit:* with `chat_template_kwargs: {enable_thinking: false}`, all four models (Lightning, Nano, Super, Ultra) answered "ready" in ~350–600 ms. Without it, Lightning wrote its reasoning as **plain text with no `<think>` tags** ("Here's a thinking process: 1. Analyze…"), which no tag-stripper can remove. Please make "no reasoning" the default for chat, or always wrap reasoning in tags / a separate field.
- *Chat history makes small models answer instead of classify:* when we passed earlier turns as real `user`/`assistant` messages to Lightning for routing, it *continued the conversation* and invented an answer ("group 15's buses arrived") instead of returning JSON. Passing history as a transcript inside one user message, plus two few-shot examples, fixed it. A docs note on this pattern would save people time.
- *Negation in Arabic answers needs grounding:* given a result table for "مين ما ركب؟" ("who has **not** boarded?"), Lightning, Nano and even Super sometimes answered as if they **had** boarded, or said "the data has no boarding information". Including the SQL (which shows the `NOT IN` filter) and an English "meaning" line from the router fixed this for Lightning and Nano. After that, Lightning gave the best speed/quality for spoken answers (first token ~300–380 ms).
- *Super is a strong SQL model:* with 3 retrieved examples, it wrote correct SQL first time for every demo question we tried, in ~0.5–2 s.
- *Ultra is excellent at analytical SQL but verbose:* its first ranking query was a correct 5-CTE query with SQL comments and long recommendation strings inside `CASE`. That ran past a 700-token budget and broke mid-string. Asking for "no comments, compute numbers, don't write text in SQL" and a 1,500-token budget made it succeed first time, with a clear, actionable spoken recommendation.
- *Small models copy few-shot values:* given an example "I supervise group 2 → my group = group 2", Lightning (and once Super) answered "group 2" for a user with **no** remembered group. For anything safety-relevant (which group to report on), we now ask deterministically instead of trusting the model. Lightning also over-asked clarifying questions ("Which buses are delayed?" doesn't need a route), so a Lightning "clarify" is double-checked by Super.
- *Grounding is fragile in small models:* for a count-only result ("7 missing"), Lightning added three invented pilgrim numbers, because our prompt said "say the total, then name up to 3". Rewording to "if the result is a single number, just say it; never add names or numbers not in the rows" fixed it. Lightning also copied English web snippets verbatim into Arabic answers ("partly cloudy 16 °C"), and Super translates them cleanly, so web answers use Super. It also introduced itself as "Nemotron, trained by NVIDIA" despite a persona prompt, so identity questions get a fixed answer. A documented, reliable way to set a persona would help app builders.
- *Two-stage routing works:* Lightning routes plain questions in ~0.5–0.9 s. Super handles only the turns that need reasoning (references, remembered facts, possible ambiguity) in ~0.7–1.7 s, and resolved every case we tried. Nano was fast but asked unnecessary clarifications and over-applied remembered facts.
- *Latency variance:* Super's routing latency ranged from 0.7 s to 10 s in one evening, and one request hung for 120 s until our client timeout. For voice we now use 10 s (routing) and 30 s (SQL, answer) timeouts and fall back to Lightning. A published latency SLO, or a `priority`/`low-latency` tier per request, would help real-time apps a lot.
- *Language drift:* the router sometimes rewrote an English follow-up ("and group 18?") into Arabic, since the earlier conversation was Arabic. It's harmless for SQL, but answers must follow the user's language, so we detect the language from the original utterance.

**NVIDIA Nemotron ASR (nemotron-3.5-asr-streaming-0.6b)**
- Fine-tuning on SADA for Najdi/Hijazi speech is exactly what Saudi products need; dialect words like "ضايع" and "ما ركب" are the hard cases for generic ASR.
- *Request:* a hosted ASR endpoint on Token Factory with the same OpenAI-compatible `/v1/audio/transcriptions` route. We had to build and deploy our own NeMo container and GPU endpoint; a hosted option would make voice agents a 10-minute integration.
- *Request:* a documented WebSocket streaming recipe (partials + endpointing) for the streaming checkpoint, and a reference Dockerfile with pinned NeMo/CUDA versions, to shorten cold starts and dependency debugging.
- *Request:* an Arabic TTS voice (ideally Saudi/Gulf) from NVIDIA. We found no NVIDIA TTS option for Arabic, so spoken Arabic replies use the browser's voices or an optional third-party neural voice; it's the one part of the voice loop NVIDIA couldn't cover.
- *Request:* word-level timestamps and confidence in the OpenAI-style response, so agents can ask "did you mean group 5 or 15?" when unsure.

---

## Note on prior work

MATS Agent is a new codebase built during the submission period; it builds on lessons from an earlier offline prototype. The following were significantly new for this submission:
- **NVIDIA Nemotron on Nebius Token Factory** replacing the prototype's local model: every LLM call is a runtime Token Factory call.
- **Multi-model routing** (Lightning / Nano fallback, Super, Ultra), with repair-then-escalate and a trace that shows every model and step.
- **Real-time voice:** push-to-talk, hands-free VAD, barge-in, sentence-streamed TTS, and Nemotron 3.5 ASR on a Nebius Serverless GPU endpoint.
- **Full bilingual support** (Arabic/English UI, RTL/LTR, answers in the language of the question).
- **Tavily** web search merged with database results.
- **Three safety layers** (static check, read-only file, SQLite authorizer + time budget + row cap).
- A **fully fictional mock dataset**, an offline test suite, and Docker deployment.

---

## Demo video script (under 3 minutes)

*On-screen English subtitles over every Arabic line. Screen recording of the deployed URL on a phone-width browser, with the voice audible.*

| Time | Screen | Audio / action | English subtitle |
|---|---|---|---|
| 0:00–0:12 | Title card: "MATS Agent: talk to your Hajj operations data". Then the app. | Narrator (EN): "During Hajj, supervisors move thousands of pilgrims in hours. They need answers, hands-free, in their own dialect." | — |
| 0:12–0:20 | Open the **Runtime** panel. | Narrator: "Every model here is NVIDIA Nemotron on Nebius Token Factory. Speech-to-text is Nemotron ASR on a Nebius GPU endpoint. The data is fictional." | — |
| 0:20–0:45 | Tap the mic. Ask by voice in Saudi dialect. Answer streams and is spoken; the table appears. | User: «مين ما ركب باص منى لعرفات؟» Agent (spoken): «فيه ٧ حجاج ما ركبوا باص منى لعرفات…» | "Who hasn't boarded the Mina → Arafat bus?" / "7 pilgrims haven't boarded the Mina → Arafat bus…" |
| 0:45–1:00 | Expand the **SQL** box, then **How it answered**. | Narrator: "It shows the SQL it ran, and every step: Lightning routed it, Super wrote the SQL, the guard checked it read-only, then the answer streamed, with milliseconds for each." | — |
| 1:00–1:20 | Turn on **Hands-free**. Ask a question, then a follow-up. | User: «وش وضع باصات فوج ٥ لعرفات؟» … then «وفوج ١٥؟» Trace shows the rewritten question. | "What's the status of group 5's buses to Arafat?" … "And group 15?" |
| 1:20–1:35 | **Barge-in**: while the agent is speaking, interrupt. Speech stops; the mic turns red. | User (over the agent): «طيب، كم حاج ضايع الحين؟» | "OK, how many pilgrims are missing right now?" |
| 1:35–1:55 | Switch UI to **English**. Ask a complex question (Ultra chip or voice). Trace shows Nemotron Ultra. | User (EN): "Rank the groups by boarding progress to Arafat and recommend what to do." | — |
| 1:55–2:20 | Ask the **Tavily** question. Sources appear under the answer. | User: "What's the weather in Arafat today, and which groups are still in Mina?" Agent merges web weather + DB groups. Narrator: "Live web results from Tavily, merged with the database, with sources." | — |
| 2:20–2:35 | Say «أنا مشرف فوج 14», then «وش وضع فوجي لعرفات؟». The 🧠 badge appears, then the trace shows the reasoning router resolving "my group" = 14. Then ask «وش وضع باصات فوج 5؟»: it asks «تقصد من وين لوين؟» with options. | Narrator: "It remembers you, and when it isn't sure, it asks instead of guessing." | "I supervise group 14." / "How's my group to Arafat?" / "Group 5's buses?" / "From where to where?" |
| 2:35–2:50 | Quick cut to a terminal: `pytest tests/test_guard.py -v`, all green (DROP, DELETE, `SELECT 1; DROP TABLE…` rejected). | Narrator: "And it's read-only by construction: a static check, a read-only database and a SQLite authorizer, all under test." | — |
| 2:50–2:58 | End card: GitHub URL, demo URL, team names. | Narrator: "MATS Agent, built by Mazen Njoom and Mshary Dajam." | — |

**Recording tips:** record with headphones off so barge-in is audible but keep the speaker volume moderate; run each question once beforehand so the memory is warm; burn the English subtitles into the video.
