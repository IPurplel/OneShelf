"""Reading goals API: a yearly book goal and the daily reading streak, in the reader's own days."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from oneshelf.api.sources import error, services
from oneshelf.goals.service import MAX_BOOKS_GOAL, GoalsService

router = APIRouter(prefix="/api")


class GoalBody(BaseModel):
    books_per_year: int | None = Field(default=None)


def _goals(request: Request) -> GoalsService:
    s = services(request)
    return GoalsService(s.conn, s.settings)


@router.get("/goals")
async def goals(request: Request, offset: int = Query(default=0, ge=-840, le=840)):
    """`offset` is the page's getTimezoneOffset() in minutes, so "today" is the reader's today."""
    return _goals(request).summary(offset_minutes=offset)


@router.put("/goals")
async def set_goals(request: Request, body: GoalBody, offset: int = Query(default=0, ge=-840, le=840)):
    try:
        _goals(request).set_books_goal(body.books_per_year)
    except ValueError:
        return error(422, "INVALID_GOAL", f"A yearly goal is between 1 and {MAX_BOOKS_GOAL} books.")
    return _goals(request).summary(offset_minutes=offset)
