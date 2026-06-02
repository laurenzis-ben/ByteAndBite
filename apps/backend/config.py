from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
FDC_API_KEY: str = os.environ.get("FDC_API_KEY", "DEMO_KEY")

OPENAI_MODEL: str = "gpt-4o"
NORMALIZE_CONCURRENCY: int = 10  # parallele OpenAI-Calls

FDC_BASE_URL: str = "https://api.nal.usda.gov/fdc/v1"

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/byteandbite",
)

DEFAULT_OUTPUT_DIR: Path = Path("output")
RECIPES_SUBDIR: str = "recipes"
MANIFEST_FILENAME: str = "manifest.json"
