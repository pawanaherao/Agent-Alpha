import asyncio
import logging
import json
import redis.asyncio as redis
from typing import Dict, List, Callable, Awaitable, Any
from src.core.config import settings

logger = logging.getLogger(__name__)

class RedisEventBus:
    """
    High-Performance Redis Pub/Sub Event Bus.
    Decouples agents and allows multi-process architecture.
    """
    def __init__(self):
        self.subscribers: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}
        self.redis_url = f"redis://{settings.REDIS_HOST}:6379"
        self.pub_client = None
        self.sub_client = None
        self.listen_task = None
        self.is_connected = False

    async def connect(self):
        """Initialize Redis connections."""
        try:
            # Publisher connection
            self.pub_client = redis.from_url(self.redis_url, decode_responses=True)
            
            # Subscriber connection
            self.sub_client = redis.from_url(self.redis_url, decode_responses=True)
            self.pubsub = self.sub_client.pubsub()
            
            # Test connection
            await self.pub_client.ping()
            self.is_connected = True
            
            # Start listener loop
            self.listen_task = asyncio.create_task(self._listener())
            logger.info(f"Redis Event Bus connected to {self.redis_url} 🚀")
            
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Falling back to internal bus.")
            self.is_connected = False

    async def disconnect(self):
        """Close Redis connections."""
        if self.listen_task:
            self.listen_task.cancel()
        if self.pub_client:
            await self.pub_client.close()
        if self.sub_client:
            await self.sub_client.close()
        self.is_connected = False

    async def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], Awaitable[None]]):
        """
        Subscribe a callback function to an event type.
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
            
        self.subscribers[event_type].append(callback)
        
        if self.is_connected:
            await self.pubsub.subscribe(event_type)
            logger.info(f"Subscribed to Redis channel: {event_type}")

    async def publish(self, event_type: str, data: Dict[str, Any]):
        """
        Publish an event to Redis.
        """
        if self.is_connected:
            try:
                payload = json.dumps(data)
                await self.pub_client.publish(event_type, payload)
            except Exception as e:
                logger.error(f"Redis publish error: {e}")
        else:
            # Fallback to local execution if Redis is down
            await self._dispatch_local(event_type, data)

    async def _listener(self):
        """
        Background task to listen for Redis messages.
        """
        try:
            async for message in self.pubsub.listen():
                if message['type'] == 'message':
                    event_type = message['channel']
                    payload = message['data']
                    try:
                        data = json.loads(payload)
                        await self._dispatch_local(event_type, data)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode JSON from {event_type}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis listener crashed: {e}")
            self.is_connected = False

    async def _dispatch_local(self, event_type: str, data: Dict[str, Any]):
        """
        Dispatch event to local subscribers.
        """
        if event_type in self.subscribers:
            tasks = []
            for callback in self.subscribers[event_type]:
                tasks.append(asyncio.create_task(self._safe_execute(callback, data)))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_execute(self, callback: Callable, data: Dict[str, Any]):
        """Execute callback safely."""
        try:
            await callback(data)
        except Exception as e:
            logger.error(f"Error in subscriber {callback.__name__}: {e}", exc_info=True)
