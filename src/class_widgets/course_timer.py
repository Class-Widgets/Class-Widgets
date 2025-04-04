from dataclasses import dataclass
from datetime import date, datetime, time
from multiprocessing import Pool, Process
from multiprocessing.pool import Pool as PoolType

from .config import DEFAULT_SUBJECT_ID, ClassInDay, ScheduleObject, Subject, Weekdays

type OffsetSeconds = float

MINUTE = 60
HOUR = 60 * MINUTE
DAY = HOUR * 24
WEEK = DAY * 7


def time_to_seconds(t: time) -> float:
    return t.hour * HOUR + t.minute * MINUTE + t.second


@dataclass
class EventItem:
    subject: Subject
    subject_id: str
    time_offset: OffsetSeconds


type GlobalOffsetEventItem = EventItem


@dataclass
class GlobalOffsetEventRing:
    """环内的事件的 time_offset 等于从环事件环
    如：
    - 10s
    - 20s
    """

    items: list[GlobalOffsetEventItem]


@dataclass
class CourseCtx:
    """课程上下文，请避免在非同步的代码中修改"""

    now: datetime
    index: int
    global_ring: GlobalOffsetEventRing
    now_global_offset: float
    schedule_start_datetime: datetime


class TimerPlugin:
    def timer_start_sync(self, ring: GlobalOffsetEventRing, start: datetime):
        pass

    # def on_timer_start(self, ring: GlobalOffsetEventRing, start: datetime):
    #     pass

    def course_start_sync(self, ctx: CourseCtx):
        pass

    # def on_course_start(self, ctx: CourseCtx):
    #     pass

    def update_sync(self, ctx: CourseCtx):
        """注意：请尽量避免在此方法内使用耗时操作，否则会阻塞其他事件的处理"""
        pass

    # def on_update(self, ctx: CourseCtx):
    #     pass

    def course_end_sync(self, ctx: CourseCtx):
        pass

    # def on_course_end(self, ctx: CourseCtx):
    #     pass

    def timer_stop_sync(self):
        pass

    # def on_timer_stop(self):
    #     pass


class Timer:
    ring: GlobalOffsetEventRing
    start: datetime
    __to_stop: bool = False
    __timer_loop: Process
    __event_pool: PoolType
    __sum_offset: float
    plugins: list[TimerPlugin]

    def __init__(
        self, ring: GlobalOffsetEventRing, start: date, plugins: list[TimerPlugin]
    ):
        self.ring = GlobalOffsetEventRing(ring.items.copy())
        self.start = datetime.combine(start, time())
        self.plugins = plugins
        self.__timer_loop = Process(target=self.__inner_loop, args=(self.plugins,))
        self.__event_pool = Pool()
        self.__sum_offset = sum(event.time_offset for event in self.ring.items)
        self.__timer_loop.start()

    def get_global_offset(self, now: datetime) -> float:
        # 因为 event ring 是从周一开始的，所以需要加上周一到现在的秒数
        return (
            (now - self.start).total_seconds() + self.start.weekday() * DAY
        ) % self.__sum_offset

    def __inner_loop(self, plugins: list[TimerPlugin]):
        # fp 瘾犯了，可惜 python 没有尾递归优化
        for plugin in plugins:
            plugin.timer_start_sync(self.ring, self.start)
        # for plugin in plugins:
        #     self.__event_pool.apply_async(
        #         func=plugin.on_timer_start, args=(self.ring, self.start)
        #     )
        while not self.__to_stop:
            for index, filtered_event in enumerate(self.ring.items):
                if self.__to_stop:
                    break
                now = datetime.now()
                temp_offset = self.get_global_offset(now)
                if temp_offset > filtered_event.time_offset:
                    continue
                ctx = CourseCtx(now, index, self.ring, temp_offset, self.start)
                for plugin in plugins:
                    plugin.course_start_sync(ctx)
                # for plugin in plugins:
                #     self.__event_pool.apply_async(
                #         func=plugin.on_course_start, args=(ctx,)
                #     )
                while not self.__to_stop and temp_offset < filtered_event.time_offset:
                    now = datetime.now()
                    temp_offset = self.get_global_offset(now)
                    ctx = CourseCtx(now, index, self.ring, temp_offset, self.start)
                    for plugin in plugins:
                        plugin.update_sync(ctx)
                    # for plugin in plugins:
                    #     _ = self.__event_pool.apply_async(
                    #         func=plugin.on_update, args=(ctx,)
                    #     )
                now = datetime.now()
                temp_offset = self.get_global_offset(now)
                ctx = CourseCtx(now, index, self.ring, temp_offset, self.start)
                for plugin in plugins:
                    plugin.course_end_sync(ctx)
                # for plugin in plugins:
                #     self.__event_pool.apply_async(
                #         func=plugin.on_course_end, args=(ctx,)
                #     )
        # for plugin in plugins:
        #     plugin.timer_stop_sync()
        # for plugin in plugins:
        #     self.__event_pool.apply_async(func=plugin.on_timer_stop, args=())

    def stop(self):
        self.__to_stop = True
        self.__event_pool.close()
        self.__timer_loop.terminate()
        for plugin in self.plugins:
            plugin.timer_stop_sync()
        # ?
        self.__timer_loop.close()


