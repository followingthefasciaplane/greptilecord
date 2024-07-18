from yoyo import step
import logging

logger = logging.getLogger(__name__)

def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    logger.info("Created config table")

def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS config")
    logger.info("Dropped config table")

steps = [
    step(apply_step, rollback_step)
]