from yoyo import step
import logging

logger = logging.getLogger(__name__)

def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            user_id TEXT PRIMARY KEY,
            role TEXT NOT NULL
        )
    """)
    logger.info("Created whitelist table")

def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS whitelist")
    logger.info("Dropped whitelist table")

steps = [
    step(apply_step, rollback_step)
]