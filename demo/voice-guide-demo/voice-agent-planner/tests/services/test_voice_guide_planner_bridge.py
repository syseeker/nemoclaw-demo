"""Tests for the Jewel voice-guide planner bridge models."""

from apps.jewel_voice_guide.planner_bridge import PlannerBridge, PlannerQueryResponse


def test_normalizes_numeric_confidence_to_label():
    """Numeric planner confidence should be accepted and normalized."""
    response = PlannerQueryResponse(
        request_id="req-1",
        status="ok",
        spoken_response="ok",
        confidence=0.9,
    )
    assert response.confidence == "high"


def test_planner_bridge_defaults_to_main_agent():
    """The bridge should default to the supported main agent path."""
    bridge = PlannerBridge(sandbox_name="clawpit")
    assert bridge.agent_name == "main"
