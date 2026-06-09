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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from db.models import Ingredient, Recipe, RecipeIngredient, RecipeNutrition, RecipeTag
from db.session import get_session

# Kontrollierte Vokabulare – spiegeln die Literal-Types aus models/recipe.py.
# Werden im Tool-Schema als enum exponiert, damit das LLM nur gültige Werte sendet.
_MEAL_TYPES = ["Frühstück", "Mittagessen", "Abendessen", "Snack", "Dessert"]
_COST_TIERS = ["günstig", "mittel", "teuer"]
_TAGS = ["glutenfrei", "laktosefrei", "nussfrei", "vegan", "vegetarisch", "ei-frei"]


def _summary(recipe: Recipe) -> dict[str, Any]:
    """Kompakte Rezept-Felder für Trefferlisten (gemeinsames Format der Such-Tools).

    Setzt voraus, dass recipe.tags geladen ist (selectinload).
    """
    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "meal_type": recipe.meal_type,
        "difficulty": recipe.difficulty,
        "total_time_min": (recipe.prep_time_min or 0) + (recipe.cook_time_min or 0),
        "cost_tier": recipe.cost_tier,
        "tags": [t.tag for t in recipe.tags],
    }


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


# ── Tool 3: find_recipes_by_ingredients ─────────────────────────────────────────

