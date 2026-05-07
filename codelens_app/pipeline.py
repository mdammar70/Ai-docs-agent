import json
from .config import (
    NEO4J_URI, NEO4J_USER, NEO4J_PASS,
    OPENAI_API_KEY, QDRANT_URL, EMBED_MODEL,
    STATE_FILE, collection_name_from_path,
)
from .parser import parse_codebase
from .neo4j_writer import ingest_to_neo4j
from .ingest_qdrant import ingest_to_qdrant


def run_pipeline(codebase_path: str) -> str:
    collection = collection_name_from_path(codebase_path)
    print(f"Codebase  : {codebase_path}")
    print(f"Collection: {collection}")
    print()

    # ── Step 1: Parse ──────────────────────────────────────
    print("[1/3] Parsing codebase...")
    all_functions, all_classes, all_imports, all_file_paths = parse_codebase(codebase_path)
    print(f"  Functions : {len(all_functions)}")
    print(f"  Classes   : {len(all_classes)}")
    print(f"  Imports   : {len(all_imports)}")
    print(f"  Files     : {len(all_file_paths)}")
    print()

    if not all_functions:
        print("No Python functions found. Check the path and try again.")
        return None

    # ── Step 2: Neo4j ──────────────────────────────────────
    print("[2/3] Ingesting into Neo4j...")
    neo4j_stats = ingest_to_neo4j(
        NEO4J_URI, NEO4J_USER, NEO4J_PASS,
        all_functions, all_classes, all_imports,
    )
    print()

    # ── Step 3: Qdrant ─────────────────────────────────────
    print("[3/3] Embedding + uploading to Qdrant...")
    qdrant_stats = ingest_to_qdrant(
        NEO4J_URI, NEO4J_USER, NEO4J_PASS,
        OPENAI_API_KEY, QDRANT_URL, collection, EMBED_MODEL,
    )
    print()

    # ── Save state ─────────────────────────────────────────
    state = {
        "codebase_path": codebase_path,
        "collection_name": collection,
        "file_count": len(all_file_paths),
        "function_count": len(all_functions),
        "class_count": len(all_classes),
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"Done. State saved to {STATE_FILE}")
    print(f"Collection '{collection}' is ready for querying.")
    return collection


def load_state() -> dict | None:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
