"""Evaluation harness: scores routing accuracy and retrieval precision/recall."""
import json
from statistics import mean

import graph_db
import router
from embeddings import NAMES_PATH
import time


def plan_with_retry(question, attempts=4):
    """Retry the planner on transient 503/overload errors with backoff."""
    for i in range(attempts):
        try:
            return router.plan(question)
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                wait = 2 ** i  
                print(f"     (transient error, retrying in {wait}s...)")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Planner failed after {attempts} attempts: {question}")
with open(NAMES_PATH) as f:
    KNOWN_SERVICES = set(json.load(f))



GOLD = [
    ("If auth-service goes down, what breaks?",
     "graph",
     {"api-gateway", "user-service", "cart-service", "checkout-service",
      "payment-service", "notification-service"}),

    ("What services does checkout-service depend on, directly and indirectly?",
     "graph",
     {"auth-service", "cart-service", "payment-service", "inventory-service",
      "order-service", "product-service"}),

    ("What writes to products-db?",
     "graph",
     {"product-service", "inventory-service"}),

    ("What reads from products-db?",
     "graph",
     {"product-service", "search-service", "inventory-service",
      "recommendation-service"}),

    ("Which service is responsible for retrying failed charges?",
     "vector",
     {"payment-service"}),

    ("Which service sends emails and notifications to users?",
     "vector",
     {"notification-service"}),

    ("Which service generates product recommendations?",
     "vector",
     {"recommendation-service"}),

    ("What consumes from the order events queue?",
     "graph",
     {"notification-service", "recommendation-service"}),

    ("If the order-events queue dies, what stops working, and which service handles search?",
     "both",
     {"notification-service", "recommendation-service", "search-service"}),
     ("If products-db goes down, what stops working?",
     "graph",
     {"product-service", "search-service", "inventory-service",
      "recommendation-service", "api-gateway", "cart-service",
      "checkout-service", "order-service"}),

    ("Which services do not touch any database?",
     "graph",
     {"api-gateway", "checkout-service", "notification-service"}),

    ("What is the most critical service in the system?",
     "graph",
     {"auth-service"}),
     ("Which services are involved with product discovery or search?",
     "vector",
     {"search-service"}),

    ("If order-events queue is unavailable, which user communication or personalization services are affected?",
     "both",
     {"notification-service", "recommendation-service"}),

    ("Which service handles failed payment charge retries, and what breaks if auth-service is down?",
     "both",
     {"payment-service", "api-gateway", "user-service", "cart-service",
      "checkout-service", "notification-service"}),
]


def retrieved_services(context):
    """Extract the set of services the system actually retrieved."""
    found = set()
    for row in context.get("graph_results", []):
        for value in row.values():
            if isinstance(value, str) and value in KNOWN_SERVICES:
                found.add(value)
    vector_results = context.get("vector_results", [])
    if vector_results:
        found.add(vector_results[0]["service"])  
    return found


def prf(expected, retrieved):
    """Precision, recall, F1 for one question."""
    if not retrieved:
        precision = 1.0 if not expected else 0.0
    else:
        precision = len(expected & retrieved) / len(retrieved)
    recall = 1.0 if not expected else len(expected & retrieved) / len(expected)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def run():
    mode_hits = 0
    precisions, recalls, f1s = [], [], []

    for question, exp_mode, exp_services in GOLD:
        p = plan_with_retry(question)
        context = router.execute(p)
        got = retrieved_services(context)

        mode_ok = p["mode"] == exp_mode
        mode_hits += mode_ok
        precision, recall, f1 = prf(exp_services, got)
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

        flag = "OK " if (mode_ok and f1 == 1.0) else "!! "
        print(f"{flag}{question}")
        print(f"     mode: got={p['mode']} expected={exp_mode} "
              f"{'ok' if mode_ok else 'WRONG'}")
        print(f"     services: P={precision:.2f} R={recall:.2f} F1={f1:.2f}")
        if got != exp_services:
            print(f"     expected: {sorted(exp_services)}")
            print(f"     got:      {sorted(got)}")

    n = len(GOLD)
    print("\n" + "=" * 60)
    print(f"Mode accuracy:   {mode_hits}/{n} = {mode_hits / n:.0%}")
    print(f"Mean precision:  {mean(precisions):.2f}")
    print(f"Mean recall:     {mean(recalls):.2f}")
    print(f"Mean F1:         {mean(f1s):.2f}")


if __name__ == "__main__":
    run()
    graph_db.close()