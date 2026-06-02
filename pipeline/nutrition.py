"""USDA FoodData Central Nährwert-Lookup mit LLM-Fallback."""
from __future__ import annotations

import asyncio

import httpx
from openai import AsyncOpenAI

import config
from models.recipe import Ingredient, NutritionInfo, ProcessedRecipe

_FDC_SEARCH = f"{config.FDC_BASE_URL}/foods/search"

# Einheiten → Gramm-Konversionsfaktoren (Näherungswerte)
_UNIT_TO_GRAMS: dict[str, float] = {
    "g": 1.0,
    "kg": 1000.0,
    "ml": 1.0,          # Wasser-Näherung
    "l": 1000.0,
    "el": 15.0,         # Esslöffel
    "tl": 5.0,          # Teelöffel
    "esslöffel": 15.0,
    "teelöffel": 5.0,
    "stück": 100.0,     # grobe Näherung
    "prise": 0.5,
    "bund": 30.0,
    "dose": 400.0,
    "pkg": 250.0,
    "packung": 250.0,
}

_NUTRIENT_IDS = {
    "calories_kcal": 1008,
    "protein_g": 1003,
    "carbs_g": 1005,
    "fat_g": 1004,
    "fiber_g": 1079,
    "sodium_mg": 1093,
    "iron_mg": 1089,
    "calcium_mg": 1087,
    "vitamin_c_mg": 1162,
}


def _to_grams(amount: float | None, unit: str | None) -> float:
    if amount is None:
        return 100.0  # Fallback: 100g
    unit_key = (unit or "g").lower().strip()
    factor = _UNIT_TO_GRAMS.get(unit_key, 1.0)
    return amount * factor


def _extract_nutrients(food_item: dict, grams: float) -> NutritionInfo:
    nutrients_raw = {n["nutrientId"]: n.get("value", 0) for n in food_item.get("foodNutrients", [])}
    factor = grams / 100.0

    kwargs: dict = {}
    for field, nid in _NUTRIENT_IDS.items():
        value = nutrients_raw.get(nid)
        kwargs[field] = round(value * factor, 2) if value is not None else None

    return NutritionInfo(**kwargs, estimated=False)


async def _lookup_ingredient(
    client: httpx.AsyncClient,
    ingredient: Ingredient,
) -> NutritionInfo | None:
    search_term = ingredient.english_name or ingredient.name
    grams = _to_grams(ingredient.amount, ingredient.unit)

    try:
        resp = await client.get(
            _FDC_SEARCH,
            params={"query": search_term, "api_key": config.FDC_API_KEY, "pageSize": 1},
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    foods = data.get("foods", [])
    if not foods:
        return None

    return _extract_nutrients(foods[0], grams)


async def _estimate_via_llm(ingredient: Ingredient) -> NutritionInfo:
    """LLM-Fallback wenn USDA keine Übereinstimmung liefert."""
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    prompt = (
        f"Schätze die Nährwerte für: {ingredient.amount} {ingredient.unit} {ingredient.name}.\n"
        "Antworte NUR mit JSON: "
        '{"calories_kcal": X, "protein_g": X, "carbs_g": X, "fat_g": X, '
        '"fiber_g": X, "sodium_mg": X, "iron_mg": X, "calcium_mg": X, "vitamin_c_mg": X}'
    )
    try:
        resp = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        import json
        data = json.loads(resp.choices[0].message.content or "{}")
        return NutritionInfo(**data, estimated=True)
    except Exception:
        return NutritionInfo(estimated=True)


def _sum_nutrition(values: list[NutritionInfo]) -> NutritionInfo:
    fields = [f for f in _NUTRIENT_IDS]
    totals: dict = {f: 0.0 for f in fields}
    any_estimated = False

    for v in values:
        any_estimated = any_estimated or v.estimated
        for f in fields:
            val = getattr(v, f)
            if val is not None:
                totals[f] += val

    return NutritionInfo(**{f: round(v, 2) for f, v in totals.items()}, estimated=any_estimated)


async def enrich_nutrition(recipes: list[ProcessedRecipe]) -> list[ProcessedRecipe]:
    async with httpx.AsyncClient() as http_client:
        for recipe in recipes:
            ingredient_nutritions: list[NutritionInfo] = []

            for ingredient in recipe.ingredients:
                info = await _lookup_ingredient(http_client, ingredient)
                if info is None:
                    info = await _estimate_via_llm(ingredient)
                ingredient_nutritions.append(info)

            total = _sum_nutrition(ingredient_nutritions)
            servings = max(recipe.servings, 1)
            recipe.nutrition_per_serving = NutritionInfo(
                **{
                    f: round(getattr(total, f) / servings, 2)
                    if getattr(total, f) is not None
                    else None
                    for f in _NUTRIENT_IDS
                },
                estimated=total.estimated,
            )

    return recipes
