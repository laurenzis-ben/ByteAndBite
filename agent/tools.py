"""Agent-Tools für den Zugriff auf die Rezept-Datenbank.

Zwei MVP-Tools:
  search_recipes      – Rezepte nach Kriterien finden (gibt kompakte Trefferliste)
  get_recipe_details  – ein einzelnes Rezept vollständig laden (Zutaten, Schritte, Nährwerte)

Jedes Tool besteht aus zwei Teilen:
  1. einer async Python-Funktion, die die DB abfragt und JSON-serialisierbare dicts liefert
  2. einem Eintrag in TOOL_SCHEMAS (OpenAI-Function-Calling-Format)

Die Trennung ist bewusst: das Schema beschreibt dem LLM *was* das Tool kann,
die Funktion führt es aus. dispatch_tool_call() verbindet beide zur Laufzeit.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from db.models import Recipe, RecipeIngredient, RecipeTag
from db.session import get_session

# Kontrollierte Vokabulare – spiegeln die Literal-Types aus models/recipe.py.
# Werden im Tool-Schema als enum exponiert, damit das LLM nur gültige Werte sendet.
_MEAL_TYPES = ["Frühstück", "Mittagessen", "Abendessen", "Snack", "Dessert"]
_COST_TIERS = ["günstig", "mittel", "teuer"]
_TAGS = ["glutenfrei", "laktosefrei", "nussfrei", "vegan", "vegetarisch", "ei-frei"]


# ── Tool 1: search_recipes ──────────────────────────────────────────────────────

async def search_recipes(
    query: str | None = None,
    meal_type: str | None = None,
    max_time_min: int | None = None,
    max_difficulty: int | None = None,
    cost_tier: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Sucht Rezepte nach Filterkriterien und gibt eine kompakte Trefferliste zurück.

    Bewusst *keine* vollständigen Rezepte – nur so viel, dass das LLM auswählen kann.
    Für Details ruft der Agent danach get_recipe_details mit der id auf.
    """
    stmt = select(Recipe).options(selectinload(Recipe.tags))

    # Freitext über Name + Beschreibung (case-insensitive)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(Recipe.name.ilike(like) | Recipe.description.ilike(like))

    if meal_type:
        stmt = stmt.where(Recipe.meal_type == meal_type)

    if cost_tier:
        stmt = stmt.where(Recipe.cost_tier == cost_tier)

    if max_difficulty is not None:
        stmt = stmt.where(Recipe.difficulty <= max_difficulty)

    # Gesamtzeit = Vorbereitung + Kochen; null-Werte als 0 behandeln
    if max_time_min is not None:
        total_time = func.coalesce(Recipe.prep_time_min, 0) + func.coalesce(
            Recipe.cook_time_min, 0
        )
        stmt = stmt.where(total_time <= max_time_min)

    # Rezept muss ALLE angeforderten Tags besitzen (je Tag ein EXISTS-Subquery)
    if tags:
        for tag in tags:
            stmt = stmt.where(
                select(RecipeTag.id)
                .where(RecipeTag.recipe_id == Recipe.id, RecipeTag.tag == tag)
                .exists()
            )

    stmt = stmt.limit(limit)

    async with get_session() as session:
        result = await session.execute(stmt)
        recipes = result.scalars().all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "meal_type": r.meal_type,
            "difficulty": r.difficulty,
            "total_time_min": (r.prep_time_min or 0) + (r.cook_time_min or 0),
            "cost_tier": r.cost_tier,
            "tags": [t.tag for t in r.tags],
        }
        for r in recipes
    ]


# ── Tool 2: get_recipe_details ──────────────────────────────────────────────────

