import aiosqlite
import asyncio
from contextlib import asynccontextmanager
import logging
from typing import List, Tuple, Any, Optional
import os
import time
from yoyo import read_migrations
from yoyo import get_backend
from utils.error_handler import DatabaseError, ConfigError

logger = logging.getLogger(__name__)

class DatabasePool:
    def __init__(self, database_name, max_connections=5, max_retries=5, retry_delay=5):
        self.database_name = database_name
        self.max_connections = max_connections
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._pool = asyncio.Queue(maxsize=max_connections)
        self._connections = set()

    async def init(self):
        for attempt in range(self.max_retries):
            try:
                for _ in range(self.max_connections):
                    conn = await aiosqlite.connect(self.database_name)
                    await conn.execute("PRAGMA foreign_keys = ON")
                    self._connections.add(conn)
                    await self._pool.put(conn)
                logger.info(f"Initialized database pool with {self.max_connections} connections")
                return
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed to initialize database pool: {str(e)}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.critical("Failed to initialize database pool after maximum retries")
                    raise DatabaseError("Failed to initialize database pool")

    @asynccontextmanager
    async def acquire(self):
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def close(self):
        while self._connections:
            conn = self._connections.pop()
            await conn.close()
        logger.info("Closed all database connections")

async def create_db_pool(database_name='bot_data.db', max_connections=5, max_retries=5, retry_delay=5):
    pool = DatabasePool(database_name, max_connections, max_retries, retry_delay)
    await pool.init()
    return pool

async def run_migrations(database_name: str, migrations_path: str):
    try:
        backend = get_backend(f'sqlite:///{database_name}')
        migrations = read_migrations(migrations_path)
        
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
        logger.info("Applied database migrations successfully")
    except Exception as e:
        logger.error(f"Error applying migrations: {str(e)}")
        raise DatabaseError(f"Failed to apply migrations: {str(e)}")

@asynccontextmanager
async def transaction(pool: DatabasePool):
    async with pool.acquire() as conn:
        await conn.execute("BEGIN")
        try:
            yield conn
            await conn.commit()
        except Exception as e:
            await conn.rollback()
            logger.error(f"Transaction error: {str(e)}")
            raise DatabaseError(f"Transaction failed: {str(e)}")
        finally:
            await conn.execute("END")

async def execute_query(pool: DatabasePool, query: str, params: Tuple = ()) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(query, params)
            await conn.commit()
    except Exception as e:
        logger.error(f"Error executing query: {str(e)}")
        raise DatabaseError(f"Failed to execute query: {str(e)}")

async def fetch_one(pool: DatabasePool, query: str, params: Tuple = ()) -> Optional[Tuple]:
    try:
        async with pool.acquire() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchone()
    except Exception as e:
        logger.error(f"Error fetching one row: {str(e)}")
        raise DatabaseError(f"Failed to fetch one row: {str(e)}")

async def fetch_all(pool: DatabasePool, query: str, params: Tuple = ()) -> List[Tuple]:
    try:
        async with pool.acquire() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"Error fetching all rows: {str(e)}")
        raise DatabaseError(f"Failed to fetch all rows: {str(e)}")

async def execute_many(pool: DatabasePool, query: str, params_list: List[Tuple]) -> None:
    try:
        async with transaction(pool) as conn:
            await conn.executemany(query, params_list)
    except Exception as e:
        logger.error(f"Error executing many queries: {str(e)}")
        raise DatabaseError(f"Failed to execute many queries: {str(e)}")

async def setup_database(pool: DatabasePool, migrations_path: str):
    try:
        db_path = pool.database_name
        await run_migrations(db_path, migrations_path)
    except Exception as e:
        logger.error(f"Error setting up database: {str(e)}")
        raise DatabaseError(f"Failed to set up database: {str(e)}")

if __name__ == "__main__":
    import asyncio
    database_name = os.getenv("DATABASE_NAME", "bot_data.db")
    migrations_path = os.getenv("MIGRATIONS_PATH", "./migrations")
    
    async def run():
        try:
            pool = await create_db_pool(database_name)
            await setup_database(pool, migrations_path)
            await pool.close()
        except Exception as e:
            logger.error(f"Error in database setup: {str(e)}")
            raise

    asyncio.run(run())