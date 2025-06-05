import ctypes
import datetime as dt
import json
import os
import platform
import re
import subprocess
import sys
import psutil
import signal
import traceback
from shutil import copy
from typing import Optional, List, Dict, Any, Type, Union
from types import TracebackType # For traceback type hinting

from PyQt5 import uic
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QEasingCurve, QSize, QPoint, QUrl, QObject, QParallelAnimationGroup, QEvent
from PyQt5.QtGui import QColor, QIcon, QPixmap, QPainter, QDesktopServices, QMouseEvent, QCloseEvent, QFocusEvent
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QProgressBar, QGraphicsBlurEffect, QPushButton, \
    QGraphicsDropShadowEffect, QSystemTrayIcon, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QListWidgetItem, QDesktopWidget
from loguru import logger
from packaging.version import Version # type: ignore
from qfluentwidgets import Theme, setTheme, setThemeColor, SystemTrayMenu, Action, FluentIcon as fIcon, isDarkTheme, \
    Dialog, ProgressRing, PlainTextEdit, ImageLabel, PushButton, InfoBarIcon, Flyout, FlyoutAnimationType, CheckBox, \
    PrimaryPushButton, IconWidget # type: ignore

import conf
import list_ # Assuming list_ contains various lists and dicts
import tip_toast # Assuming tip_toast is a module
from tip_toast import active_windows # Assuming active_windows is a variable/object in tip_toast
import utils # Assuming utils is a module
import weather_db as db # Assuming weather_db is a module
from conf import base_directory # base_directory is likely a Path object
from extra_menu import ExtraMenu, open_settings # Assuming ExtraMenu and open_settings are defined
from generate_speech import generate_speech_sync, list_pyttsx3_voices # Assuming these functions are defined
from menu import open_plaza # Assuming open_plaza is defined
from network_thread import check_update, weatherReportThread # Assuming these are defined
from play_audio import play_audio # Assuming play_audio is defined
from plugin import p_loader # Assuming p_loader is an object/module
from utils import restart, stop, share, update_timer, DarkModeWatcher # Assuming these are defined
from file import config_center, schedule_center # Assuming these are objects

if os.name == 'nt':
    import pygetwindow # type: ignore

# Forward declare classes that are used as type hints before their definition
# Forward declarations for classes defined later in the file
class ErrorDialog(Dialog): pass # type: ignore[misc]
class PluginManager(QObject): pass
class PluginMethod(QObject): pass
class WidgetsManager(QObject): pass
class openProgressDialog(QWidget): pass
class FloatingWidget(QWidget): pass
class DesktopWidget(QWidget): pass


# 适配高DPI缩放
if platform.system() == 'Windows' and platform.release() not in ['7', 'XP', 'Vista']:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough) # type: ignore
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling) # type: ignore
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps) # type: ignore
else:
    logger.warning('不兼容的系统,跳过高DPI标识')

today: dt.date = dt.date.today()

# 存储窗口对象
windows: List[QWidget] = []
order: List[Any] = []
error_dialog: Optional[ErrorDialog] = None

current_lesson_name: str = '课程表未加载'
current_state: int = 0  # 0：课间 1：上课 2: 休息段
current_time: str = dt.datetime.now().strftime('%H:%M:%S')
current_week: int = dt.datetime.now().weekday()
current_lessons: Dict[str, str] = {}
loaded_data: Dict[str, Any] = {}
parts_type: List[str] = []
notification: Any = tip_toast
excluded_lessons: List[str] = []
last_notify_time: Optional[dt.datetime] = None
notify_cooldown: int = 2

timeline_data: Dict[str, Any] = {}
next_lessons: List[str] = []
parts_start_time: List[dt.datetime] = []

temperature: str = '未设置'
weather_icon_code: int = 0
weather_name: str = ''
weather_data_temp: Optional[Dict[str, Any]] = None
city_code: int = 101010100
theme: Optional[str] = None

time_offset: int = 0
first_start: bool = True
error_cooldown_td: dt.timedelta = dt.timedelta(seconds=2)
ignore_errors_list: List[str] = []
last_error_time_dt: dt.datetime = dt.datetime.now() - error_cooldown_td

ex_menu: Optional[ExtraMenu] = None
dark_mode_watcher: Optional[DarkModeWatcher] = None
was_floating_mode: bool = False

mgr: Optional['WidgetsManager'] = None
fw: Optional['FloatingWidget'] = None
app: Optional[QApplication] = None
p_mgr: Optional[PluginManager] = None

if config_center.read_conf('Other', 'do_not_log') != '1': # type: ignore[no-untyped-call]
    logger.add(f"{base_directory}/log/ClassWidgets_main_{{time}}.log", rotation="1 MB", encoding="utf-8",
               retention="1 minute") # type: ignore[attr-defined]
    logger.info('未禁用日志输出')
else:
    logger.info('已禁用日志输出功能，若需保存日志，请在“设置”->“高级选项”中关闭禁用日志功能')


def global_exceptHook(exc_type: Type[BaseException], exc_value: BaseException, exc_tb: Optional[TracebackType]) -> None:  # 全局异常捕获
    if config_center.read_conf('Other', 'safe_mode') == '1':  # 安全模式 # type: ignore[no-untyped-call]
        return

    error_details: str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))  # 异常详情
    if error_details in ignore_errors_list:  # 忽略重复错误 # Use renamed variable
        return

    global last_error_time_dt, error_dialog, error_cooldown_td # Use renamed variables

    current_event_time = dt.datetime.now() # Renamed to avoid conflict
    if current_event_time - last_error_time_dt > error_cooldown_td:  # 冷却时间
        last_error_time_dt = current_event_time
        logger.error(f"全局异常捕获：{exc_type} {exc_value} {exc_tb}") # Use f-string for consistency
        logger.error(f"详细堆栈信息：\n{error_details}")
        if not error_dialog: # Check if an error dialog is already active
            # Assuming ErrorDialog is a QDialog or similar
            error_dialog_instance = ErrorDialog(error_details) # Create instance
            error_dialog_instance.exec() # Show modally
            # error_dialog = None # Reset after dialog is closed, handled in ErrorDialog.closeEvent potentially
    else:
        # 忽略冷却时间
        pass


sys.excepthook = global_exceptHook  # 设置全局异常捕获

def handle_dark_mode_change(is_dark: bool) -> None: # Added type hint for is_dark
    """处理DarkModeWatcher触发的UI更新"""
    if config_center.read_conf('General', 'color_mode') == '2': # type: ignore[no-untyped-call]
        logger.info(f"系统颜色模式更新: {'深色' if is_dark else '浅色'}")
        current_theme_style = Theme.DARK if is_dark else Theme.LIGHT # Use Theme enum
        setTheme(current_theme_style) # type: ignore[no-untyped-call]
        if mgr:  # Check if mgr (WidgetsManager instance) is initialized
            mgr.clear_widgets()
        else:
            logger.warning("主题更改时,mgr还未初始化")
        # Theme color logic based on state might need re-evaluation or careful handling here
        # current_color = config_center.read_conf('Color', 'attend_class' if current_state == 1 else 'finish_class') # type: ignore[no-untyped-call]
        # setThemeColor(f"#{current_color}") # type: ignore[no-untyped-call]


def setTheme_() -> None:  # 设置主题 # Added return type hint
    global theme # theme is Optional[str]
    color_mode_setting: Any = config_center.read_conf('General', 'color_mode') # type: ignore[no-untyped-call]

    if color_mode_setting == '2':  # 自动
        logger.info(f'颜色模式: 自动({color_mode_setting})')
        current_system: str = platform.system()
        if current_system == 'Darwin' and Version(platform.mac_ver()[0]) < Version('10.14'):
            logger.info("macOS版本低于10.14，不支持自动切换颜色模式，使用浅色主题。")
            setTheme(Theme.LIGHT) # type: ignore[no-untyped-call]
            return
        if current_system == 'Windows':
            win_version = sys.getwindowsversion()
            if win_version.major == 6 and win_version.minor == 1: # Windows 7
                logger.info("Windows 7不支持自动切换颜色模式，使用浅色主题。")
                setTheme(Theme.LIGHT) # type: ignore[no-untyped-call]
                return
            try:
                if win_version.build < 14393:  # Older Windows 10 builds
                    logger.info(f"Windows build {win_version.build} 不支持自动颜色模式切换，使用浅色主题。")
                    setTheme(Theme.LIGHT) # type: ignore[no-untyped-call]
                    return
            except AttributeError: # Should not happen with sys.getwindowsversion()
                logger.warning("无法获取Windows版本build号，颜色模式可能不准确。")
                # Fallback or conservative approach could be setTheme(Theme.LIGHT)

        if current_system == 'Linux': # Linux dark mode detection is complex, often DE-specific
            logger.info("Linux平台，自动颜色模式切换依赖桌面环境，可能不准确。")
            # Defaulting to light if detection is not robust or not implemented for Linux DE.
            # For a more robust solution, DE-specific settings would need to be read (e.g., via gsettings for GNOME).
            # For now, assume DarkModeWatcher handles it if possible, otherwise default.
            # setTheme(Theme.LIGHT) # Fallback if no watcher or watcher fails
            # return

        if dark_mode_watcher: # dark_mode_watcher is Optional[DarkModeWatcher]
            is_dark_system: Optional[bool] = dark_mode_watcher.isDark()
            if is_dark_system is not None:
                logger.info(f"当前系统颜色模式: {'深色' if is_dark_system else '浅色'}")
                setTheme(Theme.DARK if is_dark_system else Theme.LIGHT) # type: ignore[no-untyped-call]
            else: # isDark() returned None, indicating an issue with detection
                logger.warning("无法获取系统颜色模式，暂时使用浅色主题。")
                setTheme(Theme.LIGHT) # type: ignore[no-untyped-call]
        else: # dark_mode_watcher itself is None
            logger.warning("DarkModeWatcher 未被初始化，使用浅色主题。")
            setTheme(Theme.LIGHT) # type: ignore[no-untyped-call]
    elif color_mode_setting == '1': # Explicitly Dark
        logger.info(f'颜色模式: 深色({color_mode_setting})')
        setTheme(Theme.DARK) # type: ignore[no-untyped-call]
    else: # Default to Light (covers '0' or any other unexpected value)
        logger.info(f'颜色模式: 浅色({color_mode_setting or "0 - 默认"})')
        setTheme(Theme.LIGHT) # type: ignore[no-untyped-call]
    # theme global variable seems unused after this function. Consider if it's needed.


def get_timeline_data() -> Dict[str, Any]: # Added return type
    if len(loaded_data['timeline']) == 1:
        return loaded_data['timeline']['default']
    else:
        if str(current_week) in loaded_data['timeline'] and loaded_data['timeline'][str(current_week)]:  # 如果此周有时间线
            return loaded_data['timeline'][str(current_week)]
        else:
            return loaded_data['timeline']['default']


# 获取Part开始时间
def get_start_time() -> None: # Added return type
    global parts_start_time, timeline_data, loaded_data, order, parts_type
    # loaded_data is Dict[str, Any], schedule_center.schedule_data is likely Dict[str, Any]
    loaded_data = schedule_center.schedule_data # type: ignore[no-untyped-call]
    timeline: Dict[str, Any] = get_timeline_data()
    part: Dict[str, List[Union[int, str]]] = loaded_data['part']
    parts_start_time = [] # List[dt.datetime]
    timeline_data = {} # Dict[str, Any]
    order = [] # List[str]
    # parts_type is List[str]

    for item_name, item_value in part.items(): # item_name: str, item_value: List[Union[int, str]]
        try:
            h, m = item_value[:2]
            try:
                part_type = item_value[2]
            except IndexError:
                part_type = 'part'
            except Exception as e:
                logger.error(f'加载课程表文件[节点类型]出错：{e}')
                part_type = 'part'

            # 应用时差偏移到课程表时间
            start_time = dt.datetime.combine(today, dt.time(h, m)) + dt.timedelta(seconds=time_offset)
            parts_start_time.append(start_time)
            order.append(item_name)
            parts_type.append(part_type)
        except Exception as e:
            logger.error(f'加载课程表文件[起始时间]出错：{e}')

    paired = zip(parts_start_time, order)
    paired_sorted = sorted(paired, key=lambda x: x[0])  # 按时间大小排序
    if paired_sorted:
        # parts_start_time and order are redefined here as tuples of their respective types
        new_parts_start_time, new_order = zip(*paired_sorted)
        parts_start_time = list(new_parts_start_time) # type: ignore[assignment]
        order = list(new_order) # type: ignore[assignment]

    def sort_timeline_key(item: tuple[str, Any]) -> Union[tuple[int, int, int], str]: # Added item type and return type
        item_name: str = item[0]
        prefix: str = item_name[0]
        if len(item_name) > 1:
            try:
                # 提取节点序数
                part_num = int(item_name[1])
                # 提取课程序数
                class_num = 0
                if len(item_name) > 2:
                    class_num = int(item_name[2:])
                if prefix == 'a':
                    return part_num, class_num, 0
                else:
                    return part_num, class_num, 1
            except ValueError:
                # 如果转换失败，返回原始字符串
                return item_name
        return item_name

    # 对timeline排序后添加到timeline_data
    sorted_timeline: List[tuple[str, Any]] = sorted(timeline.items(), key=sort_timeline_key)
    for item_name, item_time in sorted_timeline: # item_name: str, item_time: Any
        try:
            timeline_data[item_name] = item_time
        except Exception as e:
            logger.error(f'加载课程表文件[课程数据]出错：{e}')


def get_part() -> Optional[tuple[dt.datetime, int, str]]: # Added return type, str for part_type
    if not parts_start_time: # parts_start_time is List[dt.datetime]
        return None

    # Inner function type hint
    def return_data() -> tuple[dt.datetime, int]: # Added return type
        c_time: dt.datetime = parts_start_time[i]
        return c_time, int(order[i])  # order is List[str]

    current_dt: dt.datetime = dt.datetime.now() # 当前时间
    i: int # Declare i for loop
    for i in range(len(parts_start_time)):  # 遍历每个Part
        time_len: dt.timedelta = dt.timedelta(minutes=0)  # Part长度

        item_name: str
        item_time: Any
        for item_name, item_time in timeline_data.items(): # timeline_data is Dict[str, Any]
            if item_name.startswith(f'a{str(order[i])}') or item_name.startswith(f'f{str(order[i])}'):
                time_len += dt.timedelta(minutes=int(item_time))  # 累计Part的时间点总长度
            time_len += dt.timedelta(seconds=1)

        if time_len != dt.timedelta(seconds=1):  # 有课程
            if i == len(parts_start_time) - 1:  # 最后一个Part
                # return_data returns tuple[dt.datetime, int], we need to add part_type
                dt_val, order_val = return_data()
                return dt_val, order_val, parts_type[i] if i < len(parts_type) else 'part'

            else:
                if current_dt <= parts_start_time[i] + time_len:
                    dt_val, order_val = return_data()
                    return dt_val, order_val, parts_type[i] if i < len(parts_type) else 'part'

    # Fallback if no part is found through the loop (e.g. if parts_start_time is not empty but loop doesn't return)
    # This was returning a 3-tuple before, ensure consistency
    if parts_start_time: # Check again to be safe
        return parts_start_time[0] + dt.timedelta(seconds=time_offset), 0, 'part' # Default part_type
    return None


def get_excluded_lessons() -> None: # Added return type
    global excluded_lessons # excluded_lessons is List[str]
    if config_center.read_conf('General', 'excluded_lesson') == "0": # type: ignore[no-untyped-call]
        excluded_lessons = []
        return
    excluded_lessons_raw: Optional[str] = config_center.read_conf('General', 'excluded_lessons') # type: ignore[no-untyped-call]
    excluded_lessons = excluded_lessons_raw.split(',') if excluded_lessons_raw else []


# 获取当前活动
def get_current_lessons() -> None:  # 获取当前课程 # Added return type
    global current_lessons # current_lessons is Dict[str, str]
    timeline: Dict[str, Any] = get_timeline_data()
    schedule: Optional[Dict[str, List[str]]] = None

    if config_center.read_conf('General', 'enable_alt_schedule') == '1' or conf.is_temp_week(): # type: ignore[no-untyped-call]
        try:
            if conf.get_week_type(): # type: ignore[no-untyped-call]
                schedule = loaded_data.get('schedule_even')
            else:
                schedule = loaded_data.get('schedule')
        except Exception as e:
            logger.error(f'加载课程表文件[单双周]出错：{e}')
            schedule = loaded_data.get('schedule')
    else:
        schedule = loaded_data.get('schedule')

    if not schedule: # Ensure schedule is not None
        logger.warning("课程表数据未加载(schedule is None) in get_current_lessons")
        return

    class_count: int = 0
    item_name: str
    for item_name, _ in timeline.items():
        if item_name.startswith('a'):
            # Ensure schedule and schedule[str(current_week)] are valid
            if str(current_week) in schedule and schedule[str(current_week)]:
                try:
                try:
                    # Ensure schedule[str(current_week)] is a list and class_count is within bounds
                    current_week_schedule: List[str] = schedule[str(current_week)]
                    if class_count < len(current_week_schedule) and current_week_schedule[class_count] != '未添加':
                        current_lessons[item_name] = current_week_schedule[class_count]
                    else:
                        current_lessons[item_name] = '暂无课程'
                except IndexError:
                    current_lessons[item_name] = '暂无课程'
                except Exception as e: # Catch any other unexpected errors
                    current_lessons[item_name] = '暂无课程'
                    logger.debug(f'加载课程表文件出错：{e}')
                class_count += 1
            else: # schedule[str(current_week)] is empty or current_week not in schedule
                current_lessons[item_name] = '暂无课程'
                class_count += 1


