"""Planner backend interfaces and implementations.

Two backends, one router:
- DirectPlannerBackend: HTTPS to NVIDIA cloud, used by default for ~95% of planner turns.
- OpenclawPlannerBackend: SSH to sandbox, used when the user's prompt requires the openclaw
  agent loop with live tools (Phase 1 escalation list lives in PlannerBackendRouter).
- PlannerBackendRouter: dispatches based on PLANNER_BACKEND env (auto|direct|openclaw).
"""

from apps.jewel_voice_guide.planner_backends.base import PlannerBackend
from apps.jewel_voice_guide.planner_backends.direct import DirectPlannerBackend
from apps.jewel_voice_guide.planner_backends.openclaw import OpenclawPlannerBackend
from apps.jewel_voice_guide.planner_backends.router import PlannerBackendMode, PlannerBackendRouter

__all__ = [
    "DirectPlannerBackend",
    "OpenclawPlannerBackend",
    "PlannerBackend",
    "PlannerBackendMode",
    "PlannerBackendRouter",
]
