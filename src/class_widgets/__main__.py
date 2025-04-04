from dataclasses import dataclass
from datetime import date
from multiprocessing import JoinableQueue, Process
from time import sleep

from pydantic_yaml import parse_yaml_file_as

from .config import ScheduleObject, Subject
from .course_timer import HOUR, MINUTE, Timer, UnitOffsetEventRing
from .course_timer_plugins import (
    CountDownDate,
    NowCourse,
    Sleep,
    TodayAttendCourse,
    TodayNotAttendCourse,
)


@dataclass
class RV:
    index: int
    ctx: str


def ui(length: int, q: JoinableQueue):  # type: ignore
    # 根据 react reducer 做的超级简陋版
    acc = list("" for _ in range(length))
    while True:
        now: RV = q.get()
        acc[now.index] = now.ctx
        print(" | ".join(acc))
        q.task_done()


def eta_to_str(eta: float):
    h = int(eta // HOUR)
    oh = h * HOUR
    m = int((eta - oh) // MINUTE)
    return f"{h}:{str(m).rjust(2, '0')}:{str(int(eta % MINUTE)).rjust(2, '0')}"


def main():
    schedule = parse_yaml_file_as(ScheduleObject, "schedule.full-example.yaml")
    global_event_ring = UnitOffsetEventRing.from_object(schedule).to_global()
    q: JoinableQueue[RV] = JoinableQueue()

    def fmt(x: list[Subject]):
        return " ".join(
            a.short_name if a.short_name else (a.name[0] if a.name else "无") for a in x
        )

    timer = Timer(
        global_event_ring,
        schedule.start,
        [
            Sleep(0.5),
            TodayAttendCourse(lambda x: q.put(RV(index=0, ctx=fmt(x)))),
            NowCourse(
                lambda s, _sid, eta: q.put(
                    RV(
                        1,
                        (s.teacher if s.teacher else "无老师")
                        + "/"
                        + (s.room if s.room else "无教室")
                        + " - "
                        + (s.name if s.name else "无课")
                        + " - ETA "
                        + eta_to_str(eta),
                    )
                )
            ),
            TodayNotAttendCourse(lambda x: q.put(RV(2, fmt(x)))),
            CountDownDate(date(2025, 5, 1), lambda x: q.put(RV(3, f"5/1 {x}天"))),
        ],
    )
    Process(target=ui, args=(4, q), daemon=True).start()
    sleep(10)
    timer.stop()
    q.join()


if __name__ == "__main__":
    main()