# 获取倒计时、弹窗提示
def get_countdown(toast: bool = False) -> Optional[List[Union[str, int]]]:  # 重构好累aaaa. Added param and return types
    global last_notify_time # Optional[dt.datetime]
    current_dt_now: dt.datetime = dt.datetime.now()
    if last_notify_time and (current_dt_now - last_notify_time).seconds < notify_cooldown:
        return None # Explicitly return None if on cooldown

    part_info: Optional[tuple[dt.datetime, int, str]] = get_part()
    if not part_info: # If get_part returns None
        logger.warning("get_part() returned None in get_countdown()")
        return ['目前课程已结束', '00:00', 100] # Default/fallback

    # current_part_start_time: dt.datetime = part_info[0] # Unused variable
    part: int = part_info[1] # part index
    # current_part_type: str = part_info[2] # Unused variable

    def after_school() -> None:  # 放学
        # Ensure part is a valid index for parts_type
        if 0 <= part < len(parts_type) and parts_type[part] == 'break':  # 休息段
            notification.push_notification(0, current_lesson_name)  # 下课
        else:
            if config_center.read_conf('Toast', 'after_school') == '1': # type: ignore[no-untyped-call]
                notification.push_notification(2)  # 放学

    current_dt_schedule_time: dt.datetime = dt.datetime.combine(today, dt.datetime.strptime(current_time, '%H:%M:%S').time())  # 当前时间 (from global current_time string)
    return_text: List[Union[str, int]] = []
    got_return_data: bool = False

    if parts_start_time: # parts_start_time is List[dt.datetime]
        # get_part() already called, use its results
        c_time: dt.datetime = part_info[0] # Start time of the current/next part
        # part index is already in `part`

        if current_dt_schedule_time >= c_time: # We are within or past the start of a part
            item_name: str
            item_time_str: Any # Can be string representation of int
            for item_name, item_time_str in timeline_data.items(): # timeline_data is Dict[str, Any]
                if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                    try:
                        item_time_int: int = int(item_time_str)
                    except ValueError:
                        logger.error(f"Invalid time value in timeline_data for {item_name}: {item_time_str}")
                        continue # Skip this timeline item

                    # 判断时间是否上下课，发送通知
                    if current_dt_schedule_time == c_time and toast:
                        if item_name.startswith('a'):
                            notification.push_notification(1, current_lesson_name)  # 上课
                            last_notify_time = current_dt_now
                        else:
                            if next_lessons:  # 下课/放学. next_lessons is List[str]
                                notification.push_notification(0, next_lessons[0])  # 下课
                                last_notify_time = current_dt_now
                            else:
                                after_school()

                    prepare_minutes_conf: str = config_center.read_conf('Toast', 'prepare_minutes') # type: ignore[no-untyped-call]
                    if prepare_minutes_conf != '0':
                        prepare_minutes_int: int = int(prepare_minutes_conf)
                        if current_dt_schedule_time == c_time - dt.timedelta(minutes=prepare_minutes_int):
                            if toast and item_name.startswith('a'):
                                if not current_state:  # 课间. current_state is int
                                    if next_lessons: # Ensure next_lessons is not empty
                                        notification.push_notification(3, next_lessons[0])  # 准备上课（预备铃）
                                        last_notify_time = current_dt_now

                    # 放学
                    if (c_time + dt.timedelta(minutes=item_time_int) == current_dt_schedule_time and
                            not next_lessons and not current_state and toast):
                        after_school()
                        last_notify_time = current_dt_now

                    add_time: int = item_time_int
                    c_time += dt.timedelta(minutes=add_time)

                    if got_return_data:
                        break

                    if c_time >= current_dt_schedule_time:
                        # 根据所在时间段使用不同标语
                        if item_name.startswith('a'):
                            return_text.append('当前活动结束还有')
                        else:
                            return_text.append('课间时长还有')
                        # 返回倒计时、进度条
                        time_diff: dt.timedelta = c_time - current_dt_schedule_time
                        minute: int
                        sec: int
                        minute, sec = divmod(time_diff.seconds, 60)
                        return_text.append(f'{minute:02d}:{sec:02d}')
                        # 进度条
                        seconds: int = time_diff.seconds
                        return_text.append(int(100 - seconds / (item_time_int * 60) * 100))
                        got_return_data = True
            if not return_text:
                return_text = ['目前课程已结束', '00:00', 100]
        else: # We are before the start of the next part (c_time)
            prepare_minutes_str: str = config_center.read_conf('Toast', 'prepare_minutes') # type: ignore[no-untyped-call]
            if prepare_minutes_str != '0' and toast:
                prepare_minutes: int = int(prepare_minutes_str)
                if current_dt_schedule_time == c_time - dt.timedelta(minutes=prepare_minutes):
                    next_lesson_name_for_toast: Optional[str] = None
                    next_lesson_key: Optional[str] = None
                    # Ensure timeline_data is sorted if order matters for finding next_lesson_key
                    # Assuming timeline_data keys are like 'a10', 'a11', 'f10' etc.
                    sorted_timeline_keys: List[str] = sorted(timeline_data.keys())
                    for key_in_loop in sorted_timeline_keys:
                        if key_in_loop.startswith(f'a{str(part)}'): # part is the index from get_part()
                            next_lesson_key = key_in_loop
                            break
                    if next_lesson_key and next_lesson_key in current_lessons: # current_lessons is Dict[str, str]
                        lesson_name_from_current: str = current_lessons[next_lesson_key]
                        if lesson_name_from_current != '暂无课程':
                            next_lesson_name_for_toast = lesson_name_from_current

                    if current_state == 0: #课间
                        # now_for_cooldown: dt.datetime = dt.datetime.now() # Use current_dt_now from function start
                        if not last_notify_time or (current_dt_now - last_notify_time).seconds >= notify_cooldown:
                            if next_lesson_name_for_toast is not None:
                                notification.push_notification(3, next_lesson_name_for_toast)
                                last_notify_time = current_dt_now

            # Check if the first lesson of the current part exists
            first_lesson_key_of_part = f'a{part}1' # Assuming format like 'a01', 'a11'
            # More robust check: iterate timeline_data for keys starting with 'a{part}'
            first_actual_lesson_key = None
            for t_key in sorted(timeline_data.keys()): # Ensure sorted order
                if t_key.startswith(f'a{str(part)}'):
                    first_actual_lesson_key = t_key
                    break

            if first_actual_lesson_key: # If there is any lesson in this part
                time_diff_before_class: dt.timedelta = c_time - current_dt_schedule_time
                minute_bc, sec_bc = divmod(time_diff_before_class.seconds, 60)
                return_text = ['距离上课还有', f'{minute_bc:02d}:{sec_bc:02d}', 100]
            else: # No lessons in this part, or timeline_data is empty for this part
                return_text = ['目前课程已结束', '00:00', 100]
        return return_text
    return ['目前课程已结束', '00:00', 100] # Fallback if parts_start_time is empty


# 获取将发生的活动
def get_next_lessons() -> None: # Added return type
    global current_lesson_name # str
    global next_lessons # List[str]
    next_lessons = []

    part_info: Optional[tuple[dt.datetime, int, str]] = get_part()
    if not part_info:
        return

    c_time_nl: dt.datetime = part_info[0] # current/next part start time
    part_nl: int = part_info[1] # current/next part index

    current_dt_schedule_time_nl: dt.datetime = dt.datetime.combine(today, dt.datetime.strptime(current_time, '%H:%M:%S').time())

    if parts_start_time: # parts_start_time is List[dt.datetime]
        # c_time_nl, part_nl already derived from get_part()

        def before_class() -> bool: # Added return type
            # part_nl is the current part index. parts_start_time is List[dt.datetime]
            # Ensure part_nl is a valid index if used with parts_start_time
            if part_nl == 0 or part_nl == 3: # Assuming these are specific part indices
                return True
            else:
                # Ensure part_nl is a valid index for parts_start_time before accessing
                if 0 <= part_nl < len(parts_start_time):
                     if current_dt_schedule_time_nl >= parts_start_time[part_nl] - dt.timedelta(minutes=60):
                        return True
                return False

        if before_class():
            item_name_nl: str
            item_time_str_nl: Any
            for item_name_nl, item_time_str_nl in timeline_data.items(): # timeline_data is Dict[str, Any]
                if item_name_nl.startswith(f'a{str(part_nl)}') or item_name_nl.startswith(f'f{str(part_nl)}'):
                    try:
                        add_time_nl: int = int(item_time_str_nl)
                    except ValueError:
                        logger.error(f"Invalid time value in timeline_data for {item_name_nl}: {item_time_str_nl}")
                        continue

                    if c_time_nl > current_dt_schedule_time_nl and item_name_nl.startswith('a'):
                        # Ensure current_lessons[item_name_nl] exists
                        if item_name_nl in current_lessons: # current_lessons is Dict[str, str]
                            next_lessons.append(current_lessons[item_name_nl])
                        else:
                            logger.warning(f"Lesson key {item_name_nl} not found in current_lessons during get_next_lessons")
                            next_lessons.append("课程信息缺失") # Placeholder
                    c_time_nl += dt.timedelta(minutes=add_time_nl)


def get_next_lessons_text() -> str: # Added return type
    if not next_lessons: # next_lessons is List[str]
        cache_text: str = '当前暂无课程'
    else:
        cache_text = ''
        # Determine loop range, ensuring it doesn't exceed length of next_lessons
        range_time: int = min(5, len(next_lessons))

        for i in range(range_time):
            lesson: str = next_lessons[i]
            if range_time > 2:
                if lesson != '暂无课程':
                    cache_text += f'{list_.get_subject_abbreviation(lesson)}  '  # type: ignore[no-untyped-call]
                else:
                    cache_text += '无  '
            else:
                if lesson != '暂无课程':
                    cache_text += f'{lesson}  '
                else:
                    cache_text += '暂无  '
    return cache_text.strip() # Remove trailing spaces


# 获取当前活动
def get_current_lesson_name() -> None: # Added return type
    global current_lesson_name, current_state # current_lesson_name: str, current_state: int
    current_dt_schedule_time_cln: dt.datetime = dt.datetime.combine(today, dt.datetime.strptime(current_time, '%H:%M:%S').time())
    current_lesson_name = '暂无课程'
    current_state = 0 # Default to 课间

    part_info_cln: Optional[tuple[dt.datetime, int, str]] = get_part()
    if not part_info_cln:
        return

    c_time_cln: dt.datetime = part_info_cln[0]
    part_cln: int = part_info_cln[1]
    # part_type_cln: str = part_info_cln[2] # This is the type of the *part itself*, not individual timeline items

    if parts_start_time: # parts_start_time is List[dt.datetime]
        # c_time_cln, part_cln derived from get_part()

        if current_dt_schedule_time_cln >= c_time_cln: # We are within or past the start of a part
             # Check part_type for the overall part first (e.g. large break between morning/afternoon)
            if 0 <= part_cln < len(parts_type) and parts_type[part_cln] == 'break':  #休息段
                # Ensure loaded_data['part_name'] and str(part_cln) key exist
                if 'part_name' in loaded_data and str(part_cln) in loaded_data['part_name']:
                    current_lesson_name = loaded_data['part_name'][str(part_cln)]
                else:
                    current_lesson_name = "休息中" # Fallback name for break
                current_state = 2 # 休息段
                # For a 'break' part, we might not need to iterate timeline_data items
                # Or, if breaks can have sub-items, the logic below is fine.
                # For now, if it's a break part, we set state and potentially return.
                # If timeline iteration is still desired for breaks, remove/adjust this return.
                # return # If break part means no specific "lesson" name from timeline

            item_name_cln: str
            item_time_str_cln: Any
            for item_name_cln, item_time_str_cln in timeline_data.items(): # timeline_data is Dict[str, Any]
                # Only consider items belonging to the current part_cln
                if item_name_cln.startswith(f'a{str(part_cln)}') or item_name_cln.startswith(f'f{str(part_cln)}'):
                    try:
                        add_time_cln: int = int(item_time_str_cln)
                    except ValueError:
                        logger.error(f"Invalid time value in timeline_data for {item_name_cln}: {item_time_str_cln}")
                        continue

                    # Important: c_time_cln here should be the start of the *current specific timeline item*,
                    # not the start of the whole part, if we are iterating through items.
                    # Let's assume c_time_cln is correctly tracking the end of the previous item / start of current.
                    # The initial c_time_cln from get_part() is the start of the whole part.
                    # We need to adjust it as we iterate.
                    # This requires careful state management of c_time_cln *within* the loop.
                    # A better way: the loop should determine WHICH item we are in.
                    # The original logic might be: current_dt_schedule_time_cln is compared against cumulative end times.

                    # Re-evaluating logic based on original:
                    # c_time_cln is the start of the *part*. We add durations to it.
                    # This means the *first* item_time added to c_time_cln gives the end of that first item.

                    potential_item_end_time = c_time_cln + dt.timedelta(minutes=add_time_cln)

                    if potential_item_end_time > current_dt_schedule_time_cln: # We are in this item
                        if item_name_cln.startswith('a'): # Activity/Lesson
                            # Ensure current_lessons has this key
                            if item_name_cln in current_lessons:
                                current_lesson_name = current_lessons[item_name_cln]
                            else:
                                logger.warning(f"Lesson key {item_name_cln} not found in current_lessons for get_current_lesson_name")
                                current_lesson_name = "未知课程" # Fallback
                            current_state = 1 # 上课
                        else: # Break between lessons (f-item)
                            current_lesson_name = '课间'
                            current_state = 0 # 课间
                        return # Found current state, exit function

                    c_time_cln = potential_item_end_time # Move c_time_cln to the end of the current item for the next iteration

            # If loop finishes and we are past the start of the part, but not within any specific item found
            # (e.g. after all timeline items for that part but before next part starts according to get_part())
            # This implies we are in a residual period after the last defined activity/break of the current part.
            # Default to '课间' or a specific "end of part" state if needed.
            # The original code implicitly handles this by current_lesson_name and current_state retaining their values
            # if the loop doesn't find a match and returns.
            # If the loop completes, it means current_dt_schedule_time_cln >= last item's end time for this part.
            # So, technically, this part is over. get_part() should give the *next* part then.
            # This state might indicate "after school" or similar if it's the last part.
            # For now, if the loop completes without returning, it means we are after all defined activities in the current part.
            # Let's set to '课间' as a general between-activities state.
            # However, if parts_type[part_cln] was 'break', it's already handled.
            if not (0 <= part_cln < len(parts_type) and parts_type[part_cln] == 'break'):
                 current_lesson_name = '课间 (Part End)' # Or some other appropriate status
                 current_state = 0


def get_hide_status() -> int: # Added return type (0 or 1)
    # 1 -> hide, 0 -> show
    # 满分啦（
    # 祝所有用 Class Widgets 的、不用 Class Widgets 的学子体测满分啊（（
    global current_state, current_lesson_name, excluded_lessons # current_state: int, current_lesson_name: str, excluded_lessons: List[str]

    hide_condition_met: bool = False
    hide_setting: str = config_center.read_conf('General', 'hide') # type: ignore[no-untyped-call]

    if hide_setting == '0': # Never hide based on state
        hide_condition_met = False
    elif hide_setting == '1': # Hide during class
        hide_condition_met = (current_state == 1) # 1 means 上课
    elif hide_setting == '2': # Hide on maximize/fullscreen
        hide_condition_met = check_windows_maximize() or check_fullscreen()
    elif hide_setting == '3': # Flexible hide (same as '1' for this condition part)
        hide_condition_met = (current_state == 1)
    else: # Default case, treat as '0'
        hide_condition_met = False

    #课程表排除
    lesson_is_excluded: bool = current_lesson_name in excluded_lessons

    if hide_condition_met and not lesson_is_excluded:
        return 1 # Hide
    else:
        return 0 # Show


