# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**CodeLens** — a Python codebase analysis tool that ingests a Python project's structure into Neo4j (graph DB), embeds function metadata into Qdrant (vector DB), and enables natural-language Q&A about the codebase using OpenAI.

The project has two parts:

1. **`codelens_app/`** — CLI application to ingest any Python codebase and query it
2. **Jupyter notebooks** (`main.ipynb`, `codelens_qdrant.ipynb`, `codelens_query.ipynb`) — reference/original implementation

## Data Flow

```
Python files → AST parse → Neo4j (graph) → Qdrant (vectors) → OpenAI (answers)
```

- **Neo4j** stores the code graph: `File`, `Class`, `Function`, `ExternalLib` nodes with `CALLS`, `INHERITS`, `IMPORTS`, `DEFINED_IN`, `BELONGS_TO`, `CALLS_EXTERNAL` edges
- **Qdrant** stores embedded function chunks (rich text with source, docstring, params, graph context) for semantic search
- **OpenAI** (`text-embedding-3-small` for embeddings, `gpt-4o-mini` for answer generation)

## CLI Application (`codelens_app/`)

### Quick Start

```bash
cd codelens_app
pip install -r requirements.txt

# Ingest any Python codebase
python -m codelens_app.cli ingest <path-to-codebase>

# Ask questions
python -m codelens_app.cli ask "how does user authentication work?"
python -m codelens_app.cli ask "where is validate_email used?"

# Check status
python -m codelens_app.cli status
```

### How It Works

Provide any local Python codebase path — the CLI:
1. **Parses** all `.py` files via AST (functions, classes, imports, calls)
2. **Ingests** the code graph into Neo4j (File/Class/Function nodes, CALLS/INHERITS/IMPORTS edges)
3. **Embeds** each function into Qdrant via OpenAI (`text-embedding-3-small`)
4. **Classifies** queries (semantic / flow / reverse_lookup), searches vectors, expands the graph, generates grounded answers with GPT-4o-mini

Collection name is auto-derived from the folder name. Re-running ingest clears old data.

### Module Structure

| File | Purpose |
|---|---|
| `config.py` | Loads `.env`, exports all settings (Neo4j, Qdrant, OpenAI) |
| `parser.py` | AST parser — extracts functions, classes, imports, calls |
| `neo4j_writer.py` | Clears DB, creates indexes, writes graph nodes + edges |
| `ingest_qdrant.py` | Fetches from Neo4j, builds chunks, embeds, uploads to Qdrant |
| `query_engine.py` | Classifies intent, vector search, graph expansion, LLM answers |
| `pipeline.py` | Orchestrates parse → Neo4j → Qdrant, saves state |
| `cli.py` | CLI entry point: `ingest`, `ask`, `status` commands |

### Configuration

All config via `.env` file (see `codelens_app/` root):
- `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASS` — Neo4j connection
- `OPENAI_API_KEY` — OpenAI API key
- `QDRANT_URL` — Qdrant endpoint
- `EMBED_MODEL` — embedding model (default: `text-embedding-3-small`)
- `LLM_MODEL` — LLM for answers (default: `gpt-4o-mini`)

Requires local services: Neo4j + Qdrant running.

## Notebooks (Reference)

The three Jupyter notebooks contain the original implementation and are kept as reference:

### Notebook 1: `main.ipynb` (Neo4j Ingestion)
- Cell 1: Install `neo4j` pip package
- Cell 2: Set `CODEBASE_PATH`, Neo4j credentials, test connection
- Cell 3: Define AST parser (extracts functions, classes, imports, call relationships)
- Cell 4: Parse all `.py` files under `CODEBASE_PATH`
- Cell 5: Spot-check parsed output
- Cell 6: Resolve call strings → internal CALLS edges + external CALLS_EXTERNAL edges
- Cell 7: Define `Neo4jWriter` class (clear DB, create indexes, write nodes/edges)
- Cell 8: Run full write pipeline
- Cell 9: Verify counts in Neo4j
- Cell 10: Reference Cypher queries for Neo4j Browser

### Notebook 2: `codelens_qdrant.ipynb` (Vector Embedding)
- Cell 1: Install `qdrant-client`, `openai`, `neo4j`
- Cell 2: Config + test all 3 connections
- Cell 3: Fetch all functions from Neo4j with their call relationships
- Cell 4: Build rich text chunks (function metadata + source + graph context)
- Cell 5: Create Qdrant collection (1536-dim, cosine distance)
- Cell 6: Embed all chunks via OpenAI batch API call
- Cell 7: Upload to Qdrant with full payload metadata
- Cell 8: Test raw vector search with 5 sample questions
- Cell 9: Define `ask()` — full QA function (vector search → context building → GPT-4o-mini answer with citations)
- Cell 10: Interactive question-answering
- Cell 11: Suggested test questions
- Cell 12: Batch question testing

### Notebook 3: `codelens_query.ipynb` (Query Engine)
- Combines vector search + graph expansion + LLM generation
- Adds **query classification**: `reverse_lookup` ("where is X used?"), `flow` ("how does X work?"), or `semantic`
- `graph_reverse_lookup()` — Cypher reverse CALLS query to find all callers of a function
- `expand_graph()` — for each vector result, fetch callees, callers, class, file from Neo4j
- `build_context()` — merge vector results + graph relationships into LLM context
- `generate_answer()` — send context + question to GPT-4o-mini with strict no-hallucination prompt
- `ask()` — top-level function routing by intent

## Key Design Decisions

- **Node ID format**: `path/to/file.py::ClassName::function_name` (stable, unique, human-readable)
- **Qdrant point IDs**: MD5 hash of the Neo4j node_id, mod 2^63 (integer requirement)
- **Rich chunk text**: Includes function signature, file location, class, params, return type, docstring, internal calls, external uses, and full source code — maximizes embedding quality
- **Graph context in payload**: `calls_internal` and `calls_external` arrays stored alongside vectors so the LLM gets relationship data without a separate Neo4j query at answer time (in notebook 2; notebook 3 re-queries Neo4j for graph expansion)
- **Temperature 0** for all LLM calls — deterministic, grounded answers

## Configuration (Notebooks — Legacy)

The notebooks have their own config in Cell 2. For the CLI app, config is in `.env` (see above).
