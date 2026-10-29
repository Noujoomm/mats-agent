"""
Arabic handling: normalization (ported from Bari), digits, Saudi dialect glossary,
and language detection.
"""
import re
import unicodedata

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_SPACES = re.compile(r"\s+")
_UNIFY = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ة": "ه",
    "ى": "ي", "ئ": "ي",
    "ؤ": "و",
    "گ": "ك",
})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_CHAR = re.compile(r"[؀-ۿ]")
_LATIN_CHAR = re.compile(r"[A-Za-z]")


def to_ascii_digits(text: str) -> str:
    return (text or "").translate(_DIGITS)


def normalize(text: str) -> str:
    """Unify alef/ta-marbuta/ya forms, drop diacritics + tatweel, ASCII digits, lowercase."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = _DIACRITICS.sub("", s)
    s = s.translate(_UNIFY).translate(_DIGITS)
    s = re.sub(r"[^\w\s]", " ", s)
    return _SPACES.sub(" ", s).strip().lower()


def detect_lang(text: str, default: str = "ar") -> str:
    ar = len(_ARABIC_CHAR.findall(text or ""))
    en = len(_LATIN_CHAR.findall(text or ""))
    if ar == 0 and en == 0:
        return default
    return "ar" if ar >= en else "en"


# Saudi (Najdi/Hijazi/Gulf) dialect -> meaning in this domain.
GLOSSARY = [
    ("ما ركب", "not boarded (no boarding scan on the trip)"),
    ("ما ركبوا", "not boarded"),
    ("ركب", "boarded (has a boarding scan)"),
    ("ضايع", "missing / lost (pilgrims.status = 'missing' or lost_person incident)"),
    ("ضايعين", "missing pilgrims"),
    ("تايه", "lost person"),
    ("مفقود", "missing"),
    ("فوج", "group (groups.group_no)"),
    ("افواج", "groups"),
    ("باص", "bus"),
    ("باصات", "buses"),
    ("حافله", "bus"),
    ("مشرف", "supervisor"),
    ("وش", "what"),
    ("ايش", "what"),
    ("وين", "where"),
    ("فين", "where"),
    ("كم واحد", "how many people"),
    ("متى", "when"),
    ("ليش", "why"),
    ("توه", "just now / still"),
    ("للحين", "still / until now"),
    ("وصلوا", "arrived (trip status = 'arrived')"),
    ("طلعوا", "departed (trip status = 'departed')"),
    ("متاخر", "delayed (trip status = 'delayed')"),
    ("مخيم", "camp"),
    ("بلاغ", "incident report"),
    ("بلاغات", "incidents"),
    ("كرسي", "wheelchair (pilgrims.needs_wheelchair = 1)"),
    ("حجاج", "pilgrims"),
    ("الحين", "now (use campaign.simulated_now)"),
    ("زحمه", "traffic"),
    ("الجو", "weather"),
]

_GLOSS_NORM = [(normalize(k), k, v) for k, v in GLOSSARY]


def glossary_text() -> str:
    return "\n".join(f"- {k} = {v}" for k, v in GLOSSARY)


def glossary_hits(question: str) -> list:
    """Dialect terms present in the question (normalized match on word boundaries)."""
    q = f" {normalize(question)} "
    hits = []
    for nk, k, v in _GLOSS_NORM:
        if f" {nk} " in q and k not in [h[0] for h in hits]:
            hits.append((k, v))
    return hits
