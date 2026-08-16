from app.schemas.base import BaseModel


class BadgeStatus(BaseModel):
    key: str
    title: str
    desc: str
    unlocked: bool
    progress: int
    progress_text: str


class GrowthProfile(BaseModel):
    total_exp: int
    level: int
    level_title: str
    level_progress_pct: int
    exp_current: int
    exp_to_next: int
    streak_days: int
    streak_title: str
    daily_boost: str
    badges: list[BadgeStatus]
