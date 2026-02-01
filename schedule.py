from abc import ABC, abstractmethod
from pathlib import Path
from shutil import copy
from typing import Dict, List, Optional, Set, Tuple, Type

from loguru import logger
from PyQt5.QtCore import QCoreApplication, QThread, pyqtSignal

import conf
import tip_toast
import utils
from basic_dirs import CW_HOME, SCHEDULE_DIR


class ScheduleProvider(ABC):
    def __init__(self, schedule_name: str):
        self.schedule_name = schedule_name
        self.time_manager = utils.TimeManagerFactory.get_instance()
        self.init()

    @abstractmethod
    def init(self) -> None:
        pass

    @staticmethod
    @abstractmethod
    def name() -> str:
        pass

    @staticmethod
    @abstractmethod
    def init_schedule(schedule_name: Path) -> bool:
        pass

    @abstractmethod
    def get_next_lessons(self) -> List[str]:
        pass

    @abstractmethod
    # 返回 (status, duration, total_time, lesson_name)
    def get_status(self) -> Tuple[int, float, float, str]:
        pass

    @abstractmethod
    def get_idx(self) -> int:
        """Return the current lesson index. -1 if is in break."""

    @abstractmethod
    def stop(self) -> None:
        pass


class ClassWidgetsScheduleVersion1Provider(ScheduleProvider):
    @staticmethod
    def name() -> str:
        return "cw1pvd"

    @staticmethod
    def init_schedule(schedule_name: Path) -> bool:
        try:
            copy(CW_HOME / 'data' / 'default_schedule.json', SCHEDULE_DIR / schedule_name)
            return True
        except Exception:
            return False

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
        self._cache_lessons_today = None
        # 缓存 _find_current_idx_and_cache 的结果，避免频繁调用（秒）
        self._find_cache_ts = 0.0
        self._find_cache_result = None
        self._find_cache_ttl = 1.0
        self._init_parser(SCHEDULE_DIR / self.schedule_name)
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
        if self.schedule is None:
            raise RuntimeError("未初始化课表模型类")
        if self.parts is None:
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
                                timeline_current_usage.get(item_name, self.parts[item_name][0])
                                * 60,
                                item_time * 60,
                                {lessons_data[lesson_cnt]},
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
                                timeline_current_usage.get(item_name, self.parts[item_name][0])
                                * 60,
                                item_time * 60,
                                {lessons_data[lesson_cnt]},
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

    def _find_current_idx_and_cache(self) -> Tuple[int, List[Tuple[int, int, Set]], int]:
        """
        统一的查找函数：计算当前时间对应的 lessons_today 与索引，并更新缓存。
        返回 (idx, lessons_today, current_time_in_seconds)
        idx 表示插入位置（如果在课间则为下一节的索引），若正在上课则为当前节的索引。
        """
        import time as _time

        # 使用短时缓存避免每次调用都做较重的计算
        now_ts = _time.time()
        if self._find_cache_result is not None and now_ts - getattr(
            self, "_find_cache_ts", 0.0
        ) < getattr(self, "_find_cache_ttl", 0.0):
            return self._find_cache_result

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
        # 更新缓存的 lessons_today
        self._cache_lessons_today = lessons_today
        self._cache_lesson_today = lessons_today

        # 二分查找当前索引或插入位置
        l, r = 0, len(lessons_today) - 1
        while l <= r:
            mid = (l + r) // 2
            start_time, duration, _ = lessons_today[mid]
            if start_time <= current_time_in_seconds < start_time + duration:
                # 正在上课
                self._cache_status = False
                self._cache_lesson_index = mid
                return mid, lessons_today, current_time_in_seconds
            if start_time < current_time_in_seconds:
                l = mid + 1
            else:
                r = mid - 1

        # 不在任何课程中，l 为下一节课的索引（可能等于 len）
        self._cache_status = True
        self._cache_lesson_index = l
        self._find_cache_ts = now_ts
        self._find_cache_result = (l, lessons_today, current_time_in_seconds)
        return l, lessons_today, current_time_in_seconds

    def get_next_lessons(self) -> List[str]:
        # 返回接下来的所有课程
        idx, lessons_today, _ = self._find_current_idx_and_cache()
        if not lessons_today:
            return []
        # 不返回当前正在进行的课程（如果正在上课，则从下一节开始）
        start = idx + 1 if not self._cache_status else idx
        if start < len(lessons_today):
            return [x for lesson in lessons_today[start:] for x in lesson[2]]
        return []

    def _init_get_status(self) -> Tuple[int, float, float, str]:
        # 使用统一查找函数初始化并返回状态
        # 返回 (status, duration, total_time, lesson_name)
        # status: 0=课间, 1=上课, 2=在所有课程之前, 3=放学
        idx, lessons_today, current_time_in_seconds = self._find_current_idx_and_cache()
        # 没有课程：视为放学
        if not lessons_today:
            return 3, -1.0, 0.0, ''
        # 正在上课 -> status=1
        if not self._cache_status:
            start, duration, names = lessons_today[idx]
            return (
                1,
                (start + duration - current_time_in_seconds),
                float(duration),
                '、'.join(names),
            )
        # 处于课间或无课
        # 在第一节之前 -> status=2
        if idx == 0:
            next_start, next_duration, _ = lessons_today[0]
            return 2, float(next_start - current_time_in_seconds), 1e9 + 7, ''
        # 已经全部结束 -> status=3
        if idx >= len(lessons_today):
            return 3, 0.0, 0.0, ''
        # 正常课间（位于第 idx-1 节与第 idx 节之间） -> status=0
        prev_start, prev_duration, _ = lessons_today[idx - 1]
        prev_end = prev_start + prev_duration
        next_start, _next_duration, _ = lessons_today[idx]
        break_total = next_start - prev_end
        return 0, float(break_total), float(next_start - current_time_in_seconds), ''

    def get_status(self) -> Tuple[int, float, float, str]:
        # 为简洁直接使用统一查找函数，实时返回状态
        # 返回 (status, duration, total_time, lesson_name)
        idx, lessons_today, current_time_in_seconds = self._find_current_idx_and_cache()
        # 没有课程：视为放学
        if not lessons_today:
            return 3, -1.0, 0.0, ''
        # 正在上课 -> status=1
        if not self._cache_status:
            start, duration, names = lessons_today[idx]
            return (
                1,
                (start + duration - current_time_in_seconds),
                float(duration),
                '、'.join(names),
            )
        # 处于课间或无课
        if idx == 0:
            next_start, next_duration, _ = lessons_today[0]
            return 2, float(next_start - current_time_in_seconds), 1e9 + 7, ''
        if idx >= len(lessons_today):
            return 3, 0.0, 0.0, ''
        prev_start, prev_duration, _ = lessons_today[idx - 1]
        prev_end = prev_start + prev_duration
        next_start, _next_duration, _ = lessons_today[idx]
        break_total = next_start - prev_end
        return 0, float(break_total), float(next_start - current_time_in_seconds), ''

    def get_idx(self) -> int:
        idx, _lessons_today, _ = self._find_current_idx_and_cache()
        # 如果在课间返回 -1
        if self._cache_status:
            return -1
        return idx

    def stop(self) -> None:
        pass


