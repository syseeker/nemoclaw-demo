"""Helper tests for the Jewel voice-guide orchestrator."""

from apps.jewel_voice_guide.orchestrator import PHOTO_REQUEST_RESPONSE, VoiceGuideOrchestratorService
from apps.jewel_voice_guide.router import route_turn


def _svc() -> VoiceGuideOrchestratorService:
    return object.__new__(VoiceGuideOrchestratorService)


def test_classifies_additive_planner_update():
    """Additive transcript refinements should be queued, not cancelled."""
    svc = _svc()
    old = "i land at 2 p.m. and want jewel marina bay sunset"
    new = "i land at 2 p.m. and want jewel marina bay sunset then supper plan it for me"
    assert svc._classify_planner_update(old, new) == "additive"


def test_extracts_repaired_text_from_json_response():
    """LLM transcript repair parser should recover normalized text from JSON."""
    svc = _svc()
    content = (
        '{"normalized_text":"Anyway I land at 2 p.m. and want Jewel Marina Bay '
        'sunset then supper plan it for me"}'
    )
    repaired = svc._extract_repaired_text(content)
    assert repaired == "anyway i land at 2 p.m. and want jewel marina bay sunset then supper plan it for me"


def test_detects_visual_request():
    """Photo-like requests should trigger the voice-friendly capability response."""
    svc = _svc()
    assert svc._is_visual_request("show me a photo of that store")
    assert PHOTO_REQUEST_RESPONSE.startswith("I can't show photos")


def test_semantically_complete_planner_candidate():
    """A multi-stop timed utterance should be eligible for debounced planner launch."""
    svc = _svc()
    utterance = "I land at 2pm and want Jewel, Marina Bay sunset, then supper plan it for me"
    decision = route_turn(utterance, {"planner_available": True, "lookup_available": True})
    assert svc._is_semantically_complete_planner(utterance, decision)


def test_low_information_fragment_is_ignored():
    """Tiny ASR fragments should not trigger normal direct replies."""
    svc = _svc()
    assert svc._is_low_information_transcript("he")
    assert not svc._is_low_information_transcript("hello")


def test_prefers_llm_repair_for_lookup_and_planner():
    """Lookup and planner candidates should use the LLM normalizer."""
    svc = _svc()
    lookup_decision = route_turn(
        "find dessert and a toy shop near rainbow tex for my kids",
        {"planner_available": True, "lookup_available": True},
    )
    planner_decision = route_turn(
        "i land at 02:00 p.m. and one jewel marina bay sunset",
        {"planner_available": True, "lookup_available": True},
    )
    assert svc._should_llm_repair("find dessert and a toy shop near rainbow tex for my kids", lookup_decision)
    assert svc._should_llm_repair("i land at 02:00 p.m. and one jewel marina bay sunset", planner_decision)
