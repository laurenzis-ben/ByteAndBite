"""Chefkoch-Scraper – RECHTLICHER HINWEIS: Nutzung nur nach Klärung mit Lukas / Rechtsabteilung."""
from __future__ import annotations

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
_SEARCH_URL = "https://www.chefkoch.de/rs/s0/{query}/Rezepte.html"
_BASE_URL = "https://www.chefkoch.de"


class ScraperSource(RecipeSource):
    """Scrapt Rezepte von Chefkoch.de.

    Respektiert robots.txt-Delay via _RATE_LIMIT_SECONDS zwischen Requests.
    query: Suchbegriff, der im Konstruktor übergeben werden kann.
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
        page = 0
        while len(urls) < n:
            search_url = _SEARCH_URL.format(query=self.query).replace("s0", f"s{page * 30}")
            resp = self._session.get(search_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.select("a.rsel-item[href]")
            if not links:
                break
            for a in links:
                href = a["href"]
                if href.startswith("/rezepte/"):
                    urls.append(_BASE_URL + href)
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

        soup = BeautifulSoup(resp.text, "html.parser")

        name_tag = soup.select_one("h1.recipe-title") or soup.select_one("h1")
        name = name_tag.get_text(strip=True) if name_tag else ""
        if not name:
            return None

        ingredient_rows = soup.select("table.ingredients tr")
        raw_ingredients: list[str] = []
        for row in ingredient_rows:
            amount = row.select_one("td.amount")
            ingredient = row.select_one("td.ingredient")
            if ingredient:
                amount_text = amount.get_text(strip=True) if amount else ""
                ingr_text = ingredient.get_text(strip=True)
                raw_ingredients.append(f"{amount_text} {ingr_text}".strip())

        instructions_tag = soup.select_one("div#rezept-zubereitung") or soup.select_one(
            "div.recipe-text"
        )
        instructions = instructions_tag.get_text(separator="\n", strip=True) if instructions_tag else ""

        return RawRecipe(
            name=name,
            instructions=instructions,
            raw_ingredients=raw_ingredients,
            url=url,
            source="scraper",
        )
