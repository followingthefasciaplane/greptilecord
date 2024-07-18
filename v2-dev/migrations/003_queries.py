from yoyo import step
import logging

logger = logging.getLogger(__name__)

def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            query_type TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    logger.info("Created queries table")

def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS queries")
    logger.info("Dropped queries table")

steps = [
    step(apply_step, rollback_step)
]