# 定义 RECT 结构体
class RECT(ctypes.Structure):
    _fields_: List[tuple[str, Any]] = [("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long)]

def get_process_name(pid: Union[int, ctypes.c_void_p]) -> str: # 获取进程名称. Added pid type and return type
    try:
        # If pid is HWND (integer), get process ID first
        actual_pid: Optional[int] = None
        if isinstance(pid, int): # Assuming HWND is passed as int
            # Ensure user32 and GetWindowThreadProcessId are available
            if hasattr(ctypes, 'windll') and hasattr(ctypes.windll, 'user32') and hasattr(ctypes.windll.user32, 'GetWindowThreadProcessId'):
                process_id_val = ctypes.c_ulong() # To store the process ID
                ctypes.windll.user32.GetWindowThreadProcessId(pid, ctypes.byref(process_id_val))
                actual_pid = process_id_val.value
            else: # Fallback or error if platform components not available
                return "unknown_os_feature_missing"
        elif isinstance(pid, ctypes.c_void_p): # If already a process ID (e.g. from c_ulong.value)
             actual_pid = pid # type: ignore # It should be int here.
        elif isinstance(pid, ctypes.c_ulong): # If it's a c_ulong object itself
            actual_pid = pid.value
        else: # Should not happen if called correctly from check_fullscreen
            return "unknown_pid_type"

        if actual_pid is None or actual_pid == 0: # Check for valid PID
            return "unknown_invalid_pid"

        return psutil.Process(actual_pid).name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, ValueError, OSError): # Added AccessDenied and OSError
        return "unknown_process_error"


def check_fullscreen() -> bool:  # 检查是否全屏. Added return type
    if os.name != 'nt':
        return False
    user32 = ctypes.windll.user32
    hwnd: Optional[int] = user32.GetForegroundWindow() # HWND is typically an int or pointer
    if not hwnd:
        return False

    # Check against desktop and shell windows
    desktop_hwnd: Optional[int] = user32.GetDesktopWindow()
    shell_hwnd: Optional[int] = user32.GetShellWindow()
    if hwnd == desktop_hwnd or hwnd == shell_hwnd:
        return False

    # Get process ID for the foreground window
    win_pid_val = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid_val))

    if win_pid_val.value == 0: # No valid process ID
        return False

    process_name: str = get_process_name(win_pid_val.value) # Pass the integer value
    current_pid: int = os.getpid()

    # logger.debug(f"前景窗口句柄: {hwnd}, PID: {win_pid_val.value}, 进程名: {process_name}")
    if win_pid_val.value == current_pid:
        return False
    # 排除特定系统进程
    excluded_system_processes = {
        'explorer.exe',             # 文件资源管理器/桌面
        'shellexperiencehost.exe',  # Shell体验主机 (开始菜单、操作中心)
        'searchui.exe',             # Cortana/搜索界面
        'applicationframehost.exe', # UWP应用框架
        'systemsettings.exe',       # 设置
        'taskmgr.exe'               # 任务管理器
    }
    if process_name in excluded_system_processes:
        # logger.debug(f"前景窗口进程 '{process_name}' 在排除列表 (系统进程), 排除.")
        return False
    title_buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buffer, 256)
    window_title_lower = title_buffer.value.strip().lower()
    # logger.debug(f"前景窗口标题: '{title_buffer.value}' (小写: '{window_title_lower}')")
    # 排除特定窗口标题
    excluded_system_window_titles = {
        "program manager",            # 桌面窗口
        "windows input experience",   # 输入法相关
        "msctfmonitor window",        # 输入法相关
        "startmenuexperiencehost"   # 开始菜单
    }
    if window_title_lower in excluded_system_window_titles:
        # logger.debug(f"前景窗口标题 '{window_title_lower}' 在排除列表 (系统窗口), 排除.")
        return False
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    # 使用桌面窗口作为屏幕尺寸参考
    screen_rect_desktop = RECT()
    user32.GetWindowRect(user32.GetDesktopWindow(), ctypes.byref(screen_rect_desktop))
    # logger.debug(f"窗口矩形: 左={rect.left}, 上={rect.top}, 右={rect.right}, 下={rect.bottom}")
    # logger.debug(f"桌面矩形: 左={screen_rect_desktop.left}, 上={screen_rect_desktop.top}, 右={screen_rect_desktop.right}, 下={screen_rect_desktop.bottom}")
    is_covering_screen = (
        rect.left <= screen_rect_desktop.left and
        rect.top <= screen_rect_desktop.top and
        rect.right >= screen_rect_desktop.right and
        rect.bottom >= screen_rect_desktop.bottom
    )
    if is_covering_screen:
        screen_area = (screen_rect_desktop.right - screen_rect_desktop.left) * (screen_rect_desktop.bottom - screen_rect_desktop.top)
        window_area = (rect.right - rect.left) * (rect.bottom - rect.top)
        is_fullscreen = window_area >= screen_area * 0.95
        # logger.debug(f"覆盖屏幕: {is_covering_screen}, 窗口面积: {window_area}, 屏幕面积: {screen_area}, 是否全屏判断: {is_fullscreen}")
        return is_fullscreen
    return False


class ErrorDialog(Dialog):  # 重大错误提示框
    def __init__(self, error_details: str = 'Traceback (most recent call last):', parent: Optional[QWidget] = None) -> None: # Added type hints
        # KeyboardInterrupt 直接 exit
        if error_details.endswith('KeyboardInterrupt') or error_details.endswith('KeyboardInterrupt\n'):
            stop() # type: ignore[no-untyped-call] # Assuming stop is available globally

        super().__init__(
            'Class Widgets 崩溃报告',
            '抱歉！Class Widgets 发生了严重的错误从而无法正常运行。您可以保存下方的错误信息并向他人求助。'
            '若您认为这是程序的Bug，请点击“报告此问题”或联系开发者。',
            parent
        )
        global error_dialog # Optional[ErrorDialog]
        # error_dialog = self # Assign the instance itself. Original was True. Let's keep it simple.
        # Reverting to original behavior for error_dialog as its type is Optional[ErrorDialog]
        # and it seems to be used as a flag elsewhere or to hold the instance.
        # For now, let's assume error_dialog is a flag that an error dialog is active.
        # The original code had `error_dialog = True`. If `error_dialog` is meant to hold the instance,
        # then `error_dialog = self` would be correct. Given it's Optional[ErrorDialog], instance is better.
        # However, the global `error_dialog` is used as a flag to prevent multiple dialogs in `global_exceptHook`.
        # So, `error_dialog = self` seems more appropriate if it's to be reset on close.
        # Let's stick to the original implication that it's a truthy check for an *active* dialog.
        # The type hint `Optional[ErrorDialog]` suggests it *can* hold an instance.
        # For now, let's ensure the logic in global_exceptHook remains compatible.
        # `error_dialog = self` makes more sense with `Optional[ErrorDialog]`.
        error_dialog = self # This instance is now the active error_dialog

        self.is_dragging: bool = False
        self.drag_position: QPoint = QPoint()
        self.title_bar_height: int = 30

        self.title_layout: QHBoxLayout = QHBoxLayout()

        self.iconLabel: ImageLabel = ImageLabel()
        self.iconLabel.setImage(f"{base_directory}/img/logo/favicon-error.ico") # type: ignore[attr-defined] # base_directory Path
        self.error_log: PlainTextEdit = PlainTextEdit()
        self.report_problem: PushButton = PushButton(fIcon.FEEDBACK, '报告此问题')
        self.copy_log_btn: PushButton = PushButton(fIcon.COPY, '复制日志')
        self.ignore_error_btn: PushButton = PushButton(fIcon.INFO, '忽略错误')
        self.ignore_same_error: CheckBox = CheckBox()
        self.ignore_same_error.setText('在下次启动之前，忽略此错误')
        self.restart_btn: PrimaryPushButton = PrimaryPushButton(fIcon.SYNC, '重新启动')

        self.iconLabel.setScaledContents(True)
        self.iconLabel.setFixedSize(50, 50)
        self.titleLabel.setText('出错啦！ヽ(*。>Д<)o゜') # titleLabel is part of Dialog
        self.titleLabel.setStyleSheet("font-family: Microsoft YaHei UI; font-size: 25px; font-weight: 500;")
        self.error_log.setReadOnly(True)
        self.error_log.setPlainText(error_details)
        self.error_log.setFixedHeight(200)
        self.restart_btn.setFixedWidth(150)
        self.yesButton.hide() # yesButton is part of Dialog
        self.cancelButton.hide()  # cancelButton is part of Dialog
        self.title_layout.setSpacing(12)

        # 按钮事件
        self.report_problem.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(
                'https://github.com/Class-Widgets/Class-Widgets/issues/'
                'new?assignees=&labels=Bug&projects=&template=BugReport.yml&title=[Bug]:'))
        )
        self.copy_log_btn.clicked.connect(self.copy_log)
        self.ignore_error_btn.clicked.connect(self.ignore_error)
        self.restart_btn.clicked.connect(restart) # type: ignore[no-untyped-call] # Assuming restart is global

        self.title_layout.addWidget(self.iconLabel)  # 标题布局
        self.title_layout.addWidget(self.titleLabel) # titleLabel from Dialog
        self.textLayout.insertLayout(0, self.title_layout)  # textLayout from Dialog
        self.textLayout.addWidget(self.error_log)
        self.textLayout.addWidget(self.ignore_same_error)
        self.buttonLayout.insertStretch(0, 1)  # buttonLayout from Dialog
        self.buttonLayout.insertWidget(0, self.copy_log_btn)
        self.buttonLayout.insertWidget(1, self.report_problem)
        self.buttonLayout.insertStretch(1)
        self.buttonLayout.insertWidget(4, self.ignore_error_btn)
        self.buttonLayout.insertWidget(5, self.restart_btn)

    def copy_log(self) -> None:  # 复制日志 # Added return type
        if QApplication.clipboard(): # Check if clipboard is available
            QApplication.clipboard().setText(self.error_log.toPlainText())
        Flyout.create( # type: ignore[no-untyped-call]
            icon=InfoBarIcon.SUCCESS,
            title='复制成功！ヾ(^▽^*)))',
            content="日志已成功复制到剪贴板。",
            target=self.copy_log_btn, # type: ignore[arg-type] # target expects QWidget
            parent=self, # type: ignore[arg-type] # parent expects QWidget
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP
        )

    def ignore_error(self) -> None: # Added return type
        global ignore_errors_list # ignore_errors_list is List[str]
        if self.ignore_same_error.isChecked():
            ignore_errors_list.append(self.error_log.toPlainText())
        self.close()

    def mousePressEvent(self, event: QMouseEvent) -> None: # Added QMouseEvent type and return type
        if event.button() == Qt.LeftButton and event.y() <= self.title_bar_height: # type: ignore[attr-defined]
            self.is_dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None: # Added QMouseEvent type and return type
        if self.is_dragging:
            self.move(event.globalPos() - self.drag_position)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None: # Added QMouseEvent type and return type
        if event.button() == Qt.LeftButton: # type: ignore[attr-defined]
            self.is_dragging = False



class PluginManager(QObject):  # 插件管理器 # Inherit from QObject for signals/slots if needed later
    def __init__(self) -> None: # Added return type
        super().__init__() # Call QObject constructor if it's a QObject
        self.cw_contexts: Dict[str, Any] = {}
        self.get_app_contexts()
        self.temp_window: List[QWidget] = [] # Assuming it holds QWidget or similar
        # Ensure PluginMethod is defined or forward-declared if it's a class type hint
        self.method: 'PluginMethod' = PluginMethod(self.cw_contexts)

    def get_app_contexts(self, path: Optional[str] = None) -> Dict[str, Any]:
        # Assuming global variables like current_lesson_name, current_state, etc. are already typed
        # And list_, conf, config_center, schedule_center, base_directory, mgr, theme are also typed or handled
        # For weather_icon and city, they need to be properly initialized and typed at the global scope.
        # If they are Optional, the access here should reflect that.
        # For simplicity in this diff, I'm assuming they exist.
        # Proper handling would involve checking `if 'weather_icon' in globals()` and `if 'city' in globals()`
        # or ensuring they are initialized with a default typed value.

        _weather_icon_val: Any = None
        _city_val: Any = None
        if 'weather_icon' in globals(): # type: ignore
            _weather_icon_val = weather_icon # type: ignore
        if 'city' in globals(): # type: ignore
             _city_val = city # type: ignore

        self.cw_contexts = {
            "Widgets_Width": list_.widget_width, # type: ignore
            "Widgets_Name": list_.widget_name, # type: ignore
            "Widgets_Code": list_.widget_conf,  # type: ignore
            "Current_Lesson": current_lesson_name,
            "State": current_state,
            "Current_Part": get_part(),
            "Next_Lessons_text": get_next_lessons_text(),
            "Next_Lessons": next_lessons,
            "Current_Lessons": current_lessons,
            "Current_Week": current_week,
            "Excluded_Lessons": excluded_lessons,
            "Current_Time": current_time,
            "Timeline_Data": timeline_data,
            "Parts_Start_Time": parts_start_time,
            "Parts_Type": parts_type,
            "Time_Offset": time_offset,
            "Schedule_Name": config_center.schedule_name, # type: ignore
            "Loaded_Data": loaded_data,
            "Order": order,
            "Weather": weather_name,
            "Temp": temperature,
            "Weather_Data": weather_data_temp,
            "Weather_Icon": _weather_icon_val,
            "Weather_API": config_center.read_conf('Weather', 'api'), # type: ignore
            "City": _city_val,
            "Notification": notification.notification_contents, # type: ignore
            "Last_Notify_Time": last_notify_time,
            "PLUGIN_PATH": os.path.normpath(os.path.join(conf.PLUGINS_DIR, path)) if path else conf.PLUGINS_DIR, # type: ignore
            "Config_Center": config_center,
            "Schedule_Center": schedule_center,
            "Base_Directory": base_directory, # type: ignore
            "Widgets_Mgr": mgr,
            "Theme": theme,
        }
        return self.cw_contexts


class PluginMethod(QObject):
    def __init__(self, app_context: Dict[str, Any]) -> None:
        super().__init__()
        self.app_contexts: Dict[str, Any] = app_context

    def register_widget(self, widget_code: str, widget_name: str, widget_width: int) -> None:
        # Assuming self.app_contexts items are Dicts or handle key assignment
        self.app_contexts['Widgets_Width'][widget_code] = widget_width # type: ignore
        self.app_contexts['Widgets_Name'][widget_code] = widget_name # type: ignore
        self.app_contexts['Widgets_Code'][widget_name] = widget_code # type: ignore

    def adjust_widget_width(self, widget_code: str, width: int) -> None:
        self.app_contexts['Widgets_Width'][widget_code] = width # type: ignore

    @staticmethod
    def get_widget(widget_code: str) -> Optional['DesktopWidget']: # Forward reference for DesktopWidget
        if mgr and hasattr(mgr, 'widgets'): # mgr is Optional[WidgetsManager]
            for widget in mgr.widgets: # Assuming mgr.widgets is List[DesktopWidget]
                if widget.path == widget_code: # Assuming widget has a 'path' attribute
                    return widget
        return None

    @staticmethod
    def change_widget_content(widget_code: str, title: str, content: str) -> None:
        target_widget: Optional['DesktopWidget'] = PluginMethod.get_widget(widget_code)
        if target_widget:
            target_widget.update_widget_for_plugin([title, content])

    @staticmethod
    def is_get_notification() -> bool:
        if hasattr(notification, 'pushed_notification'): # notification is Any
            return bool(notification.pushed_notification) # type: ignore
        return False

    @staticmethod
    def send_notification(state: int = 1, lesson_name: str = '示例课程', title: str = '通知示例', subtitle: str = '副标题',
                          content: str = '这是一条通知示例', icon: Optional[Any] = None, duration: int = 2000) -> None:
        if hasattr(notification, 'push_notification'): # notification is Any
            notification.push_notification(state, lesson_name, title, subtitle, content, icon, duration) # type: ignore

    @staticmethod
    def subprocess_exec(title: str, action: str) -> None:
        # Assuming openProgressDialog is a QWidget or similar
        w: 'openProgressDialog' = openProgressDialog(title, action) # Forward reference
        if p_mgr and hasattr(p_mgr, 'temp_window'): # p_mgr is Optional[PluginManager]
            p_mgr.temp_window = [w] # Assuming temp_window is List[QWidget]
        w.show()

    @staticmethod
    def read_config(path: str, section: str, option: str) -> Any: # Return Any as type is unknown
        try:
            with open(path, 'r', encoding='utf-8') as r:
                config_data: Dict[str, Any] = json.load(r)

            section_content: Optional[Dict[str, Any]] = config_data.get(section)
            if section_content is not None:
                return section_content.get(option)
            return None
        except FileNotFoundError:
            logger.error(f"插件读取配置文件失败：文件未找到 {path}")
            return None
        except json.JSONDecodeError:
            logger.error(f"插件读取配置文件失败：JSON解码错误 {path}")
            return None
        except Exception as e:
            logger.error(f"插件读取配置文件失败：{e}")
            return None

    @staticmethod
    def generate_speech(
            text: str,
            engine: str = "edge",
            voice: Optional[str] = None,
            timeout: float = 10.0,
            auto_fallback: bool = True
    ) -> str: # Return type is already str
        """
        同步生成语音文件（供插件调用）

        参数：
        text (str): 要转换的文本（支持中英文混合）
        engine (str): 首选的TTS引擎（默认edge）
        voice (str): 指定语音ID（可选，默认自动选择）
        timeout (float): 超时时间（秒，默认10）
        auto_fallback (bool): 是否自动回退引擎（默认True）

        返回：
        str: 生成的音频文件路径
        """
        # Assuming generate_speech_sync is correctly typed or imported
        return generate_speech_sync( # type: ignore[no-untyped-call]
            text=text,
            engine=engine,
            voice=voice,
            auto_fallback=auto_fallback,
            timeout=timeout
        )

    @staticmethod
    def play_audio(file_path: str, tts_delete_after: bool = True) -> None: # Added return type
        """
        播放音频文件

        参数：
        file_path (str): 要播放的音频文件路径
        tts_delete_after (bool): 播放后是否删除文件（默认True）

        说明：
        - 删除操作有重试机制（3次尝试）
        """
        play_audio(file_path, tts_delete_after) # type: ignore[no-untyped-call]


