"""Central config: source URL, DB connection, LLM model, thresholds.

Loaded once from environment (.env in dev, real env vars in CI/containers).
"""
import os

from dotenv import load_dotenv

load_dotenv()

FDA_SOURCE_URL = (
    "https://www.fda.gov/food/dietary-supplements/"
    "information-select-dietary-supplement-ingredients-and-other-substances"
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/ingredient_lens"
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

NORMALIZATION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("NORMALIZATION_CONFIDENCE_THRESHOLD", "0.7")
)

FUZZY_MATCH_SCORE_THRESHOLD = float(os.environ.get("FUZZY_MATCH_SCORE_THRESHOLD", "85"))

RAW_HTML_DIR = "data/raw"
PARSED_JSON_PATH = "data/parsed/ingredients_raw.json"
NORMALIZED_JSON_PATH = "data/normalized/ingredients_normalized.json"
