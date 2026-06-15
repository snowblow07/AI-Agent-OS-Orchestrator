from fastapi import APIRouter, HTTPException
import redis
from app.models import IntentPayload
from app.core import generate_intent_hash, log_event
from app.mcp_client import call_mcp_tool

# Initialize the Blueprint
router = APIRouter(prefix="/agent", tags=["Execution"])
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

@router.post("/execute")
async def execute_intent(payload: IntentPayload):
    intent_hash = generate_intent_hash(payload)

    # Idempotency Check
    if r.get(f"resolved:{intent_hash}"):
        return {"status": "DEDUPLICATED", "intent_hash": intent_hash}

    # Circuit Breaker Check
    if int(r.get(f"failures:{intent_hash}") or 0) >= 5:
        log_event(intent_hash, "IntentQuarantined", payload.model_dump())
        raise HTTPException(status_code=423, detail="QUARANTINED")

    # Lease Lock (Single-Flight)
    if not r.set(f"lease:{intent_hash}", "1", ex=30, nx=True):
        return {"status": "LOCKED", "intent_hash": intent_hash}

    log_event(intent_hash, "IntentRegistered", payload.model_dump())

    # Actual MCP Execution
    try:
        tool_result = await call_mcp_tool(payload.tool_name, payload.args)
        
        # Mark successful execution
        r.set(f"resolved:{intent_hash}", "true", ex=86400)
        log_event(intent_hash, "ExecutionSucceeded", payload.model_dump())
        
        return {
            "status": "SUCCESS", 
            "intent_hash": intent_hash, 
            "result": tool_result  # The physical text from the tool
        }
        
    except Exception as e:
        # Update Failure Model
        r.incr(f"failures:{intent_hash}")
        log_event(intent_hash, "ExecutionFailed", payload.model_dump())
        raise HTTPException(status_code=500, detail=str(e))