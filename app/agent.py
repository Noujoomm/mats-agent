"""
MATS Agent pipeline. Every step emits a trace event (step, model, ms) so the UI
can show exactly how an answer was produced.

    route + rewrite + clarify? + remember? (Fast)  ->  memory (examples, lessons, user facts)
    ->  SQL (Super, repair, escalate to Ultra)  ->  guard + execute  ->  [Tavily web]
    ->  streamed spoken answer (Fast / Ultra)
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import guard
from .arabic import detect_lang, glossary_hits, glossary_text, normalize, to_ascii_digits
from .llm import Timer, strip_think
from .schema import SCHEMA_DOC

INTENTS = ("smalltalk", "data", "complex", "web", "hybrid", "clarify", "out_of_scope")
_POOL = ThreadPoolExecutor(max_workers=8)
# Voice budgets: a stalled call must fail fast and fall back, not hang the conversation.
ROUTE_TIMEOUT = 10.0
STEP_TIMEOUT = 30.0

ROUTER_PROMPT = """You route questions for MATS Agent, a voice assistant for a Hajj campaign
operations team (pilgrims, groups, buses, trips Makkah/Mina/Arafat/Muzdalifah, boarding,
incidents, supervisors, camps). Users speak Saudi Arabic dialect or English.

SCOPE: you ONLY serve pilgrim guidance and this campaign's Hajj operations: its pilgrims,
groups, buses, trips and movement between Makkah, Mina, Arafat and Muzdalifah, boarding,
missing pilgrims, incidents, camps and supervisors, plus live conditions at the holy sites
(weather, crowding/traffic, official Hajj announcements).

Classify the LAST user message into one intent:
- out_of_scope: anything else: general knowledge, coding, sports, politics, other cities'
  weather, personal advice, jokes, and religious rulings or fatwas (حكم/فتوى/هل يجوز).
- smalltalk: greetings, thanks, or questions about YOU, the assistant. A question with
  "مين"/"who" about a pilgrim, supervisor, driver or group is data, never smalltalk.
- data: a lookup/count/list answerable from the campaign database.
- complex: needs reasoning over the database: comparisons, rankings, "which is worst/best",
  recommendations, "what should I do", priorities.
- web: needs live public information about the holy sites or Hajj only (weather in Arafat/
  Mina/Makkah, crowding/traffic there, official Hajj announcements).
