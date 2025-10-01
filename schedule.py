from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Union, Tuple

from PyQt5.QtCore import QCoreApplication

import utils
import conf


class ScheduleManager(ABC):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.time_manager = utils.TimeManagerFactory.get_instance()
        self.init()

    @abstractmethod
    def init(self) -> None:
        pass  # noqa

    @abstractmethod
    def get_next_lessons(self) -> List[str]:
        pass  # noqa

    @abstractmethod
    def get_status(self) -> Tuple[bool, float, str]:
        pass  # noqa


class ClassWidgetsScheduleVersion1Manager(ScheduleManager):
    def init(self):
        self.schedule = None
        self.parts = {}
        self.lessons = {
            'odd': {"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
            'even': {"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
        }
        self._cache_lesson_index = None
        self._cache_status = None
        self._cache_time = None
        self._cache_lesson_today = None
        self._init_parser(self.file_path)
        self._init_part()
        self._init_lessons()
        self.print_schedule()

    def _init_parser(self, file_path: Path) -> None:
        from data_model import Schedule

        self.schedule = Schedule.model_validate_json(file_path.read_text(encoding="utf-8"))

    def _init_part(self) -> None:
        if not self.schedule:
            raise RuntimeError("未初始化课表模型类")
        for part_index, part_name in self.schedule.part_name.items():
            part = self.schedule.part[part_index]
            self.parts[part_index] = (part[0] * 60 + part[1], part[2] == 'part', part_name)

    def _init_lessons(self):
        if not self.schedule:
            raise RuntimeError("未初始化课表模型类")
        if not self.parts:
            raise RuntimeError("未初始化节点")

        def sort_timeline_key(item: Tuple[int, str, int, int]):
            return item[1], item[2], item[0]

        def sort_lessons_key(item: Tuple[int, int, set]):
            return item[0]

        for week, lessons_data in self.schedule.schedule.items():
            current_week = 'default' if len(self.schedule.timeline.get(week, [])) == 0 else week
            timeline_data = self.schedule.timeline[current_week]
            timeline_data_sorted = sorted(timeline_data, key=sort_timeline_key)
            timeline_current_usage = {}
            lesson_cnt = 0
            self.lessons['odd'][week] = []
            for isbreak, item_name, _item_index, item_time in timeline_data_sorted:
                if not isbreak:
                    if lessons_data[lesson_cnt] != QCoreApplication.translate('menu', '未添加'):
                        self.lessons['odd'][week].append(
                            (
                                (
                                    timeline_current_usage.get(item_name, self.parts[item_name][0])
                                    * 60,
                                    item_time * 60,
                                    {lessons_data[lesson_cnt]},
                                )
                            )
                        )
                    lesson_cnt += 1
                timeline_current_usage[item_name] = (
                    timeline_current_usage.get(item_name, self.parts[item_name][0]) + item_time
                )

            self.lessons['odd'][week] = sorted(self.lessons['odd'][week], key=sort_lessons_key)
            merged_lessons = []
            for start_time, duration, lessons_set in self.lessons['odd'][week]:
                if (
                    not merged_lessons
                    or start_time >= merged_lessons[-1][0] + merged_lessons[-1][1]
                ):
                    merged_lessons.append((start_time, duration, lessons_set))
                else:
                    last_start, last_duration, last_lessons_set = merged_lessons[-1]
                    end_time = max(last_start + last_duration, start_time + duration)
                    merged_lessons[-1] = (
                        last_start,
                        end_time - last_start,
                        last_lessons_set.union(lessons_set),
                    )
            self.lessons['odd'][week] = merged_lessons

        for week, lessons_data in self.schedule.schedule_even.items():
            current_week = (
                'default' if len(self.schedule.timeline_even.get(week, [])) == 0 else week
            )
            timeline_data = self.schedule.timeline_even[current_week]
            timeline_data_sorted = sorted(timeline_data, key=sort_timeline_key)
            timeline_current_usage = {}
            lesson_cnt = 0
            self.lessons['even'][week] = []
            for isbreak, item_name, _item_index, item_time in timeline_data_sorted:
                if not isbreak:
                    if lessons_data[lesson_cnt] != QCoreApplication.translate('menu', '未添加'):
                        self.lessons['even'][week].append(
                            (
                                (
                                    timeline_current_usage.get(item_name, self.parts[item_name][0])
                                    * 60,
                                    item_time * 60,
                                    {lessons_data[lesson_cnt]},
                                )
                            )
                        )
                    lesson_cnt += 1
                timeline_current_usage[item_name] = (
                    timeline_current_usage.get(item_name, self.parts[item_name][0]) + item_time
                )

            self.lessons['even'][week] = sorted(self.lessons['even'][week], key=sort_lessons_key)
            merged_lessons = []
            for start_time, duration, lessons_set in self.lessons['even'][week]:
                if (
                    not merged_lessons
                    or start_time >= merged_lessons[-1][0] + merged_lessons[-1][1]
                ):
                    merged_lessons.append((start_time, duration, lessons_set))
                else:
                    last_start, last_duration, last_lessons_set = merged_lessons[-1]
                    end_time = max(last_start + last_duration, start_time + duration)
                    merged_lessons[-1] = (
                        last_start,
                        end_time - last_start,
                        last_lessons_set.union(lessons_set),
                    )
            self.lessons['even'][week] = merged_lessons

    def print_schedule(self):
        # For Debug 用完就删！！
        print(self.lessons)

    def get_next_lessons(self) -> List[str]:
        # 返回接下来的所有课程
        current_time = self.time_manager.get_current_time()
        current_weekday = self.time_manager.get_current_weekday()
        current_week_type = conf.get_week_type()
        current_time_in_seconds = (
            current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        )
        lessons_today = self.lessons['even' if current_week_type else 'odd'].get(
            str(current_weekday), []
        )
        l, r = 0, len(lessons_today) - 1
        while l <= r:
            mid = (l + r) // 2
            start_time, duration, lesson_names = lessons_today[mid]
            if start_time <= current_time_in_seconds < start_time + duration:
                return [x for lesson in lessons_today[mid:] for x in lesson[2]]
        if l < len(lessons_today):
            return [x for lesson in lessons_today[l:] for x in lesson[2]]
        return []  # 没有课程了

    def _init_get_status(self) -> Tuple[bool, float, str]:
        # 查找当前时间对应课程 返回 is_break, duration, lesson_name
        current_time = self.time_manager.get_current_time()
        self._cache_time = current_time
        current_weekday = self.time_manager.get_current_weekday()
        current_week_type = conf.get_week_type()
        current_time_in_seconds = (
            current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        )
        lessons_today = self.lessons['even' if current_week_type else 'odd'].get(
            str(current_weekday), []
        )
        self._cache_lessons_today: List[Tuple[int, int, str]] = lessons_today
        l, r = 0, len(lessons_today) - 1
        while l <= r:
            mid = (l + r) // 2
            start_time, duration, lesson_names = lessons_today[mid]
            if start_time <= current_time_in_seconds:
                if current_time_in_seconds < start_time + duration:
                    self._cache_status, self._cache_lesson_index = (
                        False,
                        mid,
                    )
                    return (
                        False,
                        (start_time + duration - current_time_in_seconds),
                        '、'.join(lesson_names),
                    )
                elif mid == len(lessons_today) - 1 or current_time_in_seconds < lessons_today[mid + 1][0]:
                    # 在当前课程结束和下一节课开始之间
                    self._cache_status, self._cache_lesson_index = True, mid + 1
                    if mid + 1 < len(lessons_today):
                        return True, (lessons_today[mid + 1][0] - current_time_in_seconds), ''
                    return True, -1.0, ''
                l = mid + 1
            else:
                r = mid - 1
        self._cache_lesson_index, self._cache_status = l, True
        if l < len(lessons_today):
            next_start_time, _next_duration, _next_lesson_names = lessons_today[l]
            return True, (next_start_time - current_time_in_seconds), ''
        return True, -1.0, ''  # 没有课程了

    def get_status(self) -> Tuple[bool, float, str]:
        if self._cache_time is None:
            return self._init_get_status()
        assert self._cache_lesson_index is not None
        assert self._cache_status is not None
        assert self._cache_lessons_today is not None

        current_time = self.time_manager.get_current_time()
        current_weekday = self.time_manager.get_current_weekday()
        current_week_type = conf.get_week_type()
        current_time_in_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second

        # 如果跨天或课表变动，重新初始化
        if self._cache_time.weekday() != current_time.weekday() or self._cache_lessons_today != self.lessons[
            'even' if current_week_type else 'odd'
        ].get(
            str(current_weekday), []
        ):
            return self._init_get_status()

        idx = self._cache_lesson_index
        lessons_today = self._cache_lessons_today

        cache_time_in_seconds = self._cache_time.hour * 3600 + self._cache_time.minute * 60 + self._cache_time.second
        if current_time_in_seconds == cache_time_in_seconds:
            if self._cache_status:
                if idx < len(lessons_today):
                    next_start, _, _ = lessons_today[idx]
                    return True, (next_start - current_time_in_seconds), ''
                return True, -1.0, ''
            start, duration, names = lessons_today[idx]
            return False, (start + duration - current_time_in_seconds), '、'.join(names)

        # 优雅地向前或向后查找
        if current_time_in_seconds > cache_time_in_seconds:
            # 向后查找
            # 先检查当前课程是否结束
            start, duration, names = lessons_today[idx]
            if current_time_in_seconds < start + duration:
                return False, (start + duration - current_time_in_seconds), '、'.join(names)
            
            # 查找下一节课
            idx += 1
            if idx < len(lessons_today):
                next_start, next_duration, next_names = lessons_today[idx]
                if current_time_in_seconds >= next_start:
                    # 已经到达下一节课时间
                    if current_time_in_seconds < next_start + next_duration:
                        self._cache_lesson_index = idx
                        self._cache_time = current_time
                        self._cache_status = False
                        return False, (next_start + next_duration - current_time_in_seconds), '、'.join(next_names)
                else:
                    # 在两节课之间
                    self._cache_lesson_index = idx
                    self._cache_time = current_time
                    self._cache_status = True
                    return True, (next_start - current_time_in_seconds), ''
            
            # 没有更多课程
            self._cache_lesson_index = idx
            self._cache_time = current_time
            self._cache_status = True
            return True, -1.0, ''

        # 向前查找
        while idx > 0:
            start, duration, names = lessons_today[idx - 1]
            if current_time_in_seconds >= start:
                if current_time_in_seconds < start + duration:
                    self._cache_lesson_index = idx - 1
                    self._cache_time = current_time
                    self._cache_status = False
                    return False, (start + duration - current_time_in_seconds), '、'.join(names)
                break
            idx -= 1
        # 如果没找到，说明还没上课
        self._cache_lesson_index = idx
        self._cache_time = current_time
        self._cache_status = True
        if idx < len(lessons_today):
            next_start, _, _ = lessons_today[idx]
            return True, (next_start - current_time_in_seconds), ''
        return True, -1.0, ''


if __name__ == '__main__':
    # For Debug 用完就删！！
    mgr = ClassWidgetsScheduleVersion1Manager(
        Path('./config/schedule/202501备份(1) @(半白bani_DeBug)254867116-backup.json')
    )
    import time
    while True:
        print(mgr.get_status())
        time.sleep(0.5)
