# Design: Zwei neue Agent-Tools (Vorrat & Nährwerte)

**Datum:** 2026-06-09
**Komponente:** Agent-Tool-Schicht (`apps/backend/agent/tools.py`)
**Status:** Genehmigt (Brainstorming abgeschlossen)

## Ziel

Die Agent-Tool-Schicht um zwei neue Tools erweitern, damit das LLM zusätzliche,
alltagsnahe Rezept-Anfragen beantworten kann:

1. `find_recipes_by_ingredients` – „Was kann ich mit dem kochen, was ich da habe?“
2. `filter_by_nutrition` – „Finde mir ein proteinreiches, kalorienarmes Gericht.“

Beide aktivieren bislang ungenutzte Schema-Felder (`ingredients`-Tabelle bzw.
`RecipeNutrition`) und fügen sich nahtlos in das bestehende
**Zwei-Stufen-Pattern** ein: Such-Tool liefert kompakte Treffer →
danach `get_recipe_details` für das vollständige Rezept.

## Kontext / Ist-Zustand

- Tools liegen in `apps/backend/agent/tools.py`: `search_recipes`, `get_recipe_details`.
- Jedes Tool = async Funktion + Eintrag in `TOOL_SCHEMAS` (OpenAI-Function-Calling)
  + Registrierung in `_TOOL_FUNCTIONS`; Re-Export in `apps/backend/agent/__init__.py`.
- Datenzugriff über `get_session()` (`apps/backend/db/session.py`), async SQLAlchemy 2.0.
- Relevante Modelle (`apps/backend/db/models.py`): `Recipe`, `RecipeIngredient`,
  `Ingredient`, `RecipeNutrition`, `RecipeTag`.
- Kontrollierte Vokabulare (`_MEAL_TYPES`, `_COST_TIERS`, `_TAGS`) werden als
  `enum` im Schema exponiert — diese Konvention übernehmen beide neuen Tools.
- Es existiert **noch kein Projekt-Test-Setup** (nur `pytest`/`pytest-asyncio`
  als Dev-Deps in `pyproject.toml`). Dieses Design führt ein minimales Harness ein.

## Tool 3 – `find_recipes_by_ingredients`

### Signatur
```python
async def find_recipes_by_ingredients(
    ingredients: list[str],
    meal_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]
```

### Verhalten
- Pro angefragter Zutat ein **case-insensitive Substring-Match** (`ilike`) gegen
  `Ingredient.name` (z. B. „Ei“ trifft „Eier“).
- Über den Join `Recipe → RecipeIngredient → Ingredient` wird ermittelt, wie
  viele der angefragten Zutaten ein Rezept abdeckt.
- **Ranking:** absteigend nach `match_count` (Anzahl getroffener Vorrats-Zutaten).
  Nur Rezepte mit `match_count ≥ 1`.
- `meal_type` (optional, `enum`) als zusätzlicher Filter.
- `limit` begrenzt die Trefferzahl (default 10).

### Rückgabe (pro Rezept)
Kompakte Felder wie `search_recipes`, **plus**:
- `matched_ingredients`: Liste der Vorrats-Zutaten, die im Rezept vorkommen.
- `match_count`: Anzahl getroffener Vorrats-Zutaten.
- `total_ingredients`: Gesamtzahl Zutaten des Rezepts.
- `missing_ingredients`: im Rezept benötigte Zutaten, die **nicht** im Vorrat sind
  („dir fehlt noch …“).

### Begründung
`missing_ingredients` macht „fast kochbare“ Rezepte für den Agenten sichtbar,
ohne ein separates Tool. Der Zwei-Stufen-Vertrag bleibt erhalten (kompakt →
danach `get_recipe_details`).

### Implementierungshinweise
- Matching: pro Begriff `Ingredient.name.ilike(f"%{begriff}%")`.
- `match_count` und Ranking lassen sich entweder per SQL-Aggregation
  (`func.count(distinct ...)` + `group_by` + `order_by`) oder durch Nachladen der
  Zutaten je Kandidat (`selectinload(Recipe.recipe_ingredients)`) und Zählung in
  Python berechnen. **Empfehlung:** SQL-Aggregation für das Ranking/Limit, danach
  `missing_ingredients` aus den geladenen Rezept-Zutaten ableiten.
- Ein Vorrats-Begriff, der mehrere Rezept-Zutaten trifft, zählt als **eine**
  getroffene Vorrats-Zutat (distinct über die Anfrage-Begriffe).

## Tool 4 – `filter_by_nutrition`

