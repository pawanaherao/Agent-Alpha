from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

class AgentMessage(BaseModel):
    """
    Standard message format for inter-agent communication.
    """
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    sender: str
    recipient: str  # Agent name or "BROADCAST"
    message_type: str
    payload: Dict[str, Any]
    correlation_id: Optional[str] = None  # To track request-response chains

class RiskDecision(BaseModel):
    """Standardized risk decision output"""
    decision: str  # APPROVED, REJECTED, MODIFIED
    reason: Optional[str] = None
    original_signal_id: str
    modifications: Optional[Dict[str, Any]] = None
