from dataclasses import dataclass
from pathlib import Path
from re import match
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, model_validator
from pydantic.functional_validators import AfterValidator
from typing_extensions import Annotated, Self


class ThemeConfig(BaseModel):
    name: str
    support_dark_mode: bool
    default_theme: Optional[Literal["dark", "light"]] = None
    radius: str
    spacing: int
    shadow: bool
    height: int
    widget_width: Dict[str, int]


@dataclass
class ThemeInfo:
    path: Path
    config: ThemeConfig


class Subjects(BaseModel):
    name: str
    teacher: Optional[str] = None
    room: Optional[str] = None
    simplified_name: Optional[str] = None


def validate_cses_time(time: str) -> str:
    regex = r"([01]\d|2[0-3]):([0-5]\d):([0-5]\d)"
    if match(regex, time):
        return time
    raise ValueError(f"Invalid time format: {repr(time)}, need {repr(regex)}")


class CsesClass(BaseModel):
    subject: str
    start_time: Annotated[str, AfterValidator(validate_cses_time)]
    end_time: Annotated[str, AfterValidator(validate_cses_time)]


class CsesSchedule(BaseModel):
    name: str
    enable_day: Literal[1, 2, 3, 4, 5, 6, 7]
    weeks: Literal["all", "odd", "even"]
    classes: List[CsesClass]


class Cses(BaseModel):
    version: Literal[1]
    subjects: List[Subjects]
    schedules: List[CsesSchedule]

    @model_validator(mode="after")
    def validate_schedule_name(self) -> Self:
        sujects_name_set = {subject.name for subject in self.subjects}
        classes_name_set = {
            class_.subject for schedule in self.schedules for class_ in schedule.classes
        }
        if forget_subject := (classes_name_set - sujects_name_set):
            err_msg = "、".join(repr(name) for name in forget_subject)
            raise ValueError(f"缺少 {err_msg} 课")
        return self


class Schedule(BaseModel):
    url: str = "local"
    part: Dict[str, List[Tuple[int, int, str]]]
    part_name: Dict[str, str]
    timeline: Dict[
        Literal["default", "0", "1", "2", "3", "4", "5", "6"], Dict[str, str]
    ]
    schedule: Dict[Literal["0", "1", "2", "3", "4", "5", "6"], List[str]]
    schedule_even: Dict[Literal["0", "1", "2", "3", "4", "5", "6"], List[str]]

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if no_name_part := set(self.part.keys()) - set(self.part_name.keys()):
            raise ValueError(
                f"缺少 {'、'.join(repr(name) for name in no_name_part)} 的名称"
            )
        return self
