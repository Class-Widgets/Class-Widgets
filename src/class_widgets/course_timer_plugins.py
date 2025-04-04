from datetime import date, datetime, time
from time import sleep
from typing import Callable

from .config import DEFAULT_SUBJECT_ID, Subject, SubjectId
from .course_timer import DAY, CourseCtx, TimerPlugin


class Sleep(TimerPlugin):
    sleeped = False
    sleep_time: float = 1.0

    def __init__(self, seconds: float):
        self.sleep_time = seconds

    def update_sync(self, ctx: CourseCtx):
        if not self.sleeped:
            self.sleeped = True
        sleep(1)

    def course_end_sync(self, ctx: CourseCtx):
        if not self.sleeped:
            sleep(1)
        self.sleeped = False


type ETA_SEC = float


class NowCourse(TimerPlugin):
    callback: Callable[[Subject, SubjectId, ETA_SEC], None]

    def __init__(self, callback: Callable[[Subject, SubjectId, ETA_SEC], None]):
        self.callback = callback

    def course_start_sync(self, ctx: CourseCtx):
        now = ctx.global_ring.items[ctx.index]
        self.callback(
            now.subject, now.subject_id, now.time_offset - ctx.now_global_offset
        )

    def update_sync(self, ctx: CourseCtx):
        now = ctx.global_ring.items[ctx.index]
        self.callback(
            now.subject, now.subject_id, now.time_offset - ctx.now_global_offset
        )


class TodayAttendCourse(TimerPlugin):
    callback: Callable[[list[Subject]], None]

    def __init__(self, callback: Callable[[list[Subject]], None]):
        self.callback = callback

    def course_start_sync(self, ctx: CourseCtx):
        today_offset = ctx.now_global_offset // DAY * DAY
        self.callback(
            list(
                course.subject
                for course in ctx.global_ring.items[: ctx.index]
                if course.subject_id != DEFAULT_SUBJECT_ID
                and course.time_offset >= today_offset
            )
        )


class TodayNotAttendCourse(TimerPlugin):
    callback: Callable[[list[Subject]], None]

    def __init__(self, callback: Callable[[list[Subject]], None]):
        self.callback = callback

    def course_start_sync(self, ctx: CourseCtx):
        next_day_offset = ctx.now_global_offset // DAY * DAY + DAY
        self.callback(
            list(
                course.subject
                for course in ctx.global_ring.items[ctx.index + 1 :]
                if course.subject_id != DEFAULT_SUBJECT_ID
                and course.time_offset < next_day_offset
            )
        )


class CountDownDate(TimerPlugin):
    date_: datetime
    callback: Callable[[int], None]

    def __init__(self, date_: date, callback: Callable[[int], None]):
        self.date = datetime.combine(date_, time())
        self.callback = callback

    def update_sync(self, ctx: CourseCtx):
        self.callback((self.date - ctx.now).days)
