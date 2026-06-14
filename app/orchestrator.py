import hashlib
import json
import sqlite3
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis

app = FastAPI(title="AI Agent OS Orchestrator")

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

DB_PATH = "data/agent_os_events.db"


class IntentPayload(BaseModel):
    graph_state_id: str
    node_id: str
    telemetry_event_id: str
    tool_name: str
    args: Dict[str, Any]
    parent_intent_hash: Optional[str] = None


def initialize_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS execution_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        intent_hash TEXT NOT NULL,
        parent_intent_hash TEXT,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def generate_intent_hash(payload: IntentPayload) -> str:
    raw = json.dumps(payload.args, sort_keys=True)
    base = f"{payload.graph_state_id}:{payload.node_id}:{payload.telemetry_event_id}:{payload.tool_name}:{raw}"
    return hashlib.sha256(base.encode()).hexdigest()


def log_event(intent_hash, event_type, payload, parent_hash=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO execution_log
        (intent_hash, parent_intent_hash, event_type, payload)
        VALUES (?, ?, ?, ?)
        """,
        (intent_hash, parent_hash, event_type, json.dumps(payload)),
    )

    conn.commit()
    conn.close()


@app.on_event("startup")
def startup():
    initialize_database()


@app.post("/execute")
async def execute_intent(payload: IntentPayload):
    intent_hash = generate_intent_hash(payload)

    # Idempotency check
    if r.get(f"resolved:{intent_hash}"):
        return {"status": "DEDUPLICATED", "intent_hash": intent_hash}

    # Circuit breaker
    if int(r.get(f"failures:{intent_hash}") or 0) >= 5:
        raise HTTPException(status_code=423, detail="QUARANTINED")

    # Lease lock (single-flight protection)
    if not r.set(f"lease:{intent_hash}", "1", ex=30, nx=True):
        return {"status": "LOCKED", "intent_hash": intent_hash}

    log_event(intent_hash, "Registered", payload.model_dump())

    print("Executing:", payload.tool_name)

    r.set(f"resolved:{intent_hash}", "true", ex=86400)

    log_event(intent_hash, "Success", payload.model_dump())

    return {"status": "SUCCESS", "intent_hash": intent_hash}