"""PostgreSQL-Speicherung der aufbereiteten Rezepte."""
from __future__ import annotations

import re

from sqlalchemy import select

from pathlib import Path

from db.models import (
    Ingredient,
    Recipe,
    RecipeIngredient,
    RecipeInstruction,
    RecipeNutrition,
    RecipeTag,
)
from db.session import get_session
from models.recipe import Ingredient as PydanticIngredient
from models.recipe import NutritionInfo, ProcessedRecipe


def _parse_steps(instructions_normalized: str) -> list[str]:
    """Zerlegt den nummerierten Anleitungstext in einzelne Schritte.

    Erwartet Format: '1. Schritt eins. 2. Schritt zwei.' oder Zeilenumbrüche.
    """
    # Versuche zuerst Zeilenumbrüche
    lines = [l.strip() for l in instructions_normalized.splitlines() if l.strip()]
    if len(lines) > 1:
        # Nummern am Zeilenanfang entfernen (z.B. "1. ", "1) ")
        return [re.sub(r"^\d+[\.\)]\s*", "", l) for l in lines]

    # Fallback: nach Nummern im Text splitten
    steps = re.split(r"\d+\.\s+", instructions_normalized)
    return [s.strip() for s in steps if s.strip()]


async def _get_or_create_ingredient(
    session,
    pydantic_ingredient: PydanticIngredient,
) -> Ingredient:
    """Sucht eine Zutat nach normalisiertem Namen oder legt sie neu an.

    So wird 'Mehl' über alle Rezepte hinweg nur einmal gespeichert.
    """
    name = pydantic_ingredient.name.strip().lower()
    result = await session.execute(
        select(Ingredient).where(Ingredient.name == name)
    )
    existing = result.scalar_one_or_none()

    if existing:
        return existing

    new_ingredient = Ingredient(
        name=name,
        english_name=pydantic_ingredient.english_name,
    )
    session.add(new_ingredient)
    await session.flush()  # ID generieren, ohne zu committen
    return new_ingredient


async def save_recipe_to_db(recipe: ProcessedRecipe) -> bool:
    """Speichert ein einzelnes Rezept in PostgreSQL.

    Gibt True zurück wenn neu gespeichert, False wenn bereits vorhanden.
    """
    async with get_session() as session:
        # Duplikat-Check via ID
        existing = await session.get(Recipe, recipe.id)
        if existing:
            return False

        # 1. Kern-Rezept anlegen
        db_recipe = Recipe(
            id=recipe.id,
            name=recipe.name,
            description=recipe.description,
            source=recipe.source,
            source_url=recipe.source_url,
            servings=recipe.servings,
            prep_time_min=recipe.prep_time_min,
            cook_time_min=recipe.cook_time_min,
            difficulty=recipe.difficulty,
            meal_type=recipe.meal_type,
            season=recipe.season,
            cost_tier=recipe.cost_tier,
            processed_at=recipe.processed_at,
        )
        session.add(db_recipe)
        await session.flush()

        # 2. Zubereitungsschritte
        steps = _parse_steps(recipe.instructions_normalized)
        for i, step_content in enumerate(steps, start=1):
            session.add(RecipeInstruction(
                recipe_id=recipe.id,
                step_number=i,
                content=step_content,
            ))

        # 3. Zutaten (dedupliziert) + Junction-Einträge
        for pydantic_ing in recipe.ingredients:
            db_ingredient = await _get_or_create_ingredient(session, pydantic_ing)
            session.add(RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=db_ingredient.id,
                amount=pydantic_ing.amount,
                unit=pydantic_ing.unit,
                preparation=pydantic_ing.preparation,
            ))

        # 4. Nährwerte
        if recipe.nutrition_per_serving:
            n: NutritionInfo = recipe.nutrition_per_serving
            session.add(RecipeNutrition(
                recipe_id=recipe.id,
                calories_kcal=n.calories_kcal,
                protein_g=n.protein_g,
                carbs_g=n.carbs_g,
                fat_g=n.fat_g,
                fiber_g=n.fiber_g,
                sodium_mg=n.sodium_mg,
                iron_mg=n.iron_mg,
                calcium_mg=n.calcium_mg,
                vitamin_c_mg=n.vitamin_c_mg,
                estimated=n.estimated,
            ))

        # 5. Tags
        for tag in recipe.allergen_tags:
            session.add(RecipeTag(recipe_id=recipe.id, tag=tag))

    return True


async def save_recipes_to_db(recipes: list[ProcessedRecipe]) -> int:
    """Speichert eine Liste von Rezepten. Gibt Anzahl neu gespeicherter zurück."""
    saved = 0
    for recipe in recipes:
        try:
            was_new = await save_recipe_to_db(recipe)
            if was_new:
                saved += 1
            else:
                print(f"[db] Übersprungen (existiert bereits): {recipe.name}")
        except Exception as exc:
            print(f"[db] Fehler beim Speichern von '{recipe.name}': {exc}")
    return saved


if __name__ == "__main__":
    import asyncio
    import json
    from pydantic import TypeAdapter

    # Importiere deine Session-Funktionen (Pfade ggf. anpassen)
    from db.session import init_engine, create_tables


    async def run_import():
        print("Initialisiere Datenbank...")
        init_engine()
        await create_tables()

        # 1. Den Ordner definieren, in dem die einzelnen Rezept-JSONs liegen
        # WICHTIG: Passe den Pfad an, falls er bei dir anders heißt!
        recipes_dir = Path("output/recipes")
        print(f"Suche nach Rezepten in {recipes_dir}...")

        recipes_list = []

        # 2. Durch alle .json Dateien im Ordner iterieren
        for file_path in recipes_dir.glob("*.json"):
            # Falls die manifest.json im selben Ordner liegt, ignorieren wir sie
            if file_path.name == "manifest.json":
                continue

            try:
                # Datei öffnen und JSON lesen
                with open(file_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

                # Das rohe Dictionary in dein Pydantic-Modell umwandeln
                # (model_validate ist der Standardweg in Pydantic V2 für einzelne Objekte)
                recipe = ProcessedRecipe.model_validate(raw_data)
                recipes_list.append(recipe)

            except RuntimeError as e:
                print(f"Validierungsfehler in {file_path.name} - Datei wird übersprungen.")
            except Exception as e:
                print(f"Allgemeiner Fehler bei {file_path.name}: {e}")

        # 3. Den Speichervorgang in die Datenbank starten
        print(f"\n{len(recipes_list)} gültige Rezepte gefunden. Starte DB-Import...")

        if recipes_list:
            saved_count = await save_recipes_to_db(recipes_list)
            print(f"Erfolgreich abgeschlossen! {saved_count} neue Rezepte wurden gespeichert.")
        else:
            print("Keine gültigen Rezepte gefunden. Import abgebrochen.")


    # Startet die asynchrone Funktion
    asyncio.run(run_import())