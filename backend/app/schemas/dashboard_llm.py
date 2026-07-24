from typing import Literal

from pydantic import BaseModel


class DashboardLlmAnalysisRequest(BaseModel):
    trend_days: int = 7


class DashboardLlmAction(BaseModel):
    type: Literal["review", "wrong", "practice", "subject", "none"]
    title: str
    desc: str


class DashboardLlmAnalysisResponse(BaseModel):
    summary: str
    findings: list[str]
    risks: list[str]
    actions: list[DashboardLlmAction]
    generated_at: str
    model: str | None = None
