"""Pytest-Fixtures: eine In-Memory-SQLite-DB mit deterministischem Rezept-Seed.

`init_engine()` aus db.session kann keine geteilte In-Memory-DB liefern
(pool_size/max_overflow erzeugen mehrere Verbindungen = mehrere DBs). Daher
setzen wir die Modul-Globals direkt mit einem StaticPool-Engine, sodass alle
get_session()-Aufrufe dieselbe In-Memory-Verbindung teilen.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import db.session as session_mod
from db.models import (
    Base,
    Ingredient,
    Recipe,
    RecipeIngredient,
    RecipeNutrition,
)


def _recipe(rid, name, meal_type, ingredients, nutrition=None):
    """Baut ein Recipe-ORM-Objekt mit Zutaten und optionalen Nährwerten.

    ingredients: Liste von (Ingredient, amount)-Tupeln.
    nutrition:   dict der Nährwert-Felder oder None (kein Nährwert-Datensatz).
    """
    r = Recipe(
        id=rid,
        name=name,
        description=f"{name} – Testrezept",
        source="dataset",
        servings=2,
        prep_time_min=10,
        cook_time_min=10,
        difficulty=2,
        meal_type=meal_type,
        season="ganzjährig",
        cost_tier="günstig",
    )
    r.recipe_ingredients = [
        RecipeIngredient(ingredient=ing, amount=amount, unit="g") for ing, amount in ingredients
    ]
    if nutrition is not None:
        r.nutrition = RecipeNutrition(**nutrition)
    return r


@pytest_asyncio.fixture
async def seeded_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Modul-Globals überschreiben, damit get_session() die Test-DB nutzt.
    session_mod._engine = engine
    session_mod._session_factory = factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Dedup-Zutaten (entsprechen dem unique-constraint auf ingredients.name).
    eier = Ingredient(name="Eier")
    spinat = Ingredient(name="Spinat")
    butter = Ingredient(name="Butter")
    feta = Ingredient(name="Feta")
    mehl = Ingredient(name="Mehl")
    tomaten = Ingredient(name="Tomaten")
    zwiebel = Ingredient(name="Zwiebel")
    knoblauch = Ingredient(name="Knoblauch")
    haferflocken = Ingredient(name="Haferflocken")
    milch = Ingredient(name="Milch")

    recipes = [
        _recipe(
            "r1", "Rührei mit Spinat", "Frühstück",
            [(eier, 120), (spinat, 80), (butter, 10)],
            {"calories_kcal": 300, "protein_g": 20, "carbs_g": 5, "fat_g": 22, "fiber_g": 2},
        ),
        _recipe(
            "r2", "Spinat-Feta-Quiche", "Mittagessen",
            [(spinat, 200), (feta, 100), (eier, 120), (mehl, 150), (butter, 50)],
            {"calories_kcal": 600, "protein_g": 25, "carbs_g": 40, "fat_g": 35, "fiber_g": 4},
        ),
        _recipe(
            "r3", "Tomatensuppe", "Mittagessen",
            [(tomaten, 400), (zwiebel, 80), (knoblauch, 10)],
            {"calories_kcal": 150, "protein_g": 4, "carbs_g": 20, "fat_g": 5, "fiber_g": 3},
        ),
        # r4 bewusst OHNE Nährwert-Datensatz -> testet NULL-/Join-Ausschluss.
        _recipe(
            "r4", "Haferbrei", "Frühstück",
            [(haferflocken, 60), (milch, 200)],
            None,
        ),
    ]

    async with factory() as s:
        s.add_all(recipes)
        await s.commit()

    yield

    await engine.dispose()
    session_mod._engine = None
    session_mod._session_factory = None