async def get_recipe_details(recipe_id: str) -> dict[str, Any] | None:
    """Lädt ein einzelnes Rezept vollständig: Zutaten, Schritte, Nährwerte, Tags.

    Gibt None zurück, wenn keine Rezept-ID passt.
    """
    stmt = (
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .options(
            selectinload(Recipe.instructions),
            selectinload(Recipe.recipe_ingredients).selectinload(
                RecipeIngredient.ingredient
            ),
            selectinload(Recipe.nutrition),
            selectinload(Recipe.tags),
        )
    )

    async with get_session() as session:
        result = await session.execute(stmt)
        recipe = result.scalar_one_or_none()

    if recipe is None:
        return None

    nutrition = None
    if recipe.nutrition:
        n = recipe.nutrition
        nutrition = {
            "calories_kcal": n.calories_kcal,
            "protein_g": n.protein_g,
            "carbs_g": n.carbs_g,
            "fat_g": n.fat_g,
            "fiber_g": n.fiber_g,
            "estimated": n.estimated,
        }

    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "servings": recipe.servings,
        "prep_time_min": recipe.prep_time_min,
        "cook_time_min": recipe.cook_time_min,
        "difficulty": recipe.difficulty,
        "meal_type": recipe.meal_type,
        "season": recipe.season,
        "cost_tier": recipe.cost_tier,
        "source_url": recipe.source_url,
        "ingredients": [
            {
                "name": ri.ingredient.name,
                "amount": ri.amount,
                "unit": ri.unit,
                "preparation": ri.preparation,
            }
            for ri in recipe.recipe_ingredients
        ],
        "steps": [
            {"step_number": s.step_number, "content": s.content}
            for s in recipe.instructions
        ],
        "nutrition_per_serving": nutrition,
        "tags": [t.tag for t in recipe.tags],
    }


# ── Tool-Schemas (OpenAI Function-Calling-Format) ───────────────────────────────
# Direkt als `tools=TOOL_SCHEMAS` an client.chat.completions.create() übergebbar.

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_recipes",
            "description": (
                "Sucht Rezepte in der Datenbank nach Kriterien wie Mahlzeitentyp, "
                "Zeitbudget, Schwierigkeit, Preisklasse und Diät-Tags. Gibt eine "
                "kompakte Trefferliste zurück. Für das vollständige Rezept danach "
                "get_recipe_details mit der zurückgegebenen id aufrufen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Freitext-Suchbegriff für Name/Beschreibung, z.B. 'Lasagne' oder 'Suppe'.",
                    },
                    "meal_type": {
                        "type": "string",
                        "enum": _MEAL_TYPES,
                        "description": "Art der Mahlzeit.",
                    },
                    "max_time_min": {
                        "type": "integer",
                        "description": "Maximale Gesamtzeit (Vorbereitung + Kochen) in Minuten.",
                    },
                    "max_difficulty": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Maximaler Schwierigkeitsgrad, 1 (einfach) bis 5 (anspruchsvoll).",
                    },
                    "cost_tier": {
                        "type": "string",
                        "enum": _COST_TIERS,
                        "description": "Preisklasse der Zutaten.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "enum": _TAGS},
                        "description": "Diät-/Allergen-Tags, die ALLE zutreffen müssen.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximale Anzahl Treffer (default 10).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recipe_details",
            "description": (
                "Lädt ein einzelnes Rezept vollständig: Zutaten mit Mengen, "
                "Zubereitungsschritte, Nährwerte pro Portion und Tags. Die recipe_id "
                "stammt aus einem vorherigen search_recipes-Aufruf."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipe_id": {
                        "type": "string",
                        "description": "Die ID des Rezepts (UUID-String aus search_recipes).",
                    }
                },
                "required": ["recipe_id"],
            },
        },
    },
]


# ── Dispatch: Tool-Name → Funktion ──────────────────────────────────────────────

_TOOL_FUNCTIONS = {
    "search_recipes": search_recipes,
    "get_recipe_details": get_recipe_details,
}


async def dispatch_tool_call(name: str, arguments: dict[str, Any]) -> Any:
    """Führt ein vom LLM angefordertes Tool anhand seines Namens aus.

    `arguments` ist das vom Modell gelieferte (bereits geparste) Argument-dict.
    """
    func_ = _TOOL_FUNCTIONS.get(name)
    if func_ is None:
        raise ValueError(f"Unbekanntes Tool: {name}")
    return await func_(**arguments)