- hybrid: needs BOTH the database and live web info (e.g. "is it safe to move group 3 given
  the weather in Arafat?").

- clarify: a key detail is missing and neither the conversation nor the known user facts
  supply it, so any answer would be a guess. Use it ONLY when:
  * a specific group's or bus's trip/status/movement is asked without saying the route
    (from where to where). A destination alone is enough when only one route goes there:
    "لعرفات" = Mina→Arafat, "لمزدلفة" = Arafat→Muzdalifah, "لمنى" is ambiguous
    (from Makkah or from Muzdalifah);
  * it needs a specific group/bus/person but none is given or implied (e.g. "فوجي"/"my
    group" when no known fact says which group: ask "وش رقم فوجك؟" with options like
    "أنا مشرف فوج 1");
  * a term or name cannot be mapped to the campaign data.
  Never ask for questions across all groups/routes, or when one reading is clearly meant.
  For clarify, also give "ask": one short question in the user's language (e.g. "تقصد من وين
  لوين؟"), and "options": 2-4 complete standalone questions the user might mean.

Context: rewrite the last message into a standalone question in the SAME language, resolving
follow-ups, pronouns and references ("وفوج ٥؟", "and group 9?", "رقمه؟", "هم", "أول واحد",
"the second bus", "نفس الفوج") from the conversation, including the [data] shown with
earlier answers. When a reference points at rows in [data], copy their exact identifiers
(pilgrim_no, group_no, bus_no) into the standalone question. Use ASCII digits.

Known facts about this user (later facts override earlier ones). Use them ONLY when the
message refers to the user themself ("my group", "فوجي", "باصاتي"); never add them to any
other question:
{facts}

Memory: if the LAST message states a lasting fact about the user or a preference (e.g.
"أنا مشرف فوج 7", "I handle buses 120 to 125", "خلك مختصر"), put it in "remember" as one
short English sentence; otherwise "remember" is null.

Dialect glossary:
{glossary}

Examples:
Conversation: user: وش وضع باصات فوج 3 لعرفات؟ / assistant: باصات فوج 3 وصلت.
LAST: وفوج ٥؟  ->  {{"intent": "data", "standalone": "وش وضع باصات فوج 5 لعرفات؟", "meaning": "What is the status of group 5's buses to Arafat?"}}
Conversation: user: How many pilgrims in group 2 need a wheelchair? / assistant: 6.
LAST: and group 9?  ->  {{"intent": "data", "standalone": "How many pilgrims in group 9 need a wheelchair?", "meaning": "How many pilgrims in group 9 need a wheelchair?"}}
LAST: كيف الجو في الرياض؟  ->  {{"intent": "out_of_scope", "standalone": "كيف الجو في الرياض؟", "meaning": "What is the weather in Riyadh?"}}
LAST: وش حكم الحلق قبل الرمي؟  ->  {{"intent": "out_of_scope", "standalone": "وش حكم الحلق قبل الرمي؟", "meaning": "What is the ruling on shaving before stoning?"}}
LAST: كيف الجو في عرفات؟ وأي أفواج للحين في منى؟  ->  {{"intent": "hybrid", "standalone": "كيف الجو في عرفات؟ وأي أفواج للحين في منى؟", "meaning": "What is the weather in Arafat, and which groups are still in Mina?"}}
LAST: كيف الجو في عرفات؟  ->  {{"intent": "web", "standalone": "كيف الجو في عرفات؟", "meaning": "What is the weather in Arafat?"}}
LAST: وش وضع باصات فوج 5؟  ->  {{"intent": "clarify", "standalone": "وش وضع باصات فوج 5؟", "meaning": "What is the status of group 5's buses?", "ask": "تقصد رحلة فوج 5 من وين لوين؟", "options": ["وش وضع باصات فوج 5 من منى لعرفات؟", "وش وضع باصات فوج 5 من عرفات لمزدلفة؟", "وش وضع باصات فوج 5 من مزدلفة لمنى؟"]}}
Conversation: assistant: 7 pilgrims have not boarded ... [data: group_no | pilgrim_no | name_en | phone; 1 | P-00026 | Abdullah Khalid Al-Namoothaji | +966-500-555-1026; ...]
LAST: وش رقم أول واحد؟  ->  {{"intent": "data", "standalone": "وش رقم جوال الحاج P-00026؟", "meaning": "What is the phone number of pilgrim P-00026?"}}
LAST (same conversation): ومين مشرف فوجه؟  ->  {{"intent": "data", "standalone": "مين مشرف فوج 1؟", "meaning": "Who is the supervisor of group 1?"}}
LAST: أنا مشرف فوج 2  ->  {{"intent": "smalltalk", "standalone": "أنا مشرف فوج 2", "meaning": "I am the supervisor of group 2.", "remember": "The user supervises group 2."}}
Known fact "The user supervises group 2." / LAST: وش وضع فوجي لعرفات؟  ->  {{"intent": "data", "standalone": "وش وضع باصات فوج 2 لعرفات؟", "meaning": "What is the status of group 2's buses to Arafat?"}}
(Always use the user's ACTUAL known facts, never the numbers in these examples.)

Also give "meaning": a precise English translation of the standalone question (keep negations
like "not boarded" explicit).

Reply with JSON only: {{"intent": "...", "standalone": "...", "meaning": "...", "ask": null, "options": [], "remember": null}}"""

SQL_PROMPT = """You write one SQLite SELECT query that answers the question.

{schema}
Simulated current time: {now}

Saudi dialect glossary:
{glossary}

Return ONLY the SQL, no explanation, no markdown fences, no comments. Single statement,
SELECT or WITH. Keep it compact: compute numbers, don't write recommendation text in SQL.
Prefer readable column aliases in English. Limit lists to 50 rows unless asked otherwise."""

ANSWER_PROMPT = """You are MATS Agent, the voice assistant of a Hajj campaign operations room,
dedicated only to pilgrim guidance and campaign operations. Your reply is SPOKEN aloud. Rules:
- {lang_rule}
- At most 3 short sentences. No markdown, no bullet points, no emojis, no SQL, no tables.
- Use only the facts given below. Never invent numbers or names. If the database result is
  empty, say nothing matched. Never say the data is missing information: the rows answer
  the question. If web results don't contain what was asked, say you couldn't find live
  information on it and suggest following the official Hajj channels.
- Use ONE language only, never mix Arabic and English.
- Say numbers as digits. If the result is a single number, just say it: never add names or
  numbers that are not in the rows. If the rows list several items, say how many there are,
  then name at most 3 of them exactly as written in the rows.
- Refer to a bus by its bus_no (e.g. "bus 130"), never by its plate. Never read out internal
  ids; name pilgrims by name (or pilgrim_no) and groups by group number.
- If web sources are given, attribute them briefly (e.g. "according to ...").
- The data is from a fictional demo campaign; the current simulated time is {now}."""

COMPLEX_RULE = ("This is an analysis question: compare, rank, and end with one concrete "
                "recommendation for the operations team.")

SMALLTALK_PROMPT = """You are MATS Agent (مساعد ماتس), a friendly bilingual voice assistant
dedicated ONLY to pilgrim guidance and Hajj campaign operations (fictional demo data). If asked
who you are, say you are MATS Agent, the campaign's operations assistant; never claim another
name or creator. Do not answer anything outside pilgrim guidance and campaign operations;
politely steer back. {lang_rule} Reply in at most 2 short sentences, no markdown. If useful,
suggest asking about buses, missing pilgrims, groups or the weather in Arafat."""

LANG_RULE = {
    "ar": "Answer in Saudi white dialect Arabic (لهجة بيضاء), natural and polite.",
    "en": "Answer in clear, simple English.",
}

FAIL_MSG = {
    "ar": "ما قدرت أطلع جواب أكيد من البيانات هالمرة. جرّب تعيد صياغة السؤال.",
    "en": "I couldn't get a reliable answer from the data this time. Please try rephrasing.",
}
ASK_WHO = {   # "my group" with nothing remembered: never guess which group
    "ar": "ما أعرف فوجك للحين. وش رقم فوجك؟ قل مثلًا: «أنا مشرف فوج 7».",
    "en": "I don't know your group yet. Which group is it? Say, for example: \u201cI supervise group 7\u201d.",
}
NO_WEB_MSG = {
    "ar": "البحث في الإنترنت غير مفعّل في هذا العرض.",
    "en": "Web search is not enabled in this demo.",
}

_WEB_HINT = re.compile(r"weather|temperature|news|announce|traffic|forecast|"
                       r"طقس|الجو|حرار|درج|اخبار|أخبار|زحم|اعلان|إعلان|تعميم", re.I)
_COMPLEX_HINT = re.compile(r"compare|rank|worst|best|recommend|should|priorit|"
                           r"قارن|مقارن|اسوا|أسوأ|افضل|أفضل|ترتيب|رتب|انصح|تنصح|توصي|اولوي|أولوي", re.I)


# Signals that routing needs reasoning (resolve a reference, use a remembered fact, or
# decide whether to ask): the reasoning router handles these, the fast one the rest.
_REF = re.compile(r"(فوجي|باصي|باصاتي|حجاجي|مخيمي|فوجه|فوجها|فوجهم|باصه|رقمه|رقمها|جواله|جوالها|"
                  r"مشرفه|مشرفها|مشرفهم|اول واحد|أول واحد|ثاني واحد|آخر واحد|اخر واحد|نفس|هذولا|"
                  r"هذا الفوج|هالفوج|هالباص|\bهم\b|\bmy\b|\bhis\b|\bher\b|\btheir\b|\bthem\b|"
                  r"\bfirst one\b|\bsecond one\b|\blast one\b|\bsame\b)", re.I)
_STATUS = re.compile(r"(وضع|حاله|حالة|status|where is|where are)", re.I)
_UNIT = re.compile(r"(باص|فوج|\bbus|\bgroup)", re.I)
_PLACE = re.compile(r"(عرفات|منى|مزدلف|مكه|مكة|arafat|mina|muzdalif|makkah|mecca)", re.I)


_SELF = re.compile(r"(فوجي|باصي|باصاتي|حجاجي|مخيمي|\bmy\b)", re.I)


# Live web search is only for the holy sites / Hajj: a hard check on top of the router.
_HAJJ = re.compile(r"(عرف|منى|مزدلف|مكه|مكة|المشاعر|الحرم|جمرات|الجمرات|الحج|حج|حاج|حجاج|"
                   r"تفويج|فوج|افواج|أفواج|مخيم|arafat|mina|muzdalif|makkah|mecca|haram|"
                   r"jamarat|hajj|pilgrim|holy site)", re.I)

_CAMPAIGN = re.compile(r"(فوج|افواج|أفواج|باص|حافل|حاج|حجاج|مشرف|\bgroups?\b|\bbus(es)?\b|"
                       r"\bpilgrims?\b|\bsupervisors?\b)", re.I)

OUT_OF_SCOPE = {
    "ar": "أنا مخصّص لإرشاد الحجاج وعمليات الحملة بس: الأفواج والباصات والتفويج والمفقودين "
          "والبلاغات، وأحوال المشاعر مثل الطقس والزحمة. اسألني مثلًا: مين ما ركب باص منى لعرفات؟",
    "en": "I'm built only for pilgrim guidance and campaign operations: groups, buses, movement, "
          "missing pilgrims, incidents, and conditions at the holy sites like weather and crowding. "
          "Try: who hasn't boarded the Mina to Arafat bus?",
}
RULING = re.compile(r"(حكم|فتوى|فتوي|يجوز|حلال|حرام|ruling|fatwa|is it permissible|halal|haram\b)", re.I)
RULING_MSG = {
    "ar": "أسئلة الأحكام الشرعية والفتوى أحيلها لمرشد الحملة الشرعي أو الجهات الرسمية، "
          "عشان تاخذ الجواب من أهل العلم. أنا أساعدك في الأفواج والباصات والتفويج.",
    "en": "For religious rulings, please ask the campaign's religious guide or the official "
          "authorities. I can help with groups, buses and movement.",
}


# "Who are you?" has one right answer; small models tend to introduce the base model instead.
IDENTITY = re.compile(r"(من انت|من أنت|مين انت|مين أنت|وش اسمك|ايش اسمك|عرفني بنفسك|عرّفني بنفسك|"
                      r"وش تسوي|ايش تسوي|who are you|what are you|your name|what can you do)", re.I)
INTRO = {
    "ar": "أنا مساعد ماتس، مساعد عمليات الحملة لإرشاد الحجاج. أعطيك وضع الأفواج والباصات "
          "والتفويج والمفقودين والبلاغات، وأحوال المشاعر، وأقدر أتذكر فوجك وأتعلم من أخطائي.",
    "en": "I'm MATS Agent, the campaign's operations assistant for pilgrim guidance. I can tell "
          "you about groups, buses, movement, missing pilgrims, incidents and conditions at the "
          "holy sites, and I remember your group and learn from my mistakes.",
}


def needs_reasoning(q, history, facts):
    if history and str(history[-1].get("context") or "").startswith("clarify:"):
        return "answer to a clarifying question"
    if _SELF.search(q):
        return "refers to the user" + ("" if facts else " (nothing remembered yet)")
    if _REF.search(q) and (history or facts):
        return "reference"
    if _STATUS.search(q) and _UNIT.search(q) and not _PLACE.search(q):
        return "maybe ambiguous"
    return ""


def trace(step, ms, model=None, detail="", status="ok"):
    return {"type": "trace", "step": step, "model": model, "ms": ms,
            "detail": detail, "status": status}


def extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = m.group(1) if m else text
    m = re.search(r"\b(with|select)\b", sql, re.I)
    if m:
        sql = sql[m.start():]
    return sql.strip().rstrip(";").strip()


def parse_route(text, question):
    """Router JSON -> dict(intent, standalone, meaning, ask, options, remember, how)."""
    try:
        m = re.search(r"\{.*\}", text, re.S)
        d = json.loads(m.group(0))
        intent = str(d.get("intent", "")).lower().strip()
        r = {"intent": intent, "standalone": to_ascii_digits(str(d.get("standalone") or question).strip()),
             "meaning": str(d.get("meaning") or "").strip(), "how": "llm",
             "ask": str(d.get("ask") or "").strip(),
             "options": [str(o).strip() for o in (d.get("options") or []) if str(o).strip()][:4],
             "remember": str(d.get("remember") or "").strip()}
        if r["remember"].lower() in ("null", "none"):
            r["remember"] = ""
        if intent == "clarify" and not (r["ask"] and r["options"]):
            r["intent"] = "data"                 # a clarification needs a question and options
        if r["intent"] in INTENTS:
            return r
    except (AttributeError, ValueError, TypeError):
        pass
    return {"intent": heuristic_intent(question), "standalone": question, "meaning": "",
            "how": "heuristic", "ask": "", "options": [], "remember": ""}


def heuristic_intent(q):
    if RULING.search(q):
        return "out_of_scope"
    web, cx = bool(_WEB_HINT.search(q)), bool(_COMPLEX_HINT.search(q))
    if web and (cx or re.search(r"فوج|group|باص|bus|حاج|pilgrim", q, re.I)):
        return "hybrid"
    return "web" if web else "complex" if cx else "data"


def data_context(columns, rows, limit=4):
    """Compact view of a result, sent back with history so follow-ups can refer to it."""
    lines = [" | ".join(columns)] + [" | ".join("" if v is None else str(v) for v in r)
                                     for r in rows[:limit]]
    more = f"; +{len(rows) - limit} more" if len(rows) > limit else ""
    return (f"{len(rows)} rows: " + "; ".join(lines) + more)[:500]


def rows_digest(columns, rows, limit=30):
    lines = [" | ".join(columns)]
    for r in rows[:limit]:
        lines.append(" | ".join("" if v is None else str(v) for v in r))
    if len(rows) > limit:
        lines.append(f"... ({len(rows) - limit} more rows)")
    return "\n".join(lines)


class Agent:
    def __init__(self, llm, settings, memory, web=None):
        self.llm = llm
        self.s = settings
        self.memory = memory
        self.web = web
        self._now = None

    @property
    def now(self):
        if self._now is None:
            conn = guard.connect(self.s.db_path)
            try:
                self._now = conn.execute("SELECT simulated_now FROM campaign").fetchone()[0]
            finally:
                conn.close()
        return self._now

    def _model(self, requested):
        return self.llm.last_model or requested

    # ───────────────────────── steps ─────────────────────────
    def route(self, question, history, facts=(), model=None):
        # History goes in as a transcript, not as chat turns: given real turns, the
        # fast model continues the conversation instead of classifying it.
        turns = [f"{h['role']}: {str(h['content'])[:400]}"
                 + (f" [data: {h['context']}]" if h.get("context") else "")
                 for h in history[-8:]
                 if h.get("role") in ("user", "assistant") and h.get("content")]
        user = (("Conversation so far:\n" + "\n".join(turns) + "\n\n") if turns else "")
        user += (f"LAST user message: {question}\n\n"
                 'Do not answer it. Reply with JSON only: '
                 '{"intent": "...", "standalone": "...", "meaning": "...", '
                 '"ask": null, "options": [], "remember": null}')
        known = "\n".join(f"- {f}" for f in facts) or "(none)"
        msgs = [{"role": "system", "content": ROUTER_PROMPT.format(glossary=glossary_text(),
                                                                    facts=known)},
                {"role": "user", "content": user}]
        return self.llm.complete(model or self.s.model_fast, msgs, temperature=0.0, max_tokens=320,
                                 timeout=ROUTE_TIMEOUT)

    def gen_sql(self, model, question, examples, failed=None, hybrid=False, lessons=()):
        hits = glossary_hits(question)
        user = ""
        if examples:
            user += "Similar questions that worked:\n" + "\n\n".join(
                f"Q: {e['question']}\nSQL: {e['sql']}" for e in examples) + "\n\n"
        if lessons:
            user += "Lessons from past mistakes on similar questions (do not repeat them):\n"
            for x in lessons:
                user += f"- Q: {x['question']}\n  Wrong SQL: {x['bad_sql']}\n  Why: {x['error']}\n"
                if x.get("fixed_sql"):
                    user += f"  Correct SQL: {x['fixed_sql']}\n"
            user += "\n"
        if hits:
            user += "Dialect terms in this question: " + "; ".join(
                f"{k} = {v}" for k, v in hits) + "\n\n"
        user += f"Question: {question}"
        if hybrid:
            user += ("\n\nThe database has no weather, news or traffic data; a web search covers "
                     "that part. Write SQL ONLY for the part about the campaign's own data, and "
                     "never put literal or made-up values (like a weather word) in the SELECT.")
        msgs = [{"role": "system", "content": SQL_PROMPT.format(
                    schema=SCHEMA_DOC, now=self.now, glossary=glossary_text())},
                {"role": "user", "content": user}]
        if failed and failed[0]:
            msgs += [{"role": "assistant", "content": failed[0]},
                     {"role": "user", "content": f"That query failed with: {failed[1]}\n"
                                                 "Fix it. Return only the corrected SQL."}]
        return extract_sql(self.llm.complete(model, msgs, temperature=0.0, max_tokens=1500,
                                             timeout=STEP_TIMEOUT))

    def sql_loop(self, question, examples, complex_, hybrid=False, lessons=()):
        """Yields events; returns (sql, result) via StopIteration value."""
        if complex_:
            plan = [(self.s.model_complex, "generate"), (self.s.model_complex, "repair"),
                    (self.s.model_complex, "repair")]
        else:
            plan = [(self.s.model_sql, "generate"), (self.s.model_sql, "repair"),
                    (self.s.model_complex, "escalate")]
        failed = None
        conn = guard.connect(self.s.db_path)
        try:
            for i, (model, phase) in enumerate(plan, 1):
                t = Timer()
                try:
                    sql = self.gen_sql(model, question, examples, failed, hybrid, lessons)
                except Exception as e:                       # noqa: BLE001
                    yield trace("sql", t.ms, model, f"{phase}: model error: {e}", "error")
                    failed = ("", f"model error: {e}")
                    continue
                yield trace("sql", t.ms, self._model(model), f"attempt {i} ({phase})")
                yield {"type": "sql", "sql": sql, "attempt": i, "model": self._model(model)}
                t = Timer()
                try:
                    res = guard.run(conn, sql, self.s.max_rows, self.s.query_timeout)
                except Exception as e:                       # noqa: BLE001
                    yield trace("guard", t.ms, None, f"rejected/failed: {e}", "error")
                    failed = (sql, str(e))
                    continue
                yield trace("guard", t.ms, None,
                            f"read-only OK, {len(res['rows'])} rows"
                            + (" (capped)" if res["truncated"] else ""))
                if failed and failed[0]:
                    # It recovered from a mistake: keep the lesson for similar questions.
                    try:
                        self.memory.add_lesson(question, failed[0], failed[1], sql, "repair")
                        yield trace("learn", 0, None, f"saved a lesson: {failed[1][:90]}")
                    except Exception:                        # noqa: BLE001
                        pass
                return sql, res
        finally:
            conn.close()
        return None, None

    # ───────────────────────── main ─────────────────────────
    def run(self, question, history=None, ui_lang="ar", client_id=None):
        history = history or []
        total = Timer()
        q = to_ascii_digits((question or "").strip())
        lang = detect_lang(q, ui_lang)
        user_facts = self.memory.facts(client_id) if client_id else []

        if IDENTITY.search(q) and len(q.split()) <= 6:
            yield trace("route", 0, None, "intent=smalltalk · introduces itself")
            yield {"type": "intent", "intent": "smalltalk", "standalone": q, "lang": lang}
            yield {"type": "token", "text": INTRO[lang]}
            yield self._done(INTRO[lang], "smalltalk", q, lang, None, total)
            return

        if _SELF.search(q) and not user_facts and not re.search(r"\d", q):
            yield trace("route", 0, None, "refers to the user, but nothing is remembered yet")
            yield {"type": "intent", "intent": "clarify", "standalone": q, "lang": lang}
            yield {"type": "clarify", "ask": ASK_WHO[lang], "options": []}
            yield {"type": "token", "text": ASK_WHO[lang]}
            yield trace("clarify", 0, None, "asked instead of guessing the user's group")
            yield self._done(ASK_WHO[lang], "clarify", q, lang, None, total, "clarify: which group is yours")
            return

        t = Timer()
        why = needs_reasoning(q, history, user_facts)
        router = self.s.model_router_reasoning if why else self.s.model_fast
        try:
            try:
                r = parse_route(self.route(q, history, user_facts, router), q)
            except Exception as e:                           # noqa: BLE001
                if router == self.s.model_fast:
                    raise
                why, router = f"{router.split('/')[-1]} unavailable ({type(e).__name__}), used fast", \
                    self.s.model_fast
                r = parse_route(self.route(q, history, user_facts, router), q)
            if r["intent"] == "clarify" and router == self.s.model_fast and "unavailable" not in why:
                # The fast model wants to ask: let the reasoning model confirm it's needed.
                why, router = "double-check clarification", self.s.model_router_reasoning
                r = parse_route(self.route(q, history, user_facts, router), q)
        except Exception as e:                               # noqa: BLE001
            r = parse_route("", q)
            r["how"] = f"heuristic ({e})"
        intent, standalone, meaning = r["intent"], r["standalone"], r["meaning"]
        if intent == "web" and _CAMPAIGN.search(f"{q} {meaning}"):
            intent = "hybrid"         # it also asks about our own groups/buses/pilgrims
        if intent in ("web", "hybrid") and not _HAJJ.search(f"{q} {standalone} {meaning}"):
            intent, r["how"] = "out_of_scope", r["how"] + " · web limited to the holy sites"
        yield trace("route", t.ms, self._model(router) if r["how"] == "llm" else None,
                    f"intent={intent}" + (f" · rewritten: {standalone}" if standalone != q else "")
                    + (f" · reasoning router ({why})" if why else "")
                    + (f" · used {len(user_facts)} remembered facts" if user_facts else "")
                    + ("" if r["how"] == "llm" else f" · {r['how']}"))
        yield {"type": "intent", "intent": intent, "standalone": standalone, "lang": lang}

        known = {normalize(f) for f in user_facts}
        if r["remember"] and client_id and normalize(r["remember"]) not in known:
            try:
                self.memory.add_fact(client_id, r["remember"])
                user_facts = self.memory.facts(client_id)
                yield trace("remember", 0, None, r["remember"])
                yield {"type": "remembered", "fact": r["remember"]}
            except Exception:                                # noqa: BLE001
                pass

        if intent == "out_of_scope":
            msg = (RULING_MSG if RULING.search(f"{q} {meaning}") else OUT_OF_SCOPE)[lang]
            yield {"type": "token", "text": msg}
            yield trace("scope", 0, None, "outside pilgrim guidance & campaign operations: declined")
            yield self._done(msg, intent, standalone, lang, None, total)
            return

        if intent == "clarify":
            yield {"type": "clarify", "ask": r["ask"], "options": r["options"]}
            yield {"type": "token", "text": r["ask"]}
            yield trace("clarify", 0, None, f"asked instead of guessing · {len(r['options'])} options")
            yield self._done(r["ask"], intent, standalone, lang, None, total,
                             "clarify: " + " | ".join(r["options"]))
            return

        sql = res = web = context = None
        # Start the web search first so it runs in parallel with the SQL steps.
        web_job = None
        if intent in ("web", "hybrid") and self.web is not None and self.web.enabled:
            web_t = Timer()
            web_job = _POOL.submit(self.web.search, meaning or standalone)
        if intent in ("data", "complex", "hybrid"):
            t = Timer()
            examples = self.memory.similar(standalone)
            lessons = self.memory.lessons(standalone)
            yield trace("memory", t.ms, None,
                        f"{len(examples)} similar examples"
                        + (f" (best {examples[0]['score']})" if examples else "")
                        + (f" · {len(lessons)} lessons from past mistakes" if lessons else ""))
            sql, res = yield from self.sql_loop(standalone, examples,
                                                complex_=(intent == "complex"),
                                                hybrid=(intent == "hybrid"), lessons=lessons)
            if res is not None:
                context = data_context(res["columns"], res["rows"])
                yield {"type": "table", "columns": res["columns"], "rows": res["rows"],
                       "truncated": res["truncated"], "sql": sql}
                try:
                    if intent != "hybrid":    # web+DB success doesn't prove the SQL is right
                        self.memory.remember(standalone, sql)
                except Exception:                            # noqa: BLE001
                    pass

        if intent in ("web", "hybrid"):
            if web_job is not None:
                try:
                    web = web_job.result(timeout=20)
                    yield trace("web", web_t.ms, "Tavily",
                                f"{len(web['results'])} sources (in parallel with SQL)")
                    yield {"type": "sources", "sources": [
                        {"title": r["title"], "url": r["url"]} for r in web["results"]]}
                except Exception as e:                       # noqa: BLE001
                    yield trace("web", web_t.ms, "Tavily", f"failed: {e}", "error")
            else:
                yield trace("web", 0, "Tavily", "disabled (no TAVILY_API_KEY)", "skipped")

        # ── answer ──
        # Web sources are mostly English: the fast model copies them verbatim into Arabic
        # answers, so web/hybrid answers go to the stronger reasoning model.
        answer_model = (self.s.model_complex if intent == "complex" else
                        self.s.model_router_reasoning if intent in ("web", "hybrid") else
                        self.s.model_answer)
        if intent == "smalltalk":
            system = SMALLTALK_PROMPT.format(lang_rule=LANG_RULE[lang])
            if r["remember"]:
                system += " The user just told you something to remember; confirm briefly that you will."
            msgs = [{"role": "system", "content": system}]
            msgs += [{"role": h["role"], "content": str(h["content"])[:400]}
                     for h in history[-4:] if h.get("role") in ("user", "assistant")]
            msgs.append({"role": "user", "content": q})
        elif res is None and web is None:
            msg = NO_WEB_MSG[lang] if intent == "web" else FAIL_MSG[lang]
            yield {"type": "token", "text": msg}
            yield trace("answer", 0, None, "no data to answer from", "error")
            yield self._done(msg, intent, standalone, lang, sql, total)
            return
        else:
            facts = []
            if res is not None:
                facts.append("This SQL query already applied every filter in the question, so its "
                             "rows ARE the complete answer (an empty result means nothing matched):\n"
                             + sql + f"\n\nResult ({len(res['rows'])} rows"
                             + (", capped" if res["truncated"] else "") + "):\n"
                             + rows_digest(res["columns"], res["rows"]))
            if web is not None:
                facts.append("Web results (Tavily):\n" + (web["answer"] or "") + "\n" + "\n".join(
                    f"- {r['title']} ({r['url']}): {r['content'][:300]}" for r in web["results"]))
            system = ANSWER_PROMPT.format(lang_rule=LANG_RULE[lang], now=self.now)
            if intent == "complex":
                system += "\n- " + COMPLEX_RULE
            if user_facts:
                system += ("\n- About this user (for tone only; never use it to narrow or change "
                           "the data): " + " ".join(user_facts))
            msgs = [{"role": "system", "content": system},
                    {"role": "user", "content": "\n\n".join(facts)
                     + f"\n\nQuestion from the operations team: {standalone}\n"
                     + (f"Meaning: {meaning}\n" if meaning else "")
                     + "".join(f"Note: {k} = {v}\n" for k, v in glossary_hits(standalone))
                     + f"Write the spoken answer to this question from the data above. {LANG_RULE[lang]}"
                     + (" Translate anything from English sources into Arabic; no English words."
                        if lang == "ar" else "")
                     + " Max 3 short sentences, no markdown."}]

        t = Timer()
        parts, first = [], None
        try:
            for piece in self.llm.stream(answer_model, msgs, temperature=0.3, max_tokens=350,
                                         timeout=STEP_TIMEOUT):
                if first is None:
                    first = t.ms
                parts.append(piece)
                yield {"type": "token", "text": piece}
        except Exception as e:                               # noqa: BLE001
            msg = FAIL_MSG[lang]
            parts = [msg]
            yield {"type": "token", "text": msg}
            yield trace("answer", t.ms, answer_model, f"stream failed: {e}", "error")
        else:
            yield trace("answer", t.ms, self._model(answer_model),
                        f"streamed, first token {first or 0} ms")
        yield self._done(strip_think("".join(parts)), intent, standalone, lang, sql, total, context)

    def _done(self, answer, intent, standalone, lang, sql, total, context=None):
        return {"type": "done", "answer": answer, "intent": intent, "question": standalone,
                "lang": lang, "sql": sql, "total_ms": total.ms, "context": context}
