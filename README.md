# AI Agent OS

Phase 1 system:
- FastAPI orchestrator
- Redis locking
- SQLite ledger
- MCP tool server

AI Agent OS is a system designed for robust, idempotent tool execution and skill management for AI agents. It consists of an execution orchestrator and a Model Context Protocol (MCP) server for defining specific skills.

## Components

### 1. Orchestrator (`app/orchestrator.py`)
A FastAPI-based service responsible for reliably executing tool intents. Key features include:
- **Idempotency & Deduplication**: Generates unique hashes for intents (based on graph state, node, tool name, and arguments) to ensure the same intent is not executed multiple times.
- **Distributed Locking**: Uses Redis leases to prevent concurrent execution of the same intent.
- **Quarantine System**: Automatically blocks intents that fail 5 or more times to prevent infinite retry loops.
- **Telemetry & Event Logging**: Records execution attempts, successes, and parent-child intent relationships in a local SQLite database (`data/agent_os_events.db`).

### 2. MCP Server (`app/mcp_server.py`)
A `FastMCP` server named **DiagnosticSkills** that exposes specific system tools to the agent.
Currently available tools:
- `ping_hardware(device_ip: str)`: Pings a specific device IP to verify if it is online.

## Requirements
- Python 3.x
- A running Redis server on `localhost:6379`
- SQLite (included with Python)
- Packages: `fastapi`, `pydantic`, `redis`, `mcp`

## Running the System

1. **Start Redis**: Ensure your local Redis server is up and running.
2. **Start the Orchestrator**: 
   ```bash
   uvicorn app.orchestrator:app --reload
   ```
3. **Start the MCP Server**:
   ```bash
   python app/mcp_server.py
   ```