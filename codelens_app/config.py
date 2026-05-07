import os
import re
from dotenv import load_dotenv

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

SKIP_DIRS = {
    ".venv", "venv", "__pycache__", ".git",
    "migrations", "node_modules", "dist", "build",
}

STATE_FILE = os.path.join(os.path.dirname(__file__), "current_state.json")


def collection_name_from_path(path: str) -> str:
    base = os.path.basename(os.path.normpath(path))
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", base).lower()
    slug = slug.strip("_")
    return slug or "codebase"
