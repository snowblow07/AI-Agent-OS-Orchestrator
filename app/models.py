from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
import uuid
import time

class IntentPayload(BaseModel):
    # Optional on ingress; if missing, the backend generates it deterministically.
    intent_id: Optional[str] = None
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_intent_id: Optional[str] = None
    tool_name: str
    args: Dict[str, Any]

class TelemetryEvent(BaseModel):
    event_type: str
    intent_id: str
    execution_id: str
    timestamp: float = Field(default_factory=time.time)
    payload: Dict[str, Any]