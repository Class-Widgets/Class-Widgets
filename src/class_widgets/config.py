from datetime import date, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel

DEFAULT_SUBJECT_ID = "default"


class Weekdays(Enum):
    monday = "1"
    tuesday = "2"
    wednesday = "3"
    thursday = "4"
    friday = "5"
    saturday = "6"
    sunday = "7"


class Subject(BaseModel):
    name: str
    room: str | None = None
    teacher: str | None = None
    short_name: str | None = None


class ClassInDay(BaseModel):
    subject: str
    start: time
    end: time


type SubjectId = str


class ScheduleObject(BaseModel):
    version: Literal[2]
    start: date
    subjects: dict[SubjectId, Subject]
    schedules: list[dict[Weekdays, list[ClassInDay]]]
