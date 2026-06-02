from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class RawRecipe(BaseModel):
    name: str
    instructions: str
    raw_ingredients: list[str]
    url: str | None = None
    source: str  # "dataset" | "scraper"


class Ingredient(BaseModel):
    name: str
    amount: float | None = None
    unit: str | None = None  # "g", "ml", "EL", "TL", "Stück", …
    preparation: str | None = None  # "gewürfelt", "gehackt", …
    english_name: str | None = None  # für USDA-Lookup


class NutritionInfo(BaseModel):
    """Nährwerte pro Portion (oder pro 100g bei USDA-Rohdaten)."""
    calories_kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None
    iron_mg: float | None = None
    calcium_mg: float | None = None
    vitamin_c_mg: float | None = None
    estimated: bool = False  # True wenn LLM-Schätzung statt USDA-Daten


# ── Structured Output für OpenAI ───────────────────────────────────────────────

AllergenTag = Literal[
    "glutenfrei", "laktosefrei", "nussfrei", "vegan", "vegetarisch", "ei-frei"
]
MealType = Literal["Frühstück", "Mittagessen", "Abendessen", "Snack", "Dessert"]
Season = Literal["Frühling", "Sommer", "Herbst", "Winter", "ganzjährig"]
CostTier = Literal["günstig", "mittel", "teuer"]


class NormalizationResult(BaseModel):
    """Direkt als response_format an OpenAI übergeben – wird strukturiert zurückgegeben."""
    description: str = Field(description="Kurzbeschreibung des Gerichts, 2–3 Sätze auf Deutsch.")
    instructions_normalized: str = Field(
        description="Anleitungstext im einheitlichen Imperativ-Stil, nummerierte Schritte."
    )
    servings: int = Field(ge=1, description="Anzahl Portionen laut Rezept.")
    prep_time_min: int | None = Field(None, description="Vorbereitungszeit in Minuten.")
    cook_time_min: int | None = Field(None, description="Koch-/Backzeit in Minuten.")
    ingredients: list[Ingredient]
    difficulty: int = Field(ge=1, le=5, description="Schwierigkeitsgrad 1 (einfach) bis 5 (anspruchsvoll).")
    allergen_tags: list[AllergenTag] = Field(default_factory=list)
    meal_type: MealType
    season: Season
    cost_tier: CostTier


class ProcessedRecipe(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    source_url: str | None = None
    source: str
    description: str
    instructions_normalized: str
    servings: int
    prep_time_min: int | None = None
    cook_time_min: int | None = None
    ingredients: list[Ingredient]
    nutrition_per_serving: NutritionInfo | None = None
    difficulty: int
    allergen_tags: list[str]
    meal_type: str
    season: str
    cost_tier: str
    processed_at: datetime = Field(default_factory=datetime.utcnow)
