from app.arabic import detect_lang, glossary_hits, normalize, to_ascii_digits
from app.llm import ThinkFilter, strip_think


def test_normalize_variants():
    assert normalize("أحمد") == normalize("احمد")
    assert normalize("فاطمة") == normalize("فاطمه")
    assert normalize("مستشفى") == normalize("مستشفي")
    assert normalize("فوج ١٢") == "فوج 12"
    assert to_ascii_digits("وفوج ٥؟") == "وفوج 5؟"


def test_detect_lang():
    assert detect_lang("كم حاج ضايع؟") == "ar"
    assert detect_lang("How many buses?") == "en"
    assert detect_lang("123", default="en") == "en"


def test_glossary_hits():
    terms = [k for k, _ in glossary_hits("مين ما ركب الباص من فوج 3؟")]
    assert "ما ركب" in terms and "فوج" in terms


def test_strip_think():
    assert strip_think("<think>plan</think>SELECT 1") == "SELECT 1"
    assert strip_think("reasoning...</think>\nSELECT 1") == "SELECT 1"
    assert strip_think("<think>never closed") == ""


def test_think_filter_across_chunks():
    f = ThinkFilter()
    chunks = ["<th", "ink>hidden ", "reasoning</thi", "nk>  Seven", " pilgrims <", "think>x</think>left."]
    out = "".join(f.feed(c) for c in chunks) + f.flush()
    assert out == "Seven pilgrims left."


def test_think_filter_orphan_close():
    f = ThinkFilter()
    out = "".join(f.feed(c) for c in ["I should count", "</think>", "Answer"]) + f.flush()
    assert out == "Answer"
