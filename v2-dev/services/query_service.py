import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from database.connection import execute_query, fetch_one, fetch_all
from utils.api_client import GreptileAPIClient, GreptileAPIError
from utils.error_handler import BotError, ConfigError, DatabaseError, APIError

logger = logging.getLogger(__name__)

class QueryService:
    def __init__(self, db_pool, api_client: GreptileAPIClient, config_service):
        self.db_pool = db_pool
        self.api_client = api_client
        self.config_service = config_service
        self.max_queries_per_day = 5
        self.max_smart_queries_per_day = 1
        self.max_searches_per_day = 10

    async def set_query_limits(self, max_queries: int, max_smart_queries: int, max_searches: int):
        self.max_queries_per_day = max_queries
        self.max_smart_queries_per_day = max_smart_queries
        self.max_searches_per_day = max_searches

    async def can_make_query(self, user_id: int, query_type: str) -> bool:
        try:
            if str(user_id) == await self.config_service.get_config('BOT_OWNER_ID'):
                return True
            today = date.today()
            query = """
            SELECT COUNT(*) FROM queries
            WHERE user_id = ? AND query_type = ? AND DATE(timestamp) = ?
            """
            row = await fetch_one(self.db_pool, query, (str(user_id), query_type, today))
            count = row[0] if row else 0
            max_queries = getattr(self, f'max_{query_type}_per_day', 5)
            return count < max_queries
        except Exception as e:
            logger.error(f"Failed to check query limit: {str(e)}")
            raise DatabaseError(f"Failed to check query limit: {str(e)}")

    async def log_query(self, user_id: int, query_type: str) -> bool:
        try:
            query = """
            INSERT INTO queries (user_id, query_type, timestamp)
            VALUES (?, ?, ?)
            """
            await execute_query(self.db_pool, query, (str(user_id), query_type, datetime.now()))
            logger.info(f"Logged {query_type} query for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to log query: {str(e)}")
            raise DatabaseError(f"Failed to log query: {str(e)}")

    async def search(self, search_query: str, repositories: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        try:
            repo_list = [
                {
                    "remote": repo['remote'],
                    "repository": f"{repo['owner']}/{repo['name']}",
                    "branch": repo['branch']
                } for repo in repositories
            ]
            results = await self.api_client.search(search_query, repo_list)
            logger.info(f"Search executed: {search_query}")
            return results
        except GreptileAPIError as e:
            logger.error(f"GreptileAPIError in search: {str(e)}")
            raise APIError(f"Error during search: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in search: {str(e)}")
            raise BotError(f"Unexpected error during search: {str(e)}")

    async def query(self, question: str, repositories: List[Dict[str, str]], genius: bool = False) -> List[Dict[str, Any]]:
        try:
            repo_list = [
                {
                    "remote": repo['remote'],
                    "repository": f"{repo['owner']}/{repo['name']}",
                    "branch": repo['branch']
                } for repo in repositories
            ]
            messages = [
                {
                    "id": "user_query",
                    "content": question,
                    "role": "user"
                }
            ]
            results = await self.api_client.query(messages, repo_list, genius=genius)
            logger.info(f"Query executed: {question}")
            return results
        except GreptileAPIError as e:
            logger.error(f"GreptileAPIError in query: {str(e)}")
            raise APIError(f"Error during query: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in query: {str(e)}")
            raise BotError(f"Unexpected error during query: {str(e)}")

    async def get_query_count(self, user_id: int, query_type: str) -> int:
        try:
            today = date.today()
            query = """
            SELECT COUNT(*) FROM queries
            WHERE user_id = ? AND query_type = ? AND DATE(timestamp) = ?
            """
            row = await fetch_one(self.db_pool, query, (str(user_id), query_type, today))
            count = row[0] if row else 0
            return count
        except Exception as e:
            logger.error(f"Failed to get query count: {str(e)}")
            raise DatabaseError(f"Failed to get query count: {str(e)}")

    async def clear_daily_queries(self) -> bool:
        try:
            query = "DELETE FROM queries WHERE DATE(timestamp) < DATE('now')"
            await execute_query(self.db_pool, query)
            logger.info("Cleared old daily queries")
            return True
        except Exception as e:
            logger.error(f"Failed to clear daily queries: {str(e)}")
            raise DatabaseError(f"Failed to clear daily queries: {str(e)}")