async def find_recipes_by_ingredients(
    ingredients: list[str],
    meal_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Findet Rezepte, die möglichst viele der angegebenen Vorrats-Zutaten nutzen.

    Jede Vorrats-Zutat wird per Substring (case-insensitive) gegen die Rezept-
    Zutaten gematcht ('Ei' trifft 'Eier'). Ergebnis ist absteigend nach Anzahl
    getroffener Vorrats-Zutaten sortiert; Rezepte ohne Treffer entfallen.

    Pro Rezept zusätzlich: matched_ingredients (getroffene Vorrats-Zutaten),
    match_count, total_ingredients und missing_ingredients ('dir fehlt noch …').
    """
    if not ingredients:
        return []

    # Kandidaten: Rezepte mit mindestens einer passenden Zutat (EXISTS-Subquery).
    match_any = or_(*[Ingredient.name.ilike(f"%{term}%") for term in ingredients])
    stmt = (
        select(Recipe)
        .where(
            select(RecipeIngredient.id)
            .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(RecipeIngredient.recipe_id == Recipe.id, match_any)
            .exists()
        )
        .options(
            selectinload(Recipe.tags),
            selectinload(Recipe.recipe_ingredients).selectinload(
                RecipeIngredient.ingredient
            ),
        )
    )
    if meal_type:
        stmt = stmt.where(Recipe.meal_type == meal_type)

    async with get_session() as session:
        result = await session.execute(stmt)
        recipes = result.scalars().unique().all()

    lowered = [(term, term.lower()) for term in ingredients]
    out: list[dict[str, Any]] = []
    for r in recipes:
        recipe_ing_names = [ri.ingredient.name for ri in r.recipe_ingredients]

        # Welche Vorrats-Begriffe kommen im Rezept vor?
        matched_terms = [
            term
            for term, low in lowered
            if any(low in name.lower() for name in recipe_ing_names)
        ]
        if not matched_terms:
            continue

        # Rezept-Zutaten, die durch keinen Vorrats-Begriff abgedeckt sind.
        missing = [
            name
            for name in recipe_ing_names
            if not any(low in name.lower() for _, low in lowered)
        ]

        summary = _summary(r)
        summary.update(
            matched_ingredients=matched_terms,
            match_count=len(matched_terms),
            total_ingredients=len(recipe_ing_names),
            missing_ingredients=missing,
        )
        out.append(summary)

    out.sort(key=lambda d: d["match_count"], reverse=True)
    return out[:limit]


# ── Tool 4: filter_by_nutrition ─────────────────────────────────────────────────

async def filter_by_nutrition(
    min_protein_g: float | None = None,
    max_calories_kcal: float | None = None,
    min_calories_kcal: float | None = None,
    max_carbs_g: float | None = None,
    max_fat_g: float | None = None,
    min_fiber_g: float | None = None,
    meal_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Sucht Rezepte nach Nährwert-Grenzen pro Portion (Kalorien + Makronährstoffe).

    Grenzwerte sind inklusiv. Rezepte ohne Nährwert-Datensatz entfallen (Inner Join):
    ein fehlender Wert kann eine Grenze nicht erfüllen. Gibt kompakte Treffer inkl.
    nutrition_per_serving zurück, damit der Agent direkt vergleichen kann.
    """
    stmt = (
        select(Recipe)
        .join(RecipeNutrition, RecipeNutrition.recipe_id == Recipe.id)
        .options(selectinload(Recipe.tags), selectinload(Recipe.nutrition))
    )

    if min_protein_g is not None:
        stmt = stmt.where(RecipeNutrition.protein_g >= min_protein_g)
    if max_calories_kcal is not None:
        stmt = stmt.where(RecipeNutrition.calories_kcal <= max_calories_kcal)
    if min_calories_kcal is not None:
        stmt = stmt.where(RecipeNutrition.calories_kcal >= min_calories_kcal)
    if max_carbs_g is not None:
        stmt = stmt.where(RecipeNutrition.carbs_g <= max_carbs_g)
    if max_fat_g is not None:
        stmt = stmt.where(RecipeNutrition.fat_g <= max_fat_g)
    if min_fiber_g is not None:
        stmt = stmt.where(RecipeNutrition.fiber_g >= min_fiber_g)
    if meal_type:
        stmt = stmt.where(Recipe.meal_type == meal_type)

    stmt = stmt.limit(limit)

    async with get_session() as session:
        result = await session.execute(stmt)
        recipes = result.scalars().unique().all()

    out: list[dict[str, Any]] = []
    for r in recipes:
        n = r.nutrition
        summary = _summary(r)
        summary["nutrition_per_serving"] = {
            "calories_kcal": n.calories_kcal,
            "protein_g": n.protein_g,
            "carbs_g": n.carbs_g,
            "fat_g": n.fat_g,
            "fiber_g": n.fiber_g,
        }
        out.append(summary)
    return out


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
    {
        "type": "function",
        "function": {
            "name": "find_recipes_by_ingredients",
            "description": (
                "Findet Rezepte, die möglichst viele der vorhandenen Zutaten "
                "verwenden ('Was kann ich mit dem kochen, was ich da habe?'). "
                "Sortiert nach Trefferquote und nennt pro Rezept die fehlenden "
                "Zutaten. Für das vollständige Rezept danach get_recipe_details "
                "mit der zurückgegebenen id aufrufen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ingredients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Vorhandene Zutaten, z.B. ['Eier', 'Spinat', 'Feta'].",
                    },
                    "meal_type": {
                        "type": "string",
                        "enum": _MEAL_TYPES,
                        "description": "Optional: Art der Mahlzeit eingrenzen.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximale Anzahl Treffer (default 10).",
                    },
                },
                "required": ["ingredients"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "filter_by_nutrition",
            "description": (
                "Sucht Rezepte nach Nährwert-Grenzen pro Portion (Kalorien und "
                "Makronährstoffe), z.B. 'proteinreich und kalorienarm'. Grenzwerte "
                "sind inklusiv. Gibt eine kompakte Trefferliste inkl. Nährwerten "
                "zurück; für das vollständige Rezept danach get_recipe_details aufrufen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_protein_g": {
                        "type": "number",
                        "description": "Mindest-Protein pro Portion in Gramm.",
                    },
                    "max_calories_kcal": {
                        "type": "number",
                        "description": "Maximale Kalorien pro Portion (kcal).",
                    },
                    "min_calories_kcal": {
                        "type": "number",
                        "description": "Minimale Kalorien pro Portion (kcal).",
                    },
                    "max_carbs_g": {
                        "type": "number",
                        "description": "Maximale Kohlenhydrate pro Portion in Gramm.",
                    },
                    "max_fat_g": {
                        "type": "number",
                        "description": "Maximales Fett pro Portion in Gramm.",
                    },
                    "min_fiber_g": {
                        "type": "number",
                        "description": "Mindest-Ballaststoffe pro Portion in Gramm.",
                    },
                    "meal_type": {
                        "type": "string",
                        "enum": _MEAL_TYPES,
                        "description": "Optional: Art der Mahlzeit eingrenzen.",
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
]


# ── Dispatch: Tool-Name → Funktion ──────────────────────────────────────────────

_TOOL_FUNCTIONS = {
    "search_recipes": search_recipes,
    "get_recipe_details": get_recipe_details,
    "find_recipes_by_ingredients": find_recipes_by_ingredients,
    "filter_by_nutrition": filter_by_nutrition,
}


async def dispatch_tool_call(name: str, arguments: dict[str, Any]) -> Any:
    """Führt ein vom LLM angefordertes Tool anhand seines Namens aus.

    `arguments` ist das vom Modell gelieferte (bereits geparste) Argument-dict.
    """
    func_ = _TOOL_FUNCTIONS.get(name)
    if func_ is None:
        raise ValueError(f"Unbekanntes Tool: {name}")
    return await func_(**arguments)
