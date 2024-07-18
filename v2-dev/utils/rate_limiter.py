import asyncio
import time
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# This is not currently fully implemented with our error handler yet

class RateLimiter:
    def __init__(self, rate: int, per: float):
        self.rate = rate
        self.per = per
        self.allowance = rate
        self.last_check = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            time_passed = now - self.last_check
            self.last_check = now
            self.allowance += time_passed * (self.rate / self.per)
            if self.allowance > self.rate:
                self.allowance = self.rate
            if self.allowance < 1:
                wait_time = (1 - self.allowance) * self.per / self.rate
                logger.warning(f"Rate limit exceeded. Waiting for {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time)
                self.allowance = 0
            else:
                self.allowance -= 1

    async def __aenter__(self):
        try:
            await self.acquire()
        except Exception as e:
            logger.error(f"Error in rate limiter: {str(e)}")
            raise RateLimitError(f"Failed to acquire rate limit: {str(e)}")

    async def __aexit__(self, exc_type, exc, tb):
        pass

class UserRateLimiter:
    def __init__(self, rate: int, per: float):
        self.rate = rate
        self.per = per
        self.user_allowances: Dict[str, float] = {}
        self.user_last_check: Dict[str, float] = {}
        self.lock = asyncio.Lock()

    async def acquire(self, user_id: str):
        async with self.lock:
            now = time.monotonic()
            if user_id not in self.user_allowances:
                self.user_allowances[user_id] = self.rate
                self.user_last_check[user_id] = now
            
            time_passed = now - self.user_last_check[user_id]
            self.user_last_check[user_id] = now
            self.user_allowances[user_id] += time_passed * (self.rate / self.per)
            
            if self.user_allowances[user_id] > self.rate:
                self.user_allowances[user_id] = self.rate
            
            if self.user_allowances[user_id] < 1:
                wait_time = (1 - self.user_allowances[user_id]) * self.per / self.rate
                logger.warning(f"User rate limit exceeded for user {user_id}. Waiting for {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time)
                self.user_allowances[user_id] = 0
            else:
                self.user_allowances[user_id] -= 1

    async def __aenter__(self):
        try:
            await self.acquire()
        except Exception as e:
            logger.error(f"Error in user rate limiter: {str(e)}")
            raise RateLimitError(f"Failed to acquire user rate limit: {str(e)}")

    async def __aexit__(self, exc_type, exc, tb):
        pass