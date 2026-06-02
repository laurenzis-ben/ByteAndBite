"""Lädt Rezepte aus dem Kaggle German Recipes Dataset (sterby/german-recipes-dataset).

Zwei Modi:
  1. Lokale JSON-Datei: --data-path ./recipes.json  (nach manuellem Kaggle-Download)
  2. Automatischer Download via Kaggle-API (braucht ~/.kaggle/kaggle.json)

Kaggle-Datensatz: https://www.kaggle.com/datasets/sterby/german-recipes-dataset
JSON-Felder: Name, Ingredients (list), Instructions (str), Url, Timestamp
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from models.recipe import RawRecipe
from .base import RecipeSource

KAGGLE_DATASET = "sterby/german-recipes-dataset"
KAGGLE_FILENAME = "recipes.json"


class DatasetSource(RecipeSource):
    def __init__(self, data_path: Path | None = None) -> None:
        self.data_path = data_path

    def fetch(self, n: int) -> list[RawRecipe]:
        path = self.data_path or self._auto_download()
        return self._load_from_file(path, n)

    def _load_from_file(self, path: Path, n: int) -> list[RawRecipe]:
        raw = json.loads(path.read_text(encoding="utf-8"))

        # Datensatz ist entweder eine Liste oder ein dict mit "recipes"-Key
        if isinstance(raw, dict):
            rows = raw.get("recipes") or list(raw.values())
        else:
            rows = raw

        recipes: list[RawRecipe] = []
        for row in rows:
            if len(recipes) >= n:
                break
            recipe = self._parse(row)
            if recipe:
                recipes.append(recipe)
        return recipes

    def _parse(self, row: dict) -> RawRecipe | None:
        # Kaggle-Felder: Name / Ingredients / Instructions / Url / Timestamp
        name = (row.get("Name") or row.get("name") or row.get("title") or "").strip()
        if not name:
            return None

        raw_ingredients = self._extract_ingredients(row)
        instructions = self._extract_instructions(row)

        return RawRecipe(
            name=name,
            instructions=instructions,
            raw_ingredients=raw_ingredients,
            url=row.get("Url") or row.get("url"),
            source="dataset",
        )

    def _extract_ingredients(self, row: dict) -> list[str]:
        ingredients = (
            row.get("Ingredients")
            or row.get("ingredients")
            or []
        )
        if isinstance(ingredients, list):
            return [str(i).strip() for i in ingredients if str(i).strip()]
        if isinstance(ingredients, str):
            return [line.strip() for line in ingredients.splitlines() if line.strip()]
        return []

    def _extract_instructions(self, row: dict) -> str:
        steps = (
            row.get("Instructions")
            or row.get("instructions")
            or row.get("steps")
            or ""
        )
        if isinstance(steps, list):
            return "\n".join(str(s).strip() for s in steps if str(s).strip())
        return str(steps).strip()

    def _auto_download(self) -> Path:
        """Lädt den Datensatz per Kaggle-API herunter (braucht ~/.kaggle/kaggle.json)."""
        try:
            import kaggle  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "Kaggle-Paket nicht installiert. Bitte ausführen:\n"
                "  uv add kaggle\n"
                "Oder Datensatz manuell herunterladen:\n"
                "  https://www.kaggle.com/datasets/sterby/german-recipes-dataset\n"
                "Und dann starten mit: --data-path ./recipes.json"
            )

        import kaggle.api  # type: ignore
        download_dir = Path(".kaggle_cache")
        download_dir.mkdir(exist_ok=True)

        json_path = download_dir / KAGGLE_FILENAME
        if json_path.exists():
            return json_path

        print("Lade Kaggle-Datensatz herunter…")
        kaggle.api.dataset_download_files(
            KAGGLE_DATASET,
            path=str(download_dir),
            unzip=False,
        )

        # Entpacken wenn als ZIP geliefert
        zip_path = download_dir / f"{KAGGLE_DATASET.split('/')[-1]}.zip"
        if zip_path.exists():
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(download_dir)

        if not json_path.exists():
            candidates = list(download_dir.glob("*.json"))
            if not candidates:
                raise FileNotFoundError(
                    f"Keine JSON-Datei nach Kaggle-Download in {download_dir} gefunden."
                )
            json_path = candidates[0]

        return json_path
