from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import json
import sqlite3
from app.models import IntentPayload, TelemetryEvent
from app.core import generate_intent_hash, publish_telemetry, lease_heartbeat, redis_client
from app.mcp_client import call_mcp_tool
from app.config import DB_PATH

router = APIRouter(prefix="/agent", tags=["Execution"])

@router.post("/execute")
async def execute_intent(payload: IntentPayload):
    # Ensure deterministic hash if not provided by the caller
    if not payload.intent_id:
        payload.intent_id = generate_intent_hash(payload.tool_name, payload.args)

    intent_hash = payload.intent_id
    exec_id = payload.execution_id

    # Circuit Breaker Check
    failures = int(await redis_client.get(f"failures:{intent_hash}") or 0)
    if failures >= 5:
        await publish_telemetry(TelemetryEvent(
            event_type="IntentQuarantined",
            intent_id=intent_hash, execution_id=exec_id,
            payload={"failures": failures, "status": "LOCKED"}
        ))
        raise HTTPException(status_code=423, detail="QUARANTINED")

    # Idempotency Check
    if await redis_client.get(f"resolved:{intent_hash}"):
        return {"status": "DEDUPLICATED", "intent_hash": intent_hash}

    # Lease Lock with Automatic Heartbeat
    async with lease_heartbeat(intent_hash, interval=10, ttl=30) as acquired:
        if not acquired:
            return {"status": "LOCKED", "intent_hash": intent_hash}

        await publish_telemetry(TelemetryEvent(
            event_type="IntentRegistered",
            intent_id=intent_hash, execution_id=exec_id,
            payload={"tool_name": payload.tool_name, "args": payload.args}
        ))

        try:
            await publish_telemetry(TelemetryEvent(
                event_type="ToolStarted",
                intent_id=intent_hash, execution_id=exec_id,
                payload={"target_ip": payload.args.get('device_ip')}
            ))

            tool_result = await call_mcp_tool(payload.tool_name, payload.args)
            
            # Mark successful execution
            await redis_client.set(f"resolved:{intent_hash}", "true", ex=86400)
            
            await publish_telemetry(TelemetryEvent(
                event_type="ExecutionSucceeded",
                intent_id=intent_hash, execution_id=exec_id,
                payload={"result": tool_result}
            ))
            
            return {
                "status": "SUCCESS", 
                "intent_hash": intent_hash, 
                "result": tool_result
            }
            
        except Exception as e:
            await redis_client.incr(f"failures:{intent_hash}")
            await publish_telemetry(TelemetryEvent(
                event_type="ExecutionFailed",
                intent_id=intent_hash, execution_id=exec_id,
                payload={"error": str(e)}
            ))
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/stream")
async def stream_events(request: Request, last_event_id: str = "0-0"):
    """Server-Sent Events backed by Redis Streams."""
    async def event_generator():
        current_id = last_event_id
        while True:
            if await request.is_disconnected():
                break
            
            # XREAD blocks for up to 2000ms waiting for new data
            streams = await redis_client.xread(
                {"agent_telemetry": current_id}, 
                count=5, 
                block=2000
            )
            
            if streams:
                for stream_name, messages in streams:
                    for msg_id, msg_data in messages:
                        current_id = msg_id
                        yield f"id: {msg_id}\ndata: {msg_data['event']}\n\n"
            else:
                # SSE Keep-Alive ping to prevent browser timeouts
                yield ": keep-alive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/executions/{intent_hash}")
async def get_execution_timeline(intent_hash: str):
    """Returns the full chronological trace of a specific intent."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT execution_id, event_type, payload, timestamp 
        FROM execution_log 
        WHERE intent_hash = ? 
        ORDER BY timestamp ASC
    """, (intent_hash,))
    
    timeline = [
        {
            "execution_id": row[0],
            "event_type": row[1],
            "payload": json.loads(row[2]),
            "timestamp": row[3]
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return {"intent_hash": intent_hash, "timeline": timeline}

@router.get("/dlq")
async def get_dead_letter_queue():
    """Fetches quarantined intents with their full SQLite context."""
    quarantined_keys = await redis_client.keys("failures:*")
    dlq = []
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for key in quarantined_keys:
        failures = int(await redis_client.get(key) or 0)
        if failures >= 5:
            intent_hash = key.split(":")[1]
            
            # Fetch the original payload and the most recent failure
            cursor.execute("""
                SELECT event_type, payload, timestamp 
                FROM execution_log 
                WHERE intent_hash = ? AND (event_type = 'IntentRegistered' OR event_type = 'ExecutionFailed')
                ORDER BY timestamp DESC
            """, (intent_hash,))
            
            history = cursor.fetchall()
            
            item = {"intent_hash": intent_hash, "failures": failures, "history": []}
            for row in history:
                item["history"].append({
                    "event": row[0],
                    "payload": json.loads(row[1]),
                    "timestamp": row[2]
                })
            dlq.append(item)
            
    conn.close()
    return {"dlq": dlq}