### Signatur
```python
async def filter_by_nutrition(
    min_protein_g: float | None = None,
    max_calories_kcal: float | None = None,
    min_calories_kcal: float | None = None,
    max_carbs_g: float | None = None,
    max_fat_g: float | None = None,
    min_fiber_g: float | None = None,
    meal_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]
```

### Verhalten
- Join `Recipe → RecipeNutrition`. Jeder gesetzte Parameter wird zu einer
  `WHERE`-Bedingung auf dem jeweiligen `RecipeNutrition`-Feld. Grenzwerte sind
  **inklusiv** (`>=` / `<=`) — konsistent zu `max_difficulty <= x` in `search_recipes`.
- **NULL-Handling:** Rezepte ohne Wert für ein gefiltertes Feld fallen heraus
  (kein `coalesce` — ein fehlender Protein-Wert kann „≥ 30 g“ nicht erfüllen).
  Umsetzung: innerer Join statt Outer Join; gefilterte Felder sind damit non-NULL.
- `meal_type` (optional, `enum`) als praktischer Kombi-Filter
  (häufigster Wunsch: „proteinreiches Mittagessen“).
- `limit` begrenzt die Trefferzahl (default 10).

### Rückgabe (pro Rezept)
Kompakte Felder wie `search_recipes`, **plus** `nutrition_per_serving`
(kcal + Makros: `calories_kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`),
damit der Agent direkt vergleichen und seine Auswahl begründen kann.

### Begründung
Aktiviert die heute in der Suche ungenutzte `RecipeNutrition`-Tabelle. Beschränkung
auf Kalorien + Makros (MVP) deckt die meisten Anfragen ab und hält das Schema schlank.

## Gemeinsame Punkte

- Beide async, nutzen `get_session()`, geben JSON-serialisierbare `dict`s zurück.
- Schemas: `meal_type` als `enum` (`_MEAL_TYPES`) wie im Bestand.
- Registrierung an drei Stellen — analog zu den bestehenden Tools:
  1. `_TOOL_FUNCTIONS` (Dispatch)
  2. `TOOL_SCHEMAS` (Function-Calling-Definition)
  3. `apps/backend/agent/__init__.py` (Re-Export + `__all__`)
- Deutschsprachige Tool-/Parameter-Beschreibungen wie im Bestand.

## Tests

Es gibt noch kein Projekt-Test-Harness. Dieses Design führt ein minimales ein:

- **In-Memory-DB:** SQLite via `aiosqlite` (neue Dev-Dependency), Tabellen über
  `Base.metadata.create_all`. `init_engine(url=...)` erlaubt die Injektion der
  Test-URL ohne Produktiv-Konfiguration.
- **Fixture (`conftest.py`):** legt eine Handvoll Rezepte mit Zutaten und
  Nährwerten an (deterministischer Seed).
- **`find_recipes_by_ingredients`:** Match-Zählung korrekt, Ranking nach
  `match_count`, `missing_ingredients` stimmt, `ilike`-Teiltreffer („Ei“→„Eier“),
  leere/0-Treffer-Fälle.
- **`filter_by_nutrition`:** Grenzwerte inklusiv (`>=` / `<=`),
  NULL-Ausschluss, Kombination mit `meal_type`.

> Hinweis: SQLite kennt `ilike` als `LIKE` (case-insensitive bei ASCII).
> Für die Tests ausreichend; Produktion läuft auf PostgreSQL (`asyncpg`).

## Bewusst weggelassen (YAGNI)

- `max_missing`-Schwellwert bei `find_recipes_by_ingredients`.
- Mikronährstoffe (`sodium_mg`, `iron_mg`, `calcium_mg`, `vitamin_c_mg`) in
  `filter_by_nutrition`.
- Mengen-/Einheiten-Bewertung beim Zutaten-Match (nur Vorhandensein zählt).
- Embedding-/Vektor-Matching für Zutaten (`Ingredient.vector_index` bleibt unberührt).

## Betroffene Dateien

| Datei | Änderung |
|---|---|
| `apps/backend/agent/tools.py` | 2 Funktionen, 2 Schema-Einträge, 2 Dispatch-Registrierungen |
| `apps/backend/agent/__init__.py` | 2 Re-Exports + `__all__` |
| `apps/backend/pyproject.toml` | Dev-Dep `aiosqlite` ergänzen |
| `apps/backend/tests/conftest.py` | neu: In-Memory-DB-Fixture + Seed |
| `apps/backend/tests/test_tools.py` | neu: Tests für beide Tools |
