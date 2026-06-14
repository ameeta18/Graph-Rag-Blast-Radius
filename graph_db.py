"""Neo4j connection helper."""
import os
from neo4j import GraphDatabase, RoutingControl
from dotenv import load_dotenv

load_dotenv()

URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        _driver.verify_connectivity()
    return _driver


def write(cypher, **params):
    """Run a write query."""
    records, _, _ = get_driver().execute_query(
        cypher, database_="neo4j", **params
    )
    return records


def read(cypher, **params):
    """Run a read query (routed to a read replica when available)."""
    records, _, _ = get_driver().execute_query(
        cypher, database_="neo4j", routing_=RoutingControl.READ, **params
    )
    return records


def close():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None