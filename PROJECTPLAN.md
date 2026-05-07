# CodeLens — Complete Project Plan for Claude Code

## What Is CodeLens

An AI-powered Developer Documentation Agent. Developers point it at a Python codebase and can:

1. Ask natural language questions and get grounded answers with exact file + line citations
2. Auto-generate docstrings for undocumented functions with a human review + approval step before anything is written to disk

---

## Tech Stack

| Layer            | Technology                                 |
| ---------------- | ------------------------------------------ |
| Backend          | Python 3.11, FastAPI                       |
| AI Orchestration | LangGraph, LangChain                       |
| LLM + Embeddings | OpenAI gpt-4o-mini, text-embedding-3-small |
| Graph Database   | Neo4j Desktop (bolt://localhost:7687)      |
| Vector Database  | Qdrant Docker (http://localhost:6333)      |
| AST Parser       | Python stdlib `ast` module                 |
| Evaluation       | RAGAS                                      |
| Frontend         | React + Vite + Tailwind CSS                |
| Deployment       | Railway                                    |

---

## Project Structure (target)

```
codelens/
├── backend/
│   ├── main.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── parser.py
│   │   ├── graph_builder.py
│   │   └── embedder.py
│   ├── query/
│   │   ├── __init__.py
│   │   ├── query_graph.py
│   │   ├── classifier.py
│   │   ├── retrievers.py
│   │   ├── merger.py
│   │   └── generator.py
│   ├── docgen/
│   │   ├── __init__.py
│   │   └── docgen_graph.py
│   ├── db/
│   │   ├── neo4j_client.py
│   │   └── qdrant_client.py
│   └── api/
│       └── routes.py
├── frontend/
│   └── (React app)
├── notebooks/
│   ├── codelens_ingest.ipynb
│   ├── codelens_qdrant.ipynb
│   └── codelens_query.ipynb
├── requirements.txt
└── docker-compose.yml
```

---

## What Is Already Built

Everything below lives in Jupyter notebooks in VSCode. It is working and tested against a real codebase at `D:\test-codebase`.

### Notebook 1 — codelens_ingest.ipynb (COMPLETE)

Ingests a local Python codebase into Neo4j.

What it does:

- Walks all `.py` files using `pathlib.Path.rglob`
- Parses each file with Python's stdlib `ast` module
- Extracts: Function nodes, Class nodes, File nodes, import relationships, internal CALLS edges, external lib calls
- Resolves raw call strings (e.g. `"self.validate"`) to actual node IDs in a second pass
- Writes everything to Neo4j using `MERGE` (idempotent — safe to re-run)

Node ID format: `"services/user_service.py::UserService::create_user"`

What is in Neo4j after ingestion (test codebase):

- 20 Function nodes
- 6 Class nodes
- 7 File nodes
- 14 ExternalLib nodes
- 26 DEFINED_IN edges
- 21 CALLS_EXTERNAL edges
- 15 BELONGS_TO edges
- 15 CALLS edges
- 12 IMPORTS edges
- 1 INHERITS edge

Neo4j indexes already created:

```cypher
CREATE INDEX fn_name  IF NOT EXISTS FOR (f:Function) ON (f.name);
CREATE INDEX fn_file  IF NOT EXISTS FOR (f:Function) ON (f.file);
CREATE INDEX cls_name IF NOT EXISTS FOR (c:Class)    ON (c.name);
CREATE INDEX fi_path  IF NOT EXISTS FOR (f:File)     ON (f.path);
```

### Notebook 2 — codelens_qdrant.ipynb (COMPLETE)

Embeds all functions into Qdrant for semantic search.

What it does:

- Pulls all 20 functions from Neo4j with their call relationships
- Builds a rich text chunk per function: file + class + params + docstring + source code + what it calls
- Embeds all chunks in one OpenAI API call using `text-embedding-3-small` (1536 dims)
- Uploads to Qdrant collection `"test_codebase"` with full metadata as payload
- Basic `ask()` function: vector search → GPT → answer with file:line citations

Verified working: asking "where is email validation?" correctly returns `validate_email` in `utils/helpers.py:5`.

### Notebook 3 — codelens_query.ipynb (COMPLETE)

Full GraphRAG query pipeline.

What it does:

- `classify_intent(question)` — LLM call classifies as SEMANTIC / STRUCTURAL / HYBRID
- `retrieve_semantic(question)` — embeds question, searches Qdrant, returns normalized results
- `retrieve_structural(question)` — LLM generates Cypher from question, runs on Neo4j, returns results. Falls back to semantic if Cypher fails or returns 0 rows
- `merge_results(semantic, structural)` — deduplicates by `file::name` key, boosts items found in both retrievers, sorts by score, returns top 8
- `ask(question)` — full pipeline: classify → retrieve → merge → GPT → cited answer with source list

Graph schema fed to the Cypher generator (hardcoded for test codebase):

- Nodes: Function, Class, File, ExternalLib with their properties
- Relationships: CALLS, CALLS_EXTERNAL, DEFINED_IN, BELONGS_TO, INHERITS, IMPORTS

---

## What Needs to Be Built

### Phase 1 — LangGraph Query Workflow

Convert the notebook `ask()` into a proper LangGraph `StateGraph`. This is the upgrade from a linear function to a proper agentic workflow with retry logic.

State object:

```python
class QueryState(TypedDict):
    question: str
    intent: str
    semantic_results: list
    structural_results: list
    merged_results: list
    answer: str
    citations: list
    retry_count: int
    critique_passed: bool
```

Nodes to build:

1. `classifier_node` — runs `classify_intent()`, sets `intent`
2. `retriever_node` — runs semantic and/or structural retrieval based on intent
3. `merger_node` — runs `merge_results()`, deduplicates and ranks
4. `generator_node` — GPT generates answer with citations
5. `critique_node` — second LLM call checks: is the answer grounded? returns PASS or FAIL
6. Conditional edge — if FAIL and `retry_count < 2` → back to retriever node with broader search. If PASS → END

File: `backend/query/query_graph.py`

Dependencies to install:

```
pip install langgraph langchain langchain-openai
```

### Phase 2 — FastAPI Backend

Wrap the ingestion pipeline and LangGraph query workflow in a FastAPI app.

Endpoints:

```
POST /ingest
  body: { codebase_path: str }
  runs full ingestion pipeline as a background task
  returns: { codebase_id: str, status: "processing" }

GET  /status/{codebase_id}
  returns: { status: "processing"|"complete"|"failed", node_count: int, edge_count: int }

POST /query
  body: { codebase_id: str, question: str }
  runs LangGraph query workflow
  returns: { answer: str, citations: list, intent: str, sources: list }

GET  /graph/summary/{codebase_id}
  returns: { nodes: {Function: int, Class: int, ...}, edges: {CALLS: int, ...} }
```

Important notes:

- Ingestion runs as a FastAPI `BackgroundTask` — it takes 30-120 seconds on real codebases
- Each ingestion gets a `codebase_id` (uuid) so multiple codebases can be loaded
- Neo4j node IDs must include `codebase_id` prefix to namespace them: `"{codebase_id}::services/user_service.py::UserService::create_user"`
- Qdrant collection name = `codebase_id`

File structure:

- `backend/main.py` — FastAPI app init
- `backend/api/routes.py` — all route handlers
- `backend/ingestion/parser.py` — move notebook parser code here
- `backend/ingestion/graph_builder.py` — move Neo4j write code here
- `backend/ingestion/embedder.py` — move Qdrant embed + upload code here
- `backend/db/neo4j_client.py` — Neo4j driver singleton
- `backend/db/qdrant_client.py` — Qdrant client singleton

Dependencies:

```
pip install fastapi uvicorn python-multipart
```

### Phase 3 — Doc Generation Workflow (LangGraph)

A second LangGraph graph for auto-generating docstrings with human approval.

Nodes:

1. `find_undocumented_node` — Cypher query: `MATCH (f:Function) WHERE f.docstring IS NULL AND NOT f.name STARTS WITH '_'`
2. `context_retriever_node` — for each function: pull its source, what it calls, what calls it, which class it belongs to
3. `doc_writer_node` — GPT writes a docstring in Google style format
4. `critique_node` — second LLM validates the docstring: is it accurate? does it describe parameters and return value correctly?
5. `human_checkpoint` — `interrupt_before` this node: show the draft to the developer and wait
6. `write_back_node` — if approved: use Python `ast` to locate the function in the file and inject the docstring. Write the file back to disk.

FastAPI endpoints for doc generation:

```
GET  /docs/undocumented/{codebase_id}
  returns list of all functions with no docstring

POST /docs/generate/{codebase_id}/{function_id}
  triggers doc generation for one function
  returns: { draft_docstring: str, function_id: str }

POST /docs/approve/{codebase_id}/{function_id}
  body: { docstring: str }  (may be edited by developer)
  writes docstring to the actual .py file
  updates Neo4j node with new docstring
  re-embeds the function in Qdrant

POST /docs/reject/{codebase_id}/{function_id}
  marks as rejected, does nothing to the file
```

File: `backend/docgen/docgen_graph.py`

### Phase 4 — React Frontend

Four panels in the UI:

**Panel 1 — Ingest**

- Text input for local codebase path or GitHub URL
- Submit button triggers `POST /ingest`
- Polls `GET /status/{codebase_id}` every 2 seconds
- Shows progress: "Parsing files... Writing to Neo4j... Embedding..."
- On complete: shows summary card with node/edge counts

**Panel 2 — Query**

- Text input for question
- Submit triggers `POST /query`
- Shows intent badge: SEMANTIC / STRUCTURAL / HYBRID
- Answer displayed with inline citations formatted as `filename:line`
- Source list shows each chunk used: file, function name, score, which retriever found it

**Panel 3 — Graph Visualizer**

- Uses `react-force-graph` library
- Fetches graph data from `GET /graph/summary/{codebase_id}`
- Nodes colored by label: Function=blue, Class=green, File=orange, ExternalLib=grey
- Clicking a node shows its properties in a side panel
- After a query: highlights nodes used in the answer

**Panel 4 — Doc Generation**

- Fetches undocumented functions from `GET /docs/undocumented/{codebase_id}`
- Lists them grouped by file
- Clicking a function triggers `POST /docs/generate`
- Shows draft docstring in a diff view (before/after)
- Approve button → `POST /docs/approve`
- Reject button → `POST /docs/reject`
- Edit box lets developer modify the draft before approving

Dependencies:

```
npm install react-force-graph axios tailwindcss
```

### Phase 5 — GitHub URL Ingestion

Accept a GitHub URL in the ingest endpoint instead of a local path.

What to build:

- Detect if input is a GitHub URL or local path
- If GitHub URL: clone to a temp directory using `gitpython`
- Run the same ingestion pipeline on the cloned repo
- Delete the temp directory after ingestion completes
- Support public repos only in the first version

```
pip install gitpython
```

### Phase 6 — RAGAS Evaluation Dashboard

Build a golden test set and measure retrieval + answer quality.

What to build:

- Create `eval/golden_set.json`: 20 questions about the test codebase with known correct answers and the expected source functions
- Script that runs all 20 questions through the query pipeline and collects: question, answer, retrieved contexts, ground truth
- RAGAS metrics to measure: `context_recall`, `answer_faithfulness`, `answer_relevance`
- FastAPI endpoint: `GET /eval/run` — runs full eval, returns scores
- Add eval scores panel to the React UI

```
pip install ragas datasets
```

### Phase 7 — Railway Deployment

- Dockerize the FastAPI backend
- Use Neo4j Aura free tier (cloud) instead of Neo4j Desktop
- Use Qdrant Cloud free tier instead of local Docker
- Update all connection strings to use environment variables
- Deploy FastAPI to Railway
- Deploy React frontend to Vercel
- Set all secrets as Railway/Vercel environment variables

---

## Key Decisions Already Made

| Decision          | Choice                                 | Reason                                                          |
| ----------------- | -------------------------------------- | --------------------------------------------------------------- |
| Node ID format    | `file::ClassName::function_name`       | Stable, human-readable, works as citation text                  |
| Embedding model   | text-embedding-3-small                 | Cheapest OpenAI model, 1536 dims, good quality                  |
| LLM model         | gpt-4o-mini                            | Cheap, fast, accurate enough for code QA                        |
| Qdrant distance   | COSINE                                 | Standard for text embeddings                                    |
| Neo4j write mode  | MERGE not CREATE                       | Idempotent, safe to re-run ingestion                            |
| Parser            | Python stdlib ast                      | Zero dependencies, works on Windows, swap for tree-sitter later |
| Language support  | Python only                            | First version. tree-sitter adds multi-language later            |
| Cypher fallback   | Falls back to semantic if Cypher fails | Resilience over correctness                                     |
| Retry limit       | Max 2 retries in critique loop         | Prevents infinite loops                                         |
| Chunk strategy    | One function = one chunk               | Functions are natural semantic units, no mid-body splitting     |
| Embedding content | Rich chunk not raw source              | File + class + params + docstring + source = better retrieval   |

---

## Graph Schema Reference

Nodes and properties:

```
(:Function)
  id, name, file, class_name, start_line, end_line,
  docstring, params, return_type, is_async, source

(:Class)
  id, name, file, start_line, end_line, bases

(:File)
  path

(:ExternalLib)
  name
```

Relationships:

```
(:Function)-[:CALLS]->(:Function)
(:Function)-[:CALLS_EXTERNAL]->(:ExternalLib)
(:Function)-[:DEFINED_IN]->(:File)
(:Function)-[:BELONGS_TO]->(:Class)
(:Class)-[:DEFINED_IN]->(:File)
(:Class)-[:INHERITS]->(:Class)
(:File)-[:IMPORTS]->(:File)
```

---

## Environment Variables Needed

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASS=password123
QDRANT_URL=http://localhost:6333
OPENAI_API_KEY=sk-...
```

---

## Build Order for Claude Code

Start each phase only after the previous one is working and tested.

1. Phase 1 first — LangGraph workflow. This is pure Python, no web server needed. Test it in a script.
2. Phase 2 second — FastAPI. Move notebook code into proper modules, then wrap with routes.
3. Phase 3 third — Doc generation. Builds on top of Phase 2 infrastructure.
4. Phase 4 fourth — React frontend. Build against the running FastAPI from Phase 2.
5. Phase 5 fifth — GitHub ingestion. Small addition to the existing ingest route.
6. Phase 6 sixth — RAGAS eval. Requires the full pipeline from Phases 1-2 to be stable.
7. Phase 7 last — Deploy only after everything works locally.

---

## Instructions for Claude Code

When starting a new phase:

1. Read this entire file first
2. Check what is already built (notebooks) before writing any new code
3. Do not rewrite what is already working — move and refactor it
4. Write one module at a time, test it, then move to the next
5. Use the exact node ID format, collection names, and schema defined in this document
6. All Neo4j writes must use MERGE not CREATE
7. All Qdrant operations must use upsert not insert
8. Every new FastAPI endpoint must have a docstring explaining what it does
9. Do not change the graph schema — adding new node types or edges breaks the existing query logic
