from yoyo import step
import logging

logger = logging.getLogger(__name__)

def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remote TEXT NOT NULL,
            owner TEXT NOT NULL,
            name TEXT NOT NULL,
            branch TEXT NOT NULL,
            last_indexed_at TIMESTAMP,
            UNIQUE(remote, owner, name, branch)
        )
    """)
    logger.info("Created repos table")

def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS repos")
    logger.info("Dropped repos table")

steps = [
    step(apply_step, rollback_step)
]