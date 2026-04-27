from fastapi import APIRouter
from typing import Optional
from datetime import date

router = APIRouter()


@router.get("/stats")
async def get_stats(from_date: Optional[date] = None, to_date: Optional[date] = None):
    return {
        "total_queries": 48,
        "total_runs": 83,
        "total_cost": 17.9010,
        "total_tokens": 2200000,
    }


@router.get("/cost-by-project")
async def cost_by_project():
    return [
        {"project": "UI Path - RPA", "runs": 11, "tokens": 1800000, "cost": 17.4858},
        {"project": "Backhaul CDR",  "runs": 2,  "tokens": 75200,   "cost": 0.2600},
        {"project": "Load Balancer", "runs": 11, "tokens": 173700,  "cost": 0.1368},
        {"project": "ISE",           "runs": 6,  "tokens": 22300,   "cost": 0.0095},
        {"project": "MagentaMOP",    "runs": 53, "tokens": 3500,    "cost": 0.0000},
    ]


@router.get("/agent-performance")
async def agent_performance():
    return [
        {"name": "uipath_discovery",    "calls": 102, "avg_tokens": 2523,  "files_scanned": 160, "total_cost": 94.565},
        {"name": "uipath_extractor",    "calls": 302, "avg_tokens": 1012,  "files_scanned": 460, "total_cost": 2.1206},
        {"name": "prometheus_extractor","calls": 52,  "avg_tokens": 1424,  "files_scanned": 10,  "total_cost": 0.4053},
        {"name": "feature_discovery",   "calls": 2,   "avg_tokens": 14973, "files_scanned": 0,   "total_cost": 0.0095},
    ]


@router.get("/queries-over-time")
async def queries_over_time():
    return [
        {"date": "2026-03-10", "count": 6},
        {"date": "2026-03-11", "count": 10},
        {"date": "2026-03-12", "count": 12},
        {"date": "2026-03-16", "count": 8},
        {"date": "2026-04-08", "count": 3},
        {"date": "2026-04-13", "count": 2},
        {"date": "2026-04-21", "count": 1},
    ]
