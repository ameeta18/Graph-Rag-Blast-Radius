# Blast Radius

A Graph RAG system for multi-hop dependency reasoning over a microservice topology. It answers questions about service dependencies, failure cascades, and "blast radius" by routing each question to either graph traversal, semantic vector search, or both, then synthesizing a grounded answer.

This project  demonstrates where graph retrieval beats pure vector RAG: questions like "if auth-service fails, what breaks?" require following dependency chains across the graph, which similarity search cannot do.

## How it works

A natural-language question goes through three stages:

1. **Plan** - one LLM call (Gemini) inspects the question and the graph schema, then emits a structured JSON plan choosing a retrieval strategy: `graph` (Cypher traversal), `vector` (semantic search over service descriptions), or `both`.
2. **Execute** - the plan is run against Neo4j and/or a FAISS index. Generated Cypher is checked to be read-only before execution.
3. **Synthesize** - a second LLM call turns the retrieved data into a readable answer, grounded only in what was retrieved.

The system shows its work: the CLI prints the chosen mode and the generated Cypher alongside each answer, so the retrieval path is auditable.

## Stack

- **Neo4j** - graph store, queried with Cypher
- **Google Gemini** - query planning, answer synthesis (`gemini-2.5-flash`), and embeddings (`gemini-embedding-001`)
- **FAISS** - vector index over service descriptions
- **Python** - no agent framework; the router is a plain, inspectable planner

## Setup

```bash
# Start Neo4j
docker run --name blastradius-neo4j -p7474:7474 -p7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env   # add your GEMINI_API_KEY

# Load the graph, build the vector index
python seed.py
python embeddings.py
```

## Usage

```bash
python cli.py        # interactive: ask questions, see the plan and answer
python eval.py       # run the evaluation harness
```

Example:

```
> If payment-service goes down, what breaks?
  [plan] mode=graph
  [cypher] MATCH (victim:Service)-[:DEPENDS_ON*1..]->(failed:Service {name: 'payment-service'}) ...
  checkout-service and api-gateway break.
```
## Evaluation

A hand-labeled set of 15 questions, with gold answers traced directly from the topology, spanning all three routing modes and including deliberately hard cases (failure cascades through a datastore, negation queries, transitive dependency chains). The harness scores two things separately: whether the planner chose the right retrieval mode, and whether the correct services were retrieved (precision/recall against the gold set).

Scoring is done against the **retrieved services** (the structured context), not the free-text answer, since retrieval and routing are the engineering being measured; synthesis is presentation.

| Metric | Score |
|---|---|
| Mode-routing accuracy | 15/15 (100%) |
| Mean precision | 0.89 |
| Mean recall | 0.93 |
| Mean F1 | 0.90 |

