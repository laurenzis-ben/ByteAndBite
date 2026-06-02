from abc import ABC, abstractmethod
from models.recipe import RawRecipe


class RecipeSource(ABC):
    @abstractmethod
    def fetch(self, n: int) -> list[RawRecipe]:
        """Gibt bis zu `n` Rezepte aus der Quelle zurück."""
        ...
