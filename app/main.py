from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.routers import projects, docs, sessions, dashboard, agents, intakes
from app.database import ping_db

app = FastAPI(
    title="Scribe API",
    description="AI-powered documentation generation and management platform.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(docs.router,     prefix="/api/v1/documents", tags=["Documents"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Sessions"])
app.include_router(dashboard.router,prefix="/api/v1/dashboard",tags=["Dashboard"])
app.include_router(agents.router,   prefix="/api/v1/agents",   tags=["Agents"])
app.include_router(intakes.router,  prefix="/api/v1/intakes",  tags=["Intakes"])


@app.get("/health", tags=["Health"])
async def health():
    db_ok = await ping_db()
    return {"status": "ok", "service": "scribe-api", "mongodb": "connected" if db_ok else "unreachable"}
