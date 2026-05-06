# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**CodeLens** — a Python codebase analysis tool that ingests a Python project's structure into Neo4j (graph DB), embeds function metadata into Qdrant (vector DB), and enables natural-language Q&A about the codebase using OpenAI.

The project is organized as three Jupyter notebooks that form a pipeline:

1. **`main.ipynb`** — Parse a Python codebase and ingest into Neo4j
2. **`codelens_qdrant.ipynb`** — Pull functions from Neo4j, embed with OpenAI, store in Qdrant, test semantic search
3. **`codelens_query.ipynb`** — Full query engine combining vector search + graph traversal + LLM answer generation

## Data Flow

```
Python files → AST parse → Neo4j (graph) → Qdrant (vectors) → OpenAI (answers)
```

- **Neo4j** stores the code graph: `File`, `Class`, `Function`, `ExternalLib` nodes with `CALLS`, `INHERITS`, `IMPORTS`, `DEFINED_IN`, `BELONGS_TO`, `CALLS_EXTERNAL` edges
- **Qdrant** stores embedded function chunks (rich text with source, docstring, params, graph context) for semantic search
- **OpenAI** (`text-embedding-3-small` for embeddings, `gpt-4o-mini` for answer generation)

## Running the Notebooks

Requires local services:
- **Neo4j** running at `bolt://localhost:7687` (default credentials: `neo4j` / `password123`)
- **Qdrant** running at `http://localhost:6333`
- **OpenAI API key** set in notebook config cells

Run cells top-to-bottom in each notebook. Each cell prints what it did.

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

## Configuration

All config is in Cell 2 of each notebook:
- `CODEBASE_PATH` — path to the Python codebase to analyze (default: `D:\test-codebase`)
- `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASS` — Neo4j connection
- `OPENAI_API_KEY` — OpenAI API key
- `QDRANT_URL` — Qdrant endpoint
- `COLLECTION` — Qdrant collection name (default: `test_codebase`)
- `EMBED_MODEL` — `text-embedding-3-small` (1536 dims)
