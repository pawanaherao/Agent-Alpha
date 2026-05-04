import asyncio
import logging
import json
from datetime import date, datetime, time
import redis.asyncio as redis
from typing import Dict, List, Callable, Awaitable, Any, Set
from src.core.config import settings

logger = logging.getLogger(__name__)


def _normalize_json_payload(value: Any) -> Any:
    """
    Coerce common runtime scalar types (NumPy/Pandas/date-like) into
    stdlib-json-safe values before publishing through Redis.
    """
    if isinstance(value, dict):
        return {key: _normalize_json_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json_payload(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _normalize_json_payload(value.item())
        except Exception:
            return value
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return _normalize_json_payload(value.tolist())
        except Exception:
            return value
    return value

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
        self.pubsub = None
        self.listen_task = None
        self.is_connected = False
        self._subscribed_channels: Set[str] = set()
        self._pending_channels: Set[str] = set()
        self._subscription_tasks: Set[asyncio.Task] = set()

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
            
            # Subscribe to all channels that were registered before connect().
            for event_type in self.subscribers:
                await self._subscribe_channel(event_type)
            
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
        for task in list(self._subscription_tasks):
            task.cancel()
        if self.pub_client:
            await self.pub_client.close()
        if self.sub_client:
            await self.sub_client.close()
        self.is_connected = False
        self._subscribed_channels.clear()
        self._pending_channels.clear()
        self._subscription_tasks.clear()

    def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], Awaitable[None]]):
        """
        Subscribe a callback function to an event type.
        B22 fix: Made sync (like in-memory EventBus) — Redis channel subscription
        is lazy and happens on first publish or when connect() runs.
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
            
        self.subscribers[event_type].append(callback)

        # If Redis is already connected, subscribe this channel immediately so
        # post-startup subscribers do not miss published events.
        if self.is_connected and self.pubsub:
            self._schedule_channel_subscription(event_type)

        # Note: actual Redis channel subscription is deferred to connect()
        # when subscribe() is called before the bus comes online.
        logger.debug(f"Registered subscriber for Redis channel: {event_type}")

    async def _subscribe_channel(self, event_type: str):
        if not self.is_connected or not self.pubsub:
            return
        if event_type in self._subscribed_channels:
            return

        await self.pubsub.subscribe(event_type)
        self._subscribed_channels.add(event_type)
        logger.debug(f"Redis channel subscribed: {event_type}")

    def _schedule_channel_subscription(self, event_type: str):
        if event_type in self._subscribed_channels or event_type in self._pending_channels:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        self._pending_channels.add(event_type)
        task = loop.create_task(self._subscribe_channel(event_type))
        self._subscription_tasks.add(task)

        def _finalize_subscription(subscription_task: asyncio.Task):
            self._subscription_tasks.discard(subscription_task)
            self._pending_channels.discard(event_type)
            try:
                subscription_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error(f"Failed to subscribe Redis channel {event_type}: {exc}")

        task.add_done_callback(_finalize_subscription)

    async def publish(self, event_type: str, data: Dict[str, Any]):
        """
        Publish an event to Redis.
        """
        if self.is_connected:
            try:
                payload = json.dumps(_normalize_json_payload(data))
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