class WidgetsManager(QObject): # Inherit from QObject
    def __init__(self) -> None: # Added return type
        super().__init__() # Call QObject constructor
        self.widgets: List[DesktopWidget] = []  # 小组件实例. DesktopWidget is forward-declared
        self.widgets_list: List[str] = []  # 小组件列表配置 (list of widget file names like 'widget-time.ui')
        self.state: int = 1 # 0 for hidden, 1 for shown (presumably)

        self.widgets_width: int = 0  # 小组件总宽度
        self.spacing: int = 0  # 小组件间隔

        self.start_pos_x: int = 0  # 小组件起始位置
        self.start_pos_y: int = 0

        self.hide_status: Optional[Tuple[int, int]] = None # [0] -> 在 current_state 设置的灵活隐藏， [1] -> 隐藏模式
                                                        # Example: (current_state_val, hide_mode_flag)

    def sync_widget_animation(self, target_pos: QPoint) -> None: # Added target_pos type and return type
        # Assuming DesktopWidget has 'path' and 'animate_expand'
        widget: DesktopWidget
        for widget in self.widgets:
            if widget.path == 'widget-current-activity.ui':
                widget.animate_expand(target_pos) # 主组件形变动画

    def init_widgets(self) -> None:  # 初始化小组件. Added return type
        self.widgets_list = list_.get_widget_config() # type: ignore[no-untyped-call] # Returns List[str]
        self.check_widgets_exist()
        # theme is Optional[str], conf.load_theme_config returns Dict[str, Any]
        loaded_theme_config: Dict[str, Any] = conf.load_theme_config(theme) # type: ignore[no-untyped-call]
        self.spacing = int(loaded_theme_config.get('spacing', 0)) # Default to 0 if not found

        self.get_start_pos()
        cnt_all: Dict[str, int] = {} # Counts occurrences of each widget path

        # 添加小组件实例
        w_idx: int
        widget_path_str: str
        for w_idx, widget_path_str in enumerate(self.widgets_list):
            cnt_all[widget_path_str] = cnt_all.get(widget_path_str, -1) + 1
            # DesktopWidget constructor needs to be checked for param types
            # Assuming get_widget_pos returns List[int] or Tuple[int, int]
            pos: List[int] = self.get_widget_pos("", w_idx) # Pass w_idx as cnt for position calculation
            widget_instance: DesktopWidget = DesktopWidget(
                parent=self,  # WidgetsManager instance
                path=widget_path_str,
                enable_tray=(w_idx == 0), # Only first widget enables tray
                cnt=cnt_all[widget_path_str],
                position=QPoint(pos[0], pos[1]), # Pass QPoint for position
                widget_cnt=w_idx
            )
            self.widgets.append(widget_instance)

        self.create_widgets()

    def close_all_widgets(self) -> None: # Added return type
        # 统一关闭所有组件
        if hasattr(self, '_closing') and self._closing: # Check the flag itself
            return
        self._closing: bool = True # Initialize the flag
        widget: DesktopWidget
        for widget in self.widgets:
            widget.close()  # 触发各个widget的closeEvent

    def check_widgets_exist(self) -> None: # Added return type
        # list_.widget_width is Dict[str, int]
        # Iterate over a copy for safe removal
        widget_path_str: str
        for widget_path_str in list(self.widgets_list):
            if widget_path_str not in list_.widget_width: # type: ignore
                self.widgets_list.remove(widget_path_str)

    @staticmethod
    def get_widget_width(path: str) -> int: # Added path type and return type
        # theme is Optional[str]
        # conf.load_theme_width returns Dict[str, int]
        # list_.widget_width is Dict[str, int]
        try:
            width: int = conf.load_theme_width(theme)[path] # type: ignore[no-untyped-call,index]
        except KeyError:
            width = list_.widget_width[path] # type: ignore
        return int(width) # Ensure it's int

    @staticmethod
    def get_widgets_height() -> int: # Added return type
        # theme is Optional[str]
        # conf.load_theme_config returns Dict[str, Any]
        loaded_theme_config: Dict[str, Any] = conf.load_theme_config(theme) # type: ignore[no-untyped-call]
        return int(loaded_theme_config.get('height', 100)) # Default to 100 if not found, ensure int

    def create_widgets(self) -> None: # Added return type
        widget: DesktopWidget
        for widget in self.widgets:
            widget.show()
            # Assuming widget.path and widget.windowTitle() are str
            logger.info(f'显示小组件：({widget.path}, {widget.windowTitle()})') # Corrected logging format

    def adjust_ui(self) -> None:  # 更新小组件UI. Added return type
        widget: DesktopWidget # self.widgets is List[DesktopWidget]
        for widget in self.widgets:
            # 调整窗口尺寸
            width: int = self.get_widget_width(widget.path) # Assuming widget.path is str
            height: int = self.get_widgets_height()
            # widget.widget_cnt should be int. get_widget_pos returns List[int]
            pos_x: int = self.get_widget_pos(widget.path, widget.widget_cnt)[0]
            opacity_setting: Any = config_center.read_conf('General', 'opacity') # type: ignore[no-untyped-call]
            op: float = int(opacity_setting) / 100 if opacity_setting is not None else 1.0

            if widget.animation is None: # Assuming animation is Optional[QPropertyAnimation]
                widget.widget_transition(pos_x, width, height, op)

    def get_widget_pos(self, path: str, cnt: Optional[int] = None) -> List[int]:  # 获取小组件位置. Added types
        # self.widgets_list is List[str]
        num: int
        if cnt is None:
            try:
                num = self.widgets_list.index(path)
            except ValueError: # path not in list
                logger.error(f"Widget path '{path}' not found in widgets_list for position calculation.")
                # Return a default or error position
                return [self.start_pos_x, self.start_pos_y]
        else:
            num = cnt

        self.get_start_pos() # Recalculates start_pos_x, start_pos_y, widgets_width
        pos_x_calc: float = float(self.start_pos_x + self.spacing * num) # Ensure float for precision before int conversion

        i: int
        for i in range(num):
            try:
                # theme is Optional[str], self.widgets_list[i] is str
                # conf.load_theme_width returns Dict[str, int]
                pos_x_calc += conf.load_theme_width(theme)[self.widgets_list[i]] # type: ignore[no-untyped-call,index]
            except KeyError:
                # list_.widget_width is Dict[str, int]
                pos_x_calc += list_.widget_width[self.widgets_list[i]] # type: ignore
            except Exception as e: # Catch any other potential errors like list index out of bounds
                logger.warning(f"Error calculating widget position for index {i}, path {self.widgets_list[i] if i < len(self.widgets_list) else 'OOB'}: {e}")
                pos_x_calc += 0 # Or handle more gracefully
        return [int(pos_x_calc), int(self.start_pos_y)]

    def get_start_pos(self) -> None: # Added return type
        self.calculate_widgets_width()
        # app is Optional[QApplication]
        if app and app.primaryScreen():
            screen_geometry: QRect = app.primaryScreen().availableGeometry()
            screen_width: int = screen_geometry.width()
            # screen_height: int = screen_geometry.height() # Unused
        else: # Fallback if app or primaryScreen is not available
            logger.warning("QApplication or primaryScreen not available for get_start_pos. Using defaults.")
            screen_width = 1920 # Default width

        margin_str: Any = config_center.read_conf('General', 'margin') # type: ignore[no-untyped-call]
        margin_val: int = int(margin_str) if margin_str is not None and margin_str.isdigit() else 0
        self.start_pos_y = max(0, margin_val)
        self.start_pos_x = (screen_width - self.widgets_width) // 2

    def calculate_widgets_width(self) -> None:  # 计算小组件占用宽度. Added return type
        self.widgets_width = 0
        # 累加小组件宽度
        # self.widgets_list is List[str]
        widget_path_str: str
        for widget_path_str in self.widgets_list:
            try:
                self.widgets_width += self.get_widget_width(widget_path_str)
            except Exception as e:
                logger.warning(f'计算小组件宽度发生错误 for {widget_path_str}：{e}')
                # self.widgets_width += 0 # No need, already 0 if error

        if self.widgets_list: # Ensure list is not empty to avoid negative index with len()-1
             self.widgets_width += self.spacing * (len(self.widgets_list) - 1)

    def hide_windows(self) -> None: # Added return type
        self.state = 0
        widget: DesktopWidget
        for widget in self.widgets:
            widget.animate_hide()

    def full_hide_windows(self) -> None: # Added return type
        self.state = 0
        widget: DesktopWidget
        for widget in self.widgets:
            widget.animate_hide(True) # Assuming animate_hide takes Optional[bool]

    def show_windows(self) -> None: # Added return type
        # fw is Optional[FloatingWidget]
        if fw and fw.animating:  # 避免动画Bug
            return
        if fw and fw.isVisible():
            fw.close()
        self.state = 1
        widget: DesktopWidget
        for widget in self.widgets:
            widget.animate_show()

    def clear_widgets(self) -> None: # Added return type
        global fw, was_floating_mode # fw: Optional[FloatingWidget], was_floating_mode: bool
        if fw and fw.isVisible():
            fw.close()
            was_floating_mode = True
        else:
            was_floating_mode = False

        widget_to_remove: DesktopWidget
        for widget_to_remove in list(self.widgets): # Iterate over a copy for safe removal
            widget_to_remove.animate_hide_opacity()
            # Assuming animate_hide_opacity calls close/deleteLater or we handle it after loop
            # The original code removes from self.widgets then calls init() which re-populates.
            # This might lead to issues if animate_hide_opacity is async.
            # For now, following original structure.

        # Clear the list after initiating animations.
        # Widgets will be closed/deleted by their animations or when init() rebuilds.
        # However, the original `self.widgets.remove(widget)` was inside the loop.
        # This is problematic if init() relies on an empty self.widgets before it runs.
        # Let's clear it before init(), assuming animations don't need the widget in *this* list.

        # Original logic had remove inside the loop, which is bad practice.
        # It should be:
        # 1. Animate all widgets to hide.
        # 2. Wait for animations (if possible, or assume they handle their own cleanup).
        # 3. Clear the list of widgets.
        # 4. Re-initialize.
        # For now, let's replicate the original logic of removing one by one, then calling init.
        # This is likely flawed if animations are not instant and init() rebuilds too soon.
        # A better approach:
        # for widget in self.widgets: widget.animate_hide_opacity_and_destroy()
        # self.widgets.clear()
        # init()
        # For now, sticking to the structure:
        widgets_copy = list(self.widgets)
        self.widgets.clear() # Clear the main list
        for widget_instance in widgets_copy:
            # widget_instance.animate_hide_opacity() # This should lead to close/deleteLater
            # The original code had self.widgets.remove(widget) INSIDE the loop.
            # This is risky. If init() is called right after, it's fine.
            # The crucial part is that init() must be able to run correctly
            # even if old widgets are still in their closing animation.
            # Let's assume animate_hide_opacity eventually calls self.close() which should make it safe.
             pass # Widgets are animated, init() will rebuild.
                 # The DesktopWidget.animate_hide_opacity calls self.close which should handle deletion.

        init() # init is a global function

    def update_widgets(self) -> None: # Added return type
        c: int = 0
        self.adjust_ui() # This itself loops through self.widgets

        widget: DesktopWidget
        for widget in self.widgets:
            if c == 0:
                get_countdown(True) # Assuming get_countdown is typed
            widget.update_data(path=widget.path) # Assuming widget.path is str
            c += 1

        if p_loader: # p_loader is Optional[PluginLoader]
            p_loader.update_plugins() # type: ignore[no-untyped-call]

        if hasattr(notification, 'pushed_notification'): # notification is Any
            if notification.pushed_notification: # type: ignore
                notification.pushed_notification = False # type: ignore

    def decide_to_hide(self) -> None: # Added return type
        hide_method: Optional[str] = config_center.read_conf('General', 'hide_method') # type: ignore[no-untyped-call]
        if hide_method == '0':  # 正常
            self.hide_windows()
        elif hide_method == '1':  # 单击即完全隐藏
            self.full_hide_windows()
        elif hide_method == '2':  # 最小化为浮窗
            if fw and not fw.animating: # fw is Optional[FloatingWidget]
                self.full_hide_windows()
                fw.show()
        else: # Default or unknown, treat as '0'
            self.hide_windows()

    def cleanup_resources(self) -> None: # Added return type
        self.hide_status = None # 重置hide_status
        widgets_to_clean: List[DesktopWidget] = list(self.widgets) # self.widgets is List[DesktopWidget]
        self.widgets.clear()
        widget: DesktopWidget
        for widget in widgets_to_clean:
            widget_path: str = getattr(widget, 'path', '未知组件')
            try:
                # Assuming weather_timer is QTimer or similar, weather_thread is QThread or similar
                if hasattr(widget, 'weather_timer') and widget.weather_timer:
                    try:
                        widget.weather_timer.stop() # type: ignore
                    except RuntimeError: # Catch if timer already stopped or similar
                        pass
                if hasattr(widget, 'weather_thread') and widget.weather_thread:
                    try:
                        if widget.weather_thread.isRunning(): # type: ignore
                            widget.weather_thread.quit() # type: ignore
                            if not widget.weather_thread.wait(500): # type: ignore
                                logger.warning(f"组件 {widget_path} 的天气线程未正常退出，强制终止")
                                widget.weather_thread.terminate() # type: ignore
                                widget.weather_thread.wait() # type: ignore
                    except RuntimeError: # Catch if thread already finished or error during quit/terminate
                        pass
                widget.deleteLater()
            except Exception as ex:
                logger.error(f"清理组件 {widget_path} 时发生异常: {ex}")

    def stop(self) -> None: # Added return type
        if mgr: # mgr is Optional[WidgetsManager]
            mgr.cleanup_resources()

        widget: DesktopWidget
        for widget in self.widgets: # self.widgets is List[DesktopWidget]
            widget.stop() # Assuming DesktopWidget has stop()

        # self.animation and self.opacity_animation are not defined in WidgetsManager __init__
        # These seem to belong to DesktopWidget or FloatingWidget.
        # If they were meant for WidgetsManager, they need to be initialized.
        # For now, assuming this might be a leftover or intended for subclasses.
        if hasattr(self, 'animation') and self.animation: # type: ignore
            self.animation.stop() # type: ignore
        if hasattr(self, 'opacity_animation') and self.opacity_animation: # type: ignore
            self.opacity_animation.stop() # type: ignore

        # QObject (if it is one, currently not) or QWidget would have close()
        # If WidgetsManager is not a QWidget, it won't have a close method unless defined.
        # self.close() # This will error if WidgetsManager is not a QWidget.
        # For now, assume it's meant to be closed if it's a window (which it isn't directly).
        # This method might be intended to be called on individual widgets instead.
        # Since it's cleaning up resources, perhaps no direct 'close' of manager itself is needed.
        pass


