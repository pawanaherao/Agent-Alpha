import asyncio
from typing import Dict, List, Callable, Awaitable, Any
import logging

logger = logging.getLogger(__name__)

class EventBus:
    """
    Asynchronous Event Bus for inter-agent communication.
    Supports publish-subscribe pattern.
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
        logger.info(f"Subscribed to {event_type}")

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

# Global Event Bus Instance
event_bus = EventBus()