@dataclass
class UnitOffsetEventRing:
    """环内的事件的 time_offset 等于它的持续时间的事件环

    如：
    - 10s
    - 10s
    """

    items: list[EventItem]

    @staticmethod
    def __day_events(
        day_obj_list: list[ClassInDay],
        default_subject: Subject,
        subjects: dict[str, Subject],
    ) -> list[EventItem]:
        day_ring: list[EventItem] = []
        acc_offset = 0
        for item_obj in sorted(day_obj_list, key=lambda x: x.start):
            # acc_offset = sum(event.time_offset for event in day_ring)
            start_offset = time_to_seconds(item_obj.start)
            end_offset = time_to_seconds(item_obj.end)
            end_less_then_before = acc_offset > end_offset
            end_less_then_start = item_obj.end <= item_obj.start
            no_subject = item_obj.subject not in subjects
            if end_less_then_before or end_less_then_start or no_subject:
                continue
            # days = (int(day_of_week.value) - 1) * DAY
            if len(day_ring) == 0:
                day_ring.append(
                    EventItem(default_subject, DEFAULT_SUBJECT_ID, start_offset)
                )
                acc_offset = start_offset

            now_subject_item = subjects[item_obj.subject]
            if acc_offset > start_offset:
                offset = end_offset - acc_offset
                day_ring.append(
                    EventItem(
                        now_subject_item,
                        item_obj.subject,
                        offset,
                    )
                )
                acc_offset += offset
            elif acc_offset == start_offset:
                offset = end_offset - start_offset
                day_ring.append(
                    EventItem(
                        now_subject_item,
                        item_obj.subject,
                        offset,
                    )
                )
                acc_offset += offset
            else:
                temp_events = [
                    EventItem(
                        default_subject,
                        DEFAULT_SUBJECT_ID,
                        start_offset - acc_offset,
                    ),
                    EventItem(
                        now_subject_item,
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
                    DEFAULT_SUBJECT_ID,
                    DAY - acc_offset,
                )
            )
        return day_ring

    @staticmethod
    def __week_events(
        week_obj: dict[Weekdays, list[ClassInDay]],
        default_subject: Subject,
        subjects: dict[str, Subject],
    ) -> list[EventItem]:
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
                        DEFAULT_SUBJECT_ID,
                        (back_day_of_week - acc_day_of_week) * DAY,
                    )
                )
            week_ring.extend(
                UnitOffsetEventRing.__day_events(
                    day_obj_list, default_subject, subjects
                )
            )
            acc_day_of_week = day_of_week_int
        if acc_day_of_week < 7:
            week_ring.append(
                EventItem(
                    default_subject,
                    DEFAULT_SUBJECT_ID,
                    (7 - acc_day_of_week) * DAY,
                )
            )
        return week_ring

    @staticmethod
    def from_object(obj: ScheduleObject) -> "UnitOffsetEventRing":
        temp_ring: list[EventItem] = []
        default_subject = obj.subjects.get(DEFAULT_SUBJECT_ID, Subject(name="无课"))
        if len(obj.schedules) == 0:
            return UnitOffsetEventRing(
                [EventItem(default_subject, DEFAULT_SUBJECT_ID, WEEK)]
            )
        for week_obj in obj.schedules:
            temp_ring.extend(
                UnitOffsetEventRing.__week_events(
                    week_obj, default_subject, obj.subjects
                )
            )

        clean_ring: list[EventItem] = []
        for item in temp_ring:
            if len(clean_ring) == 0 or clean_ring[-1].subject_id != item.subject_id:
                clean_ring.append(item)
            else:
                clean_ring[-1].time_offset += item.time_offset

        return UnitOffsetEventRing(clean_ring)

    def to_global(self):
        global_offset_ring: list[GlobalOffsetEventItem] = []
        acc_offset = 0
        # 注意：这里使用 copy() 方法来避免修改原始的 unit_offset_ring
        for event in self.items.copy():
            event.time_offset = acc_offset + event.time_offset
            acc_offset = event.time_offset
            global_offset_ring.append(event)
        return GlobalOffsetEventRing(global_offset_ring)
