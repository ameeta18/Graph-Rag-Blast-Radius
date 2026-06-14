"""Graph RAG router: plan a retrieval strategy, execute it, synthesize an answer."""
import os
import json
import faiss
from google import genai
from google.genai import types
from dotenv import load_dotenv

import graph_db
from embeddings import embed_texts, INDEX_PATH, NAMES_PATH

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
PLANNER_MODEL = "gemini-2.5-flash"


# Planner 

SCHEMA_DESCRIPTION = """\
GRAPH SCHEMA
Node label: Service
  properties:
    name        unique string id, e.g. "auth-service", "payments-db"
    kind        one of: "service" | "database" | "queue"
    description short text of what it does

Relationship types (all directed):
  (A)-[:DEPENDS_ON]->(B)     A makes synchronous calls to B. If B fails, A breaks.
  (A)-[:READS_FROM]->(B)     service A reads from datastore B
  (A)-[:WRITES_TO]->(B)      service A writes to datastore B
  (A)-[:PUBLISHES_TO]->(B)   service A publishes events to queue B
  (A)-[:CONSUMES_FROM]->(B)  service A consumes events from queue B

KEY SEMANTICS
- "Blast radius of X" / "what breaks if X fails" = every node that reaches X
  through outgoing DEPENDS_ON edges, directly or transitively. In Cypher:
    MATCH (victim:Service)-[:DEPENDS_ON*1..]->(failed:Service {name: $X})
    RETURN DISTINCT victim.name
- A "single point of failure" is a service many others depend on with no
  alternative; surface candidates by counting incoming DEPENDS_ON edges.
- Always RETURN node names (e.g. victim.name), never whole nodes.
- Queries must be READ-ONLY. Never emit CREATE, MERGE, DELETE, SET, REMOVE.
"""

ROUTING_RULES = """\
CHOOSE A MODE
- "graph": the question is about structure, connectivity, dependencies,
  failure cascades, or counts of relationships. Write Cypher for it.
- "vector": the question describes a service by its FUNCTION or PURPOSE
  without naming it (e.g. "which service handles retries?"). Provide a
  vector_query (a short phrase to embed); leave cypher empty.
- "both": the question has a structural part AND a by-meaning part. Provide
  both cypher and vector_query.
"""

EXAMPLES = """\
EXAMPLES

Question: If auth-service goes down, what breaks?
{"mode": "graph", "cypher": "MATCH (victim:Service)-[:DEPENDS_ON*1..]->(failed:Service {name: 'auth-service'}) RETURN DISTINCT victim.name", "vector_query": "", "reasoning": "Failure-cascade over dependency edges is a structural traversal."}

Question: Which service is responsible for retrying failed charges?
{"mode": "vector", "cypher": "", "vector_query": "retrying failed payment charges", "reasoning": "Describes a service by function without naming it, so semantic search fits."}

Question: What writes to products-db?
{"mode": "graph", "cypher": "MATCH (s:Service)-[:WRITES_TO]->(:Service {name: 'products-db'}) RETURN DISTINCT s.name", "vector_query": "", "reasoning": "A direct relationship lookup against a named datastore."}

Question: If the order events queue fails, what stops working, and which service handles recommendations?
{"mode": "both", "cypher": "MATCH (s:Service)-[:CONSUMES_FROM]->(:Service {name: 'order-events'}) RETURN DISTINCT s.name", "vector_query": "product recommendations", "reasoning": "One part is a structural consumer lookup; the other names a service by its function."}
"""

SYSTEM_PROMPT = f"""You are a query planner for a Graph RAG system over a microservice \
dependency graph. Given a user question, decide how to retrieve the answer and \
return ONLY a JSON object with keys: mode, cypher, vector_query, reasoning.

{SCHEMA_DESCRIPTION}
{ROUTING_RULES}
{EXAMPLES}"""


def plan(question):
    """Ask Gemini for a retrieval plan. Returns a dict."""
    resp = client.models.generate_content(
        model=PLANNER_MODEL,
        contents=f"Question: {question}",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0,
        ),
    )
    return json.loads(resp.text.strip())



# Execution
FORBIDDEN = ("CREATE", "MERGE", "DELETE", "SET ", "REMOVE", "DROP", "DETACH")


def is_read_only(cypher):
    """Reject any Cypher that could modify the graph."""
    upper = cypher.upper()
    return not any(kw in upper for kw in FORBIDDEN)


def semantic_search(query, k=3):
    """Vector search over service descriptions. Returns [{service, score}]."""
    index = faiss.read_index(INDEX_PATH)
    with open(NAMES_PATH) as f:
        names = json.load(f)
    qvec = embed_texts([query])
    faiss.normalize_L2(qvec)
    scores, idxs = index.search(qvec, k)
    return [
        {"service": names[i], "score": round(float(s), 3)}
        for s, i in zip(scores[0], idxs[0])
    ]


def execute(p):
    """Run whatever the plan asked for. Returns a context dict for synthesis."""
    context = {}
    cypher = p.get("cypher")
    if cypher:
        if not is_read_only(cypher):
            raise ValueError(f"Refusing to run non-read-only Cypher: {cypher}")
        rows = graph_db.read(cypher)
        context["graph_results"] = [dict(r) for r in rows]
    vq = p.get("vector_query")
    if vq:
        context["vector_results"] = semantic_search(vq)
    return context


# Synthesis

def synthesize(question, context):
    """Turn retrieved data into a readable answer."""
    prompt = (
        f"Question: {question}\n\n"
        f"Retrieved data (JSON):\n{json.dumps(context, indent=2)}\n\n"
        "How to read the data:\n"
        "- 'graph_results' are the rows returned by a graph traversal that was "
        "built specifically to answer the question. Treat each returned service "
        "as a direct answer to the structural part of the question (e.g. if the "
        "question asks what breaks or what stops working, the returned services "
        "ARE the ones that break or stop working).\n"
        "- 'vector_results' are services ranked by semantic similarity; the "
        "top-ranked one best matches the described function.\n\n"
        "Answer using ONLY the retrieved data. Be concise and refer to services "
        "by name. If a section is empty, say you could not find that part in the graph."
    )
    resp = client.models.generate_content(
        model=PLANNER_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction="You explain microservice dependency and failure "
            "analysis clearly and concisely for an engineer.",
            temperature=0.2,
        ),
    )
    return resp.text.strip()


def answer(question):
    p = plan(question)
    context = execute(p)
    final = synthesize(question, context)
    return final, p, context


if __name__ == "__main__":
    questions = [
        "If auth-service goes down, what breaks?",
        "Which service handles retry logic for payments?",
        "If the message queue dies what stops working, and which service owns recommendations?",
    ]
    for q in questions:
        final, p, context = answer(q)
        print("\n" + "=" * 70)
        print(f"Q: {q}")
        print(f"[plan: mode={p['mode']}]")
        print(f"\n{final}")
    graph_db.close()