class ScheduleManager:
    def __init__(self):
        self.provider: Optional[ScheduleProvider] = None
        self.providers: Dict[str, Type[ScheduleProvider]] = {}
        self._init_providers()

    def _init_providers(self):
        hard_coded_providers: List[Tuple[str, Type[ScheduleProvider]]] = [
            ("cw1pvd", ClassWidgetsScheduleVersion1Provider)
        ]
        for name, pvd in hard_coded_providers:
            self.providers[name] = pvd

    def switch_manager(self, provider_str: str, schedule_name: str):
        if self.provider:
            self.provider.stop()
        self.provider = self.providers[provider_str](schedule_name)

    def _init_schedule(self, provider_str: str, schedule_name: Path) -> bool:
        if provider_str not in self.providers:
            return False
        return self.providers[provider_str].init_schedule(schedule_name)

    def create_new_schedule(self, provider_str: str, schedule_name: Path) -> bool:
        return self._init_schedule(provider_str, schedule_name)

    def get_next_lessons(self) -> List[str]:
        if not self.provider:
            return []
        return self.provider.get_next_lessons()

    def get_status(self) -> Tuple[int, float, float, str]:
        if not self.provider:
            return 3, -1.0, 0.0, ''
        return self.provider.get_status()

    def get_idx(self) -> int:
        if not self.provider:
            return -1
        return self.provider.get_idx()

    def is_ready(self) -> bool:
        return self.provider is not None


