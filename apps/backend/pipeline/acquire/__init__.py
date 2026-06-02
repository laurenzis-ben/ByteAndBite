from .base import RecipeSource
from .dataset import DatasetSource
from .scraper import ScraperSource
from typing import Literal


def get_source(name: Literal["dataset", "scraper"]) -> RecipeSource:
    if name == "dataset":
        return DatasetSource()
    return ScraperSource()


__all__ = ["RecipeSource", "DatasetSource", "ScraperSource", "get_source"]
