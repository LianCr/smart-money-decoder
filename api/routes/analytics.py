"""api/routes/analytics.py — SQL analytics over the judgment archives (read-only, zero token).

Thin forwarder: the SQL lives in analytics/schema.sql + analytics/views.sql, the loading in
analytics/loader.py. Each request rebuilds an in-memory SQLite DB from .data/ (a few ms at
current archive size), so the numbers can never drift from the archives they describe.
"""

from fastapi import APIRouter

from analytics import loader
from api.shared import _err

router = APIRouter()


@router.get("/analytics")
def analytics_all():
    """Every analytics view: scorecard summary, hit rate by confidence / follow call,
    wallet activity, market summary."""
    return loader.analytics_report(loader.DEFAULT_DATA_DIR)


@router.get("/analytics/{view}")
def analytics_view(view: str):
    """One view by name, e.g. /analytics/v_hit_rate_by_confidence."""
    if view not in loader.VIEWS:
        return _err(404, "UNKNOWN_VIEW", f"unknown view '{view}'; available: {', '.join(loader.VIEWS)}")
    report = loader.analytics_report(loader.DEFAULT_DATA_DIR)
    return {"engine": report["engine"], "view": view, "rows": report["views"][view]}
