import hashlib
import json
import sqlite3
import asyncio
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from app.models import IntentPayload, TelemetryEvent
from app.config import DB_PATH

# Async Redis for Streams and non-blocking locks
redis_client = aioredis.Redis(host="localhost", port=6379, decode_responses=True)

def generate_intent_hash(tool_name: str, args: dict) -> str:
    """Deterministic fingerprint generation."""
    raw = json.dumps(args, sort_keys=True)
    base = f"{tool_name}:{raw}"
    return hashlib.sha256(base.encode()).hexdigest()

async def publish_telemetry(event: TelemetryEvent):
    """Dual-writes to SQLite (Immutable) and Redis Streams (Observable)."""
    # 1. Write to SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO execution_log
        (intent_hash, execution_id, parent_intent_hash, event_type, payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event.intent_id, 
            event.execution_id, 
            getattr(event, 'parent_intent_id', None), 
            event.event_type, 
            json.dumps(event.payload)
        ),
    )
    conn.commit()
    conn.close()

    # 2. Publish to Redis Stream (capped at ~10,000 recent events to save memory)
    await redis_client.xadd(
        "agent_telemetry",
        {"event": event.model_dump_json()},
        maxlen=10000 
    )

@asynccontextmanager
async def lease_heartbeat(intent_hash: str, interval: int = 15, ttl: int = 60):
    """Maintains the mutex lease while the MCP tool executes."""
    lease_key = f"lease:{intent_hash}"
    
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(interval)
                await redis_client.expire(lease_key, ttl)
        except asyncio.CancelledError:
            pass

    # Attempt to acquire the mutex
    acquired = await redis_client.set(lease_key, "1", ex=ttl, nx=True)
    if not acquired:
        yield False
        return

    # Start the background heartbeat
    task = asyncio.create_task(heartbeat())
    try:
        yield True
    finally:
        task.cancel()
        # Note: We do not explicitly delete the key here.
        # Letting the TTL expire acts as a natural debounce window.