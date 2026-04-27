"""
Seed a demo document into MongoDB for testing the View Docs page.
Run with: python seed_doc.py
Requires scribe-api to be running on :8000, or set MONGODB_URL directly.
"""
import asyncio
import uuid
from datetime import datetime

SEED_CONTENT = """# ISE Multi Active Clusters

## Overview

The ISE Multi Active Clusters feature helps users navigate multiple network security clusters when searching for and managing devices. Instead of guessing which cluster contains their devices, users now see an intelligent tooltip that displays cluster names alongside their corresponding IP address ranges. This eliminates confusion about where to search and ensures users select the correct cluster based on their device's IP address.

The feature supports operations from a single cluster to four or more clusters, each handling different network segments like DT, ANF, MANET, and T-Cloud environments. By providing clear visual guidance about IP ranges, this feature reduces search errors and improves user efficiency when working across distributed network infrastructure.

## User Workflows

**Searching for a device across clusters**

1. The user opens the ISE Device Search panel and enters a device IP address or hostname.
2. A cluster selector tooltip appears, showing each available cluster alongside its IP address range.
3. The user identifies the correct cluster from the tooltip and clicks to select it.
4. The search is scoped to the selected cluster and results are returned immediately.

**Managing multiple cluster environments**

- Network engineers can toggle between DT, ANF, MANET, and T-Cloud segments without leaving the current view.
- The active cluster is highlighted in the header bar so users always know which environment they are operating in.
- Switching clusters preserves the current search query, so users can compare results across environments.

## Business Rules

- A user must select a cluster before initiating a device search when more than one cluster is available.
- Cluster IP ranges are mutually exclusive — a given device IP will resolve to exactly one cluster.
- Clusters are loaded from the ISE configuration service at login and cached for the session duration.
- If a cluster becomes unreachable mid-session, the UI displays a degraded-mode banner and disables operations on that cluster only.

## Integration Points

| System | Integration |
|---|---|
| ISE Configuration Service | Cluster registry — provides cluster names, IP ranges, and segment labels |
| ISE Device Search API | Scoped device queries via `?cluster={id}` parameter |
| Session Store | Active cluster selection persisted across navigation |
| Splunk Logging | Cluster selection and search events forwarded for audit trail |

## Edge Cases

- **Overlapping IP ranges**: Validated at configuration time; two clusters cannot share an IP range. A configuration error banner is shown if this is detected.
- **No clusters configured**: The cluster selector is hidden and device search operates in legacy single-cluster mode.
- **Cluster timeout during selection**: A spinner is shown; if the cluster does not respond within 5 seconds the user is prompted to retry or select another cluster.
- **Device not found in selected cluster**: A "not found in this cluster" message is shown with a suggestion to search other clusters.
"""

SEED_CONTENT_V2 = """# ISE Multi Active Clusters

## Overview

The ISE Multi Active Clusters feature enables network engineers to navigate and manage devices across multiple security cluster environments from a single interface. Users benefit from an intelligent cluster selector that maps IP address ranges to cluster names, removing the need to manually track which cluster hosts a specific device.

The feature covers up to four concurrent cluster environments — DT, ANF, MANET, and T-Cloud — each handling distinct network segments. Visual guidance through IP range tooltips reduces operator errors and accelerates device lookup across distributed infrastructure.

## User Workflows

**Searching for a device across clusters**

1. The user opens the ISE Device Search panel and enters a device IP address or hostname.
2. A cluster selector tooltip appears, showing each available cluster alongside its IP address range.
3. The user identifies the correct cluster from the tooltip and clicks to select it.
4. The search is scoped to the selected cluster and results are returned immediately.

**Managing multiple cluster environments**

- Network engineers can toggle between DT, ANF, MANET, and T-Cloud segments without leaving the current view.
- The active cluster is highlighted in the header bar so users always know which environment they are operating in.
- Switching clusters preserves the current search query, so users can compare results across environments.

## Business Rules

- A user must select a cluster before initiating a device search when more than one cluster is available.
- Cluster IP ranges are mutually exclusive — a given device IP will resolve to exactly one cluster.
- Clusters are loaded from the ISE configuration service at login and cached for the session duration.
- If a cluster becomes unreachable mid-session, the UI displays a degraded-mode banner and disables operations on that cluster only.

## Integration Points

| System | Integration |
|---|---|
| ISE Configuration Service | Cluster registry — provides cluster names, IP ranges, and segment labels |
| ISE Device Search API | Scoped device queries via `?cluster={id}` parameter |
| Session Store | Active cluster selection persisted across navigation |
| Splunk Logging | Cluster selection and search events forwarded for audit trail |

## Edge Cases

- **Overlapping IP ranges**: Validated at configuration time; two clusters cannot share an IP range. A configuration error banner is shown if this is detected.
- **No clusters configured**: The cluster selector is hidden and device search operates in legacy single-cluster mode.
- **Cluster timeout during selection**: A spinner is shown; if the cluster does not respond within 5 seconds the user is prompted to retry or select another cluster.
- **Device not found in selected cluster**: A "not found in this cluster" message is shown with a suggestion to search other clusters.
"""


async def seed():
    try:
        import motor.motor_asyncio
        import os
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

        mongo_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
        db = client["scribe"]

        # Find first available project
        project = await db["projects"].find_one({})
        if not project:
            print("No projects found in MongoDB. Create a project first, then run this script.")
            return

        project_id = str(project["_id"])
        print(f"Seeding document for project: {project.get('name', project_id)} ({project_id})")

        doc_id = str(uuid.uuid4())[:12]
        now = datetime.utcnow().isoformat()
        doc = {
            "_id": doc_id,
            "project_id": project_id,
            "session_id": "seed_session",
            "feature": "ISE Multi Active Clusters",
            "content": SEED_CONTENT_V2,
            "depth": "standard",
            "approved": False,
            "versions": [
                {"content": SEED_CONTENT, "saved_at": now},
            ],
            "generated_at": now,
        }

        await db["documents"].replace_one(
            {"project_id": project_id, "feature": "ISE Multi Active Clusters"},
            doc,
            upsert=True,
        )

        # Bump project docs_count
        await db["projects"].update_one(
            {"_id": project["_id"]},
            {"$set": {"docs_count": 1}},
        )

        print(f"Seeded document {doc_id} for project {project_id}")
        print("Restart scribe-api and refresh the project list — 'View Docs' button should now appear.")

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(seed())
