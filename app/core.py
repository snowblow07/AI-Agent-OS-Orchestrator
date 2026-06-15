import hashlib
import json
import sqlite3
import os
from app.models import IntentPayload
from app.config import DB_PATH

def initialize_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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