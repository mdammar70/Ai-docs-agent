from openai import OpenAI
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from .config import (
    NEO4J_URI, NEO4J_USER, NEO4J_PASS,
    OPENAI_API_KEY, QDRANT_URL, EMBED_MODEL, LLM_MODEL,
)


def _get_clients(collection: str):
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    qdrant = QdrantClient(url=QDRANT_URL)
    neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    return openai_client, qdrant, neo4j_driver


def classify_query(q: str) -> str:
    q = q.lower()
    if "where is" in q or "used" in q:
        return "reverse_lookup"
    if "how" in q or "flow" in q or "happens" in q:
        return "flow"
    return "semantic"


def vector_search(openai_client, qdrant, collection, question: str, top_k: int = 5):
    q_embedding = openai_client.embeddings.create(
        model=EMBED_MODEL, input=[question]
    ).data[0].embedding

    results = qdrant.query_points(
        collection_name=collection,
        query=q_embedding,
        limit=top_k,
        with_payload=True,
    )
    return results.points or []


def expand_graph(neo4j_driver, node_ids: list[str]):
    with neo4j_driver.session() as session:
        result = session.run("""
        MATCH (f:Function)
        WHERE f.id IN $node_ids
        OPTIONAL MATCH (f)-[:CALLS]->(called)
        OPTIONAL MATCH (caller)-[:CALLS]->(f)
        OPTIONAL MATCH (f)-[:BELONGS_TO]->(c:Class)
        OPTIONAL MATCH (f)-[:DEFINED_IN]->(file:File)
        RETURN f.id as id,
               collect(DISTINCT called.id) as callees,
               collect(DISTINCT caller.id) as callers,
               collect(DISTINCT c.name) as classes,
               collect(DISTINCT file.path) as files
        """, node_ids=node_ids)
        return [record.data() for record in result]


def graph_reverse_lookup(neo4j_driver, question: str):
    q = question.lower()
    if "where is" in q:
        keyword = q.split("where is")[-1]
    else:
        keyword = q
    keyword = keyword.replace("used", "").replace("?", "").strip()

    with neo4j_driver.session() as session:
        result = session.run("""
        MATCH (caller:Function)-[:CALLS]->(callee:Function)
        WHERE toLower(callee.name) CONTAINS toLower($keyword)
        OPTIONAL MATCH (caller)-[:DEFINED_IN]->(file:File)
        RETURN callee.name as target,
               caller.name as caller,
               file.path as file
        """, keyword=keyword)
        return [r.data() for r in result]


def build_context(vector_results, graph_results):
    context = []
    context.append("PRIMARY FUNCTIONS:\n")
    for r in vector_results:
        p = r.payload
        context.append(
            f"{p['file']}:{p['start_line']}-{p['end_line']}\n"
            f"{p['name']}()\n"
            f"{p['source'][:500]}\n"
        )
    context.append("\nGRAPH RELATIONSHIPS:\n")
    for g in graph_results:
        context.append(
            f"Function: {g['id']}\n"
            f"Calls: {g['callees']}\n"
            f"Called By: {g['callers']}\n"
        )
    return "\n".join(context)


def generate_answer(openai_client, question: str, context: str):
    prompt = f"""
You are a senior software engineer analyzing a codebase.

Answer ONLY based on the provided context.
DO NOT hallucinate.

Provide:
1. Clear explanation
2. Execution flow (if applicable)
3. Exact file + line citations

---

CONTEXT:
{context}

---

QUESTION:
{question}
"""
    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content


def ask(collection: str, question: str):
    openai_client, qdrant, neo4j_driver = _get_clients(collection)

    try:
        intent = classify_query(question)
        print(f"Intent: {intent}")

        if intent == "reverse_lookup":
            results = graph_reverse_lookup(neo4j_driver, question)
            if not results:
                print("\nNo usages found.")
                return
            print(f"\nFunction usage results:\n")
            for r in results:
                print(f"- {r['caller']} → {r['target']} ({r['file']})")
            return

        vector_results = vector_search(openai_client, qdrant, collection, question)
        if not vector_results:
            print("\nNo relevant functions found.")
            return

        node_ids = [r.payload["node_id"] for r in vector_results]
        graph_results = expand_graph(neo4j_driver, node_ids)
        context = build_context(vector_results, graph_results)
        answer = generate_answer(openai_client, question, context)

        print(f"\n{answer}")
    finally:
        neo4j_driver.close()
