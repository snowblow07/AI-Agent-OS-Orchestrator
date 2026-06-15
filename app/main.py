from fastapi import FastAPI
from db.init_db import initialize_database
from app.api import router as agent_router

# Run startup tasks
initialize_database()

# Initialize API
app = FastAPI(title="AI Agent OS Orchestrator")

# Register Blueprints
app.include_router(agent_router)