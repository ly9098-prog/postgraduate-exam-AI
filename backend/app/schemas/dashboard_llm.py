from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel


class DashboardLlmAnalysisRequest(BaseModel):
    trend_days: int = Field(default=7, ge=1, le=90)


class DashboardLlmAction(BaseModel):
    type: Literal["review", "wrong", "practice", "subject"]
    title: str
    desc: str


class DashboardLlmAnalysisResponse(BaseModel):
    summary: str
    findings: list[str]
    risks: list[str]
    actions: list[DashboardLlmAction]
    generated_at: str
    model: str | None = None
    # True only when the configured remote model produced the result.  False
    # means the endpoint safely fell back to deterministic local data analysis.
    generated: bool = False
