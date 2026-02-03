import redis.asyncio as redis
from typing import Optional, Any
from src.core.config import settings
import json
import logging

logger = logging.getLogger(__name__)

class RedisClient:
    """
    Redis wrapper for caching and Pub/Sub.
    """
    def __init__(self):
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        """Initialize Redis connection."""
        try:
            self.client = redis.Redis(
                host=settings.REDIS_HOST,
                port=6379,
                decode_responses=True
            )
            await self.client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            logger.info("Disconnected from Redis")

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not self.client:
            return None
        return await self.client.get(key)

    async def set(self, key: str, value: Any, ttl: int = None):
        """Set value in cache with optional TTL."""
        if not self.client:
            return
        await self.client.set(key, value, ex=ttl)

    async def get_json(self, key: str) -> Optional[dict]:
        """Get JSON value from cache."""
        if not self.client:
            return None
        data = await self.client.get(key)
        return json.loads(data) if data else None

    async def set_json(self, key: str, value: dict, ttl: int = None):
        """Set JSON value in cache."""
        if not self.client:
            return
        await self.client.set(key, json.dumps(value), ex=ttl)

cache = RedisClient()
