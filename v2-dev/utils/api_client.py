import aiohttp
import asyncio
import logging
from typing import Dict, List, Any, Optional
from utils.error_handler import APIError, BotError

logger = logging.getLogger(__name__)

GreptileAPIError = APIError

class GreptileAPIClient:
    def __init__(self, api_key: str, github_token: str, base_url: str = 'https://api.greptile.com/v2'):
        self.api_key = api_key
        self.github_token = github_token
        self.base_url = base_url
        self.session = None

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        await self._ensure_session()
        
        url = f"{self.base_url}/{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'X-GitHub-Token': self.github_token,
            'Content-Type': 'application/json'
        }
        kwargs['headers'] = headers

        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    logger.error(f"API error response: {error_text}")
                    error_data = await response.json()
                    raise APIError(
                        status_code=response.status,
                        message=error_data.get('message', 'Unknown error'),
                        details=error_data.get('details')
                    )
                return await response.json()
        except aiohttp.ClientResponseError as e:
            logger.error(f"HTTP error occurred: {e.status} - {e.message}")
            raise APIError(status_code=e.status, message=e.message)
        except aiohttp.ClientError as e:
            logger.error(f"Client error occurred: {str(e)}")
            raise APIError(status_code=500, message=f"Client error: {str(e)}")
        except asyncio.TimeoutError:
            logger.error("Request timed out")
            raise APIError(status_code=504, message="Request timed out")
        except Exception as e:
            logger.error(f"Unexpected error occurred: {str(e)}")
            raise BotError(f"Unexpected error in API request: {str(e)}")

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_repository_status(self, repo_id: str) -> Dict[str, Any]:
        """Retrieves information about a specific repository."""
        try:
            result = await self._make_request('GET', f'repositories/{repo_id}')
            logger.info(f"Retrieved status for repository {repo_id}: {result.get('status', 'unknown')}")
            return result
        except Exception as e:
            logger.error(f"Failed to get repository status for {repo_id}: {str(e)}")
            raise

    async def index_repository(self, remote: str, repository: str, branch: str) -> Dict[str, Any]:
        """Initiates processing of a specified repository."""
        payload = {
            "remote": remote,
            "repository": repository,
            "branch": branch,
            "reload": True,
            "notify": False
        }
        try:
            result = await self._make_request('POST', 'repositories', json=payload)
            logger.info(f"Indexing initiated for repository {repository}: {result.get('response', 'No response')}")
            return result
        except Exception as e:
            logger.error(f"Failed to index repository {repository}: {str(e)}")
            raise

    async def search(self, query: str, repositories: List[Dict[str, str]], session_id: Optional[str] = None) -> Dict[str, Any]:
        """Searches for relevant code in the repositories."""
        payload = {
            "query": query,
            "repositories": repositories,
            "sessionId": session_id,
            "stream": False
        }
        try:
            result = await self._make_request('POST', 'search', json=payload)
            logger.info(f"Search executed: {query}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute search: {str(e)}")
            raise

    async def query(self, messages: List[Dict[str, str]], repositories: List[Dict[str, str]], session_id: Optional[str] = None, genius: bool = False) -> Dict[str, Any]:
        """Submits a natural language query about the codebase."""
        payload = {
            "messages": messages,
            "repositories": repositories,
            "sessionId": session_id,
            "stream": False,
            "genius": genius
        }
        try:
            result = await self._make_request('POST', 'query', json=payload)
            logger.info(f"Query executed: {messages[-1]['content'] if messages else 'No message content'}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute query: {str(e)}")
            raise