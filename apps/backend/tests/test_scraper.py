"""Tests für den Chefkoch-JSON-LD-Parser.

Die Fixture `chefkoch_flammkuchen.html` ist eine echte, gespeicherte Chefkoch-
Rezeptseite – so testen wir das Parsing ohne Netzwerkzugriff.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.acquire.scraper import parse_recipe_html

_FIXTURE = Path(__file__).parent / "fixtures" / "chefkoch_flammkuchen.html"
_URL = "https://www.chefkoch.de/rezepte/1107291216818673/Schneller-Flammkuchen.html"


@pytest.fixture
def recipe_html() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_extracts_name(recipe_html: str) -> None:
    recipe = parse_recipe_html(recipe_html, _URL)
    assert recipe is not None
    assert recipe.name == "Schneller Flammkuchen von meerjungfrau"


def test_extracts_ingredients_as_list(recipe_html: str) -> None:
    recipe = parse_recipe_html(recipe_html, _URL)
    assert recipe is not None
    # Zutaten kommen direkt als Liste aus dem JSON-LD – inkl. korrekter Umlaute.
    assert "2 EL Öl" in recipe.raw_ingredients
    assert "125 ml Wasser" in recipe.raw_ingredients


def test_flattens_instruction_steps_into_text(recipe_html: str) -> None:
    recipe = parse_recipe_html(recipe_html, _URL)
    assert recipe is not None
    # Die einzelnen HowToStep-Texte müssen im Anweisungstext auftauchen.
    assert "Knetteig bereiten" in recipe.instructions
    assert "im heißen ofen" in recipe.instructions.lower()


def test_sets_url_and_source(recipe_html: str) -> None:
    recipe = parse_recipe_html(recipe_html, _URL)
    assert recipe is not None
    assert recipe.url == _URL
    assert recipe.source == "scraper"


def test_returns_none_when_no_recipe_jsonld() -> None:
    assert parse_recipe_html("<html><body>kein Rezept</body></html>", _URL) is None
