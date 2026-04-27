import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(os.getenv("MONGODB_URL", "mongodb://localhost:27017"))
    return _client


def get_db():
    return get_client()["scribe"]


def get_projects_collection():
    return get_db()["projects"]


def get_sessions_collection():
    return get_db()["sessions"]


def get_events_collection():
    return get_db()["agent_events"]


async def ping_db() -> bool:
    try:
        await get_client().admin.command("ping")
        return True
    except Exception:
        return False