class ScheduleThread(QThread):
    status_updated = pyqtSignal(int, float, float, str)
    next_lessons_updated = pyqtSignal(list)
    idx_updated = pyqtSignal(int)

    def __init__(self, schedule_manager: ScheduleManager):
        super().__init__()
        self.schedule_manager = schedule_manager
        self._running = True

    def run(self):
        while self._running:
            status = self.schedule_manager.get_status()
            self.status_updated.emit(*status)
            logger.debug(f"Status updated: {status}")

            next_lessons = self.schedule_manager.get_next_lessons()
            self.next_lessons_updated.emit(next_lessons)
            logger.debug(f"Next lessons: {next_lessons}")

            idx = self.schedule_manager.get_idx()
            logger.debug(f"Current lesson index: {idx}")
            self.idx_updated.emit(idx)

            self.msleep(500)  # 每500毫秒更新一次状态

    def stop(self):
        self._running = False
        self.wait()


class NotificationManager:
    def __init__(self, schedule_thread: ScheduleThread):
        self.idx: Optional[int] = None
        self.status: Optional[int] = None
        self.current_lesson_name: Optional[str] = None
        self.next_lessons: Optional[List[str]] = None
        self.schedule_thread = schedule_thread
        schedule_thread.status_updated.connect(self.on_status_updated)
        schedule_thread.next_lessons_updated.connect(self.on_next_lessons_updated)
        schedule_thread.idx_updated.connect(self.update_idx)

    def update_idx(self, idx: int) -> None:
        if self.idx is None:
            self.idx = idx
            return
        if idx != self.idx:
            # 发送通知
            self._provide_notification(idx)
        self.idx = idx

    def on_status_updated(
        self, status: int, duration: float, total_time: float, lesson_name: str
    ) -> None:
        # status: 0=课间,1=上课,2=在所有课程之前,3=放学
        self.status = status
        if status == 1:
            self.current_lesson_name = lesson_name
        else:
            self.current_lesson_name = ''

    def on_next_lessons_updated(self, lessons: List[str]) -> None:
        self.next_lessons = lessons

    def _provide_notification(self, idx: int) -> None:
        assert self.next_lessons is not None
        assert self.current_lesson_name is not None
        assert self.status is not None
        assert self.status != 2
        if self.status == 1:
            tip_toast.push_notification(1, self.current_lesson_name)
        elif self.status == 0:
            tip_toast.push_notification(0, self.next_lessons[0])
        elif self.status == 3:
            tip_toast.push_notification(2, '')


schedule_manager = ScheduleManager()
schedule_thread = ScheduleThread(schedule_manager)
notification_manager = NotificationManager(schedule_thread)

if __name__ == '__main__':
    thread_test = ScheduleThread(schedule_manager)

    def print_status(status: int, duration: float, total_time: float, lesson_name: str):
        print(
            f"status: {status}, duration: {duration}, total_time: {total_time}, lesson_name: {lesson_name}"
        )

    def print_next_lessons(lessons: list):
        print(f"next_lessons: {lessons}")

    thread_test.status_updated.connect(print_status)
    thread_test.next_lessons_updated.connect(print_next_lessons)
    thread_test.start()
    app = QCoreApplication([])
    app.exec_()
    thread_test.stop()