class openProgressDialog(QWidget):
    def __init__(self, action_title: str = '打开 记事本', action: str = 'notepad') -> None: # Added types
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Tool) # type: ignore[attr-defined]

        auto_delay_str: Any = config_center.read_conf('Plugin', 'auto_delay') # type: ignore[no-untyped-call]
        time_val: int = int(auto_delay_str) if auto_delay_str is not None and auto_delay_str.isdigit() else 3 # Default to 3s
        self.action: str = action

        # app is Optional[QApplication]
        if app and app.primaryScreen():
            screen_geometry: QRect = app.primaryScreen().availableGeometry()
            self.screen_width: int = screen_geometry.width()
            self.screen_height: int = screen_geometry.height()
        else: # Fallback
            self.screen_width = 1920
            self.screen_height = 1080

        self.init_ui()
        self.init_font()
        self.move((self.screen_width - self.width()) // 2, self.screen_height - self.height() - 100)

        self.action_name: Optional[QLabel] = self.findChild(QLabel, 'action_name')
        if self.action_name:
            self.action_name.setText(action_title)

        self.opening_countdown: Optional[ProgressRing] = self.findChild(ProgressRing, 'opening_countdown')
        if self.opening_countdown:
            self.opening_countdown.setRange(0, time_val - 1)

        self.progress_timer: QTimer = QTimer(self)
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(1000)

        self.timer: QTimer = QTimer(self)
        self.timer.timeout.connect(self.execute_action)
        self.timer.start(time_val * 1000)

        self.cancel_opening: Optional[QPushButton] = self.findChild(QPushButton, 'cancel_opening')
        if self.cancel_opening:
            self.cancel_opening.clicked.connect(self.cancel_action)

        self.intro_animation()

    def update_progress(self) -> None: # Added return type
        if self.opening_countdown:
            self.opening_countdown.setValue(self.opening_countdown.value() + 1)

    def execute_action(self) -> None: # Added return type
        self.timer.stop()
        subprocess.Popen(self.action)
        self.close()

    def cancel_action(self) -> None: # Added return type
        self.timer.stop()
        self.close()

    def save_position(self) -> None: # Added return type
        pass # No operation

    def init_ui(self) -> None: # Added return type
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | # type: ignore[attr-defined]
            Qt.X11BypassWindowManagerHint  # type: ignore[attr-defined] #绕过窗口管理器以在全屏显示通知
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # type: ignore[attr-defined]

        # base_directory is Path from conf
        theme_ui_path: str = f'{base_directory}/ui/default/toast-open_dialog.ui' # type: ignore[attr-defined]
        if isDarkTheme(): # type: ignore[no-untyped-call]
            theme_ui_path = f'{base_directory}/ui/default/dark/toast-open_dialog.ui' # type: ignore[attr-defined]

        uic.loadUi(theme_ui_path, self)

        backgnd: Optional[QFrame] = self.findChild(QFrame, 'backgnd')
        if backgnd:
            shadow_effect: QGraphicsDropShadowEffect = QGraphicsDropShadowEffect(self)
            shadow_effect.setBlurRadius(28)
            shadow_effect.setXOffset(0)
            shadow_effect.setYOffset(6)
            shadow_effect.setColor(QColor(0, 0, 0, 80))
            backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self) -> None: # Added return type
        font_path: str = f'{base_directory}/font/HarmonyOS_Sans_SC_Bold.ttf' # type: ignore[attr-defined]
        font_id: int = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_families: List[str] = QFontDatabase.applicationFontFamilies(font_id)
            if font_families:
                font_family: str = font_families[0]
                self.setStyleSheet(f"""
                    QLabel, ProgressRing, PushButton{{
                        font-family: "{font_family}";
                        font-weight: bold
                        }}
                    """)

    def intro_animation(self) -> None:  # 弹出动画. Added return type
        self.setMinimumWidth(300)
        label_width_offset: int = 0
        if self.action_name: # action_name is Optional[QLabel]
             label_width_offset = self.action_name.sizeHint().width() - 120

        self.animation: QPropertyAnimation = QPropertyAnimation(self, b'windowOpacity') # type: ignore[misc]
        self.animation.setDuration(400)
        self.animation.setStartValue(0)
        self.animation.setEndValue(1)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc) # type: ignore[attr-defined]

        self.animation_rect: QPropertyAnimation = QPropertyAnimation(self, b'geometry') # type: ignore[misc]
        self.animation_rect.setDuration(450)
        start_rect: QRect = QRect(self.x(), self.screen_height, self.width(), self.height())
        self.animation_rect.setStartValue(start_rect)

        end_width: int = self.width() + label_width_offset
        end_x: int = (self.screen_width - end_width) // 2
        end_y: int = self.screen_height - 250
        end_height: int = self.height()
        end_rect: QRect = QRect(end_x, end_y, end_width, end_height)
        self.animation_rect.setEndValue(end_rect)
        self.animation_rect.setEasingCurve(QEasingCurve.Type.InOutCirc) # type: ignore[attr-defined]

        self.animation.start()
        self.animation_rect.start()

    def closeEvent(self, event: QCloseEvent) -> None: # Added QCloseEvent and return type
        event.ignore()
        self.setMinimumWidth(0)
        # self.position is not defined in __init__. Assuming it's a QPoint if used.
        # self.position = self.pos()
        self.save_position() # Currently does nothing
        self.deleteLater()
        self.hide()
        if p_mgr and hasattr(p_mgr, 'temp_window'): # p_mgr is Optional[PluginManager]
            p_mgr.temp_window.clear() # temp_window is List[QWidget]


class FloatingWidget(QWidget):  # 浮窗
    def __init__(self) -> None: # Added return type
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.animation_rect = None
        self.animation = None
        self.m_Position = None
        self.p_Position = None
        self.m_flag = None
        self.r_Position = None
        self._is_topmost_callback_added = False
        self.init_ui()
        self.init_font()
        self.position = None
        self.animating = False
        self.focusing = False
        self.text_changed = False

        self.current_lesson_name_text = self.findChild(QLabel, 'subject')
        self.activity_countdown = self.findChild(QLabel, 'activity_countdown')
        self.countdown_progress_bar = self.findChild(ProgressRing, 'progressBar')

        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        # 动态获取屏幕尺寸
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        # 加载保存的位置
        saved_pos = self.load_position()
        if saved_pos:
            # 边界检查
            saved_pos = self.adjust_position_to_screen(saved_pos)
            self.position = saved_pos
        else:
            # 使用动态计算的默认位置
            self.position = QPoint(
                (screen_width - self.width()) // 2,  # 居中横向
                50  # 距离顶部 50px
            )

        if hasattr(utils, 'update_timer') and utils.update_timer: # utils.update_timer is QTimer
            utils.update_timer.add_callback(self.update_data) # type: ignore[no-untyped-call]

    def adjust_position_to_screen(self, pos: QPoint) -> QPoint: # Added types
        screen: Optional[QWidget] = QApplication.screenAt(pos) # screenAt returns QScreen
        if not screen:
            screen = QApplication.primaryScreen() # primaryScreen returns QScreen

        if not screen: # Still no screen (e.g. in tests or headless)
             return pos # Return original pos if no screen info

        screen_geometry: QRect = screen.availableGeometry()
        window_width: int = self.width()
        window_height: int = self.height()

        # Screen boundaries
        screen_left: int = screen_geometry.x()
        screen_right: int = screen_geometry.x() + screen_geometry.width()
        screen_top: int = screen_geometry.y()
        screen_bottom: int = screen_geometry.y() + screen_geometry.height()

        new_x: int = pos.x()
        new_y: int = pos.y()

        # Adjust if window is more than halfway off screen horizontally
        if pos.x() < screen_left:
            visible_width_left: int = (pos.x() + window_width) - screen_left
            if visible_width_left < window_width / 2:
                new_x = screen_left
        elif (pos.x() + window_width) > screen_right:
            visible_width_right: int = screen_right - pos.x()
            if visible_width_right < window_width / 2:
                new_x = screen_right - window_width

        # Adjust if window is more than halfway off screen vertically
        if pos.y() < screen_top:
            visible_height_top: int = (pos.y() + window_height) - screen_top
            if visible_height_top < window_height / 2:
                new_y = screen_top
        elif (pos.y() + window_height) > screen_bottom:
            visible_height_bottom: int = screen_bottom - pos.y()
            if visible_height_bottom < window_height / 2:
                new_y = screen_bottom - window_height

        return QPoint(new_x, new_y)

    def _ensure_topmost(self) -> None: # Added return type
        # 始终处于顶层
        if active_windows: # type: ignore[name-defined] # active_windows from tip_toast
            return
        if os.name == 'nt':
            try:
                hwnd: int = self.winId().__int__() # type: ignore[attr-defined]
                if ctypes.windll.user32.IsWindow(hwnd): # type: ignore[attr-defined]
                    HWND_TOPMOST: int = -1
                    SWP_NOMOVE: int = 0x0002
                    SWP_NOSIZE: int = 0x0001
                    SWP_SHOWWINDOW: int = 0x0040
                    SWP_NOACTIVATE: int = 0x0010
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOSIZE | SWP_SHOWWINDOW) # type: ignore[attr-defined]
                    self.raise_()
                else: # hwnd is not a valid window
                    if self._is_topmost_callback_added:
                        try:
                            if hasattr(utils, 'update_timer') and utils.update_timer:
                                utils.update_timer.remove_callback(self._ensure_topmost) # type: ignore[no-untyped-call]
                        except ValueError: # Callback might have already been removed
                            pass
                        self._is_topmost_callback_added = False
                        logger.debug(f"句柄 {hwnd} 无效，已移除置顶回调。")
            except RuntimeError as e: # Catch specific C++ object already deleted errors
                 if 'Internal C++ object' in str(e) and 'already deleted' in str(e):
                     logger.debug(f"尝试访问已删除的 FloatingWidget 时出错，移除回调: {e}")
                     if self._is_topmost_callback_added:
                         try:
                            if hasattr(utils, 'update_timer') and utils.update_timer:
                                utils.update_timer.remove_callback(self._ensure_topmost) # type: ignore[no-untyped-call]
                         except ValueError:
                             pass
                         self._is_topmost_callback_added = False
                 else: # Other runtime errors
                     logger.error(f"检查或设置浮窗置顶时发生运行时错误: {e}")
            except Exception as e: # Catch any other exceptions
                logger.error(f"检查或设置浮窗置顶时出错: {e}")
                if self._is_topmost_callback_added: # Attempt to remove callback on other errors too
                    try:
                        if hasattr(utils, 'update_timer') and utils.update_timer:
                           utils.update_timer.remove_callback(self._ensure_topmost) # type: ignore[no-untyped-call]
                    except ValueError:
                        pass
                    self._is_topmost_callback_added = False
                    logger.debug(f"因错误 {e} 移除浮窗置顶回调。")

    def save_position(self) -> None: # Added return type
        current_screen = QApplication.screenAt(self.pos())
        if not current_screen:
            current_screen = QApplication.primaryScreen()

        if not current_screen: return # No screen available

        screen_geometry: QRect = current_screen.availableGeometry()
        current_pos: QPoint = self.pos()
        x_pos: int = current_pos.x()
        window_w: int = self.width()

        if mgr and mgr.state: # mgr is Optional[WidgetsManager], state is int
            return # Don't save if main widgets are shown (mgr.state == 1)

        screen_left_edge: int = screen_geometry.left()
        screen_right_edge: int = screen_geometry.right()

        # Adjust x if more than half off-screen
        if x_pos < screen_left_edge:
            if (x_pos + window_w) - screen_left_edge < window_w / 2:
                x_pos = screen_left_edge
        elif (x_pos + window_w) > screen_right_edge:
            if self.animating: # Don't save during animation if it might be moving off-screen
                return
            if screen_right_edge - x_pos < window_w / 2:
                x_pos = screen_right_edge - window_w

        # Clamp y to be within screen
        y_pos: int = min(max(current_pos.y(), screen_geometry.top()), screen_geometry.bottom() - self.height()) # ensure full widget visible

        final_pos: QPoint = QPoint(x_pos, y_pos)
        config_center.write_conf('FloatingWidget', 'pos_x', str(final_pos.x())) # type: ignore[no-untyped-call]
        if not self.animating: # Only save Y if not animating (X might be saved during animation for edge cases)
            config_center.write_conf('FloatingWidget', 'pos_y', str(final_pos.y())) # type: ignore[no-untyped-call]

    def load_position(self) -> Optional[QPoint]: # Added return type
        x = config_center.read_conf('FloatingWidget', 'pos_x')
        y = config_center.read_conf('FloatingWidget', 'pos_y')
        if x and y:
            return QPoint(int(x), int(y))
        return None

    def init_ui(self):
        setTheme_()
        if os.path.exists(f'{base_directory}/ui/{theme}/widget-floating.ui'):
            if isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']:
                uic.loadUi(f'{base_directory}/ui/{theme}/dark/widget-floating.ui', self)
            else:
                uic.loadUi(f'{base_directory}/ui/{theme}/widget-floating.ui', self)
        else:
            if isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']:
                uic.loadUi(f'{base_directory}/ui/default/dark/widget-floating.ui', self)
            else:
                uic.loadUi(f'{base_directory}/ui/default/widget-floating.ui', self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 根据平台和设置应用窗口标志
        if sys.platform == 'darwin':
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Widget | Qt.X11BypassWindowManagerHint
        else:
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.X11BypassWindowManagerHint

        self.setWindowFlags(flags)

        # 始终添加置顶回调逻辑
        if os.name == 'nt':
            if not self._is_topmost_callback_added:
                try:
                    if hasattr(utils, 'update_timer') and utils.update_timer:
                        utils.update_timer.add_callback(self._ensure_topmost)
                        self._is_topmost_callback_added = True
                        self._ensure_topmost() # 立即执行一次确保初始置顶
                    else:
                        logger.warning("utils.update_timer 不可用，无法为浮窗添加置顶回调。")
                except Exception as e:
                    logger.error(f"为浮窗添加置顶回调时出错: {e}")

        if sys.platform == 'darwin':
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Widget |  # macOS 失焦时仍然显示
                Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        else:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                                Qt.WindowType.Tool |
                                Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
                                )

        backgnd = self.findChild(QFrame, 'backgnd')
        shadow_effect = QGraphicsDropShadowEffect(self)
        shadow_effect.setBlurRadius(28)
        shadow_effect.setXOffset(0)
        shadow_effect.setYOffset(6)
        shadow_effect.setColor(QColor(0, 0, 0, 75))
        backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = f'{base_directory}/font/HarmonyOS_Sans_SC_Bold.ttf'
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(f"""
                QLabel, ProgressRing{{
                    font-family: "{font_family}";
                    }}
                """)

    def update_data(self):
        time_color = QColor(f'#{config_center.read_conf("Color", "floating_time")}')
        self.activity_countdown.setStyleSheet(f"color: {time_color.name()}; background: transparent")
        if self.animating:  # 执行动画时跳过更新
            return
        if platform.system() == 'Windows' and platform.release() != '7':
            self.setWindowOpacity(int(config_center.read_conf('General', 'opacity')) / 100)  # 设置窗口透明度
        else:
            self.setWindowOpacity(1.0)
        cd_list = get_countdown()
        self.text_changed = False
        if self.current_lesson_name_text.text() != current_lesson_name:
            self.text_changed = True

        self.current_lesson_name_text.setText(current_lesson_name)

        if cd_list:  # 模糊倒计时
            blur_floating = config_center.read_conf('General', 'blur_floating_countdown') == '1'
            if blur_floating:  # 模糊显示
                if cd_list[1] == '00:00':
                    self.activity_countdown.setText(f"< - 分钟")
                else:
                    minutes = int(cd_list[1].split(':')[0]) + 1
                    self.activity_countdown.setText(f"< {minutes} 分钟")
            else:  # 精确显示
                self.activity_countdown.setText(cd_list[1])
            self.countdown_progress_bar.setValue(cd_list[2])

        self.adjustSize_animation()

        self.update()

    def showEvent(self, event):  # 窗口显示
        logger.info('显示浮窗')
        current_screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        screen_geometry = current_screen.availableGeometry()

        if self.position:
            if self.position.y() > screen_geometry.center().y():
                # 下半屏
                start_pos = QPoint(
                    self.position.x(),
                    screen_geometry.bottom() + self.height()
                )
            else:
                # 上半屏
                start_pos = QPoint(
                    self.position.x(),
                    screen_geometry.top() - self.height()
                )
        else:
            # 默认:顶部中央滑入
            start_pos = QPoint(
                (screen_geometry.width() - self.width()) // 2,
                screen_geometry.top() - self.height()
            )
            self.position = QPoint(
                (screen_geometry.width() - self.width()) // 2,
                max(50, int(config_center.read_conf('General', 'margin')))
            )

        self.animation = QPropertyAnimation(self, b'windowOpacity')
        self.animation.setDuration(450)
        self.animation.setStartValue(0)
        self.animation.setEndValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.animation_rect = QPropertyAnimation(self, b'geometry')
        self.animation_rect.setDuration(600)
        self.animation_rect.setStartValue(QRect(start_pos, self.size()))
        self.animation_rect.setEndValue(QRect(self.position, self.size()))

        if platform.system() == 'Darwin':
            self.animation_rect.setEasingCurve(QEasingCurve.Type.OutQuad)
        elif platform.system() == 'Windows':
            self.animation_rect.setEasingCurve(QEasingCurve.Type.OutBack)
        else:
            self.animation_rect.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.animating = True
        self.animation.start()
        self.animation_rect.start()
        self.animation_rect.finished.connect(self.animation_done)

    def animation_done(self):
        self.animating = False

    def closeEvent(self, event):
        # 跳过动画
        if QApplication.instance().closingDown():
            self.save_position()
            event.accept()
            return
        event.ignore()
        self.setMinimumWidth(0)
        self.position = self.pos()
        self.save_position()
        current_screen = QApplication.screenAt(self.pos())
        if not current_screen:
            current_screen = QApplication.primaryScreen()
        screen_geometry = current_screen.availableGeometry()
        screen_center_y = screen_geometry.y() + (screen_geometry.height() // 2)
        # 动态动画
        current_pos = self.pos()
        base_duration = 350  # 基础
        max_duration = 550   # 最大
        min_duration = 250   # 最小
        # 获取主组件位置
        main_widget = next(
            (w for w in mgr.widgets if w.path == 'widget-current-activity.ui'),
            None
        )
        if main_widget:
            if current_pos.y() > screen_center_y:  # 下半屏
                # 屏幕底部
                target_y = screen_geometry.bottom() + self.height() + 10
                # 任务栏补偿
                if platform.system() == "Windows":
                    target_y += 30

                target_pos = QPoint(
                    main_widget.x(),
                    target_y
                )
                distance = abs(current_pos.y() - target_y)
            else:  # 上半屏
                target_pos = main_widget.pos()
                distance = abs(current_pos.y() - target_pos.y())
        else:
            target_pos = QPoint(
                screen_geometry.center().x() - self.width() // 2,
                int(config_center.read_conf('General', 'margin'))
            )
            distance = abs(current_pos.y() - target_pos.y())

        max_distance = screen_geometry.height()
        distance_ratio = min(distance / max_distance, 1.0)
        duration = int(base_duration + (max_duration - base_duration) * (distance_ratio ** 0.7))
        duration = max(min_duration, min(duration, max_duration))
        # 多平台兼容
        if platform.system() == "Darwin":
            curve = QEasingCurve.Type.OutQuad
            duration = int(duration * 0.85)
        curve = QEasingCurve.Type.Linear
        if platform.system() == "Windows":
            curve = QEasingCurve.Type.OutCubic
            if current_pos.y() > screen_center_y:
                duration += 50  # 底部移动稍慢
            curve = QEasingCurve.Type.InOutQuad
        elif platform.system() == "Darwin":
            curve = QEasingCurve.Type.InOutQuad # macOS 也用这个吧

        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(int(duration * 1.15))
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(0.0)

        self.animation_rect = QPropertyAnimation(self, b"geometry")
        self.animation_rect.setDuration(duration)
        self.animation_rect.setStartValue(self.geometry())
        self.animation_rect.setEndValue(QRect(target_pos, self.size()))
        self.animation_rect.setEasingCurve(curve)

        self.animating = True
        self.animation.start()
        self.animation_rect.start()

        def cleanup():
            self.hide()
            self.save_position()
            self.animating = False
            if self._is_topmost_callback_added:
                try:
                    utils.update_timer.remove_callback(self._ensure_topmost)
                except ValueError:
                    pass
                self._is_topmost_callback_added = False

        self.animation_rect.finished.connect(cleanup)

    def hideEvent(self, event):
        event.accept()
        logger.info('隐藏浮窗')
        self.animating = False
        self.setMinimumSize(QSize(self.width(), self.height()))

    def adjustSize_animation(self):
        if not self.text_changed:
            return
        self.setMinimumWidth(200)
        current_geometry = self.geometry()
        label_width = self.current_lesson_name_text.sizeHint().width() + 120
        offset = label_width - current_geometry.width()
        target_geometry = current_geometry.adjusted(0, 0, offset, 0)
        self.animation = QPropertyAnimation(self, b'geometry')
        self.animation.setDuration(450)
        self.animation.setStartValue(current_geometry)
        self.animation.setEndValue(target_geometry)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)
        self.animating = True  # 避免动画Bug x114514
        self.animation.start()
        self.animation.finished.connect(self.animation_done)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.m_flag = True
            self.m_Position = event.globalPos() - self.pos()  # 获取鼠标相对窗口的位置
            self.p_Position = event.globalPos()  # 获取鼠标相对屏幕的位置
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.m_flag:
            self.move(event.globalPos() - self.m_Position)  # 更改窗口位置
            event.accept()

    def mouseReleaseEvent(self, event):
        self.r_Position = event.globalPos()  # 获取鼠标相对窗口的位置
        self.m_flag = False
        # 保存位置到配置文件
        self.save_position()
        # 特定隐藏模式下不执行操作
        hide_mode = config_center.read_conf('General', 'hide')
        if hide_mode == '1' or hide_mode == '2':
             return # 阻止手动展开/收起
        if (
                hasattr(self, "p_Position")
                and self.r_Position == self.p_Position
                and not self.animating
        ): # 非特定隐藏模式下执行点击事件
            if hide_mode == '3':
                if mgr.state:
                    mgr.decide_to_hide()
                    mgr.hide_status = (current_state, 1)
                else:
                    mgr.show_windows()
                    mgr.hide_status = (current_state, 0)
            elif hide_mode == '0':
                mgr.show_windows()
                self.close()

    def focusInEvent(self, event):
        self.focusing = True

    def focusOutEvent(self, event):
        self.focusing = False

    def stop(self):
        if mgr:
            mgr.cleanup_resources()
        for widget in self.widgets:
            widget.stop()
        if self.animation:
            self.animation.stop()
        if self.opacity_animation:
            self.opacity_animation.stop()
        self.close()

