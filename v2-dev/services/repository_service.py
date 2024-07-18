import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from database.connection import execute_query, fetch_one, fetch_all
from utils.api_client import GreptileAPIClient, GreptileAPIError
from utils.error_handler import BotError, ConfigError, DatabaseError, APIError

logger = logging.getLogger(__name__)

class RepositoryService:
    def __init__(self, db_pool, api_client: GreptileAPIClient, config_service):
        self.db_pool = db_pool
        self.api_client = api_client
        self.config_service = config_service

    async def add_repository(self, remote: str, owner: str, name: str, branch: str) -> bool:
        try:
            query = """
            INSERT INTO repos (remote, owner, name, branch, last_indexed_at)
            VALUES (?, ?, ?, ?, NULL)
            """
            await execute_query(self.db_pool, query, (remote, owner, name, branch))
            logger.info(f"Added repository: {owner}/{name} ({remote}/{branch})")
            
            # Initiate indexing
            repo = {'remote': remote, 'owner': owner, 'name': name, 'branch': branch}
            await self.index_repository(repo)
            
            return True
        except Exception as e:
            logger.error(f"Failed to add repository: {str(e)}")
            raise DatabaseError(f"Failed to add repository: {str(e)}")

    async def remove_repository(self, owner: str, name: str) -> bool:
        try:
            query = "DELETE FROM repos WHERE owner = ? AND name = ?"
            await execute_query(self.db_pool, query, (owner, name))
            logger.info(f"Removed repository: {owner}/{name}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove repository: {str(e)}")
            raise DatabaseError(f"Failed to remove repository: {str(e)}")

    async def remove_all_repositories(self) -> bool:
        try:
            query = "DELETE FROM repos"
            await execute_query(self.db_pool, query)
            logger.info("Removed all repositories")
            return True
        except Exception as e:
            logger.error(f"Failed to remove all repositories: {str(e)}")
            raise DatabaseError(f"Failed to remove all repositories: {str(e)}")

    async def get_all_repositories(self) -> List[Dict[str, Any]]:
        try:
            query = "SELECT remote, owner, name, branch, last_indexed_at FROM repos"
            rows = await fetch_all(self.db_pool, query)
            return [dict(zip(['remote', 'owner', 'name', 'branch', 'last_indexed_at'], row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to fetch repositories: {str(e)}")
            raise DatabaseError(f"Failed to fetch repositories: {str(e)}")

    async def update_last_indexed(self, remote: str, owner: str, name: str, branch: str) -> bool:
        try:
            query = """
            UPDATE repos
            SET last_indexed_at = ?
            WHERE remote = ? AND owner = ? AND name = ? AND branch = ?
            """
            result = await execute_query(self.db_pool, query, (datetime.now(), remote, owner, name, branch))
            if result and result.rowcount > 0:
                logger.info(f"Updated last_indexed_at for repository {owner}/{name}")
                return True
            else:
                logger.warning(f"Failed to update last_indexed_at for repository {owner}/{name}. No matching record found.")
                return False
        except Exception as e:
            logger.error(f"Failed to update last_indexed_at: {str(e)}")
            raise DatabaseError(f"Failed to update last_indexed_at: {str(e)}")

    async def get_repository_status(self, repo: Dict[str, str]) -> Optional[Dict[str, Any]]:
        repo_id = f"{repo['remote']}:{repo['branch']}:{repo['owner']}/{repo['name']}"
        try:
            status_info = await self.api_client.get_repository_status(repo_id)
            logger.info(f"Repository {repo_id} status: {status_info.get('status', 'unknown')}")
            return status_info
        except GreptileAPIError as e:
            logger.error(f"API error while getting status for repository {repo_id}: {str(e)}")
            raise APIError(f"Failed to get status for repository {repo_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while getting status for repository {repo_id}: {str(e)}")
            raise BotError(f"Unexpected error while getting status for repository {repo_id}: {str(e)}")

    async def index_repository(self, repo: Dict[str, str]) -> Optional[Dict[str, Any]]:
        try:
            result = await self.api_client.index_repository(
                repo['remote'],
                f"{repo['owner']}/{repo['name']}",
                repo['branch']
            )
            logger.info(f"Indexing started for repository {repo['owner']}/{repo['name']}")
            return result
        except GreptileAPIError as e:
            logger.error(f"API error while indexing repository {repo['owner']}/{repo['name']}: {str(e)}")
            raise APIError(f"Failed to index repository {repo['owner']}/{repo['name']}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while indexing repository {repo['owner']}/{repo['name']}: {str(e)}")
            raise BotError(f"Unexpected error while indexing repository {repo['owner']}/{repo['name']}: {str(e)}")

    async def check_and_update_repo_status(self) -> List[Dict[str, Any]]:
        try:
            repos = await self.get_all_repositories()
            status_updates = []
            for repo in repos:
                status_info = await self.get_repository_status(repo)
                if status_info:
                    status = status_info.get('status', 'unknown')
                    if status == 'completed':
                        await self.update_last_indexed(repo['remote'], repo['owner'], repo['name'], repo['branch'])
                    elif status == 'failed':
                        logger.error(f"Repository {repo['owner']}/{repo['name']} indexing has failed.")
                    elif status == 'processing':
                        indexing_timeout = await self.config_service.get_config('INDEXING_TIMEOUT', 7200)  # 2 hours default
                        if repo['last_indexed_at'] and (datetime.now() - repo['last_indexed_at']).total_seconds() > indexing_timeout:
                            logger.warning(f"Repository {repo['owner']}/{repo['name']} has been processing for over {indexing_timeout} seconds.")
                    status_updates.append({**repo, 'status': status})
                else:
                    status_updates.append({**repo, 'status': 'unknown'})
            return status_updates
        except Exception as e:
            logger.error(f"Failed to check and update repository status: {str(e)}")
            raise BotError(f"Failed to check and update repository status: {str(e)}")

    async def get_repository(self, owner: str, name: str) -> Optional[Dict[str, Any]]:
        try:
            query = "SELECT remote, owner, name, branch, last_indexed_at FROM repos WHERE owner = ? AND name = ?"
            row = await fetch_one(self.db_pool, query, (owner, name))
            if row:
                return dict(zip(['remote', 'owner', 'name', 'branch', 'last_indexed_at'], row))
            return None
        except Exception as e:
            logger.error(f"Failed to fetch repository {owner}/{name}: {str(e)}")
            raise DatabaseError(f"Failed to fetch repository {owner}/{name}: {str(e)}")

    async def get_repository_by_id(self, repo_id: str) -> Optional[Dict[str, Any]]:
        try:
            remote, branch, full_name = repo_id.split(':')
            owner, name = full_name.split('/')
            return await self.get_repository(owner, name)
        except ValueError:
            raise ConfigError(f"Invalid repository ID format: {repo_id}")
        except Exception as e:
            logger.error(f"Failed to get repository by ID {repo_id}: {str(e)}")
            raise BotError(f"Failed to get repository by ID {repo_id}: {str(e)}")

    async def is_repository_indexed(self, owner: str, name: str) -> bool:
        try:
            repo = await self.get_repository(owner, name)
            if repo is None:
                return False
            status_info = await self.get_repository_status(repo)
            return status_info.get('status') == 'completed' if status_info else False
        except Exception as e:
            logger.error(f"Failed to check if repository {owner}/{name} is indexed: {str(e)}")
            raise BotError(f"Failed to check if repository {owner}/{name} is indexed: {str(e)}")

    async def get_indexing_progress(self, owner: str, name: str) -> Optional[float]:
        try:
            repo = await self.get_repository(owner, name)
            if repo is None:
                return None
            status_info = await self.get_repository_status(repo)
            return status_info.get('progress') if status_info else None
        except Exception as e:
            logger.error(f"Failed to get indexing progress for repository {owner}/{name}: {str(e)}")
            raise BotError(f"Failed to get indexing progress for repository {owner}/{name}: {str(e)}")

    async def cancel_indexing(self, owner: str, name: str) -> bool:
        try:
            repo = await self.get_repository(owner, name)
            if repo is None:
                raise ConfigError(f"Repository {owner}/{name} not found")
            result = await self.api_client.cancel_indexing(f"{repo['remote']}:{repo['branch']}:{owner}/{name}")
            logger.info(f"Cancelled indexing for repository {owner}/{name}")
            return result.get('success', False)
        except GreptileAPIError as e:
            logger.error(f"API error while cancelling indexing for repository {owner}/{name}: {str(e)}")
            raise APIError(f"Failed to cancel indexing for repository {owner}/{name}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while cancelling indexing for repository {owner}/{name}: {str(e)}")
            raise BotError(f"Unexpected error while cancelling indexing for repository {owner}/{name}: {str(e)}")

    async def get_repository_statistics(self, owner: str, name: str) -> Optional[Dict[str, Any]]:
        try:
            repo = await self.get_repository(owner, name)
            if repo is None:
                raise ConfigError(f"Repository {owner}/{name} not found")
            stats = await self.api_client.get_repository_statistics(f"{repo['remote']}:{repo['branch']}:{owner}/{name}")
            logger.info(f"Retrieved statistics for repository {owner}/{name}")
            return stats
        except GreptileAPIError as e:
            logger.error(f"API error while getting statistics for repository {owner}/{name}: {str(e)}")
            raise APIError(f"Failed to get statistics for repository {owner}/{name}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while getting statistics for repository {owner}/{name}: {str(e)}")
            raise BotError(f"Unexpected error while getting statistics for repository {owner}/{name}: {str(e)}")