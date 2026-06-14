"""Load the microservice topology into Neo4j."""
import graph_db

NODES = [
    ("api-gateway", "service", "Public entry point. Routes all external HTTP traffic to internal services and enforces request limits."),
    ("auth-service", "service", "Authentication and authorization. Issues and validates JWT tokens for every authenticated request."),
    ("user-service", "service", "User profiles and account management. Handles registration, profile edits, and account settings."),
    ("product-service", "service", "Product catalog. Serves product details, pricing, and metadata."),
    ("search-service", "service", "Product search and filtering. Backs the search bar and category browsing."),
    ("cart-service", "service", "Shopping cart. Adds, removes, and persists items in a user's cart."),
    ("checkout-service", "service", "Orchestrates the checkout flow across payment, inventory, and order creation."),
    ("payment-service", "service", "Processes payments and card authorizations. Owns retry logic for failed charges."),
    ("order-service", "service", "Order creation and lifecycle. Persists orders and emits order events."),
    ("inventory-service", "service", "Stock levels and reservations. Reserves items during checkout to prevent oversell."),
    ("notification-service", "service", "Sends transactional emails and push notifications to users."),
    ("recommendation-service", "service", "Generates product recommendations from catalog and order history."),
    ("users-db", "database", "PostgreSQL store for user accounts and credentials."),
    ("products-db", "database", "PostgreSQL store for the product catalog and stock counts."),
    ("orders-db", "database", "PostgreSQL store for placed orders."),
    ("payments-db", "database", "PostgreSQL store for payment and transaction records."),
    ("cart-cache", "database", "Redis cache holding active shopping cart state."),
    ("order-events", "queue", "Kafka topic streaming order lifecycle events to downstream consumers."),
]

EDGES = [
    ("api-gateway", "DEPENDS_ON", "auth-service"),
    ("api-gateway", "DEPENDS_ON", "user-service"),
    ("api-gateway", "DEPENDS_ON", "product-service"),
    ("api-gateway", "DEPENDS_ON", "search-service"),
    ("api-gateway", "DEPENDS_ON", "cart-service"),
    ("api-gateway", "DEPENDS_ON", "checkout-service"),

    ("auth-service", "READS_FROM", "users-db"),
    ("auth-service", "WRITES_TO", "users-db"),

    ("user-service", "DEPENDS_ON", "auth-service"),
    ("user-service", "READS_FROM", "users-db"),
    ("user-service", "WRITES_TO", "users-db"),

    ("product-service", "READS_FROM", "products-db"),
    ("product-service", "WRITES_TO", "products-db"),

    ("search-service", "DEPENDS_ON", "product-service"),
    ("search-service", "READS_FROM", "products-db"),

    ("cart-service", "DEPENDS_ON", "auth-service"),
    ("cart-service", "DEPENDS_ON", "product-service"),
    ("cart-service", "READS_FROM", "cart-cache"),
    ("cart-service", "WRITES_TO", "cart-cache"),

    ("checkout-service", "DEPENDS_ON", "auth-service"),
    ("checkout-service", "DEPENDS_ON", "cart-service"),
    ("checkout-service", "DEPENDS_ON", "payment-service"),
    ("checkout-service", "DEPENDS_ON", "inventory-service"),
    ("checkout-service", "DEPENDS_ON", "order-service"),

    ("payment-service", "DEPENDS_ON", "auth-service"),
    ("payment-service", "READS_FROM", "payments-db"),
    ("payment-service", "WRITES_TO", "payments-db"),

    ("order-service", "DEPENDS_ON", "inventory-service"),
    ("order-service", "READS_FROM", "orders-db"),
    ("order-service", "WRITES_TO", "orders-db"),
    ("order-service", "PUBLISHES_TO", "order-events"),

    ("inventory-service", "READS_FROM", "products-db"),
    ("inventory-service", "WRITES_TO", "products-db"),

    ("notification-service", "DEPENDS_ON", "user-service"),
    ("notification-service", "CONSUMES_FROM", "order-events"),

    ("recommendation-service", "DEPENDS_ON", "product-service"),
    ("recommendation-service", "READS_FROM", "products-db"),
    ("recommendation-service", "CONSUMES_FROM", "order-events"),
]


ALLOWED_RELS = {"DEPENDS_ON", "READS_FROM", "WRITES_TO", "PUBLISHES_TO", "CONSUMES_FROM"}


def seed():
    print("Clearing existing graph...")
    graph_db.write("MATCH (n) DETACH DELETE n")

    print(f"Creating {len(NODES)} nodes...")
    for name, kind, description in NODES:
        graph_db.write(
            "MERGE (s:Service {name: $name}) "
            "SET s.kind = $kind, s.description = $description",
            name=name, kind=kind, description=description,
        )

    print(f"Creating {len(EDGES)} edges...")
    for src, rel, dst in EDGES:
        if rel not in ALLOWED_RELS:
            raise ValueError(f"Unexpected relationship type: {rel}")
        graph_db.write(
            f"MATCH (a:Service {{name: $src}}), (b:Service {{name: $dst}}) "
            f"MERGE (a)-[:{rel}]->(b)",
            src=src, dst=dst,
        )


def verify():
    n = graph_db.read("MATCH (n:Service) RETURN count(n) AS c")[0]["c"]
    e = graph_db.read("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    print(f"\nGraph loaded: {n} nodes, {e} edges.")

    print("\nBlast radius if 'auth-service' fails "
          "(anything depending on it, directly or transitively):")
    rows = graph_db.read(
        "MATCH (victim:Service)-[:DEPENDS_ON*1..]->(failed:Service {name: 'auth-service'}) "
        "RETURN DISTINCT victim.name AS name ORDER BY name"
    )
    for row in rows:
        print(f"  - {row['name']}")
    print("\n(Note: 'notification-service' should appear via the 2-hop path "
          "notification-service -> user-service -> auth-service.)")


if __name__ == "__main__":
    seed()
    verify()
    graph_db.close()