class DesktopWidget(QWidget):  # 主要小组件
    def __init__(self, parent=WidgetsManager, path='widget-time.ui', enable_tray=False, cnt=0, position=None, widget_cnt = None):
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Tool)

        self.cnt = cnt
        self.widget_cnt = widget_cnt

        self.tray_menu = None

        self.last_widgets = list_.get_widget_config()
        self.path = path

        self.last_code = 101010100
        self.radius = conf.load_theme_config(theme)['radius']
        self.last_theme = config_center.read_conf('General', 'theme')
        self.last_color_mode = config_center.read_conf('General', 'color_mode')
        self.w = 100

        # 天气预警动画相关
        self.weather_alert_timer = None
        self.weather_alert_animation = None
        self.weather_alert_text = None
        self.alert_showing = False

        self.position = parent.get_widget_pos(self.path) if position is None else position
        self.animation = None
        self.opacity_animation = None
        mgr.hide_status = None
        self._is_topmost_callback_added = False # 添加一个标志来跟踪回调是否已添加

        try:
            self.w = conf.load_theme_config(theme)['widget_width'][self.path]
        except KeyError:
            self.w = list_.widget_width[self.path]
        self.h = conf.load_theme_config(theme)['height']

        init_config()
        self.init_ui(path)
        self.init_font()

        if enable_tray:
            self.init_tray_menu()  # 初始化托盘菜单

        # 样式
        self.backgnd = self.findChild(QFrame, 'backgnd')
        if self.backgnd is None:
            self.backgnd = self.findChild(QLabel, 'backgnd')

        stylesheet = self.backgnd.styleSheet()  # 应用圆角
        updated_stylesheet = re.sub(r'border-radius:\d+px;', f'border-radius:{self.radius}px;', stylesheet)
        self.backgnd.setStyleSheet(updated_stylesheet)

        if path == 'widget-time.ui':  # 日期显示
            self.date_text = self.findChild(QLabel, 'date_text')
            self.date_text.setText(f'{today.year} 年 {today.month} 月')
            self.day_text = self.findChild(QLabel, 'day_text')
            self.day_text.setText(f'{today.day}日  {list_.week[today.weekday()]}')

        elif path == 'widget-countdown.ui':  # 活动倒计时
            self.countdown_progress_bar = self.findChild(QProgressBar, 'progressBar')
            self.activity_countdown = self.findChild(QLabel, 'activity_countdown')
            self.ac_title = self.findChild(QLabel, 'activity_countdown_title')

        elif path == 'widget-current-activity.ui':  # 当前活动
            self.current_subject = self.findChild(QPushButton, 'subject')
            self.blur_effect_label = self.findChild(QLabel, 'blurEffect')
            # 模糊效果
            self.blur_effect = QGraphicsBlurEffect()
            self.current_subject.mouseReleaseEvent = self.rightReleaseEvent

            update_timer.add_callback(self.detect_theme_changed)

        elif path == 'widget-next-activity.ui':  # 接下来的活动
            self.nl_text = self.findChild(QLabel, 'next_lesson_text')

        elif path == 'widget-countdown-day.ui':  # 自定义倒计时
            self.custom_title = self.findChild(QLabel, 'countdown_custom_title')
            self.custom_countdown = self.findChild(QLabel, 'custom_countdown')

        elif path == 'widget-weather.ui':  # 天气组件
            content_layout = self.findChild(QHBoxLayout, 'horizontalLayout_2')
            content_layout.setSpacing(1)
            self.temperature = self.findChild(QLabel, 'temperature')
            self.weather_icon = self.findChild(QLabel, 'weather_icon')
            self.alert_icon = IconWidget(self)
            self.alert_icon.setFixedSize(22,22)
            self.alert_icon.hide()

            # 预警标签
            self.weather_alert_text = QLabel(self)
            self.weather_alert_text.setAlignment(Qt.AlignCenter)
            self.weather_alert_text.setStyleSheet(self.temperature.styleSheet())
            self.weather_alert_text.setFont(self.temperature.font())
            self.weather_alert_text.hide()
            content_layout.addWidget(self.alert_icon)
            content_layout.addWidget(self.weather_alert_text)

            self.weather_alert_timer = None
            self.weather_alert_opacity = QGraphicsOpacityEffect(self)
            self.weather_alert_opacity.setOpacity(1.0)
            self.weather_alert_text.setGraphicsEffect(self.weather_alert_opacity)
            self.weather_alert_animation = QPropertyAnimation(self.weather_alert_opacity, b"opacity")
            self.weather_alert_animation.setDuration(700)
            self.weather_alert_animation.setEasingCurve(QEasingCurve.OutCubic)
            self.alert_icon_opacity = QGraphicsOpacityEffect(self)
            self.alert_icon_opacity.setOpacity(1.0)
            self.alert_icon.setGraphicsEffect(self.alert_icon_opacity)
            self.alert_icon_animation = QPropertyAnimation(self.alert_icon_opacity, b"opacity")
            self.alert_icon_animation.setDuration(700)
            self.alert_icon_animation.setEasingCurve(QEasingCurve.OutCubic)

            self.showing_temperature = True  # 跟踪状态(预警/气温)

            self.weather_timer = QTimer(self)
            self.weather_timer.setInterval(30 * 60 * 1000)  # 30分钟更新一次
            self.weather_timer.timeout.connect(self.get_weather_data)
            self.weather_timer.start()
            self.get_weather_data()
            update_timer.add_callback(self.detect_weather_code_changed)

        if hasattr(self, 'img'):  # 自定义图片主题兼容
            img = self.findChild(QLabel, 'img')
            if platform.system() == 'Windows' and platform.release() != '7':
                opacity = QGraphicsOpacityEffect(self)
                opacity.setOpacity(0.65)
                img.setGraphicsEffect(opacity)

        self.resize(self.w, self.height())

        # 设置窗口位置
        if first_start:
            self.animate_window(self.position)
            if platform.system() == 'Windows' and platform.release() != '7':
                self.setWindowOpacity(int(config_center.read_conf('General', 'opacity')) / 100)
            else:
                self.setWindowOpacity(1.0)
        else:
            self.move(self.position[0], self.position[1])
            self.resize(self.w, self.height())
            if platform.system() == 'Windows' and platform.release() != '7':
                self.setWindowOpacity(0)
                self.animate_show_opacity()
            else:
                self.setWindowOpacity(1.0)
                self.show()

        self.update_data('')

    @staticmethod
    def _onThemeChangedFinished():
        print('theme_changed')

    def update_widget_for_plugin(self, context=None):
        if context is None:
            context = ['title', 'desc']
        try:
            title = self.findChild(QLabel, 'title')
            desc = self.findChild(QLabel, 'content')
            if title is not None:
                title.setText(context[0])
            if desc is not None:
                desc.setText(context[1])
        except Exception as e:
            logger.error(f"更新插件小组件时出错：{e}")

    def init_ui(self, path):
        if conf.load_theme_config(theme)['support_dark_mode']:
            if os.path.exists(f'{base_directory}/ui/{theme}/{path}'):
                if isDarkTheme():
                    uic.loadUi(f'{base_directory}/ui/{theme}/dark/{path}', self)
                else:
                    uic.loadUi(f'{base_directory}/ui/{theme}/{path}', self)
            else:
                if isDarkTheme():
                    uic.loadUi(f'{base_directory}/ui/{theme}/dark/widget-base.ui', self)
                else:
                    uic.loadUi(f'{base_directory}/ui/{theme}/widget-base.ui', self)
        else:
            if os.path.exists(f'{base_directory}/ui/{theme}/{path}'):
                uic.loadUi(f'{base_directory}/ui/{theme}/{path}', self)
            else:
                uic.loadUi(f'{base_directory}/ui/{theme}/widget-base.ui', self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if config_center.read_conf('General', 'hide') == '2' or (not int(config_center.read_conf('General', 'enable_click'))):
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        if config_center.read_conf('General', 'pin_on_top') == '1':  # 置顶
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.WindowDoesNotAcceptFocus | Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
            # 修改为使用定时器确保持续置顶
            if os.name == 'nt':
                if not self._is_topmost_callback_added:
                    try:
                        # 确保 utils.update_timer 存在且有效
                        if hasattr(utils, 'update_timer') and utils.update_timer:
                            utils.update_timer.add_callback(self._ensure_topmost)
                            self._is_topmost_callback_added = True
                            self._ensure_topmost() # 立即执行一次确保初始置顶
                            # logger.debug("已添加置顶定时回调。")
                        else:
                            logger.warning("utils.update_timer 不可用，无法添加置顶回调。")
                    except Exception as e:
                        logger.error(f"添加置顶回调时出错: {e}")

        elif config_center.read_conf('General', 'pin_on_top') == '2':  # 置底
            # 避免使用WindowStaysOnBottomHint,防止争夺底层
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowDoesNotAcceptFocus
            )
            if os.name == 'nt':
                def set_window_pos():
                    hwnd = self.winId().__int__()
                    # 稍高于最底层的值
                    ctypes.windll.user32.SetWindowPos(hwnd, 2, 0, 0, 0, 0, 0x0214)
                QTimer.singleShot(100, set_window_pos)
            else:
                QTimer.singleShot(100, self.lower)
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
            )

        if sys.platform == 'darwin':
            self.setWindowFlag(Qt.WindowType.Widget, True)
        else:
            self.setWindowFlag(Qt.WindowType.Tool, True)

    def _ensure_topmost(self):
        # 突然忘记写移除了,不写了,应该没事(
        if active_windows:
            return
        if os.name == 'nt':
            try:
                hwnd = self.winId().__int__()
                if ctypes.windll.user32.IsWindow(hwnd):
                    HWND_TOPMOST = -1
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    SWP_SHOWWINDOW = 0x0040
                    SWP_NOACTIVATE = 0x0010
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOSIZE | SWP_SHOWWINDOW)
                    self.raise_()
                else:
                    if self._is_topmost_callback_added:
                        try:
                            utils.update_timer.remove_callback(self._ensure_topmost)
                        except ValueError:
                            pass # 可能已经被移除了
                        self._is_topmost_callback_added = False
                        logger.debug(f"窗口句柄 {hwnd} 无效，已自动移除置顶回调。")
            except RuntimeError as e:
                 if 'Internal C++ object' in str(e) and 'already deleted' in str(e):
                     logger.debug(f"尝试访问已删除的 DesktopWidget 时出错，移除回调: {e}")
                     if self._is_topmost_callback_added:
                         try:
                            utils.update_timer.remove_callback(self._ensure_topmost)
                         except ValueError:
                             pass # 可能已经被移除了
                         self._is_topmost_callback_added = False
                 else:
                     logger.error(f"检查或设置窗口置顶时发生运行时错误: {e}")
            except Exception as e:
                logger.error(f"检查或设置窗口置顶时出错: {e}")
                if self._is_topmost_callback_added:
                    try:
                        utils.update_timer.remove_callback(self._ensure_topmost)
                    except ValueError:
                        pass
                    self._is_topmost_callback_added = False
                    logger.debug(f"因错误 {e} 移除置顶回调。")

    def closeEvent(self, event):
        if self._is_topmost_callback_added:
            try:
                utils.update_timer.remove_callback(self._ensure_topmost)
                self._is_topmost_callback_added = False
                # logger.debug("窗口关闭，已移除置顶回调。")
            except ValueError:
                logger.debug("尝试移除不存在的置顶回调。")
            except Exception as e:
                logger.error(f"关闭窗口时移除置顶回调出错: {e}")
        super().closeEvent(event)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 添加阴影效果
        if conf.load_theme_config(theme)['shadow']:  # 修改阴影问题
            shadow_effect = QGraphicsDropShadowEffect(self)
            shadow_effect.setBlurRadius(28)
            shadow_effect.setXOffset(0)
            shadow_effect.setYOffset(6)
            shadow_effect.setColor(QColor(0, 0, 0, 75))

            self.backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = f'{base_directory}/font/HarmonyOS_Sans_SC_Bold.ttf'
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(f"""
                QLabel, QPushButton{{
                    font-family: "{font_family}";
                    }}
                """)

    def animate_expand(self, target_geometry):
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(400)
        self.animation.setStartValue(QRect(target_geometry.x(), -self.height(),
                                          self.width(), self.height()))
        self.animation.setEndValue(target_geometry)
        self.animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self.raise_()
        self.show()

    def init_tray_menu(self):
        if not first_start:
            return

        utils.tray_icon = utils.TrayIcon(self)
        utils.tray_icon.setToolTip(f"Class Widgets - {config_center.schedule_name[:-5]}")
        self.tray_menu = SystemTrayMenu(title='Class Widgets', parent=self)
        self.tray_menu.addActions([
            Action(fIcon.HIDE, '完全隐藏/显示小组件', triggered=lambda: self.hide_show_widgets()),
            Action(fIcon.BACK_TO_WINDOW, '最小化为浮窗', triggered=lambda: self.minimize_to_floating()),
        ])
        self.tray_menu.addSeparator()
        self.tray_menu.addActions([
            Action(fIcon.SHOPPING_CART, '插件广场', triggered=open_plaza),
            Action(fIcon.DEVELOPER_TOOLS, '额外选项', triggered=self.open_extra_menu),
            Action(fIcon.SETTING, '设置', triggered=open_settings)
        ])
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(Action(fIcon.SYNC, '重新启动', triggered=restart))
        self.tray_menu.addAction(Action(fIcon.CLOSE, '退出', triggered=stop))
        utils.tray_icon.setContextMenu(self.tray_menu)

        utils.tray_icon.activated.connect(self.on_tray_icon_clicked)
        utils.tray_icon.show()

    @staticmethod
    def on_tray_icon_clicked(reason):  # 点击托盘图标隐藏
        if config_center.read_conf('General', 'hide') == '0':
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                if mgr.state:
                    mgr.decide_to_hide()
                else:
                    mgr.show_windows()
        elif config_center.read_conf('General', 'hide') == '3':
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                if mgr.state:
                    mgr.decide_to_hide()
                    mgr.hide_status = (current_state, 1)
                else:
                    mgr.show_windows()
                    mgr.hide_status = (current_state, 0)



    def rightReleaseEvent(self, event):  # 右键事件
        event.ignore()
        if event.button() == Qt.MouseButton.RightButton:
            self.open_extra_menu()

    def update_data(self, path=''):
        global current_time, current_week, start_y, time_offset, today

        today = dt.date.today()
        current_time = dt.datetime.now().strftime('%H:%M:%S')
        time_offset = conf.get_time_offset()

        get_start_time()
        get_current_lessons()
        get_current_lesson_name()
        get_excluded_lessons()
        get_next_lessons()
        hide_status = get_hide_status()

        if (hide_mode:=config_center.read_conf('General', 'hide')) in ['1','2']:  # 上课自动隐藏
            if hide_status:
                mgr.decide_to_hide()
            else:
                mgr.show_windows()
        elif hide_mode == '3': # 灵活隐藏
            if mgr.hide_status is None:
                mgr.hide_status = (-1, hide_status)
            elif mgr.hide_status[0] != current_state:
                mgr.hide_status = (-1, hide_status)
            if mgr.hide_status[1]:
                mgr.decide_to_hide()
            else:
                mgr.show_windows()



        if conf.is_temp_week():  # 调休日
            current_week = config_center.read_conf('Temp', 'set_week')
        else:
            current_week = dt.datetime.now().weekday()

        cd_list = get_countdown()

        if path == 'widget-time.ui':  # 日期显示
            self.date_text.setText(f'{today.year} 年 {today.month} 月')
            self.day_text.setText(f'{today.day} 日 {list_.week[today.weekday()]}')

        if path == 'widget-current-activity.ui':  # 当前活动
            self.current_subject.setText(f'  {current_lesson_name}')

            if current_state != 2:  # 非休息段
                render = QSvgRenderer(list_.get_subject_icon(current_lesson_name))
                self.blur_effect_label.setStyleSheet(
                    f'background-color: rgba{list_.subject_color(current_lesson_name)}, 200);'
                )
            else:  # 休息段
                render = QSvgRenderer(list_.get_subject_icon('课间'))
                self.blur_effect_label.setStyleSheet(
                    f'background-color: rgba{list_.subject_color("课间")}, 200);'
                )
            pixmap = QPixmap(render.defaultSize())
            pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(pixmap)
            render.render(painter)
            if (isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']
                    or isDarkTheme() and conf.load_theme_config(theme)['default_theme'] == 'dark'):  # 在暗色模式显示亮色图标
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor("#FFFFFF"))
            painter.end()

            self.current_subject.setIcon(QIcon(pixmap))
            self.blur_effect.setBlurRadius(25)  # 模糊半径
            self.blur_effect_label.setGraphicsEffect(self.blur_effect)

        elif path == 'widget-next-activity.ui':  # 接下来的活动
            self.nl_text.setText(get_next_lessons_text())

        if path == 'widget-countdown.ui':  # 活动倒计时
            if cd_list:
                if config_center.read_conf('General', 'blur_countdown') == '1':  # 模糊倒计时
                    if cd_list[1] == '00:00':
                        self.activity_countdown.setText(f"< - 分钟")
                    else:
                        self.activity_countdown.setText(f"< {int(cd_list[1].split(':')[0]) + 1} 分钟")
                else:
                    self.activity_countdown.setText(cd_list[1])
                self.ac_title.setText(cd_list[0])
                self.countdown_progress_bar.setValue(cd_list[2])

        if path == 'widget-countdown-day.ui':  # 自定义倒计时
            conf.update_countdown(self.cnt)
            self.custom_title.setText(f'距离 {conf.get_cd_text_custom()} 还有')
            self.custom_countdown.setText(conf.get_custom_countdown())
        self.update()

    def get_weather_data(self):
        logger.info('获取天气数据')
        if not hasattr(self, 'weather_thread') or not self.weather_thread.isRunning():
            self.weather_thread = weatherReportThread()
            self.weather_thread.weather_signal.connect(self.update_weather_data)
            self.weather_thread.start()

    def detect_weather_code_changed(self):
        current_code = config_center.read_conf('Weather')
        if current_code != self.last_code:
            self.last_code = current_code
            self.get_weather_data()

    def toggle_weather_alert(self):
        if self.showing_temperature:
            # 切换预警
            self.weather_alert_animation.setStartValue(0.0)
            self.weather_alert_animation.setEndValue(1.0)
            self.alert_icon_animation.setStartValue(0.0)
            self.alert_icon_animation.setEndValue(1.0)
            # 渐隐
            self.weather_opacity = QGraphicsOpacityEffect(self.weather_icon)
            self.temperature_opacity = QGraphicsOpacityEffect(self.temperature)
            self.weather_icon.setGraphicsEffect(self.weather_opacity)
            self.temperature.setGraphicsEffect(self.temperature_opacity)
            weather_fade_out = QPropertyAnimation(self.weather_opacity, b'opacity')
            temp_fade_out = QPropertyAnimation(self.temperature_opacity, b'opacity')
            weather_fade_out.setDuration(700)
            temp_fade_out.setDuration(700)
            weather_fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
            temp_fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
            weather_fade_out.setStartValue(1.0)
            weather_fade_out.setEndValue(0.0)
            temp_fade_out.setStartValue(1.0)
            temp_fade_out.setEndValue(0.0)
            # 重置不透明度
            self.fade_out_group = QParallelAnimationGroup(self)
            self.fade_out_group.addAnimation(weather_fade_out)
            self.fade_out_group.addAnimation(temp_fade_out)
            if not hasattr(self, 'weather_alert_opacity') or not self.weather_alert_opacity:
                self.weather_alert_opacity = QGraphicsOpacityEffect(self.weather_alert_text)
                self.weather_alert_text.setGraphicsEffect(self.weather_alert_opacity)
            if not hasattr(self, 'alert_icon_opacity') or not self.alert_icon_opacity:
                self.alert_icon_opacity = QGraphicsOpacityEffect(self.alert_icon)
                self.alert_icon.setGraphicsEffect(self.alert_icon_opacity)

            alert_text_fade_in = QPropertyAnimation(self.weather_alert_opacity, b'opacity')
            alert_icon_fade_in = QPropertyAnimation(self.alert_icon_opacity, b'opacity')
            alert_text_fade_in.setDuration(700)
            alert_icon_fade_in.setDuration(700)
            alert_text_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            alert_icon_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            alert_text_fade_in.setStartValue(0.0)
            alert_text_fade_in.setEndValue(1.0)
            alert_icon_fade_in.setStartValue(0.0)
            alert_icon_fade_in.setEndValue(1.0)

            self.fade_in_group = QParallelAnimationGroup(self)
            self.fade_in_group.addAnimation(alert_text_fade_in)
            self.fade_in_group.addAnimation(alert_icon_fade_in)
            try: self.fade_out_group.finished.disconnect()
            except TypeError: pass

            def _start_alert_fade_in():
                if hasattr(self, 'weather_alert_text') and self.weather_alert_text.text():
                    self.weather_icon.hide()
                    self.temperature.hide()
                    self.weather_alert_opacity.setOpacity(0.0)
                    self.weather_alert_text.show()
                    if hasattr(self, 'alert_icon') and isinstance(self.alert_icon, IconWidget) and self.alert_icon.icon is not None and not self.alert_icon.icon.isNull():
                        self.alert_icon_opacity.setOpacity(0.0)
                        self.alert_icon.show()
                        self.fade_in_group.start()
                    else:
                        self.alert_icon.hide() # 隐藏图标
                        self.weather_alert_text.move(self.weather_icon.pos())
                        self.weather_alert_text.setGraphicsEffect(self.weather_alert_opacity)
                        alert_text_fade_in = QPropertyAnimation(self.weather_alert_opacity, b'opacity')
                        alert_text_fade_in.setDuration(700)
                        alert_text_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
                        alert_text_fade_in.setStartValue(0.0)
                        alert_text_fade_in.setEndValue(1.0)
                        alert_text_fade_in.start()

                    self.weather_info_timer.start(3000)
                else:
                    # 没有预警文本显示天气图标和温度
                    self.weather_icon.show()
                    self.temperature.show()
                    if hasattr(self, 'weather_opacity'): self.weather_opacity.setOpacity(1.0)
                    if hasattr(self, 'temperature_opacity'): self.temperature_opacity.setOpacity(1.0)
                    self.showing_temperature = True
                    self.alert_icon.hide()


            self.fade_out_group.finished.connect(_start_alert_fade_in)

            self.fade_out_group.start()
        else:
            # 切换到气温
            self.weather_alert_animation.setStartValue(1.0)
            self.weather_alert_animation.setEndValue(0.0)
            self.alert_icon_animation.setStartValue(1.0)
            self.alert_icon_animation.setEndValue(0.0)
            if not hasattr(self, 'weather_alert_opacity') or not self.weather_alert_opacity:
                self.weather_alert_opacity = QGraphicsOpacityEffect(self.weather_alert_text)
                self.weather_alert_text.setGraphicsEffect(self.weather_alert_opacity)
            if not hasattr(self, 'alert_icon_opacity') or not self.alert_icon_opacity:
                self.alert_icon_opacity = QGraphicsOpacityEffect(self.alert_icon)
                self.alert_icon.setGraphicsEffect(self.alert_icon_opacity)

            alert_text_fade_out = QPropertyAnimation(self.weather_alert_opacity, b'opacity')
            alert_icon_fade_out = QPropertyAnimation(self.alert_icon_opacity, b'opacity')
            alert_text_fade_out.setDuration(500)
            alert_icon_fade_out.setDuration(500)
            alert_text_fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
            alert_icon_fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
            alert_text_fade_out.setStartValue(1.0)
            alert_text_fade_out.setEndValue(0.0)
            alert_icon_fade_out.setStartValue(1.0)
            alert_icon_fade_out.setEndValue(0.0)

            self.fade_out_group = QParallelAnimationGroup(self)
            self.fade_out_group.addAnimation(alert_text_fade_out)
            self.fade_out_group.addAnimation(alert_icon_fade_out)
            if not hasattr(self, 'weather_opacity') or not self.weather_opacity:
                self.weather_opacity = QGraphicsOpacityEffect(self.weather_icon)
                self.weather_icon.setGraphicsEffect(self.weather_opacity)
            if not hasattr(self, 'temperature_opacity') or not self.temperature_opacity:
                self.temperature_opacity = QGraphicsOpacityEffect(self.temperature)
                self.temperature.setGraphicsEffect(self.temperature_opacity)

            weather_fade_in = QPropertyAnimation(self.weather_opacity, b'opacity')
            temp_fade_in = QPropertyAnimation(self.temperature_opacity, b'opacity')
            weather_fade_in.setDuration(500)
            temp_fade_in.setDuration(500)
            weather_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            temp_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            weather_fade_in.setStartValue(0.0)
            weather_fade_in.setEndValue(1.0)
            temp_fade_in.setStartValue(0.0)
            temp_fade_in.setEndValue(1.0)

            self.fade_in_group = QParallelAnimationGroup(self)
            self.fade_in_group.addAnimation(weather_fade_in)
            self.fade_in_group.addAnimation(temp_fade_in)
            try: self.fade_out_group.finished.disconnect()
            except TypeError: pass

            def _start_temperature_fade_in():
                self.weather_alert_text.hide()
                self.alert_icon.hide()
                self.weather_opacity.setOpacity(0.0)
                self.temperature_opacity.setOpacity(0.0)
                self.weather_icon.show()
                self.temperature.show()
                self.fade_in_group.start()
            # 连接淡出组完成信号
            self.fade_out_group.finished.connect(_start_temperature_fade_in)
            self.fade_out_group.start()

        self.showing_temperature = not self.showing_temperature

    def detect_theme_changed(self):
        theme_ = config_center.read_conf('General', 'theme')
        color_mode = config_center.read_conf('General', 'color_mode')
        widgets = list_.get_widget_config()
        if theme_ != self.last_theme or color_mode != self.last_color_mode or widgets != self.last_widgets:
            self.last_theme = theme_
            self.last_color_mode = color_mode
            self.last_widgets = widgets
            logger.info(f'切换主题：{theme_}，颜色模式{color_mode}')
            mgr.clear_widgets()

    def update_weather_data(self, weather_data):  # 更新天气数据(已兼容多api)
        global weather_name, temperature, weather_data_temp
        if type(weather_data) is dict and hasattr(self, 'weather_icon') and 'error' not in weather_data:
            logger.success('已获取天气数据')
            alert_data = weather_data.get('alert')
            weather_data = weather_data.get('now')
            weather_data_temp = weather_data

            weather_name = db.get_weather_by_code(db.get_weather_data('icon', weather_data))
            current_city = self.findChild(QLabel, 'current_city')
            try:  # 天气组件
                self.weather_icon.setPixmap(
                    QPixmap(db.get_weather_icon_by_code(db.get_weather_data('icon', weather_data)))
                )
                self.alert_icon.hide()
                if db.is_supported_alert():
                    alert_type = db.get_weather_data('alert', alert_data if alert_data else weather_data)
                    if alert_type:
                        self.alert_icon.setIcon(
                            db.get_alert_image(alert_type)
                        )
                        self.alert_icon.hide()
                        try:
                            alert_title = db.get_weather_data('alert_title', alert_data if alert_data else weather_data)
                            if alert_title:
                                alert_type_match = re.search(r'发布(\w+)(蓝|黄|橙|红)色预警', alert_title)
                                if alert_type_match:
                                    alert_type = alert_type_match.group(1)  # 类型
                                    logger.success(f'天气预警: {alert_title} --> {alert_type}预警')
                                    alert_text = alert_type + '预警'
                                else:
                                    logger.success(f'天气预警: {alert_title} --> {alert_title}')
                                    alert_text = alert_title
                                self.weather_alert_text.setFixedWidth(80)
                                self.weather_alert_text.setFixedHeight(40)
                                # 调整字体大小
                                font = self.weather_alert_text.font()
                                if len(alert_text) <= 4:
                                    font.setPointSize(14)
                                elif len(alert_text) <= 6:
                                    font.setPointSize(12)
                                else:
                                    font.setPointSize(10)

                                self.weather_alert_text.setFont(font)
                                self.weather_alert_text.setText(alert_text)
                                self.weather_alert_text.setAlignment(Qt.AlignCenter)
                                if not self.weather_alert_timer:
                                    self.weather_alert_timer = QTimer(self)
                                    self.weather_alert_timer.timeout.connect(self.toggle_weather_alert)
                                    self.weather_alert_timer.start(6000)
                                    self.weather_info_timer = QTimer(self)
                                    self.weather_info_timer.timeout.connect(self.toggle_weather_alert)
                                    self.weather_info_timer.setSingleShot(True)
                        except Exception as e:
                            logger.warning(f'获取天气预警标题失败：{e}')
                            self.weather_alert_text.setText('暂无预警信息')

                self.temperature.setText(f"{db.get_weather_data('temp', weather_data)}")
                current_city.setText(f"{db.search_by_num(config_center.read_conf('Weather', 'city'))} · "
                                     f"{weather_name}")
                update_stylesheet = re.sub(
                    r'border-image: url\((.*?)\);',
                    f"border-image: url({db.get_weather_stylesheet(db.get_weather_data('icon', weather_data))});",
                    self.backgnd.styleSheet()
                )
                self.backgnd.setStyleSheet(update_stylesheet)
            except Exception as e:
                logger.error(f'天气组件出错：{e}')
        else:
            logger.error(f'获取天气数据出错：{weather_data}')
            try:
                if hasattr(self, 'weather_icon'):
                    self.weather_icon.setPixmap(QPixmap(f'{base_directory}/img/weather/99.svg'))
                    self.alert_icon.hide()
                    self.weather_alert_text.hide()
                    self.temperature.setText('--°')
                    current_city = self.findChild(QLabel, 'current_city')
                    if current_city:
                        current_city.setText(f"{db.search_by_num(config_center.read_conf('Weather', 'city'))} · 未知")
                    if hasattr(self, 'backgnd'):
                        update_stylesheet = re.sub(
                            r'border-image: url\((.*?)\);',
                            f"border-image: url({db.get_weather_stylesheet('99')});",
                            self.backgnd.styleSheet()
                        )
                        self.backgnd.setStyleSheet(update_stylesheet)
            except Exception as e:
                logger.error(f'天气图标设置失败：{e}')

    def open_extra_menu(self):
        global ex_menu
        if ex_menu is None or not ex_menu.isVisible():
            ex_menu = ExtraMenu()
            ex_menu.show()
            ex_menu.destroyed.connect(self.cleanup_extra_menu)
            logger.info('打开“额外选项”')
        else:
            ex_menu.raise_()
            ex_menu.activateWindow()

    @staticmethod
    def cleanup_extra_menu():
        global ex_menu
        ex_menu = None

    @staticmethod
    def hide_show_widgets():  # 隐藏/显示主界面（全部隐藏）
        hide_mode = config_center.read_conf('General', 'hide')
        if hide_mode == '1' or hide_mode == '2':
            hide_mode_text = "上课时自动隐藏" if hide_mode == '1' else "窗口最大化时隐藏"
            w = Dialog(
                "暂时无法变更“状态”",
                f"您正在使用 {hide_mode_text} 模式，无法变更隐藏状态\n"
                "若变更状态，将修改隐藏模式“灵活隐藏” (您稍后可以在“设置”中更改此选项)\n"
                "您确定要隐藏组件吗?",
                None
            )
            w.yesButton.setText("确定")
            w.yesButton.clicked.connect(lambda: config_center.write_conf('General', 'hide', '3'))
            w.cancelButton.setText("取消")
            w.buttonLayout.insertStretch(1)
            w.setFixedWidth(550)
            if w.exec():
                if mgr.state:
                    mgr.full_hide_windows()
                else:
                    mgr.show_windows()
        else:
            if mgr.state:
                mgr.full_hide_windows()
            else:
                mgr.show_windows()

    @staticmethod
    def minimize_to_floating():  # 最小化到浮窗
        hide_mode = config_center.read_conf('General', 'hide')
        if hide_mode == '1' or hide_mode == '2':
            hide_mode_text = "上课时自动隐藏" if hide_mode == '1' else "窗口最大化时隐藏"
            w = Dialog(
                "暂时无法变更“状态”",
                f"您正在使用 {hide_mode_text} 模式，无法变更隐藏状态\n"
                "若变更状态，将修改隐藏模式“灵活隐藏” (您可以在“设置”中更改此选项)\n"
                "您确定要隐藏组件吗?",
                None
            )
            w.yesButton.setText("确定")
            w.yesButton.clicked.connect(lambda: config_center.write_conf('General', 'hide', '3'))
            w.cancelButton.setText("取消")
            w.buttonLayout.insertStretch(1)
            w.setFixedWidth(550)
            if w.exec():
                if mgr.state:
                    fw.show()
                    mgr.full_hide_windows()
                else:
                    mgr.show_windows()
        else:
            if mgr.state:
                fw.show()
                mgr.full_hide_windows()
            else:
                mgr.show_windows()

    def clear_animation(self):  # 清除动画
        self.animation = None

    def animate_window(self, target_pos):  # **初次**启动动画
        # 创建位置动画
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(300)  # 持续时间
        if os.name == 'nt':
            self.animation.setStartValue(QRect(target_pos[0], -self.height(), self.w, self.h))
        else:
            self.animation.setStartValue(QRect(target_pos[0], 0, self.w, self.h))
        self.animation.setEndValue(QRect(target_pos[0], target_pos[1], self.w, self.h))
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_hide(self, full=False):  # 隐藏窗口
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(625)  # 持续时间
        height = self.height()
        self.setFixedHeight(height)  # 防止连续打断窗口高度变小

        if full and os.name == 'nt':
            '''全隐藏 windows'''
            self.animation.setEndValue(QRect(self.x(), -height, self.width(), self.height()))
        elif os.name == 'nt':
            '''半隐藏 windows'''
            self.animation.setEndValue(QRect(self.x(), -height + 40, self.width(), self.height()))
        else:
            '''其他系统'''
            self.animation.setEndValue(QRect(self.x(), 0, self.width(), self.height()))
            self.animation.finished.connect(lambda: self.hide())

        self.animation.setEasingCurve(QEasingCurve.Type.OutExpo)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_hide_opacity(self):  # 隐藏窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)  # 持续时间
        self.animation.setStartValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.close)

    def animate_show_opacity(self):  # 显示窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(350)  # 持续时间
        self.animation.setStartValue(0)
        self.animation.setEndValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_show(self):  # 显示窗口
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(525)  # 持续时间
        # 获取当前窗口的宽度和高度，确保动画过程中保持一致
        self.animation.setEndValue(
        QRect(self.x(), int(config_center.read_conf('General', 'margin')), self.width(), self.height()))
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.finished.connect(self.clear_animation)

        if os.name != 'nt':
            self.show()

        self.animation.start()

    def widget_transition(self, pos_x, width, height, opacity=1):  # 窗口形变
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(525)  # 持续时间
        self.animation.setStartValue(QRect(self.x(), self.y(), self.width(), self.height()))
        self.animation.setEndValue(QRect(pos_x, self.y(), width, height))
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)  # 设置动画效果
        self.animation.start()

        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(525)  # 持续时间
        self.opacity_animation.setStartValue(self.windowOpacity())
        self.opacity_animation.setEndValue(opacity)
        self.opacity_animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.opacity_animation.start()

        self.animation.finished.connect(self.clear_animation)

    # 点击自动隐藏
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            return  # 右键不执行
        if config_center.read_conf('General', 'pin_on_top') == '2':  # 置底
            return  # 置底不执行
        if config_center.read_conf('General', 'hide') == '0':  # 置顶
            if mgr.state:
                mgr.decide_to_hide()
            else:
                mgr.show_windows()
        elif config_center.read_conf('General', 'hide') == '3':  # 隐藏
            if mgr.state:
                mgr.decide_to_hide()
                mgr.hide_status = (current_state, 1)
            else:
                mgr.show_windows()
                mgr.hide_status = (current_state, 0)
        else:
            event.ignore()

    def stop(self):
        if mgr:
            mgr.cleanup_resources()
        for widget in self.widgets:
            widget.stop()
        if self.animation:
            self.animation.stop()
        if self.opacity_animation:
            self.opacity_animation.stop()
        self.close()


