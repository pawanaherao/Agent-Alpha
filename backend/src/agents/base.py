from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import logging

from src.core.messages import AgentMessage
from src.core.event_bus import event_bus

logger = logging.getLogger(__name__)

class BaseAgent(ABC):
    """
    Abstract Base Class for all AI Agents.
    Handles lifecycle, configuration, and communication.
    """
    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(f"agent.{name}")
        self.status = "INITIALIZING"  # INITIALIZING, READY, RUNNING, ERROR
        self.last_execution_time: Optional[datetime] = None
        self.error_count = 0

    async def start(self):
        """Lifecycle hook: Start"""
        self.status = "READY"
        self.logger.info(f"{self.name} started.")

    async def stop(self):
        """Lifecycle hook: Stop"""
        self.status = "STOPPED"
        self.logger.info(f"{self.name} stopped.")

    async def process_message(self, message: AgentMessage):
        """
        Handle incoming direct messages.
        """
        self.logger.info(f"{self.name} received message: {message.message_type}")
        # Default implementation does nothing; override in subclasses

    async def publish_event(self, event_type: str, payload: Dict[str, Any]):
        """
        Publish an event to the global bus.
        """
        await event_bus.publish(event_type, payload)

    def get_health(self) -> Dict[str, Any]:
        """
        Return agent health status.
        """
        return {
            "name": self.name,
            "status": self.status,
            "error_count": self.error_count,
            "last_execution": self.last_execution_time
        }
