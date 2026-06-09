"""Chefkoch-Scraper – liest Rezepte über den schema.org/Recipe JSON-LD-Block.

Chefkoch bettet pro Rezeptseite einen `<script type="application/ld+json">`-Block
mit einem `Recipe`-Objekt ein (für Suchmaschinen). Wir parsen dieses strukturierte
JSON statt brüchiger CSS-Selektoren – das ist deutlich robuster gegen Redesigns.
"""
from __future__ import annotations

import json
import re
import time

import requests
from bs4 import BeautifulSoup

from models.recipe import RawRecipe
from .base import RecipeSource

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ByteAndBite-Research-Bot/0.1; "
        "educational prototype)"
    )
}
_RATE_LIMIT_SECONDS = 2.0
_SEARCH_URL = "https://www.chefkoch.de/rs/s{offset}/{query}/Rezepte.html"
_RESULTS_PER_PAGE = 30
# Volle Rezept-URL: /rezepte/<ziffern>/<slug>.html
_RECIPE_URL_RE = re.compile(
    r"https://www\.chefkoch\.de/rezepte/\d+/[^\s\"']+\.html"
)


# ── Parsing (rein, ohne Netzwerk – testbar) ──────────────────────────────────


def _find_recipe_node(data: object) -> dict | None:
    """Sucht rekursiv das `Recipe`-Objekt in einem JSON-LD-Baum."""
    if isinstance(data, dict):
        node_type = data.get("@type")
        if node_type == "Recipe" or (
            isinstance(node_type, list) and "Recipe" in node_type
        ):
            return data
        for value in data.values():
            found = _find_recipe_node(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_recipe_node(item)
            if found:
                return found
    return None


def _flatten_instructions(instructions: object) -> str:
    """Macht aus `recipeInstructions` (String | HowToStep/HowToSection) einen Text."""
    if isinstance(instructions, str):
        return instructions.strip()

    steps: list[str] = []

    def collect(node: object) -> None:
        if isinstance(node, str):
            text = node.strip()
            if text:
                steps.append(text)
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, dict):
            node_type = node.get("@type")
            if node_type == "HowToSection":
                collect(node.get("itemListElement", []))
            else:  # HowToStep o. Ä.
                text = (node.get("text") or node.get("name") or "").strip()
                if text:
                    steps.append(text)

    collect(instructions)
    return "\n".join(steps)


def parse_recipe_html(html: str, url: str) -> RawRecipe | None:
    """Baut aus dem HTML einer Chefkoch-Rezeptseite ein `RawRecipe`.

    Gibt `None` zurück, wenn kein verwertbarer `Recipe`-JSON-LD-Block existiert.
    """
    soup = BeautifulSoup(html, "html.parser")

    recipe_node: dict | None = None
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        recipe_node = _find_recipe_node(data)
        if recipe_node:
            break

    if not recipe_node:
        return None

    name = (recipe_node.get("name") or "").strip()
    if not name:
        return None

    raw_ingredients = [
        str(i).strip() for i in recipe_node.get("recipeIngredient", []) if str(i).strip()
    ]
    instructions = _flatten_instructions(recipe_node.get("recipeInstructions", ""))

    return RawRecipe(
        name=name,
        instructions=instructions,
        raw_ingredients=raw_ingredients,
        url=url,
        source="scraper",
    )


# ── Quelle (mit Netzwerk) ────────────────────────────────────────────────────


class ScraperSource(RecipeSource):
    """Scrapt Rezepte von Chefkoch.de über die Suchseite + JSON-LD-Parsing.

    query: Suchbegriff (default "Hauptgericht").
    Hält _RATE_LIMIT_SECONDS zwischen Requests ein.
    """

    def __init__(self, query: str = "Hauptgericht") -> None:
        self.query = query
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def fetch(self, n: int) -> list[RawRecipe]:
        urls = self._collect_recipe_urls(n)
        recipes: list[RawRecipe] = []
        for url in urls:
            recipe = self._scrape_recipe(url)
            if recipe:
                recipes.append(recipe)
            time.sleep(_RATE_LIMIT_SECONDS)
        return recipes

    def _collect_recipe_urls(self, n: int) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        page = 0
        while len(urls) < n:
            search_url = _SEARCH_URL.format(
                offset=page * _RESULTS_PER_PAGE, query=self.query
            )
            try:
                resp = self._session.get(search_url, timeout=10)
                resp.raise_for_status()
            except requests.RequestException:
                break
            found = _RECIPE_URL_RE.findall(resp.text)
            new = [u for u in found if u not in seen]
            if not new:
                break
            for u in new:
                seen.add(u)
                urls.append(u)
                if len(urls) >= n:
                    break
            page += 1
            time.sleep(_RATE_LIMIT_SECONDS)
        return urls[:n]

    def _scrape_recipe(self, url: str) -> RawRecipe | None:
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            return None
        return parse_recipe_html(resp.text, url)
