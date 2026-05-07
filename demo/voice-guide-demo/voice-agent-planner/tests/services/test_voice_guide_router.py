"""Routing tests for the Jewel voice-guide orchestrator."""

from apps.jewel_voice_guide.router import route_turn


def test_routes_broad_overview_to_direct():
    """Broad overview requests should stay on the direct path."""
    decision = route_turn(
        "What can I do at Jewel for two hours?",
        {"planner_available": True, "lookup_available": True},
    )
    assert decision.route == "direct"
    assert decision.reason == "broad_overview"


def test_routes_jewel_local_question_to_lookup():
    """Local Jewel factual requests should use the lookup path."""
    decision = route_turn(
        "Find dessert and a toy shop near Rain Vortex for my kids.",
        {"planner_available": True, "lookup_available": True},
    )
    assert decision.route == "lookup"
    assert decision.reason == "jewel_local_factual_request"


def test_routes_cross_destination_plan_to_planner():
    """Cross-destination itinerary requests should use the planner path."""
    decision = route_turn(
        "I land at 2pm and want Jewel, Marina Bay sunset, then supper.",
        {"planner_available": True, "lookup_available": True},
    )
    assert decision.route == "planner"
    assert decision.reason == "multi_step_or_live_data_request"
