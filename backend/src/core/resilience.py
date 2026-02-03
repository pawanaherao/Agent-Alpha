import asyncio
from typing import Callable, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class CircuitBreakerOpenException(Exception):
    """Raised when circuit breaker is open"""
    pass

class CircuitBreaker:
    """
    Circuit Breaker pattern to prevent cascading failures.
    States: CLOSED (Normal), OPEN (Failing), HALF_OPEN (Recovering)
    """
    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  # seconds
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "CLOSED" 

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        """
        if self.state == "OPEN":
            if self._should_retry():
                self.state = "HALF_OPEN"
                logger.info(f"Circuit Breaker '{self.name}' entering HALF_OPEN state.")
            else:
                raise CircuitBreakerOpenException(f"Circuit Breaker '{self.name}' is OPEN.")

        try:
            result = await func(*args, **kwargs)
            
            if self.state == "HALF_OPEN":
                self._reset()
                logger.info(f"Circuit Breaker '{self.name}' recovered to CLOSED state.")
            
            return result

        except Exception as e:
            self._record_failure()
            logger.error(f"Circuit Breaker '{self.name}' call failed: {e}")
            raise e

    def _record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit Breaker '{self.name}' tripped to OPEN state after {self.failure_count} failures.")

    def _should_retry(self) -> bool:
        if not self.last_failure_time:
            return True
        return (datetime.now() - self.last_failure_time) > timedelta(seconds=self.recovery_timeout)

    def _reset(self):
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = None
