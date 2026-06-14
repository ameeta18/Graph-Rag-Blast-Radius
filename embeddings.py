"""Build a FAISS index from the service descriptions stored in Neo4j."""
import os
import json
import faiss
import numpy as np
from google import genai
from dotenv import load_dotenv

import graph_db

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
EMBED_MODEL = "gemini-embedding-001"
INDEX_PATH = "faiss.index"
NAMES_PATH = "names.json"


def fetch_services():
    """Get (name, description) for every service, in a stable order."""
    rows = graph_db.read(
        "MATCH (s:Service) RETURN s.name AS name, s.description AS description "
        "ORDER BY s.name"
    )
    return [(r["name"], r["description"]) for r in rows]


def embed_texts(texts):
    """Embed a list of strings; returns a float32 numpy array (n, dim)."""
    result = client.models.embed_content(model=EMBED_MODEL, contents=texts)
    vectors = [e.values for e in result.embeddings]
    return np.array(vectors, dtype="float32")


def build_index():
    services = fetch_services()
    names = [name for name, _ in services]
    descriptions = [desc for _, desc in services]

    print(f"Embedding {len(descriptions)} service descriptions with {EMBED_MODEL}...")
    vectors = embed_texts(descriptions)
    print(f"Got vectors of shape {vectors.shape} (services, dimensions).")

  
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    faiss.write_index(index, INDEX_PATH)
    with open(NAMES_PATH, "w") as f:
        json.dump(names, f)
    print(f"Saved {INDEX_PATH} and {NAMES_PATH}.")
    return index, names


def search(query, k=3):
    """Quick semantic search to sanity-check the index."""
    index = faiss.read_index(INDEX_PATH)
    with open(NAMES_PATH) as f:
        names = json.load(f)

    qvec = embed_texts([query])
    faiss.normalize_L2(qvec)
    scores, idxs = index.search(qvec, k)

    print(f"\nTop {k} services for: \"{query}\"")
    for score, i in zip(scores[0], idxs[0]):
        print(f"  {score:.3f}  {names[i]}")


if __name__ == "__main__":
    build_index()
    
    search("which service handles retrying failed charges?")
    search("where is shopping cart data kept?")
    graph_db.close()