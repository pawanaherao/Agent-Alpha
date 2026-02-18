import asyncio
from typing import Dict, List, Callable, Awaitable, Any
import logging

logger = logging.getLogger(__name__)

class EventBus:
    """
    Asynchronous Event Bus for inter-agent communication.
    Supports publish-subscribe pattern.
    Fallback in-memory implementation.
    """
    def __init__(self):
        # Map event_type -> List of callback functions
        self.subscribers: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}

    def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], Awaitable[None]]):
        """
        Subscribe a callback function to an event type.
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to {event_type} (in-memory)")

    async def publish(self, event_type: str, data: Dict[str, Any]):
        """
        Publish an event to all subscribers asynchronously.
        """
        if event_type in self.subscribers:
            tasks = []
            for callback in self.subscribers[event_type]:
                # Create a task for each subscriber to run in parallel
                tasks.append(asyncio.create_task(self._safe_execute(callback, data)))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_execute(self, callback: Callable, data: Dict[str, Any]):
        """
        Execute callback with exception handling to prevent crashing the bus.
        """
        try:
            await callback(data)
        except Exception as e:
            logger.error(f"Error in event subscriber {callback.__name__}: {e}", exc_info=True)

# ============================================================================
# GLOBAL EVENT BUS INSTANCE FACTORY
# ============================================================================
# Phase 5: Medallion Architecture Upgrade
# Tries Redis-backed, falls back to in-memory

_event_bus = None

def initialize_event_bus():
    """Initialize event bus with Redis if available, fallback to in-memory."""
    global _event_bus
    
    try:
        from src.core.event_bus_redis import RedisEventBus
        _event_bus = RedisEventBus()
        logger.info("Event Bus: Using Redis-backed implementation")
        return True
    except ImportError:
        logger.debug("RedisEventBus not available, using in-memory Event Bus")
        _event_bus = EventBus()
        logger.info("Event Bus: Using in-memory implementation")
        return False
    except Exception as e:
        logger.warning(f"Failed to initialize Redis Event Bus: {e}")
        logger.info("Event Bus: Falling back to in-memory implementation")
        _event_bus = EventBus()
        return False

def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        initialize_event_bus()
    return _event_bus

# Initialize on import
event_bus = get_event_bus()

