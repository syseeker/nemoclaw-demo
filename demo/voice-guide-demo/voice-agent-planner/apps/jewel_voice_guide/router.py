"""Routing rules for the Jewel voice-guide Phase 1 demo."""

from __future__ import annotations

import re
from dataclasses import dataclass

GREETING_PATTERNS = [
    r"\bhi\b",
    r"\bhello\b",
    r"\bhey\b",
    r"\bgood morning\b",
    r"\bgood afternoon\b",
    r"\bgood evening\b",
]

OVERVIEW_PATTERNS = [
    r"\bwhat is jewel\b",
    r"\bwhat can i do\b",
    r"\bcan you tell me about jewel\b",
    r"\bis this a good place for families\b",
    r"\bis jewel good for families\b",
]

JEWEL_TERMS = [
    "jewel",
    "rain vortex",
    "forest valley",
    "canopy park",
    "airport mall",
]

LOOKUP_TERMS = [
    "dessert",
    "toy",
    "kids",
    "family",
    "store",
    "shop",
    "restaurant",
    "food",
    "attraction",
    "inside jewel",
]

LIVE_DATA_TERMS = [
    "weather",
    "open now",
    "opening hours",
    "current hours",
    "traffic",
    "transit",
    "delay",
    "closure",
    "live",
    "today",
    "tonight",
]

PLANNING_TERMS = [
    "plan",
    "itinerary",
    "route",
    "schedule",
    "best way",
    "then",
    "after",
    "before",
    "land at",
]

CROSS_DESTINATION_TERMS = [
    "marina bay",
    "sentosa",
    "gardens by the bay",
    "city",
    "singapore",
    "downtown",
]


@dataclass(slots=True)
class RouteDecision:
    """Represents the chosen response path for a user turn."""

    route: str
    reason: str
    confidence: str
    features: dict[str, bool]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _has_time_or_duration(text: str) -> bool:
    return bool(re.search(r"\b\d+\s*(am|pm|hours?|mins?|minutes?)\b", text))


def extract_features(user_text: str) -> dict[str, bool]:
    """Extract lightweight boolean routing features from a spoken turn."""
    text = user_text.strip().lower()
    is_greeting = _matches_any(text, GREETING_PATTERNS)
    is_overview = _matches_any(text, OVERVIEW_PATTERNS)
    is_jewel_local = _contains_any(text, JEWEL_TERMS) or (
        _contains_any(text, LOOKUP_TERMS) and "marina bay" not in text
    )
    has_planning_constraints = (
        _contains_any(text, PLANNING_TERMS)
        or _has_time_or_duration(text)
        or text.count(", then ") > 0
        or len(re.findall(r"\bthen\b", text)) > 0
    )
    needs_live_data = _contains_any(text, LIVE_DATA_TERMS)
    is_cross_destination = _contains_any(text, CROSS_DESTINATION_TERMS)
    requires_tools = needs_live_data

    return {
        "is_greeting_or_overview": is_greeting or is_overview,
        "is_jewel_local": is_jewel_local,
        "has_planning_constraints": has_planning_constraints,
        "needs_live_data": needs_live_data,
        "is_cross_destination": is_cross_destination,
        "requires_tools": requires_tools,
    }


def route_turn(user_text: str, system_state: dict[str, bool]) -> RouteDecision:
    """Choose the cheapest path that can still answer the turn well."""
    features = extract_features(user_text)

    if features["is_greeting_or_overview"]:
        return RouteDecision(
            route="direct",
            reason="broad_overview",
            confidence="high",
            features=features,
        )

    if (
        features["is_jewel_local"]
        and not features["has_planning_constraints"]
        and not features["needs_live_data"]
    ):
        return RouteDecision(
            route="lookup",
            reason="jewel_local_factual_request",
            confidence="high",
            features=features,
        )

    if (
        features["has_planning_constraints"]
        or features["is_cross_destination"]
        or features["needs_live_data"]
        or features["requires_tools"]
    ):
        if system_state.get("planner_available", False):
            return RouteDecision(
                route="planner",
                reason="multi_step_or_live_data_request",
                confidence="high",
                features=features,
            )

        if features["is_jewel_local"] and system_state.get("lookup_available", False):
            return RouteDecision(
                route="lookup",
                reason="planner_unavailable_fallback_lookup",
                confidence="medium",
                features=features,
            )

        return RouteDecision(
            route="direct",
            reason="planner_unavailable_fallback_direct",
            confidence="low",
            features=features,
        )

    return RouteDecision(
        route="direct",
        reason="default_safe_direct",
        confidence="medium",
        features=features,
    )
