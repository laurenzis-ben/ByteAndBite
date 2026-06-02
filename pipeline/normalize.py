"""LLM-Normalisierung via OpenAI Structured Outputs."""
from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

import config
from models.recipe import NormalizationResult, ProcessedRecipe, RawRecipe

_SYSTEM_PROMPT = """Du bist ein präziser Rezept-Assistent für die deutsche Küche.
Du erhältst ein rohes Rezept und lieferst eine strukturierte, normalisierte Version zurück.

Regeln:
- Anleitungen: Imperativ-Stil, nummerierte Schritte (1. Zwiebeln würfeln. 2. Öl erhitzen. …)
- Zutaten: Menge als Dezimalzahl, Einheit normiert (g, ml, EL, TL, Stück), Zubereitung separat
- english_name der Zutat: englische Übersetzung für Nährwert-Lookup (z.B. "Mehl" → "wheat flour")
- Zeiten: in Minuten, null wenn nicht angegeben
- Allergene: nur setzen, wenn das Gericht WIRKLICH frei davon ist
- Schwierigkeit: 1 = 5 Zutaten, einfache Schritte; 5 = Profi-Techniken, viele Schritte
"""


async def _normalize_one(
    client: AsyncOpenAI,
    raw: RawRecipe,
    semaphore: asyncio.Semaphore,
) -> ProcessedRecipe | None:
    ingredients_text = "\n".join(f"- {i}" for i in raw.raw_ingredients)
    user_content = (
        f"Rezeptname: {raw.name}\n\n"
        f"Zutaten:\n{ingredients_text}\n\n"
        f"Zubereitung:\n{raw.instructions}"
    )

    async with semaphore:
        try:
            response = await client.beta.chat.completions.parse(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format=NormalizationResult,
            )
        except Exception as exc:
            print(f"[normalize] Fehler bei '{raw.name}': {exc}")
            return None

    parsed = response.choices[0].message
    if parsed.refusal:
        print(f"[normalize] Refusal bei '{raw.name}': {parsed.refusal}")
        return None

    result: NormalizationResult = parsed.parsed

    return ProcessedRecipe(
        name=raw.name,
        source_url=raw.url,
        source=raw.source,
        description=result.description,
        instructions_normalized=result.instructions_normalized,
        servings=result.servings,
        prep_time_min=result.prep_time_min,
        cook_time_min=result.cook_time_min,
        ingredients=result.ingredients,
        difficulty=result.difficulty,
        allergen_tags=list(result.allergen_tags),
        meal_type=result.meal_type,
        season=result.season,
        cost_tier=result.cost_tier,
    )


async def normalize_batch(raw_recipes: list[RawRecipe]) -> list[ProcessedRecipe]:
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    semaphore = asyncio.Semaphore(config.NORMALIZE_CONCURRENCY)

    tasks = [_normalize_one(client, raw, semaphore) for raw in raw_recipes]
    results = await asyncio.gather(*tasks)

    return [r for r in results if r is not None]
