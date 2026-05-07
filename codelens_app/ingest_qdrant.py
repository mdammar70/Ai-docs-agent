import hashlib
from openai import OpenAI
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct


def fetch_all_functions(neo4j_uri, neo4j_user, neo4j_pass):
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
    cypher = """
    MATCH (f:Function)
    OPTIONAL MATCH (f)-[:CALLS]->(callee:Function)
    OPTIONAL MATCH (f)-[:CALLS_EXTERNAL]->(ext:ExternalLib)
    OPTIONAL MATCH (f)-[:BELONGS_TO]->(c:Class)
    RETURN
        f.id          AS id,
        f.name        AS name,
        f.file        AS file,
        f.start_line  AS start_line,
        f.end_line    AS end_line,
        f.class_name  AS class_name,
        f.docstring   AS docstring,
        f.params      AS params,
        f.return_type AS return_type,
        f.is_async    AS is_async,
        f.source      AS source,
        collect(DISTINCT callee.name) AS calls_internal,
        collect(DISTINCT ext.name)    AS calls_external
    """
    with driver.session() as s:
        results = [dict(r) for r in s.run(cypher)]
    driver.close()
    return results


def build_chunk(fn: dict) -> str:
    lines = []
    lines.append(f"Function: {fn['name']}")
    lines.append(f"File: {fn['file']} (lines {fn['start_line']}-{fn['end_line']})")

    if fn.get("class_name"):
        lines.append(f"Class: {fn['class_name']}")
    if fn.get("is_async"):
        lines.append("Type: async function")
    if fn.get("params"):
        lines.append(f"Parameters: {fn['params']}")
    if fn.get("return_type"):
        lines.append(f"Returns: {fn['return_type']}")
    if fn.get("docstring"):
        lines.append(f"Description: {fn['docstring']}")

    calls_in = [c for c in fn.get("calls_internal", []) if c]
    if calls_in:
        lines.append(f"Calls internally: {', '.join(calls_in)}")

    calls_ext = [c for c in fn.get("calls_external", []) if c]
    if calls_ext:
        meaningful = [c for c in calls_ext if "." not in c or not c.startswith("self")]
        if meaningful:
            lines.append(f"Uses: {', '.join(meaningful[:6])}")

    if fn.get("source"):
        lines.append(f"\nSource code:\n{fn['source']}")

    return "\n".join(lines)


def embed_texts(openai_client, texts: list[str], model: str, batch_size: int = 50) -> list[list[float]]:
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = openai_client.embeddings.create(model=model, input=batch)
        all_embeddings.extend(item.embedding for item in response.data)
    return all_embeddings


def make_point_id(node_id: str) -> int:
    return int(hashlib.md5(node_id.encode()).hexdigest(), 16) % (2**63)


def ingest_to_qdrant(neo4j_uri, neo4j_user, neo4j_pass, openai_key, qdrant_url, collection, embed_model):
    print("  Fetching functions from Neo4j...")
    functions = fetch_all_functions(neo4j_uri, neo4j_user, neo4j_pass)
    print(f"  Fetched {len(functions)} functions")

    print("  Building text chunks...")
    chunks = [(fn, build_chunk(fn)) for fn in functions]

    openai_client = OpenAI(api_key=openai_key)

    print(f"  Embedding {len(chunks)} chunks with {embed_model}...")
    texts = [chunk for _, chunk in chunks]
    embeddings = embed_texts(openai_client, texts, embed_model)
    print(f"  Got {len(embeddings)} embeddings")

    qdrant = QdrantClient(url=qdrant_url)

    existing = [c.name for c in qdrant.get_collections().collections]
    if collection in existing:
        qdrant.delete_collection(collection)
        print(f"  Deleted existing collection: {collection}")

    qdrant.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
    )
    print(f"  Created collection: {collection}")

    points = [
        PointStruct(
            id=make_point_id(fn["id"]),
            vector=embedding,
            payload={
                "node_id": fn["id"],
                "name": fn["name"],
                "file": fn["file"],
                "class_name": fn["class_name"],
                "start_line": fn["start_line"],
                "end_line": fn["end_line"],
                "docstring": fn["docstring"],
                "params": fn["params"],
                "return_type": fn["return_type"],
                "is_async": fn["is_async"],
                "source": fn["source"],
                "calls_internal": [c for c in fn.get("calls_internal", []) if c],
                "calls_external": [c for c in fn.get("calls_external", []) if c],
                "chunk_text": texts[i],
            },
        )
        for i, (fn, embedding) in enumerate(zip(
            [fn for fn, _ in chunks], embeddings
        ))
    ]

    qdrant.upsert(collection_name=collection, points=points)

    info = qdrant.get_collection(collection)
    stored = (
        getattr(info, "vectors_count", None)
        or getattr(info, "points_count", None)
        or getattr(info, "indexed_vectors_count", None)
    )
    print(f"  Uploaded {len(points)} points — stored: {stored}")

    return {"vectors_uploaded": len(points), "stored_count": stored}
