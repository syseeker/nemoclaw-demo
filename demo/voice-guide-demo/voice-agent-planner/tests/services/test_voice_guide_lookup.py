"""Lookup tests for the curated Jewel dataset."""

from pathlib import Path

from apps.jewel_voice_guide.lookup import JewelKnowledgeIndex


def test_lookup_returns_grounded_pair_for_dessert_and_toy():
    """Lookup should return dessert and toy recommendations for the demo prompt."""
    data_path = Path(__file__).resolve().parents[2] / "apps" / "jewel_voice_guide" / "jewel_knowledge.json"
    index = JewelKnowledgeIndex(data_path)

    result = index.answer("Find dessert and a toy shop near Rain Vortex for my kids.")

    assert result is not None
    assert "Rain Vortex" in result.spoken_response
    categories = {item["category"] for item in result.recommendations}
    assert "dessert" in categories
    assert "toy_store" in categories


def test_lookup_returns_family_activity_shortlist():
    """Lookup should return family-oriented recommendations for Jewel prompts."""
    data_path = Path(__file__).resolve().parents[2] / "apps" / "jewel_voice_guide" / "jewel_knowledge.json"
    index = JewelKnowledgeIndex(data_path)

    result = index.answer("What family-friendly things are inside Jewel?")

    assert result is not None
    assert result.confidence == "high"
    assert len(result.recommendations) >= 1
