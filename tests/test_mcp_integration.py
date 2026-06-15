import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
import redis.asyncio as aioredis
import sqlite3

from app.main import app
from app.core import generate_intent_hash
from app.models import IntentPayload
from app.config import DB_PATH

client = TestClient(app)

TEST_PAYLOAD = {
    "tool_name": "ping_hardware",
    "args": {"device_ip": "10.0.0.1"}
}

@pytest_asyncio.fixture(autouse=True)
async def setup_and_teardown():
    r = aioredis.Redis(host='localhost', port=6379, decode_responses=True)
    intent_hash = generate_intent_hash(TEST_PAYLOAD["tool_name"], TEST_PAYLOAD["args"])
    
    # Pre-test cleanup
    await r.delete(f"resolved:{intent_hash}")
    await r.delete(f"failures:{intent_hash}")
    await r.delete(f"lease:{intent_hash}")
    
    yield
    
    # Post-test cleanup
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM execution_log WHERE intent_hash = ?", (intent_hash,))
    conn.commit()
    conn.close()

@pytest.mark.asyncio
async def test_live_mcp_execution():
    """Validates orchestrator integration, telemetry events, and physical MCP execution."""
    response = client.post("/agent/execute", json=TEST_PAYLOAD)
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "SUCCESS"
    assert "intent_hash" in data
    assert "10.0.0.1 is online" in data["result"]

    # Verify timeline was recorded accurately
    timeline_response = client.get(f"/agent/executions/{data['intent_hash']}")
    timeline = timeline_response.json()["timeline"]
    
    events_recorded = [event["event_type"] for event in timeline]
    assert "IntentRegistered" in events_recorded
    assert "ToolStarted" in events_recorded
    assert "ExecutionSucceeded" in events_recorded