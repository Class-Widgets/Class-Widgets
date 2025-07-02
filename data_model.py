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
    raise ValueError({"need": repr(regex), "got": time})


class CsesClass(BaseModel):
    subject: str
    start_time: Annotated[str, AfterValidator(validate_cses_time)]
    end_time: Annotated[str, AfterValidator(validate_cses_time)]


class CsesSchedule(BaseModel):
    name: str
    enable_day: Literal[1, 2, 3, 4, 5, 6, 7]
    weeks: Literal["all", "odd", "even"]
    classes: List[CsesClass]

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        def to_offset(t: str) -> int:
            h, m, s = map(int, t.split(":"))
            return h * 3600 + m * 60 + s  # 还是建议引入个支持最新 YAML 格式的包）

        offsets = [
            (to_offset(class_.start_time), to_offset(class_.end_time))
            for class_ in self.classes
        ]

        n = len(offsets)
        for i in range(n):
            s1, e1 = offsets[i]
            if e1 <= s1:
                raise ValueError({"conflict": f"class {i} has an end_time earlier than its start_time."})
            for j in range(i + 1, n):
                s2, e2 = offsets[j]
                if s1 < e2 and s2 < e1: # 若 [s1,e1) 与 [s2,e2) 有交集。
                    raise ValueError({"conflict": f"class {i} time overlaps with class {j}."})
        return self


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
            raise ValueError({"forget": {"subjects name": forget_subject}})
        return self

    @model_validator(mode="after")
    def validate_schedule_weeks_enable_day(self) -> Self:
        count_map: Dict[Tuple[str, int], List[str]] = dict()
        for schedule in self.schedules:
            current_id = (schedule.weeks, schedule.enable_day)
            current_status = count_map.get(current_id, [])
            count_map[current_id] = current_status + [schedule.name]
        conflict_map = dict(
            (id, names) for id, names in count_map.items() if len(names) > 1
        )
        if len(conflict_map) != 0:
            raise ValueError({"conflict": {"weeks & enable_day": conflict_map}})
        return self

    @model_validator(mode="after")
    def validate_subject_name(self) -> Self:
        count_map: Dict[str, int] = dict()
        for subject in self.subjects:
            current_status = count_map.get(subject.name, 0)
            count_map[subject.name] = current_status + 1
        conflicts = list(
            id for id, count in count_map.items() if count > 1
        )
        if len(conflicts) != 0:
            raise ValueError({"conflict": {"subject name": conflicts}})
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
    def validate_part_name(self) -> Self:
        if no_name_part := set(self.part.keys()) - set(self.part_name.keys()):
            raise ValueError({"forget": {"part name": no_name_part}})
        return self

    @model_validator(mode="after")
    def validate_dict_name(self) -> Self:
        days = set(["0", "1", "2", "3", "4", "5", "6"])
        if forget_day := days - self.schedule.keys():
            raise ValueError({"forget": {"schedule key": forget_day}})
        if forget_day := days - self.schedule_even.keys():
            raise ValueError({"forget": {"schedule_even key": forget_day}})
        timeline_day = set(["default", "0", "1", "2", "3", "4", "5", "6"])
        if forget_day := timeline_day - self.timeline.keys():
            raise ValueError({"forget": {"timeline key": forget_day}})
        return self
