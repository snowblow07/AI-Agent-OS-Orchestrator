from typing import Any, Dict, Optional
from pydantic import BaseModel

class IntentPayload(BaseModel):
    graph_state_id: str
    node_id: str
    telemetry_event_id: str
    tool_name: str
    args: Dict[str, Any]
    parent_intent_hash: Optional[str] = None