"""Curated Jewel lookup path for the Phase 1 voice-guide demo."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class LookupResult:
    """Carries a grounded response from the local Jewel knowledge index."""

    spoken_response: str
    display_response: str
    confidence: str
    recommendations: list[dict]
    citations: list[str]
    planner_metadata: dict


class JewelKnowledgeIndex:
    """Loads and queries the small curated Jewel dataset used by `LookupPath`."""

    def __init__(self, data_path: str | Path):
        """Initialize the lookup index from a JSON dataset path."""
        self._data_path = Path(data_path)
        self._data = self._load()

    @property
    def available(self) -> bool:
        """Return whether the dataset loaded any lookup items."""
        return bool(self._data.get("items"))

    def _load(self) -> dict:
        if not self._data_path.exists():
            return {"items": []}
        with self._data_path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _requested_categories(self, text: str) -> list[str]:
        requested_categories: list[str] = []
        if "dessert" in text or "sweet" in text:
            requested_categories.append("dessert")
        if "toy" in text or "kids" in text or "children" in text:
            requested_categories.append("toy_store")
        if "family" in text or "kid" in text:
            requested_categories.append("family_activity")
        if "food" in text or "restaurant" in text or "eat" in text:
            requested_categories.append("dining")
        return requested_categories

    def _match_items(self, user_text: str) -> list[dict]:
        text = user_text.lower()
        requested_categories = self._requested_categories(text)

        location_terms = []
        if "rain vortex" in text:
            location_terms.append("rain vortex")
        if "forest valley" in text:
            location_terms.append("forest valley")
        if "canopy" in text:
            location_terms.append("canopy")

        matches: list[tuple[int, dict]] = []
        for item in self._data.get("items", []):
            score = 0
            if item["category"] in requested_categories:
                score += 5
            if any(tag in item.get("tags", []) for tag in ["family_friendly", "kids"]) and (
                "family" in text or "kids" in text
            ):
                score += 2
            hint = item.get("location_hint", "").lower()
            if any(term in hint for term in location_terms):
                score += 3
            if "rain vortex" in text and "rain vortex" in hint:
                score += 2
            if "what can i do" in text and item["category"] in {"attraction", "family_activity"}:
                score += 2
            if score > 0:
                matches.append((score, item))

        matches.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        return [item for _, item in matches]

    def answer(self, user_text: str) -> LookupResult | None:
        """Return a grounded lookup answer for a Jewel-local request."""
        items = self._match_items(user_text)
        if not items:
            return None

        text = user_text.lower()
        requested_categories = self._requested_categories(text)
        selected: list[dict] = []
        selected_ids: set[str] = set()

        for category in requested_categories:
            for item in items:
                if item["category"] == category and item["id"] not in selected_ids:
                    selected.append(item)
                    selected_ids.add(item["id"])
                    break

        for item in items:
            if item["id"] in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item["id"])
            if len(selected) >= 3:
                break

        selected = selected[:3]

        recommendations = [
            {
                "id": item["id"],
                "name": item["name"],
                "category": item["category"],
                "location_hint": item["location_hint"],
                "reason": item["reason"],
                "fit_score": item["fit_score"],
                "tags": item["tags"],
            }
            for item in selected
        ]

        if "dessert" in text and ("toy" in text or "kids" in text):
            spoken = (
                f"For a sweet stop, try {selected[0]['name']}, then head to {selected[1]['name']} "
                f"for a kid-friendly toy option near the Rain Vortex area."
            )
            display = (
                f"Recommended pair: {selected[0]['name']} for dessert, then {selected[1]['name']} "
                "for a nearby toy stop."
            )
        elif "family" in text or "kids" in text:
            names = ", ".join(item["name"] for item in selected[:3])
            spoken = f"Family-friendly Jewel picks include {names}."
            display = f"Family-friendly shortlist: {names}."
        else:
            names = ", ".join(item["name"] for item in selected[:2])
            spoken = f"Good Jewel options for that are {names}."
            display = f"Grounded Jewel options: {names}."

        return LookupResult(
            spoken_response=spoken,
            display_response=display,
            confidence="high",
            recommendations=recommendations,
            citations=["jewel_knowledge_index"],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": False,
                "route_class": "lookup",
                "response_style": "voice_friendly",
            },
        )
