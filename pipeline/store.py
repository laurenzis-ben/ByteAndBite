"""JSON-Datei-Speicherung mit Manifest und Duplikaterkennung."""
from __future__ import annotations

import difflib
import json
from pathlib import Path

import config
from models.recipe import ProcessedRecipe

_DUPLICATE_THRESHOLD = 0.85  # Jaro-Winkler-ähnlicher Schwellenwert via difflib


def _load_manifest(manifest_path: Path) -> list[dict]:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return []


def _is_duplicate(name: str, manifest: list[dict]) -> bool:
    existing_names = [entry["name"] for entry in manifest]
    if not existing_names:
        return False
    best = difflib.get_close_matches(name, existing_names, n=1, cutoff=_DUPLICATE_THRESHOLD)
    return bool(best)


def store_recipes(recipes: list[ProcessedRecipe], output_dir: Path) -> int:
    """Speichert Rezepte als JSON-Dateien. Gibt Anzahl neu gespeicherter Rezepte zurück."""
    recipes_dir = output_dir / config.RECIPES_SUBDIR
    recipes_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / config.MANIFEST_FILENAME
    manifest = _load_manifest(manifest_path)
    existing_ids = {entry["id"] for entry in manifest}

    saved = 0
    for recipe in recipes:
        if recipe.id in existing_ids:
            print(f"[store] Übersprungen (ID existiert): {recipe.name}")
            continue
        if _is_duplicate(recipe.name, manifest):
            print(f"[store] Übersprungen (Duplikat): {recipe.name}")
            continue

        recipe_path = recipes_dir / f"{recipe.id}.json"
        recipe_path.write_text(
            recipe.model_dump_json(indent=2),
            encoding="utf-8",
        )

        manifest.append({
            "id": recipe.id,
            "name": recipe.name,
            "tags": recipe.allergen_tags,
            "meal_type": recipe.meal_type,
            "season": recipe.season,
            "difficulty": recipe.difficulty,
            "ingredient_names": [i.name for i in recipe.ingredients],
        })
        saved += 1

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return saved