def check_windows_maximize():  # 检查窗口是否最大化
    if os.name != 'nt' or not pygetwindow:
        # logger.debug("非Windows NT系统或pygetwindow未加载, 无法检查最大化.")
        return False
    # 需要排除的特定窗口标题 (全字匹配, 大小写不敏感)
    excluded_titles_exact_lower = {
        'residentsidebar',  # 希沃侧边栏
        'program manager',  # Windows桌面
        'desktop',          # Windows桌面 (备用)
        'snippingtool',     # 系统截图工具
        # '' 空标题不再默认排除
    }
    # 需要排除的标题中包含的关键词 (大小写不敏感)
    excluded_keywords_in_title_lower = {
        'overlay',
        'snipping',
        'sidebar',
        'flyout' # qfluentwidgets的浮出控件
    }
    # 需要排除的进程名 (全字或部分匹配, 大小写不敏感)
    excluded_process_names_lower = {
        'shellexperiencehost.exe',
        'searchui.exe',
        'startmenuexperiencehost.exe',
        'applicationframehost.exe',
        'systemsettings.exe',
        'taskmgr.exe'
    }
    # 用户自定义的忽略进程列表 (全字匹配, 大小写不敏感)
    # 例：easinote.exe 每行一个，用逗号分隔
    ignored_process_names_for_maximize_lower = {
        'easinote.exe'
    }

    current_pid = os.getpid()

    try:
        all_windows = pygetwindow.getAllWindows()
    except Exception as e:
        logger.warning(f"获取窗口列表时发生错误 (pygetwindow): {str(e)}")
        # logger.debug("获取窗口列表失败.")
        return False

    for window in all_windows:
        try:
            if not window._hWnd:
                # logger.debug(f"窗口 '{getattr(window, 'title', 'N/A')}' 无效句柄, 跳过.")
                continue
            if not window.visible:
                # logger.debug(f"窗口 '{window.title}' 不可见, 跳过.")
                continue
            if not window.isMaximized:
                # logger.debug(f"窗口 '{window.title}' 未最大化, 跳过.")
                continue
            # logger.debug(f"发现可见且已最大化的窗口: '{window.title}' (句柄: {window._hWnd})")
            try:
                hwnd_int = window._hWnd
                pid_val = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd_int, ctypes.byref(pid_val))
                win_pid = pid_val.value
                if win_pid == 0:
                    continue # 无效PID
                process_name = psutil.Process(win_pid).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, ValueError, OSError) :
                # logger.debug(f"无法获取窗口 '{title}' 的进程信息,跳过.")
                continue

            if win_pid == current_pid:
                # logger.debug(f"窗口 '{title}' (PID: {win_pid}, 进程: {process_name}) 是自身进程, 排除.")
                continue

            title = window.title.strip()
            title_lower = title.lower()

            if process_name in ignored_process_names_for_maximize_lower:
                # logger.debug(f"窗口 '{title}' (进程: {process_name}) 在忽略列表, 排除.")
                continue

            if process_name in excluded_process_names_lower:
                # logger.debug(f"窗口 '{title}' (进程: {process_name}) 在排除的进程名列表, 排除.")
                continue

            if title_lower in excluded_titles_exact_lower:
                # logger.debug(f"窗口标题 '{title_lower}' 在排除列表, 排除.")
                continue

            if any(keyword in title_lower for keyword in excluded_keywords_in_title_lower):
                # logger.debug(f"窗口标题 '{title_lower}' 包含排除的关键词, 排除.")
                continue

            # 如果进程是 explorer.exe,但不是“资源管理器”则认为是特殊explorer(应该是桌面)
            if process_name == 'explorer.exe':
                if title_lower in excluded_titles_exact_lower or \
                   any(keyword in title_lower for keyword in excluded_keywords_in_title_lower):
                    # logger.debug(f"explorer.exe 窗口 '{title_lower}' 命中标题排除规则, 排除.")
                    continue
            # logger.debug(f"找到有效最大化窗口: '{title}' (PID: {win_pid}, 进程: {process_name}). 返回 True.")
            return True

        except Exception as e:
            if window and hasattr(window, 'title'):
                logger.debug(f"处理窗口 '{getattr(window, 'title', 'N/A')}' 时发生错误: {str(e)}")
            else:
                logger.debug(f"处理一个未知窗口时发生错误: {str(e)}")
            continue
    return False



