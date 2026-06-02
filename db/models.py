"""SQLAlchemy 2.0 ORM-Modelle – spiegeln das ER-Diagramm aus dem Brainstorming wider.

Tabellen:
  recipes              – Kern-Rezeptdaten
  recipe_instructions  – Zubereitungsschritte (1:n zu recipes)
  ingredients          – Zutaten dedupliziert über alle Rezepte
  recipe_ingredients   – Junction-Tabelle (Rezept ↔ Zutat + Menge)
  recipe_nutrition     – Nährwerte pro Portion (1:1 zu recipes)
  recipe_tags          – Allergen-/Kategorietags (n zu recipes)
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


# ── Recipes ────────────────────────────────────────────────────────────────────

class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50))       # "dataset" | "scraper"
    source_url: Mapped[str | None] = mapped_column(Text)
    servings: Mapped[int] = mapped_column(Integer, default=1)
    prep_time_min: Mapped[int | None] = mapped_column(Integer)
    cook_time_min: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[int] = mapped_column(SmallInteger)  # 1–5
    meal_type: Mapped[str] = mapped_column(String(50))
    season: Mapped[str] = mapped_column(String(50))
    cost_tier: Mapped[str] = mapped_column(String(20))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Beziehungen
    instructions: Mapped[list[RecipeInstruction]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeInstruction.step_number"
    )
    recipe_ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    nutrition: Mapped[RecipeNutrition | None] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", uselist=False
    )
    tags: Mapped[list[RecipeTag]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )


# ── Instructions ───────────────────────────────────────────────────────────────

class RecipeInstruction(Base):
    __tablename__ = "recipe_instructions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="instructions")


# ── Ingredients (dedupliziert) ─────────────────────────────────────────────────

class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    english_name: Mapped[str | None] = mapped_column(String(255))
    # Platzhalter für pgvector-Embedding (wird später befüllt)
    vector_index: Mapped[str | None] = mapped_column(Text)

    recipe_ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="ingredient"
    )


# ── Junction: Recipe ↔ Ingredient + Menge ──────────────────────────────────────

class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_ingredient"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.id"), nullable=False)
    amount: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    preparation: Mapped[str | None] = mapped_column(String(255))

    recipe: Mapped[Recipe] = relationship(back_populates="recipe_ingredients")
    ingredient: Mapped[Ingredient] = relationship(back_populates="recipe_ingredients")


# ── Nutrition (1:1 zu Recipe) ──────────────────────────────────────────────────

class RecipeNutrition(Base):
    __tablename__ = "recipe_nutrition"

    recipe_id: Mapped[str] = mapped_column(
        ForeignKey("recipes.id"), primary_key=True
    )
    calories_kcal: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    fiber_g: Mapped[float | None] = mapped_column(Float)
    sodium_mg: Mapped[float | None] = mapped_column(Float)
    iron_mg: Mapped[float | None] = mapped_column(Float)
    calcium_mg: Mapped[float | None] = mapped_column(Float)
    vitamin_c_mg: Mapped[float | None] = mapped_column(Float)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)

    recipe: Mapped[Recipe] = relationship(back_populates="nutrition")


# ── Tags ───────────────────────────────────────────────────────────────────────

class RecipeTag(Base):
    __tablename__ = "recipe_tags"
    __table_args__ = (
        UniqueConstraint("recipe_id", "tag", name="uq_recipe_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="tags")
