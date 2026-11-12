"""사용자 입력, 연습 메뉴, 1주 계획의 데이터 모델 (Pydantic)."""
from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["초급", "중급", "상급"]
Position = Literal["가드", "포워드", "센터", "미정"]  # 미정: 초보자 옵션에서 묻지 않는 경우
RATINGS = ("쉬웠음", "적당", "어려웠음")  # 슛 외 연습 메뉴의 자기평가


class UserInput(BaseModel):
    """사용자가 입력하는 조건. 장소·장비는 가진 것의 이름 목록으로 받는다 (예: 골대, 콘, 벽, 공)."""

    position: Position
    level: Level
    is_beginner: bool = Field(default=False, description="농구를 처음 시작하는 사람 (초보자 옵션)")
    goals: list[str] = Field(default_factory=list, description="약점·목표")
    days_per_week: int = Field(ge=1, le=7, description="주 N일")
    minutes_per_session: int = Field(ge=1, description="회당 M분")
    equipment: list[str] = Field(default_factory=list, description="있는 장소·장비")


class Drill(BaseModel):
    """연습 메뉴 목록(data/)의 한 항목."""

    name: str
    purpose: str
    requires: list[str] = Field(default_factory=list, description="필요한 장소·장비")
    difficulty: Level
    is_shooting: bool = Field(description="슛 연습 메뉴이면 True (난이도 판정 방식이 다르다)")


class PlannedDrill(BaseModel):
    """계획 안의 연습 메뉴. 이름은 연습 메뉴 목록의 이름과 같아야 한다 (T5에서 확인)."""

    name: str
    sets: int = Field(ge=1)
    reps: int = Field(ge=1)
    minutes: int = Field(ge=1, description="이 연습 메뉴의 소요 시간(분)")
    purpose: str


class DayPlan(BaseModel):
    day: str = Field(description="요일 또는 N일차 (예: 월, 1일차)")
    drills: list[PlannedDrill] = Field(min_length=1)

    @property
    def total_minutes(self) -> int:
        return sum(d.minutes for d in self.drills)


class WeeklyPlan(BaseModel):
    days: list[DayPlan] = Field(min_length=1)
