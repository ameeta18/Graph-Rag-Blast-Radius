"""Interactive CLI for the Graph RAG system."""
import json

import graph_db
import router


def main():
    print("Blast Radius - Graph RAG over a microservice dependency graph")
    print("Ask about dependencies, failure cascades, or what a service does.")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            break

        try:
            final, plan, context = router.answer(question)
        except Exception as e:
            print(f"  [error: {e}]\n")
            continue

        print(f"\n  [plan] mode={plan['mode']} - {plan['reasoning']}")
        if plan.get("cypher"):
            print(f"  [cypher] {plan['cypher']}")
        if plan.get("vector_query"):
            print(f"  [vector] \"{plan['vector_query']}\"")

        print(f"\n{final}\n")

    graph_db.close()
    print("Bye.")


if __name__ == "__main__":
    main()