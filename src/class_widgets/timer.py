from dataclasses import dataclass
from datetime import date, datetime, time
from multiprocessing import Process
from time import sleep
from typing import Callable

from .config import DEFAULT_ID, ClassInDay, ScheduleObject, Subject, Weekdays

type OffsetSeconds = int
type EtaSeconds = int

MINUTE = 60
HOUR = 60 * MINUTE
DAY = HOUR * 24
WEEK = DAY * 7


def time_to_seconds(t: time) -> int:
    return t.hour * HOUR + t.minute * MINUTE + t.second


@dataclass
class EventItem:
    subject: Subject
    subject_id: str
    time_offset: OffsetSeconds


type GlobalOffsetRing = list[EventItem]


class Timer:
    ring: list[EventItem]
    start: date
    __to_stop: bool = False
    __state: Process | None

    def __init__(self, ring: list[EventItem], start: date):
        self.ring = ring
        self.start = start
        self.__to_stop = False
        self.__state = None

    def __inner_loop(
        self, action: (Callable[[EtaSeconds, GlobalOffsetRing, int], None])
    ):
        start_time = datetime.combine(self.start, time())
        sum_offset = sum(event.time_offset for event in self.ring)

        def get_global_offset():
            return (
                (datetime.now() - start_time).total_seconds()
                + self.start.weekday() * DAY
            ) % sum_offset

        global_offset_ring: list[EventItem] = []
        acc_offset = 0
        for event in self.ring:
            event.time_offset = acc_offset + event.time_offset
            acc_offset = event.time_offset
            global_offset_ring.append(event)
        while not self.__to_stop:
            for index, filtered_event in enumerate(global_offset_ring):
                temp_offset = get_global_offset()
                while not self.__to_stop and temp_offset < filtered_event.time_offset:
                    action(
                        int(filtered_event.time_offset - temp_offset),
                        global_offset_ring,
                        index,
                    )
                    sleep(1)
                    temp_offset = get_global_offset()

    def stop(self):
        if self.__state is None:
            return
        self.__to_stop = True
        self.__state.join()

    def exec(self, action: Callable[[EtaSeconds, GlobalOffsetRing, int], None]):
        self.__state = Process(target=self.__inner_loop, args=(action,))
        self.__state.start()
        return


@dataclass
class EventRing:
    ring: list[EventItem]
    start: date

    @staticmethod
    def from_object(obj: ScheduleObject) -> "EventRing":
        temp_ring: list[EventItem] = []
        default_subject = obj.subjects.get(DEFAULT_ID, Subject(name="无课"))

        def day_events(day_obj_list: list[ClassInDay]) -> list[EventItem]:
            day_ring: list[EventItem] = []
            acc_offset = 0
            for item_obj in sorted(day_obj_list, key=lambda x: x.start):
                # acc_offset = sum(event.time_offset for event in day_ring)
                start_offset = time_to_seconds(item_obj.start)
                end_offset = time_to_seconds(item_obj.end)
                end_less_then_before = acc_offset > end_offset
                end_less_then_start = item_obj.end <= item_obj.start
                no_subject = item_obj.subject not in obj.subjects
                if end_less_then_before or end_less_then_start or no_subject:
                    continue
                # days = (int(day_of_week.value) - 1) * DAY
                if len(day_ring) == 0:
                    day_ring.append(
                        EventItem(default_subject, DEFAULT_ID, start_offset)
                    )
                    acc_offset = start_offset
                if acc_offset > start_offset:
                    offset = end_offset - acc_offset
                    day_ring.append(
                        EventItem(
                            obj.subjects[item_obj.subject],
                            item_obj.subject,
                            offset,
                        )
                    )
                    acc_offset += offset
                elif acc_offset == start_offset:
                    offset = end_offset - start_offset
                    day_ring.append(
                        EventItem(
                            obj.subjects[item_obj.subject],
                            item_obj.subject,
                            offset,
                        )
                    )
                    acc_offset += offset

                else:
                    temp_events = [
                        EventItem(
                            default_subject,
                            DEFAULT_ID,
                            start_offset - acc_offset,
                        ),
                        EventItem(
                            obj.subjects[item_obj.subject],
                            item_obj.subject,
                            end_offset - start_offset,
                        ),
                    ]
                    day_ring.extend(temp_events)
                    acc_offset += sum(event.time_offset for event in temp_events)
            if acc_offset < DAY and len(day_ring) != 0:
                day_ring.append(
                    EventItem(
                        default_subject,
                        DEFAULT_ID,
                        DAY - acc_offset,
                    )
                )
            return day_ring

        def week_events(week_obj: dict[Weekdays, list[ClassInDay]]) -> list[EventItem]:
            acc_day_of_week = 1
            week_ring: list[EventItem] = []
            for day_of_week, day_obj_list in sorted(
                week_obj.items(), key=lambda x: x[0].value
            ):
                day_of_week_int = int(day_of_week.value)
                back_day_of_week = day_of_week_int - 1
                # e.g. 周三大于周一，补一天周二
                if acc_day_of_week < back_day_of_week:
                    week_ring.append(
                        EventItem(
                            default_subject,
                            DEFAULT_ID,
                            (back_day_of_week - acc_day_of_week) * DAY,
                        )
                    )
                week_ring.extend(day_events(day_obj_list))
                acc_day_of_week = day_of_week_int
            if acc_day_of_week < 7:
                week_ring.append(
                    EventItem(
                        default_subject,
                        DEFAULT_ID,
                        (7 - acc_day_of_week) * DAY,
                    )
                )
            return week_ring

        for week_obj in obj.schedules:
            temp_ring.extend(week_events(week_obj))

        clean_ring = []
        for item in temp_ring:
            if len(clean_ring) == 0 or clean_ring[-1].subject_id != item.subject_id:
                clean_ring.append(item)
            else:
                clean_ring[-1].time_offset += item.time_offset

        return EventRing(clean_ring, start=obj.start)

    def to_timer(self) -> Timer:
        return Timer(ring=self.ring, start=self.start)