def init_config():  # 重设配置文件
    config_center.write_conf('Temp', 'set_week', '')
    config_center.write_conf('Temp', 'set_schedule', '')
    if config_center.read_conf('Temp', 'temp_schedule') != '':  # 修复换课重置
        copy(f'{base_directory}/config/schedule/backup.json',
             f'{base_directory}/config/schedule/{config_center.schedule_name}')
        config_center.write_conf('Temp', 'temp_schedule', '')
        schedule_center.update_schedule()


def init():
    global theme, radius, mgr, screen_width, first_start, fw, was_floating_mode
    update_timer.remove_all_callbacks()

    theme = config_center.read_conf('General', 'theme')  # 主题
    if not os.path.exists(f'{base_directory}/ui/{theme}/theme.json'):
        logger.warning(f'主题 {theme} 不存在，使用默认主题')
        theme = 'default'
    logger.info(f'应用主题：{theme}')

    mgr = WidgetsManager()
    fw = FloatingWidget()

    # 获取屏幕横向分辨率
    screen_geometry = app.primaryScreen().availableGeometry()
    screen_width = screen_geometry.width()

    widgets = list_.get_widget_config()

    for widget in widgets:  # 检查组件
        if widget not in list_.widget_name:
            widgets.remove(widget)  # 移除不存在的组件(确保移除插件后不会出错)

    mgr.init_widgets()
    if not first_start and was_floating_mode:
        if fw:
            fw.show()
            mgr.full_hide_windows()

    update_timer.add_callback(mgr.update_widgets)
    update_timer.start()

    version = config_center.read_conf("Version", "version")
    build_uuid = config_center.read_conf("Version", "build_runid") or "(Debug)"
    build_type = config_center.read_conf("Version", "build_type")
    if "__BUILD_RUNID__" in build_uuid or "__BUILD_TYPE__" in build_type:
        logger.success(f'Class Widgets 初始化完成。版本: {version} - (Debug)')
    else:
        logger.success(f'Class Widgets 初始化完成。版本: {version} Build UUID: {build_uuid}({build_type})')
    p_loader.run_plugins()  # 运行插件

    first_start = False


def setup_signal_handlers_optimized(app):
    """退出信号处理器"""
    def signal_handler(signum, frame):
        logger.debug(f'收到信号 {signal.Signals(signum).name},退出...')
        # utils.stop 处理退出
        utils.stop(0)

    signal.signal(signal.SIGTERM, signal_handler)  # taskkill
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    if os.name == 'posix':
        signal.signal(signal.SIGQUIT, signal_handler) # 终端退出
        signal.signal(signal.SIGHUP, signal_handler)  # 终端挂起

if __name__ == '__main__':
    if share.attach() and config_center.read_conf('Other', 'multiple_programs') != '1':
        logger.debug('不允许多开实例')
        from qfluentwidgets import Dialog
        app = QApplication.instance() or QApplication(sys.argv)
        dlg = Dialog(
            'Class Widgets 正在运行',
            'Class Widgets 正在运行！请勿打开多个实例，否则将会出现不可预知的问题。'
            '\n(若您需要打开多个实例，请在“设置”->“高级选项”中启用“允许程序多开”)'
        )
        dlg.yesButton.setText('好')
        dlg.cancelButton.hide()
        dlg.buttonLayout.insertStretch(0, 1)
        dlg.setFixedWidth(550)
        dlg.exec()
        sys.exit(0)
    if not share.create(1):
        print(f'无法创建共享内存: {share.errorString()}') # logger 可能还没准备好
        sys.exit(1)

    scale_factor = float(config_center.read_conf('General', 'scale'))
    os.environ['QT_SCALE_FACTOR'] = str(scale_factor)
    logger.info(f"当前缩放系数：{scale_factor * 100}%")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    share.create(1)  # 创建共享内存
    logger.info(
        f"共享内存：{share.isAttached()} 是否允许多开实例：{config_center.read_conf('Other', 'multiple_programs')}")
    try:
        dark_mode_watcher = DarkModeWatcher(parent=app)
        dark_mode_watcher.darkModeChanged.connect(handle_dark_mode_change) # 连接信号
        # 初始主题设置依赖于 darkModeChanged 信号
    except Exception as e:
        logger.error(f"初始化颜色模式监测器时出错: {e}")
        dark_mode_watcher = None

    if scale_factor > 1.8 or scale_factor < 1.0:
        logger.warning("当前缩放系数可能导致显示异常，建议使缩放系数在 100% 到 180% 之间")
        msg_box = Dialog('缩放系数过大',
                         f"当前缩放系数为 {scale_factor * 100}%，可能导致显示异常。\n建议将缩放系数设置为 100% 到 180% 之间。")
        msg_box.yesButton.setText('好')
        msg_box.cancelButton.hide()
        msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()

    # 优化操作系统和版本输出
    system = platform.system()
    if system == 'Darwin':
        system = 'macOS'
    osRelease = platform.release()
    if system == 'Windows':
        osRelease = 'Windows ' + osRelease
    if system == 'macOS':
        osRelease = 'Darwin Kernel Version ' + osRelease
    osVersion = platform.version()
    if system == 'macOS':
        osVersion = 'macOS ' + platform.mac_ver()[0]

    logger.info(f"操作系统：{system}，版本：{osRelease}/{osVersion}")

    # list_pyttsx3_voices()

    if share.attach() and config_center.read_conf('Other', 'multiple_programs') != '1':
        msg_box = Dialog(
            'Class Widgets 正在运行',
            'Class Widgets 正在运行！请勿打开多个实例，否则将会出现不可预知的问题。'
            '\n(若您需要打开多个实例，请在“设置”->“高级选项”中启用“允许程序多开”)'
        )
        msg_box.yesButton.setText('好')
        msg_box.cancelButton.hide()
        msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()
        stop(-1)
    else:
        mgr = WidgetsManager()
        app.aboutToQuit.connect(mgr.cleanup_resources)
        setup_signal_handlers_optimized(app)

        if config_center.read_conf('Other', 'initialstartup') == '1':  # 首次启动
            try:
                conf.add_shortcut('ClassWidgets.exe', f'{base_directory}/img/favicon.ico')
                conf.add_shortcut_to_startmenu(f'{base_directory}/ClassWidgets.exe',
                                               f'{base_directory}/img/favicon.ico')
                config_center.write_conf('Other', 'initialstartup', '')
            except Exception as e:
                logger.error(f'添加快捷方式失败：{e}')
            try:
                list_.create_new_profile('新课表 - 1.json')
            except Exception as e:
                logger.error(f'创建新课表失败：{e}')

        p_mgr = PluginManager()
        p_loader.set_manager(p_mgr)
        p_loader.load_plugins()

        init()
        get_start_time()
        get_current_lessons()
        get_current_lesson_name()
        get_next_lessons()

        # 如果在全屏或最大化模式下启动，首先折叠主组件后显示浮动窗口动画。
        if check_windows_maximize() or check_fullscreen():
            mgr.decide_to_hide()  # 折叠动画,其实这里可用`mgr.full_hide_windows()`但是播放动画似乎更好()

        if current_state == 1:
            setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}")
        else:
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")

        # w = ErrorDialog()
        # w.exec()
        if config_center.read_conf('Version', 'auto_check_update') == '1':
            check_update()

    status = app.exec()

    utils.stop(status)
>>>>>>> REPLACE

[end of main.py]
