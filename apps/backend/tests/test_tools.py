"""Tests für die beiden neuen Agent-Tools.

Nutzt die `seeded_db`-Fixture aus conftest.py (In-Memory-SQLite, 4 Rezepte).
"""
from __future__ import annotations

import pytest

from agent.tools import filter_by_nutrition, find_recipes_by_ingredients


# ── find_recipes_by_ingredients ─────────────────────────────────────────────────

async def test_ranks_by_number_of_matched_ingredients(seeded_db):
    """Mehr getroffene Vorrats-Zutaten => weiter oben."""
    results = await find_recipes_by_ingredients(["Spinat", "Feta"])

    ids = [r["id"] for r in results]
    # r2 hat Spinat+Feta (2), r1 hat nur Spinat (1); r3/r4 keine -> raus.
    assert ids == ["r2", "r1"]
    assert results[0]["match_count"] == 2
    assert results[1]["match_count"] == 1


async def test_reports_matched_and_missing_ingredients(seeded_db):
    results = await find_recipes_by_ingredients(["Spinat", "Feta"])
    r2 = next(r for r in results if r["id"] == "r2")

    assert set(r2["matched_ingredients"]) == {"Spinat", "Feta"}
    assert r2["total_ingredients"] == 5
    # Was im Rezept steckt, aber nicht im Vorrat war:
    assert set(r2["missing_ingredients"]) == {"Eier", "Mehl", "Butter"}


async def test_matches_ingredient_substring_case_insensitive(seeded_db):
    """'Ei' soll 'Eier' treffen (ilike-Substring)."""
    results = await find_recipes_by_ingredients(["ei"])
    ids = {r["id"] for r in results}

    assert ids == {"r1", "r2"}  # beide enthalten 'Eier'


async def test_returns_empty_when_nothing_matches(seeded_db):
    results = await find_recipes_by_ingredients(["Schokolade"])
    assert results == []


async def test_meal_type_filter_applies(seeded_db):
    results = await find_recipes_by_ingredients(["Spinat"], meal_type="Mittagessen")
    ids = {r["id"] for r in results}
    assert ids == {"r2"}  # r1 ist Frühstück -> raus


# ── filter_by_nutrition ─────────────────────────────────────────────────────────

async def test_min_protein_is_inclusive_and_excludes_lower(seeded_db):
    """min_protein_g=20 schließt r1 (genau 20) EIN, r3 (4) aus."""
    results = await filter_by_nutrition(min_protein_g=20)
    ids = {r["id"] for r in results}
    assert ids == {"r1", "r2"}


async def test_max_calories_filters_out_high_calorie(seeded_db):
    results = await filter_by_nutrition(max_calories_kcal=400)
    ids = {r["id"] for r in results}
    assert ids == {"r1", "r3"}  # r2 (600) raus


async def test_recipes_without_nutrition_are_excluded(seeded_db):
    """r4 hat keinen Nährwert-Datensatz und darf nie auftauchen."""
    results = await filter_by_nutrition(max_calories_kcal=10000)
    ids = {r["id"] for r in results}
    assert "r4" not in ids


async def test_combines_nutrition_with_meal_type(seeded_db):
    results = await filter_by_nutrition(min_protein_g=20, meal_type="Mittagessen")
    ids = {r["id"] for r in results}
    assert ids == {"r2"}  # r1 erfüllt Protein, ist aber Frühstück


async def test_payload_includes_nutrition_per_serving(seeded_db):
    results = await filter_by_nutrition(max_calories_kcal=400)
    r1 = next(r for r in results if r["id"] == "r1")
    n = r1["nutrition_per_serving"]
    assert n["calories_kcal"] == 300
    assert n["protein_g"] == 20
