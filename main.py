import contextlib
import ctypes
import datetime as dt
import json
import os
import platform
import re
import signal
import subprocess
import sys
import traceback
from functools import lru_cache
from shutil import copy
from typing import Any, Dict, List, Optional, Tuple, Union

import psutil
from loguru import logger
from packaging.version import Version
from PyQt5 import uic
from PyQt5.QtCore import (
    QCoreApplication,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PyQt5.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFocusEvent,
    QFontDatabase,
    QHideEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
    QShowEvent,
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QWidget,
)
from qfluentwidgets import (
    Action,
    CheckBox,
    Dialog,
    Flyout,
    FlyoutAnimationType,
    IconWidget,
    ImageLabel,
    InfoBarIcon,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressRing,
    PushButton,
    SystemTrayMenu,
    Theme,
    isDarkTheme,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import FluentIcon as fIcon

import splash

splash_window = splash.Splash()
splash_window.run()
splash_window.update_status((0, QCoreApplication.translate('main', '加载模块...')))

import conf
import list_
import menu
import tip_toast
import utils
import weather as db
from basic_dirs import CONFIG_HOME, CW_HOME, SCHEDULE_DIR
from conf import load_theme_config
from extra_menu import ExtraMenu, open_settings, settings
from file import config_center, schedule_center
from generate_speech import generate_speech_sync
from i18n_manager import app, global_i18n_manager
from menu import open_plaza
from network_thread import check_update, getCity
from plugin import p_loader
from tip_toast import active_windows
from utils import DarkModeWatcher, TimeManagerFactory, restart, stop, update_timer
from weather import WeatherReportThread as weatherReportThread
from weather import weather_manager

if os.name == 'nt':
    import pygetwindow

today = dt.date.today()

# 存储窗口对象
windows = []
order = []
error_dialog = None

current_lesson_name = '课程表未加载'
current_state = 0  # 0：课间 1：上课 2: 休息段
current_time = dt.datetime.now().strftime('%H:%M:%S')
current_week = dt.datetime.now().weekday()
current_lessons = {}
loaded_data = {}
parts_type = []
notification = tip_toast
excluded_lessons = []
last_notify_time = None
notify_cooldown = 2  # 2秒内仅能触发一次通知(防止触发114514个通知导致爆炸

timeline_data = []
next_lessons = []
parts_start_time = []

temperature = QCoreApplication.translate("main", '未设置')
weather_icon = 0
weather_name = ''
weather_data_temp = None
city = 101010100  # 默认城市
theme = None

first_start = True
error_cooldown = dt.timedelta(seconds=2)  # 冷却时间(s)
ignore_errors = []
last_error_time = dt.datetime.now() - error_cooldown  # 上一次错误

ex_menu = None
dark_mode_watcher = None
was_floating_mode = False  # 浮窗状态


@logger.catch
def global_exceptHook(exc_type: type, exc_value: Exception, exc_tb: any) -> None:
    if config_center.read_conf('Other', 'safe_mode') == '1':
        return
    error_details = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    if error_details in ignore_errors:
        return
    global last_error_time, error_dialog, error_cooldown
    current_time = dt.datetime.now()
    if current_time - last_error_time > error_cooldown:
        last_error_time = current_time
        # 获取异常抛出位置
        tb_last = exc_tb
        while tb_last.tb_next:  # 找到最后一帧
            tb_last = tb_last.tb_next
        frame = tb_last.tb_frame
        file_name = os.path.basename(frame.f_code.co_filename)
        line_no = tb_last.tb_lineno
        func_name = frame.f_code.co_name
        process = psutil.Process()
        memory_info = process.memory_info()
        thread_count = process.num_threads()
        log_msg = f"""发生全局异常:
├─异常类型: {exc_type.__name__} {exc_type}
├─异常信息: {exc_value}
├─发生位置: {file_name}:{line_no} in {func_name}
├─运行状态: 内存使用 {memory_info.rss / 1024 / 1024:.1f}MB 线程数: {thread_count}
└─详细堆栈信息:"""
        tip_msg = f"""运行状态: 内存使用 {memory_info.rss / 1024 / 1024:.1f}MB 线程数: {thread_count}
└─异常类型: {exc_type.__name__} {exc_type}"""
        logger.opt(exception=(exc_type, exc_value, exc_tb), depth=0).error(log_msg)
        logger.complete()
        if not error_dialog:
            w = ErrorDialog(f'{tip_msg}\n{error_details}')
            w.exec()


sys.excepthook = global_exceptHook  # 设置全局异常捕获


def handle_dark_mode_change(is_dark: bool) -> None:
    """处理DarkModeWatcher触发的UI更新"""
    if config_center.read_conf('General', 'color_mode') == '2':
        logger.info(f"系统颜色模式更新: {'深色' if is_dark else '浅色'}")
        current_theme = Theme.DARK if is_dark else Theme.LIGHT
        setTheme(current_theme)
        if mgr:
            mgr.clear_widgets()
        else:
            logger.warning("主题更改时,mgr还未初始化")
        # if current_state == 1:
        #      setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}")
        # else:
        #      setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")


def setTheme_() -> None:  # 设置主题
    global theme
    color_mode = config_center.read_conf('General', 'color_mode')
    if color_mode == '2':  # 自动
        logger.info(f'颜色模式: 自动({color_mode})')
        if platform.system() == 'Darwin' and Version(platform.mac_ver()[0]) < Version('10.14'):
            return
        if platform.system() == 'Windows':
            # Windows 7特殊处理
            if sys.getwindowsversion().major == 6 and sys.getwindowsversion().minor == 1:
                setTheme(Theme.LIGHT)
                return
            # 检查Windows版本是否支持深色模式（Windows 10 build 14393及以上）
            try:
                win_build = sys.getwindowsversion().build
                if win_build < 14393:  # 不支持深色模式的最低版本
                    return
            except AttributeError:
                # 无法获取版本信息，保守返回
                return
        if platform.system() == 'Linux':
            return
        if dark_mode_watcher:
            is_dark = dark_mode_watcher.is_dark()
            if is_dark is not None:
                logger.info(f"当前颜色模式: {'深色' if is_dark else '浅色'}")
                setTheme(Theme.DARK if is_dark else Theme.LIGHT)
            else:
                logger.warning("无法获取系统颜色模式，暂时使用浅色主题")
                setTheme(Theme.LIGHT)
        else:
            logger.warning("DarkModeWatcher 未被初始化，使用浅色主题")
            setTheme(Theme.LIGHT)
    elif color_mode == '1':
        logger.info(f'颜色模式: 深色({color_mode})')
        setTheme(Theme.DARK)
    else:
        logger.info(f'颜色模式: 浅色({color_mode})')
        setTheme(Theme.LIGHT)


def get_timeline_data() -> List[Tuple[int, str, int, int]]:
    # if len(loaded_data['timeline']) == 1:
    #     return loaded_data['timeline']['default']
    # else:
    #     if str(current_week) in loaded_data['timeline'] and loaded_data['timeline'][str(current_week)]:  # 如果此周有时间线
    #         return loaded_data['timeline'][str(current_week)]
    #     else:
    #         return loaded_data['timeline']['default']
    if (
        str(current_week)
        in (data := loaded_data['timeline_even' if conf.get_week_type() else 'timeline'])
        and data[str(current_week)]
    ):  # 如果此周有时间线
        return data[str(current_week)]
    if conf.get_week_type() and (data := loaded_data.get('timeline_even', {}).get('default', [])):
        return data
    return loaded_data['timeline'].get('default', [])


# 获取Part开始时间
def get_start_time() -> None:
    global parts_start_time, timeline_data, loaded_data, order, parts_type
    loaded_data = schedule_center.schedule_data
    timeline = get_timeline_data()  # 实际上这里的 Tuple 是靠 List 实现的
    part: Dict[str, Tuple[int, int, str]] = loaded_data['part']
    parts_start_time = []
    timeline_data = []
    order = []

    for item_name, item_value in part.items():
        try:
            h, m = item_value[:2]
            try:
                part_type = item_value[2]
            except IndexError:
                part_type = 'part'
            except Exception as e:
                logger.error(f'加载课程表文件[节点类型]出错：{e}')
                part_type = 'part'

            # 使用基础时间，不应用偏移（偏移在比较时统一处理）
            current_time_manager = TimeManagerFactory.get_instance()
            base_time = dt.datetime.combine(current_time_manager.get_today(), dt.time(h, m))
            parts_start_time.append(base_time)
            order.append(item_name)
            parts_type.append(part_type)
        except Exception as e:
            logger.error(f'加载课程表文件[起始时间]出错：{e}')

    paired = zip(parts_start_time, order)
    paired_sorted = sorted(paired, key=lambda x: x[0])  # 按时间大小排序
    if paired_sorted:
        parts_start_time, order = zip(*paired_sorted)

    def sort_timeline_key(item: Tuple[int, str, int, int]):
        # if len(item_name) > 1:
        #     try:
        #         # 提取节点序数
        #         part_num = int(item_name[1])
        #         # 提取课程序数
        #         class_num = 0
        #         if len(item_name) > 2:
        #             class_num = int(item_name[2:])
        #         if prefix == 'a':
        #             return part_num, class_num, 0
        #         else:
        #             return part_num, class_num, 1
        #     except ValueError:
        #         # 如果转换失败，返回原始字符串
        #         return item_name
        # return item_name
        return item[1], item[2], item[0]

    # 对timeline排序后添加到timeline_data
    timeline_data = sorted(timeline, key=sort_timeline_key)
    # timeline_data = timeline.copy()  # 直接复制，避免修改原数据


def get_part() -> Optional[Tuple[dt.datetime, int]]:
    if not parts_start_time:
        return None

    def return_data():
        base_time = parts_start_time[i]
        current_manager = TimeManagerFactory.get_instance()
        c_time = current_manager.get_current_time().replace(
            hour=base_time.hour,
            minute=base_time.minute,
            second=base_time.second,
            microsecond=base_time.microsecond,
        )
        return c_time, int(order[i])  # 返回开始时间、Part序号

    current_dt = TimeManagerFactory.get_instance().get_current_time()  # 当前时间

    for i, base_time in enumerate(parts_start_time):  # 遍历每个Part
        time_len = dt.timedelta(minutes=0)  # Part长度

        for _isbreak, item_name, _item_index, item_time in timeline_data:
            # if item_name.startswith(f'a{str(order[i])}') or item_name.startswith(f'f{str(order[i])}'):
            if item_name == order[i]:
                time_len += dt.timedelta(minutes=int(item_time))  # 累计Part的时间点总长度
            time_len += dt.timedelta(seconds=1)

        if time_len != dt.timedelta(seconds=1):  # 有课程
            if i == len(parts_start_time) - 1:  # 最后一个Part
                return return_data()
            # 将基础时间转换为当前时间基准进行比较
            current_manager = TimeManagerFactory.get_instance()
            adjusted_start_time = current_manager.get_current_time().replace(
                hour=base_time.hour,
                minute=base_time.minute,
                second=base_time.second,
                microsecond=base_time.microsecond,
            )
            if current_dt <= adjusted_start_time + time_len:
                return return_data()

    return parts_start_time[0], 0


def get_excluded_lessons() -> None:
    global excluded_lessons
    if config_center.read_conf('General', 'excluded_lesson') == "0":
        excluded_lessons = []
        return
    excluded_lessons_raw = config_center.read_conf('General', 'excluded_lessons')
    excluded_lessons = excluded_lessons_raw.split(',') if excluded_lessons_raw != '' else []


# 获取当前活动
def get_current_lessons() -> None:  # 获取当前课程
    global current_lessons
    timeline = get_timeline_data()
    if config_center.read_conf('General', 'enable_alt_schedule') == '1' or conf.is_temp_week():
        try:
            schedule = (
                loaded_data.get('schedule_even')
                if conf.get_week_type()
                else loaded_data.get('schedule')
            )
        except Exception as e:
            logger.error(f'加载课程表文件[单双周]出错：{e}')
            schedule = loaded_data.get('schedule')
    else:
        schedule = loaded_data.get('schedule')
    class_count = 0
    for isbreak, item_name, item_index, _item_time in timeline:
        if not isbreak:
            if schedule[str(current_week)]:
                try:
                    if schedule[str(current_week)][class_count] != QCoreApplication.translate(
                        'main', '未添加'
                    ):
                        current_lessons[(isbreak, item_name, item_index)] = schedule[
                            str(current_week)
                        ][class_count]
                    else:
                        current_lessons[(isbreak, item_name, item_index)] = (
                            QCoreApplication.translate('main', '暂无课程')
                        )
                except IndexError:
                    current_lessons[(isbreak, item_name, item_index)] = QCoreApplication.translate(
                        'main', '暂无课程'
                    )
                except Exception as e:
                    current_lessons[(isbreak, item_name, item_index)] = QCoreApplication.translate(
                        'main', '暂无课程'
                    )
                    logger.debug(f'加载课程表文件出错：{e}')
                class_count += 1
            else:
                current_lessons[(isbreak, item_name, item_index)] = QCoreApplication.translate(
                    'main', '暂无课程'
                )
                class_count += 1


# 获取倒计时、弹窗提示
def get_countdown(toast: bool = False) -> Optional[List[Union[str, int]]]:  # 重构好累aaaa
    global last_notify_time
    current_dt = TimeManagerFactory.get_instance().get_current_time()
    if last_notify_time and (current_dt - last_notify_time).seconds < notify_cooldown:
        return None

    def after_school():  # 放学
        if parts_type[part] == 'break':  # 休息段
            notification.push_notification(0, current_lesson_name)  # 下课
        elif config_center.read_conf('Toast', 'after_school') == '1':
            notification.push_notification(2)  # 放学

    # 当前时间舍去毫秒，否则后面判定时间相等始终是False
    current_dt = TimeManagerFactory.get_instance().get_current_time_without_ms()
    return_text = []
    got_return_data = False

    if parts_start_time:
        c_time, part = get_part()

        if current_dt >= c_time:
            for isbreak, item_name, _item_index, item_time in timeline_data:
                # if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                if item_name == str(part):
                    # 判断时间是否上下课，发送通知
                    if current_dt == c_time and toast:
                        if not isbreak:
                            notification.push_notification(1, next_lessons[0])  # 上课
                            last_notify_time = current_dt
                        elif next_lessons:  # 下课/放学
                            notification.push_notification(0, next_lessons[0])  # 下课
                            last_notify_time = current_dt
                        else:
                            after_school()

                    if (
                        (
                            current_dt
                            == c_time
                            - dt.timedelta(
                                minutes=int(config_center.read_conf('Toast', 'prepare_minutes'))
                            )
                            and current_dt != last_notify_time
                        )
                        and (
                            config_center.read_conf('Toast', 'prepare_minutes') != '0'
                            and toast
                            and not isbreak
                        )
                        and not current_state
                    ):  # 课间
                        notification.push_notification(3, next_lessons[0])  # 准备上课（预备铃）
                        last_notify_time = current_dt

                    # 放学
                    if (
                        c_time + dt.timedelta(minutes=int(item_time)) == current_dt
                        and not next_lessons
                        and toast
                    ):
                        after_school()
                        last_notify_time = current_dt

                    add_time = int(item_time)
                    c_time += dt.timedelta(minutes=add_time)

                    if got_return_data:
                        break

                    if c_time >= current_dt:
                        # 根据所在时间段使用不同标语
                        if not isbreak:
                            return_text.append(
                                QCoreApplication.translate('main', '当前活动结束还有')
                            )
                        else:
                            return_text.append(QCoreApplication.translate('main', '课间时长还有'))
                        # 返回倒计时、进度条
                        time_diff = c_time - current_dt
                        minute, sec = divmod(time_diff.seconds, 60)
                        return_text.append(f'{minute:02d}:{sec:02d}')
                        # 进度条
                        seconds = time_diff.seconds
                        return_text.append(int(100 - seconds / (int(item_time) * 60) * 100))
                        got_return_data = True
            if not return_text:
                return_text = [QCoreApplication.translate('main', '目前课程已结束'), '00:00', 100]
        else:
            prepare_minutes_str = config_center.read_conf('Toast', 'prepare_minutes')
            if prepare_minutes_str != '0' and toast:
                prepare_minutes = int(prepare_minutes_str)
                if current_dt == c_time - dt.timedelta(minutes=prepare_minutes):
                    next_lesson_name = None
                    next_lesson_key = None
                    if timeline_data:
                        for isbreak, item_name, item_index, item_time in timeline_data:
                            # if key.startswith(f'a{str(part)}'):
                            if not isbreak and item_name == str(part):
                                next_lesson_key = (isbreak, item_name, item_index)
                                break
                    if next_lesson_key and next_lesson_key in current_lessons:
                        lesson_name = current_lessons[next_lesson_key]
                        if lesson_name != QCoreApplication.translate('main', '暂无课程'):
                            next_lesson_name = lesson_name
                    if current_state == 0:
                        now = TimeManagerFactory.get_instance().get_current_time()
                        if (
                            not last_notify_time
                            or (now - last_notify_time).seconds >= notify_cooldown
                        ) and next_lesson_name is not None:
                            notification.push_notification(3, next_lesson_name)
            # if f'a{part}1' in timeline_data:

            def have_class():
                return any(
                    not data[0] and data[1] == str(part) and data[2] == 1 for data in timeline_data
                )

            if have_class():  # 有课程
                time_diff = c_time - current_dt
                minute, sec = divmod(time_diff.seconds, 60)
                return_text = [
                    QCoreApplication.translate('main', '距离上课还有'),
                    f'{minute:02d}:{sec:02d}',
                    100,
                ]
            else:
                return_text = [QCoreApplication.translate('main', '目前课程已结束'), '00:00', 100]
        return return_text
    return None


# 获取将发生的活动
def get_next_lessons() -> None:
    global current_lesson_name
    global next_lessons
    next_lessons = []
    part = 0
    current_dt = TimeManagerFactory.get_instance().get_current_time()  # 当前时间

    if parts_start_time:
        c_time, part = get_part()

        def before_class():
            if part in {0, 3}:
                return True
            return current_dt >= TimeManagerFactory.get_instance().get_current_time().replace(
                hour=parts_start_time[part].hour,
                minute=parts_start_time[part].minute,
                second=parts_start_time[part].second,
                microsecond=parts_start_time[part].microsecond,
            ) - dt.timedelta(minutes=60)

        if before_class():
            for isbreak, item_name, item_index, item_time in timeline_data:
                # if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                if item_name == str(part):
                    add_time = int(item_time)
                    # if c_time > current_dt and item_name.startswith('a'):
                    if c_time > current_dt and not isbreak:
                        next_lessons.append(current_lessons[(isbreak, item_name, item_index)])
                    c_time += dt.timedelta(minutes=add_time)


def get_next_lessons_text() -> str:
    MAX_DISPLAY_LENGTH = 16
    if not next_lessons:
        return QCoreApplication.translate('main', '暂无课程')
    if config_center.read_conf('General', 'enable_display_full_next_lessons') == '0':
        return utils.slice_str_by_length(
            f"{next_lessons[0]} {'...' if len(next_lessons) > 1 else ''}", MAX_DISPLAY_LENGTH
        )
    if utils.get_str_length(full_text := (' '.join(next_lessons))) <= MAX_DISPLAY_LENGTH:
        return full_text
    return utils.slice_str_by_length(
        ' '.join([list_.get_subject_abbreviation(x) for x in next_lessons[:5]]), MAX_DISPLAY_LENGTH
    )


# 获取当前活动
def get_current_lesson_name() -> None:
    global current_lesson_name, current_state
    current_dt = TimeManagerFactory.get_instance().get_current_time()  # 当前时间
    current_lesson_name = QCoreApplication.translate('main', '暂无课程')
    current_state = 0

    if parts_start_time:
        c_time, part = get_part()

        if current_dt >= c_time:
            if parts_type[part] == 'break':  # 休息段
                current_lesson_name = loaded_data['part_name'][str(part)]
                current_state = 2

            for isbreak, item_name, item_index, item_time in timeline_data:
                # if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                if item_name == str(part):
                    add_time = int(item_time)
                    c_time += dt.timedelta(minutes=add_time)
                    if c_time > current_dt:
                        # if item_name.startswith('a'):
                        if not isbreak:
                            current_lesson_name = current_lessons[(isbreak, item_name, item_index)]
                            current_state = 1
                        else:
                            current_lesson_name = QCoreApplication.translate('main', '课间')
                            current_state = 0
                        return


def get_hide_status() -> int:
    # 1 -> hide, 0 -> show
    # 满分啦（
    # 祝所有用 Class Widgets 的、不用 Class Widgets 的学子体测满分啊（（
    global current_state, current_lesson_name, excluded_lessons
    return (
        1
        if {
            '0': lambda: 0,
            '1': lambda: current_state,
            '2': lambda: check_windows_maximize() or check_fullscreen(),
            '3': lambda: current_state,
        }[str(config_center.read_conf('General', 'hide'))]()
        and current_lesson_name not in excluded_lessons
        else 0
    )


# 定义 RECT 结构体
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_process_name(pid: Union[int, Any]) -> str:  # 获取进程名称
    try:
        if isinstance(pid, int):
            pid = ctypes.windll.user32.GetWindowThreadProcessId(pid, None)
        return psutil.Process(pid).name().lower()
    except (psutil.NoSuchProcess, AttributeError, ValueError):
        return "unknown"


def check_fullscreen() -> bool:  # 检查是否全屏
    if os.name != 'nt':
        return False
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    if hwnd == user32.GetDesktopWindow():
        return False
    if hwnd == user32.GetShellWindow():
        return False
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_name = get_process_name(pid.value)
    current_pid = os.getpid()
    # logger.debug(f"前景窗口句柄: {hwnd}, PID: {pid.value}, 进程名: {process_name}")
    if pid.value == current_pid:
        return False
    # 排除特定系统进程
    excluded_system_processes = {
        'explorer.exe',  # 文件资源管理器/桌面
        'shellexperiencehost.exe',  # Shell体验主机 (开始菜单、操作中心)
        'searchui.exe',  # Cortana/搜索界面
        'applicationframehost.exe',  # UWP应用框架
        'systemsettings.exe',  # 设置
        'taskmgr.exe',  # 任务管理器
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
        "program manager",  # 桌面窗口
        "windows input experience",  # 输入法相关
        "msctfmonitor window",  # 输入法相关
        "startmenuexperiencehost",  # 开始菜单
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
        rect.left <= screen_rect_desktop.left
        and rect.top <= screen_rect_desktop.top
        and rect.right >= screen_rect_desktop.right
        and rect.bottom >= screen_rect_desktop.bottom
    )
    if is_covering_screen:
        screen_area = (screen_rect_desktop.right - screen_rect_desktop.left) * (
            screen_rect_desktop.bottom - screen_rect_desktop.top
        )
        window_area = (rect.right - rect.left) * (rect.bottom - rect.top)
        return window_area >= screen_area * 0.95
        # logger.debug(f"覆盖屏幕: {is_covering_screen}, 窗口面积: {window_area}, 屏幕面积: {screen_area}, 是否全屏判断: {is_fullscreen}")
    return False


class ErrorDialog(Dialog):  # 重大错误提示框
    def __init__(
        self,
        error_details: str = 'Traceback (most recent call last):',
        parent: Optional[Any] = None,
    ) -> None:
        # KeyboardInterrupt 直接 exit
        if error_details.endswith(('KeyboardInterrupt', 'KeyboardInterrupt\n')):
            stop()

        global splash_window

        splash_window.error()

        super().__init__(
            QCoreApplication.translate('ErrorDialog', 'Class Widgets 崩溃报告'),
            QCoreApplication.translate(
                'ErrorDialog',
                '抱歉！Class Widgets 发生了严重的错误从而无法正常运行。您可以保存下方的错误信息并向他人求助。'
                '若您认为这是程序的Bug，请点击“报告此问题”或联系开发者。',
            ),
            parent,
        )
        global error_dialog
        error_dialog = True

        self.is_dragging = False
        self.drag_position = QPoint()
        self.title_bar_height = 30

        self.title_layout = QHBoxLayout()

        self.iconLabel = ImageLabel()
        self.iconLabel.setImage(str(CW_HOME / "img/logo/favicon-error.ico"))
        self.error_log = PlainTextEdit()
        self.report_problem = PushButton(fIcon.FEEDBACK, self.tr('报告此问题'))
        self.copy_log_btn = PushButton(fIcon.COPY, self.tr('复制日志'))
        self.ignore_error_btn = PushButton(fIcon.INFO, self.tr('忽略错误'))
        self.ignore_same_error = CheckBox()
        self.ignore_same_error.setText(self.tr('在下次启动之前，忽略此错误'))
        self.restart_btn = PrimaryPushButton(fIcon.SYNC, self.tr('重新启动'))

        self.iconLabel.setScaledContents(True)
        self.iconLabel.setFixedSize(50, 50)
        self.titleLabel.setText(self.tr('出错啦！ヽ(*。>Д<)o゜'))
        self.titleLabel.setStyleSheet(
            "font-family: Microsoft YaHei UI; font-size: 25px; font-weight: 500;"
        )
        self.error_log.setReadOnly(True)  # 只读模式
        self.error_log.setPlainText(error_details)
        self.error_log.setMinimumHeight(200)
        self.error_log.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard  # 允许鼠标和键盘选择文本
        )
        self.restart_btn.setFixedWidth(150)
        self.yesButton.hide()
        self.cancelButton.hide()  # 隐藏取消按钮
        self.title_layout.setSpacing(12)
        self.resize(650, 450)
        QApplication.processEvents()

        # 按钮事件
        self.report_problem.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(
                    'https://github.com/Class-Widgets/Class-Widgets/issues/'
                    'new?assignees=&labels=Bug&projects=&template=BugReport.yml&title=[Bug]:'
                )
            )
        )
        self.copy_log_btn.clicked.connect(self.copy_log)
        self.ignore_error_btn.clicked.connect(self.ignore_error)
        self.restart_btn.clicked.connect(restart)

        self.title_layout.addWidget(self.iconLabel)  # 标题布局
        self.title_layout.addWidget(self.titleLabel)
        self.textLayout.insertLayout(0, self.title_layout)  # 页面
        self.textLayout.addWidget(self.error_log)
        self.textLayout.addWidget(self.ignore_same_error)
        self.buttonLayout.insertStretch(0, 1)  # 按钮布局
        self.buttonLayout.insertWidget(0, self.copy_log_btn)
        self.buttonLayout.insertWidget(1, self.report_problem)
        self.buttonLayout.insertStretch(1)
        self.buttonLayout.insertWidget(4, self.ignore_error_btn)
        self.buttonLayout.insertWidget(5, self.restart_btn)

    def copy_log(self) -> None:  # 复制日志
        QApplication.clipboard().setText(self.error_log.toPlainText())
        Flyout.create(
            icon=InfoBarIcon.SUCCESS,
            title=self.tr('复制成功！ヾ(^▽^*)))'),
            content=self.tr("日志已成功复制到剪贴板。"),
            target=self.copy_log_btn,
            parent=self,
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP,
        )

    def ignore_error(self) -> None:
        global ignore_errors
        if self.ignore_same_error.isChecked():
            ignore_errors.append(self.error_log.toPlainText())
        self.close()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton and event.y() <= self.title_bar_height:
            self.is_dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: Any) -> None:
        if self.is_dragging:
            self.move(event.globalPos() - self.drag_position)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            self.is_dragging = False


class PluginManager:  # 插件管理器
    def __init__(self) -> None:
        self.cw_contexts = {}
        self.get_app_contexts()
        self.temp_window = []
        self.method = PluginMethod(self.cw_contexts)

    def get_app_contexts(self, path: Optional[str] = None) -> Dict[str, Any]:
        self.cw_contexts = {
            "Widgets_Width": list_.widget_width,
            "Widgets_Name": list_.widget_name,
            "Widgets_Code": list_.widget_conf,  # 小组件列表
            "Current_Lesson": current_lesson_name,  # 当前课程名
            "State": current_state,  # 0：课间 1：上课（上下课状态）
            "Current_Part": get_part(),  # 返回开始时间、Part序号
            "Next_Lessons_text": get_next_lessons_text(),  # 下节课程
            "Next_Lessons": next_lessons,  # 下节课程
            "Current_Lessons": current_lessons,  # 当前课程
            "Current_Week": current_week,  # 当前周次
            "Excluded_Lessons": excluded_lessons,  # 排除的课程
            "Current_Time": current_time,  # 当前时间
            "Timeline_Data": timeline_data,  # 时间线数据
            "Parts_Start_Time": parts_start_time,  # 节点开始时间
            "Parts_Type": parts_type,  # 节点类型
            "Time_Offset": TimeManagerFactory.get_instance().get_time_offset(),  # 时差偏移
            "Schedule_Name": config_center.schedule_name,  # 课程表名称
            "Loaded_Data": loaded_data,  # 加载的课程表数据
            "Order": order,  # 课程顺序
            "Weather": weather_name,  # 天气情况
            "Temp": temperature,  # 温度
            "Weather_Data": weather_data_temp,  # 天气数据
            "Weather_Icon": weather_icon,  # 天气图标
            "Weather_API": config_center.read_conf('Weather', 'api'),  # 天气API
            "City": city,  # 城市代码
            "Notification": notification.notification_contents,  # 检测到的通知内容
            "Last_Notify_Time": last_notify_time,  # 上次通知时间
            "PLUGIN_PATH": (
                str(conf.PLUGIN_HOME / path) if path else str(conf.PLUGIN_HOME)
            ),  # 传递插件目录
            "Config_Center": config_center,  # 配置中心实例
            "Schedule_Center": schedule_center,  # 课程表中心实例
            "Base_Directory": CW_HOME,  # 资源目录
            "Widgets_Mgr": mgr,  # 组件管理器实例
            "Theme": theme,  # 当前主题
        }
        return self.cw_contexts


class PluginMethod:  # 插件方法
    def __init__(self, app_context: Dict[str, Any]) -> None:
        self.app_contexts = app_context

    def register_widget(
        self, widget_code: str, widget_name: str, widget_width: int
    ) -> None:  # 注册小组件
        self.app_contexts['Widgets_Width'][widget_code] = widget_width
        self.app_contexts['Widgets_Name'][widget_code] = widget_name
        self.app_contexts['Widgets_Code'][widget_name] = widget_code

    def adjust_widget_width(self, widget_code: str, width: int) -> None:  # 调整小组件宽度
        self.app_contexts['Widgets_Width'][widget_code] = width

    @staticmethod
    def get_widget(widget_code: str) -> Optional[Any]:  # 获取小组件实例
        for widget in mgr.widgets:
            if widget.path == widget_code:
                return widget
        return None

    @staticmethod
    def change_widget_content(widget_code: str, title: str, content: str) -> None:  # 修改小组件内容
        for widget in mgr.widgets:
            if widget.path == widget_code:
                widget.update_widget_for_plugin([title, content])

    @staticmethod
    def is_get_notification() -> bool:  # 检查是否有通知
        return bool(notification.pushed_notification)

    @staticmethod
    def send_notification(
        state: int = 1,
        lesson_name: str = QCoreApplication.translate('main', '示例课程'),
        title: str = QCoreApplication.translate('main', '通知示例'),
        subtitle: str = QCoreApplication.translate('main', '副标题'),
        content: str = QCoreApplication.translate('main', '这是一条通知示例'),
        icon: Optional[Any] = None,
        duration: int = 2000,
    ) -> None:  # 发送通知
        notification.push_notification(state, lesson_name, title, subtitle, content, icon, duration)

    @staticmethod
    def subprocess_exec(title: str, action: str) -> None:  # 执行系统命令
        w = openProgressDialog(title, action)
        p_mgr.temp_window = [w]
        w.show()

    @staticmethod
    def read_config(path: str, section: str, option: str) -> Optional[Any]:  # 读取配置文件
        try:
            with open(path, encoding='utf-8') as r:
                config = json.load(r)
            return config.get(section, option)
        except Exception as e:
            logger.error(f"插件读取配置文件失败：{e}")
            return None

    @staticmethod
    def generate_speech(
        text: str,
        engine: str = "edge",
        voice: Optional[str] = None,
        timeout: float = 10.0,
        auto_fallback: bool = True,
    ) -> str:
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
        return generate_speech_sync(
            text=text, engine=engine, voice_id=voice, auto_fallback=auto_fallback, timeout=timeout
        )

    @staticmethod
    def play_audio(file_path: str, tts_delete_after: bool = True):
        """
        播放音频文件

        Args:
        file_path (str): 要播放的音频文件路径
        tts_delete_after (bool): 播放后是否删除文件（默认True）

        Note:
        - 删除操作有重试机制（3次尝试）
        """
        if tts_delete_after:
            from play_audio import play_audio_async

            play_audio_async(file_path, cleanup_callback=True)
        else:
            from play_audio import play_audio

            play_audio(file_path)


class WidgetsManager:
    def __init__(self) -> None:
        self.widgets = []  # 小组件实例
        self.widgets_list = []  # 小组件列表配置
        self.state = 1

        self.widgets_width = 0  # 小组件总宽度
        self.spacing = 0  # 小组件间隔

        self.start_pos_x = 0  # 小组件起始位置
        self.start_pos_y = 0

        self.hide_status = None  # [0] -> 在 current_state 设置的灵活隐藏， [1] -> 隐藏模式

    def sync_widget_animation(self, target_pos: Any) -> None:
        for widget in self.widgets:
            if widget.path == 'widget-current-activity.ui':
                widget.animate_expand(target_pos)  # 主组件形变动画

    def init_widgets(self) -> None:  # 初始化小组件
        self.widgets_list = list_.get_widget_config()
        self.check_widgets_exist()
        self.spacing = conf.load_theme_config(theme).config.spacing

        self.get_start_pos()
        cnt_all = {}

        # 添加小组件实例
        for w in range(len(self.widgets_list)):
            cnt_all[self.widgets_list[w]] = cnt_all.get(self.widgets_list[w], -1) + 1
            widget = DesktopWidget(
                self,
                self.widgets_list[w],
                w == 0,
                cnt=cnt_all[self.widgets_list[w]],
                position=self.get_widget_pos("", w),
                widget_cnt=w,
            )
            self.widgets.append(widget)

        self.create_widgets()

    def close_all_widgets(self) -> None:
        # 统一关闭所有组件
        if hasattr(self, '_closing'):
            return
        self._closing = True
        for widget in self.widgets:
            widget.close()  # 触发各个widget的closeEvent

    def check_widgets_exist(self) -> None:
        for widget in self.widgets_list:
            if widget not in list_.widget_width:
                self.widgets_list.remove(widget)

    @staticmethod
    def get_widget_width(path: str) -> int:
        return load_theme_config(
            str('default' if theme is None else theme)
        ).config.widget_width.get(path, list_.widget_width.get(path, 0))

    @staticmethod
    def get_widgets_height() -> int:
        return conf.load_theme_config(theme).config.height

    def create_widgets(self) -> None:
        for widget in self.widgets:
            widget.show()
            # print(int(widget.winId()))
            # print(ctypes.c_void_p(int(widget.winId())).value)
            if utils.focus_manager:
                QTimer.singleShot(
                    0,
                    lambda w=widget: utils.focus_manager.ignore.emit(
                        ctypes.c_void_p(int(w.winId())).value
                    ),
                )
            logger.info(f'显示小组件：{widget.path, widget.windowTitle()}')

    def adjust_ui(self) -> None:  # 更新小组件UI
        if self.state == 0:
            return
        for widget in self.widgets:
            # 调整窗口尺寸
            width = self.get_widget_width(widget.path)
            height = self.get_widgets_height()
            pos = self.get_widget_pos(widget.path, widget.widget_cnt)
            pos_x, pos_y = pos[0], pos[1]
            op = int(config_center.read_conf('General', 'opacity')) / 100

            if widget.animation is None:
                widget.widget_transition(pos_x, width, height, op, pos_y)

    def get_widget_pos(self, path: str, cnt: Optional[int] = None) -> List[int]:  # 获取小组件位置
        num = self.widgets_list.index(path) if cnt is None else cnt
        self.get_start_pos()
        pos_x = self.start_pos_x + self.spacing * num
        for i in range(num):
            widget = self.widgets_list[i]
            pos_x += conf.load_theme_config(
                str('default' if theme is None else theme)
            ).config.widget_width.get(widget, list_.widget_width.get(widget, 0))
        return [int(pos_x), int(self.start_pos_y)]

    def get_start_pos(self) -> None:
        self.calculate_widgets_width()
        screen_geometry = app.primaryScreen().availableGeometry()
        screen_width = screen_geometry.width()

        margin = max(0, int(config_center.read_conf('General', 'margin')))
        self.start_pos_y = margin
        self.start_pos_x = (screen_width - self.widgets_width) // 2

    def calculate_widgets_width(self) -> None:  # 计算小组件占用宽度
        self.widgets_width = 0
        # 累加小组件宽度
        for widget in self.widgets_list:
            try:
                self.widgets_width += self.get_widget_width(widget)
            except Exception as e:
                logger.warning(f'计算小组件宽度发生错误：{e}')
                self.widgets_width += 0

        self.widgets_width += self.spacing * (len(self.widgets_list) - 1)

    def hide_windows(self) -> None:
        self.state = 0
        for widget in self.widgets:
            widget.animate_hide()

    def full_hide_windows(self) -> None:
        self.state = 0
        for widget in self.widgets:
            widget.animate_hide(True)

    def show_windows(self) -> None:
        if fw.animating:  # 避免动画Bug
            return
        if fw.isVisible():
            fw.close()
        self.state = 1
        for widget in self.widgets:
            widget.animate_show()

    def clear_widgets(self) -> None:
        global fw, was_floating_mode
        if fw and fw.isVisible():
            fw.close()
            was_floating_mode = True
        else:
            was_floating_mode = False
        for widget in self.widgets:
            widget.animate_hide_opacity()
        for widget in self.widgets:
            self.widgets.remove(widget)
        init()

    def update_widgets(self) -> None:
        c = 0
        self.adjust_ui()

        for widget in self.widgets:
            if c == 0:
                get_countdown(True)
            widget.update_data(path=widget.path)
            c += 1

        if notification.pushed_notification:
            notification.pushed_notification = False

    def decide_to_hide(self) -> None:
        if config_center.read_conf('General', 'hide_method') == '0':  # 正常
            if fw.isVisible() and not fw.animating:
                fw.close()
            self.hide_windows()
        elif config_center.read_conf('General', 'hide_method') == '1':  # 单击即完全隐藏
            if fw.isVisible() and not fw.animating:
                fw.close()
            self.full_hide_windows()
        elif config_center.read_conf('General', 'hide_method') == '2':  # 最小化为浮窗
            if not fw.animating:
                self.full_hide_windows()
                fw.show()
                if utils.focus_manager:
                    QTimer.singleShot(
                        0,
                        lambda w=fw: utils.focus_manager.ignore.emit(
                            ctypes.c_void_p(int(w.winId())).value
                        ),
                    )
        else:
            self.hide_windows()

    def reapply_window_states(self) -> None:
        """应用组件窗口状态"""
        for widget in self.widgets:
            try:
                widget.apply_window_state()
                # logger.debug(f'重新应用小组件窗口状态：{widget.path}')
            except Exception as e:
                logger.error(f'应用小组件 {widget.path} 窗口状态时出错: {e}')

    def cleanup_resources(self):
        self.hide_status = None  # 重置hide_status
        widgets_to_clean = list(self.widgets)
        self.widgets.clear()
        for widget in widgets_to_clean:
            widget_path = getattr(widget, 'path', self.tr('未知组件'))
            try:
                if hasattr(widget, 'weather_timer') and widget.weather_timer:
                    with contextlib.suppress(RuntimeError):
                        widget.weather_timer.stop()
                if hasattr(widget, 'weather_thread') and widget.weather_thread:
                    try:
                        if widget.weather_thread.isRunning():
                            widget.weather_thread.quit()
                            if not widget.weather_thread.wait(500):
                                logger.warning(f"组件 {widget_path} 的天气线程未正常退出，强制终止")
                                widget.weather_thread.terminate()
                                widget.weather_thread.wait()
                    except RuntimeError:
                        pass
                widget.deleteLater()
            except Exception as ex:
                logger.error(f"清理组件 {widget_path} 时发生异常: {ex}")

    def stop(self) -> None:
        if mgr:
            mgr.cleanup_resources()
        for widget in self.widgets:
            widget.stop()
        if self.animation:
            self.animation.stop()
        if self.opacity_animation:
            self.opacity_animation.stop()
        self.close()


class openProgressDialog(QWidget):
    def __init__(self, action_title='打开 记事本', action='notepad'):
        super().__init__()
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.Tool
        )
        time = int(config_center.read_conf('Plugin', 'aguto_delay'))
        self.action = action

        screen_geometry = app.primaryScreen().availableGeometry()
        self.screen_width = screen_geometry.width()
        self.screen_height = screen_geometry.height()
        self.init_ui()
        self.init_font()
        self.move((self.screen_width - self.width()) // 2, self.screen_height - self.height() - 100)

        self.action_name = self.findChild(QLabel, 'action_name')
        self.action_name.setText(action_title)

        self.opening_countdown = self.findChild(ProgressRing, 'opening_countdown')
        self.opening_countdown.setRange(0, time - 1)
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(1000)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.execute_action)
        self.timer.start(time * 1000)

        self.cancel_opening = self.findChild(QPushButton, 'cancel_opening')
        self.cancel_opening.clicked.connect(self.cancel_action)

        self.intro_animation()

    def update_progress(self):
        self.opening_countdown.setValue(self.opening_countdown.value() + 1)

    def execute_action(self):
        self.timer.stop()
        subprocess.Popen(self.action)
        self.close()

    def cancel_action(self):
        self.timer.stop()
        self.close()

    def save_position(self) -> None:
        pass

    def init_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if isDarkTheme():
            uic.loadUi(str(CW_HOME / 'ui/default/dark/toast-open_dialog.ui'), self)
        else:
            uic.loadUi(str(CW_HOME / 'ui/default/toast-open_dialog.ui'), self)

        backgnd = self.findChild(QFrame, 'backgnd')
        shadow_effect = QGraphicsDropShadowEffect(self)
        shadow_effect.setBlurRadius(28)
        shadow_effect.setXOffset(0)
        shadow_effect.setYOffset(6)
        shadow_effect.setColor(QColor(0, 0, 0, 80))
        backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self) -> None:
        font_path = str(CW_HOME / 'font/HarmonyOS_Sans_SC_Bold.ttf')
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(
                f"""
                QLabel, ProgressRing, PushButton{{
                    font-family: "{font_family}";
                    font-weight: bold
                    }}
                """
            )

    def intro_animation(self):  # 弹出动画
        self.setMinimumWidth(300)
        label_width = self.action_name.sizeHint().width() - 120
        self.animation = QPropertyAnimation(self, b'windowOpacity')
        self.animation.setDuration(400)
        self.animation.setStartValue(0)
        self.animation.setEndValue(1)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animation_rect = QPropertyAnimation(self, b'geometry')
        self.animation_rect.setDuration(450)
        self.animation_rect.setStartValue(
            QRect(self.x(), self.screen_height, self.width(), self.height())
        )
        self.animation_rect.setEndValue(
            QRect(
                (self.screen_width - (self.width() + label_width)) // 2,
                self.screen_height - 250,
                self.width() + label_width,
                self.height(),
            )
        )
        self.animation_rect.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animation.start()
        self.animation_rect.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.setMinimumWidth(0)
        self.position = self.pos()
        # 关闭时保存一次位置
        self.save_position()
        self.deleteLater()
        self.hide()
        p_mgr.temp_window.clear()


class FloatingWidget(QWidget):  # 浮窗
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.Tool
        )
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

        # 加载保存的位置
        saved_pos = self.load_position()
        if saved_pos:
            # 边界检查
            saved_pos = self.adjust_position_to_screen(saved_pos)
            self.position = saved_pos
        else:
            # 使用动态计算的默认位置
            self.position = QPoint(
                (screen_width - self.width()) // 2, 50  # 居中横向  # 距离顶部 50px
            )

        update_timer.add_callback(self.update_data)

    def adjust_position_to_screen(self, pos: QPoint) -> QPoint:
        screen = QApplication.screenAt(pos)
        if not screen:
            screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        window_width = self.width()
        window_height = self.height()
        # 计算屏幕边界
        screen_left = screen_geometry.x()
        screen_right = screen_geometry.x() + screen_geometry.width()
        screen_top = screen_geometry.y()
        screen_bottom = screen_geometry.y() + screen_geometry.height()

        new_x, new_y = pos.x(), pos.y()
        if pos.x() < screen_left:
            # 当窗口可见部分不足50%时调整
            visible_width = (pos.x() + window_width) - screen_left
            if visible_width < window_width / 2:
                new_x = screen_left
        elif (pos.x() + window_width) > screen_right:
            visible_width = screen_right - pos.x()
            if visible_width < window_width / 2:
                new_x = screen_right - window_width
        if pos.y() < screen_top:
            visible_height = (pos.y() + window_height) - screen_top
            if visible_height < window_height / 2:
                new_y = screen_top
        elif (pos.y() + window_height) > screen_bottom:
            visible_height = screen_bottom - pos.y()
            if visible_height < window_height / 2:
                new_y = screen_bottom - window_height
        return QPoint(new_x, new_y)

    def _ensure_topmost(self) -> None:
        # 始终处于顶层
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
                    ctypes.windll.user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOSIZE | SWP_SHOWWINDOW,
                    )
                    self.raise_()
                elif self._is_topmost_callback_added:
                    try:
                        utils.update_timer.remove_callback(self._ensure_topmost)
                    except ValueError:
                        pass  # 可能已经被移除了
                    self._is_topmost_callback_added = False
                    logger.debug(f"句柄 {hwnd} 无效，已移除置顶回调。")
            except RuntimeError as e:
                if 'Internal C++ object' in str(e) and 'already deleted' in str(e):
                    logger.debug(f"尝试访问已删除的 FloatingWidget 时出错，移除回调: {e}")
                    if self._is_topmost_callback_added:
                        try:
                            utils.update_timer.remove_callback(self._ensure_topmost)
                        except ValueError:
                            pass  # 可能已经被移除了
                        self._is_topmost_callback_added = False
                else:
                    logger.error(f"检查或设置浮窗置顶时发生运行时错误: {e}")
            except Exception as e:
                logger.error(f"检查或设置浮窗置顶时出错: {e}")
                if self._is_topmost_callback_added:
                    with contextlib.suppress(ValueError):
                        utils.update_timer.remove_callback(self._ensure_topmost)
                    self._is_topmost_callback_added = False
                    logger.debug(f"因错误 {e} 移除浮窗置顶回调。")

    def save_position(self):
        current_screen = QApplication.screenAt(self.pos())
        if not current_screen:
            current_screen = QApplication.primaryScreen()
        screen_geometry = current_screen.availableGeometry()
        pos = self.pos()
        x = pos.x()
        window_width = self.width()
        if mgr.state:
            return
        screen_left = screen_geometry.left()
        screen_right = screen_geometry.right()
        if x < screen_left:
            visible_width = (x + window_width) - screen_left
            if visible_width < window_width / 2:
                x = screen_left
        elif (x + window_width) > screen_right:
            if self.animating:
                return
            visible_width = screen_right - x
            if visible_width < window_width / 2:
                x = screen_right - window_width
        y = min(max(pos.y(), screen_geometry.top()), screen_geometry.bottom())
        pos = QPoint(x, y)
        config_center.write_conf('FloatingWidget', 'pos_x', str(pos.x()))
        if not self.animating:
            config_center.write_conf('FloatingWidget', 'pos_y', str(pos.y()))

    def load_position(self) -> Optional[QPoint]:
        x = config_center.read_conf('FloatingWidget', 'pos_x')
        y = config_center.read_conf('FloatingWidget', 'pos_y')
        if x and y:
            return QPoint(int(x), int(y))
        return None

    def init_ui(self):
        theme_info = conf.load_theme_config(str('default' if theme is None else theme))
        theme_path = theme_info.path
        theme_config = theme_info.config
        if (theme_path / 'widget-floating.ui').exists():
            if isDarkTheme() and theme_config.support_dark_mode:
                uic.loadUi(theme_path / 'dark/widget-floating.ui', self)
            else:
                uic.loadUi(theme_path / 'widget-floating.ui', self)
        elif isDarkTheme() and theme_config.support_dark_mode:
            uic.loadUi(str(CW_HOME / 'ui/default/dark/widget-floating.ui'), self)
        else:
            uic.loadUi(str(CW_HOME / 'ui/default/widget-floating.ui'), self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 根据平台和设置应用窗口标志
        if sys.platform == 'darwin':
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Widget
                | Qt.BypassWindowManagerHint
            )
        else:
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.BypassWindowManagerHint
            )

        self.setWindowFlags(flags)

        # 始终添加置顶回调逻辑
        if os.name == 'nt' and not self._is_topmost_callback_added:
            try:
                if hasattr(utils, 'update_timer') and utils.update_timer:
                    utils.update_timer.add_callback(self._ensure_topmost, 0.5)
                    self._is_topmost_callback_added = True
                    self._ensure_topmost()  # 立即执行一次确保初始置顶
                else:
                    logger.warning("utils.update_timer 不可用，无法为浮窗添加置顶回调。")
            except Exception as e:
                logger.error(f"为浮窗添加置顶回调时出错: {e}")

        if sys.platform == 'darwin':
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Widget  # macOS 失焦时仍然显示
                | Qt.BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )

        backgnd = self.findChild(QFrame, 'backgnd')
        shadow_effect = QGraphicsDropShadowEffect(self)
        shadow_effect.setBlurRadius(28)
        shadow_effect.setXOffset(0)
        shadow_effect.setYOffset(6)
        shadow_effect.setColor(QColor(0, 0, 0, 75))
        backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self) -> None:
        font_path = str(CW_HOME / 'font/HarmonyOS_Sans_SC_Bold.ttf')
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(
                f"""
                QLabel, ProgressRing{{
                    font-family: "{font_family}";
                    }}
                """
            )

    def update_data(self) -> None:
        time_color = QColor(f'#{config_center.read_conf("Color", "floating_time")}')
        self.activity_countdown.setStyleSheet(
            f"color: {time_color.name()}; background: transparent"
        )
        if self.animating:  # 执行动画时跳过更新
            return
        if platform.system() == 'Windows' and platform.release() != '7':
            self.setWindowOpacity(
                int(config_center.read_conf('General', 'opacity')) / 100
            )  # 设置窗口透明度
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
                    self.activity_countdown.setText(self.tr("< - 分钟"))
                else:
                    minutes = int(cd_list[1].split(':')[0]) + 1
                    self.activity_countdown.setText(
                        self.tr("< {minutes} 分钟").format(minutes=minutes)
                    )
            else:  # 精确显示
                self.activity_countdown.setText(cd_list[1])
            self.countdown_progress_bar.setValue(cd_list[2])

        self.adjustSize_animation()

        self.update()

    def showEvent(self, event: QShowEvent) -> None:  # 窗口显示
        logger.info('显示浮窗')
        current_screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        screen_geometry = current_screen.availableGeometry()

        if self.position:
            if self.position.y() > screen_geometry.center().y():
                # 下半屏
                start_pos = QPoint(self.position.x(), screen_geometry.bottom() + self.height())
            else:
                # 上半屏
                start_pos = QPoint(self.position.x(), screen_geometry.top() - self.height())
        else:
            # 默认:顶部中央滑入
            start_pos = QPoint(
                (screen_geometry.width() - self.width()) // 2, screen_geometry.top() - self.height()
            )
            self.position = QPoint(
                (screen_geometry.width() - self.width()) // 2,
                max(50, int(config_center.read_conf('General', 'margin'))),
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

    def animation_done(self) -> None:
        self.animating = False

    def closeEvent(self, event: QCloseEvent) -> None:
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
        max_duration = 550  # 最大
        min_duration = 250  # 最小
        # 获取主组件位置
        main_widget = next((w for w in mgr.widgets if w.path == 'widget-current-activity.ui'), None)
        if main_widget:
            if current_pos.y() > screen_center_y:  # 下半屏
                # 屏幕底部
                target_y = screen_geometry.bottom() + self.height() + 10
                # 任务栏补偿
                if platform.system() == "Windows":
                    target_y += 30

                target_pos = QPoint(main_widget.x(), target_y)
                distance = abs(current_pos.y() - target_y)
            else:  # 上半屏
                target_pos = main_widget.pos()
                distance = abs(current_pos.y() - target_pos.y())
        else:
            target_pos = QPoint(
                screen_geometry.center().x() - self.width() // 2,
                int(config_center.read_conf('General', 'margin')),
            )
            distance = abs(current_pos.y() - target_pos.y())

        max_distance = screen_geometry.height()
        distance_ratio = min(distance / max_distance, 1.0)
        duration = int(base_duration + (max_duration - base_duration) * (distance_ratio**0.7))
        duration = max(min_duration, min(duration, max_duration))
        # 多平台兼容
        curve = QEasingCurve.Type.OutCubic
        if system == "Windows":
            if current_pos.y() > screen_center_y:
                duration += 50
        elif system == "Darwin":
            duration = int(duration * 0.85)

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
                with contextlib.suppress(ValueError):
                    utils.update_timer.remove_callback(self._ensure_topmost)
                self._is_topmost_callback_added = False

        self.animation_rect.finished.connect(cleanup)

        if utils.focus_manager:
            QTimer.singleShot(
                500,
                lambda: (
                    utils.focus_manager.remove_ignore.emit(ctypes.c_void_p(int(self.winId())).value)
                ),
            )

    def hideEvent(self, event: QHideEvent) -> None:
        event.accept()
        logger.info('隐藏浮窗')
        self.animating = False
        self.setMinimumSize(QSize(self.width(), self.height()))

    def adjustSize_animation(self) -> None:
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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.m_flag = True
            self.m_Position = event.globalPos() - self.pos()  # 获取鼠标相对窗口的位置
            self.p_Position = event.globalPos()  # 获取鼠标相对屏幕的位置
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton and self.m_flag:
            self.move(event.globalPos() - self.m_Position)  # 更改窗口位置
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.r_Position = event.globalPos()  # 获取鼠标相对窗口的位置
        self.m_flag = False
        # 保存位置到配置文件
        self.save_position()
        # 特定隐藏模式下不执行操作
        hide_mode = config_center.read_conf('General', 'hide')
        if hide_mode in {'1', '2'}:
            return  # 阻止手动展开/收起
        if (
            hasattr(self, "p_Position")
            and self.r_Position == self.p_Position
            and not self.animating
        ):  # 非特定隐藏模式下执行点击事件
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
        if utils.focus_manager:
            utils.focus_manager.restore_requested.emit()

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.focusing = True

    def focusOutEvent(self, event: QFocusEvent) -> None:
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
    def __init__(
        self,
        parent: WidgetsManager = WidgetsManager,
        path: str = 'widget-time.ui',
        enable_tray: bool = False,
        cnt: int = 0,
        position: Optional[Tuple[int, int]] = None,
        widget_cnt: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.Tool)

        self.cnt = cnt
        self.widget_cnt = widget_cnt

        self.tray_menu = None

        self.last_widgets = list_.get_widget_config()
        self.path = path
        theme_config = conf.load_theme_config(str('default' if theme is None else theme)).config
        initial_api = config_center.read_conf('Weather', 'api') or 'unknown'
        initial_city = config_center.read_conf('Weather', 'city') or '0'
        self.last_code = f"{initial_api}|{initial_city}"
        self.radius = theme_config.radius
        self.last_theme = config_center.read_conf('General', 'theme')
        self.last_color_mode = config_center.read_conf('General', 'color_mode')
        self.w = 100

        # 天气预警动画相关
        self.weather_alert_timer = None
        self.weather_alert_animation = None
        self.weather_alert_text = None
        self.alert_showing = False

        self.position = parent.get_widget_pos(self.path, None) if position is None else position
        self.animation = None
        self.opacity_animation = None
        mgr.hide_status = None
        self._is_topmost_callback_added = False  # 添加一个标志来跟踪回调是否已添加

        try:
            self.w = theme_config.widget_width[self.path]
        except KeyError:
            self.w = list_.widget_width[self.path]
        self.h = theme_config.height

        self.init_ui(path)
        self.init_font()

        if enable_tray:
            self.init_tray_menu()  # 初始化托盘菜单

        # 样式
        self.backgnd = self.findChild(QFrame, 'backgnd')
        if self.backgnd is None:
            self.backgnd = self.findChild(QLabel, 'backgnd')

        stylesheet = self.backgnd.styleSheet()  # 应用圆角
        updated_stylesheet = re.sub(
            r'border-radius:\s*\d+px', f'border-radius: {self.radius}', stylesheet
        )
        self.backgnd.setStyleSheet(updated_stylesheet)

        if path == 'widget-time.ui':  # 日期显示
            self.date_text = self.findChild(QLabel, 'date_text')
            self.date_text.setText(
                self.tr('{year} 年 {month}').format(
                    year=today.year, month=list_.month[today.month - 1]
                )
            )
            self.day_text = self.findChild(QLabel, 'day_text')
            self.day_text.setText(
                self.tr('{day}日  {week}').format(day=today.day, week=list_.week[today.weekday()])
            )

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
            self.weather_icon = self.findChild(IconWidget, 'weather_icon')
            self.alert_icon = IconWidget(self)
            self.alert_icon.setFixedSize(22, 22)
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
            self.weather_alert_animation = QPropertyAnimation(
                self.weather_alert_opacity, b"opacity"
            )
            self.weather_alert_animation.setDuration(700)
            self.weather_alert_animation.setEasingCurve(QEasingCurve.OutCubic)
            self.alert_icon_opacity = QGraphicsOpacityEffect(self)
            self.alert_icon_opacity.setOpacity(1.0)
            self.alert_icon.setGraphicsEffect(self.alert_icon_opacity)
            self.alert_icon_animation = QPropertyAnimation(self.alert_icon_opacity, b"opacity")
            self.alert_icon_animation.setDuration(700)
            self.alert_icon_animation.setEasingCurve(QEasingCurve.OutCubic)

            self.showing_temperature = True  # 是否正在显示气温
            self.showing_alert = False  # 是否正在显示预警

            # 天气提醒标签
            self.weather_reminder_text = QLabel(self)
            self.weather_reminder_text.setAlignment(Qt.AlignCenter)
            self.weather_reminder_text.setStyleSheet(self.temperature.styleSheet())
            self.weather_reminder_text.setFont(self.temperature.font())
            self.weather_reminder_text.setFixedWidth(138)
            self.weather_reminder_text.hide()

            # 天气提醒图标
            self.reminder_icon = IconWidget(self)
            self.reminder_icon.setFixedSize(26, 26)
            self.reminder_icon.hide()

            content_layout.addWidget(self.reminder_icon)
            content_layout.addWidget(self.weather_reminder_text)

            # 天气提醒状态变量
            self.current_reminders = []  # 存储提醒列表
            self.current_reminder_index = 0  # 当前提醒索引
            self.showing_reminder = False  # 是否正在显示提醒

            refresh_interval = int(config_center.read_conf('Weather', 'refresh_interval'))
            self.weather_callback_id = update_timer.add_callback(
                self.get_weather_data, interval=refresh_interval * 60  # 转换为秒
            )
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
    def _onThemeChangedFinished() -> None:
        print('theme_changed')

    def update_widget_for_plugin(self, context: Optional[List[str]] = None) -> None:
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

    def init_ui(self, path: str) -> None:
        theme_info = conf.load_theme_config(str('default' if theme is None else theme))
        theme_config = theme_info.config
        theme_path = theme_info.path
        if (theme_path / path).exists():
            if theme_config.support_dark_mode and isDarkTheme():
                uic.loadUi(theme_path / 'dark' / path, self)
            else:
                uic.loadUi(theme_path / path, self)
        elif theme_config.support_dark_mode and isDarkTheme():
            uic.loadUi(theme_path / 'dark/widget-base.ui', self)
        else:
            uic.loadUi(theme_path / 'widget-base.ui', self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.apply_window_state()
        if sys.platform == 'darwin':
            self.setWindowFlag(Qt.WindowType.Widget, True)
        else:
            self.setWindowFlag(Qt.WindowType.Tool, True)

    def apply_window_state(self) -> None:
        """应用窗口状态"""
        if self._is_topmost_callback_added:
            try:
                utils.update_timer.remove_callback(self._ensure_topmost)
                self._is_topmost_callback_added = False
            except (ValueError, AttributeError):
                pass

        was_visible = self.isVisible()
        current_geometry = self.geometry() if was_visible else None
        current_opacity = self.windowOpacity() if was_visible else 1.0
        pin_on_top = config_center.read_conf('General', 'pin_on_top', '0')
        enable_click = config_center.read_conf('General', 'enable_click', '1')
        self.state_animation_group = QParallelAnimationGroup(self)
        if was_visible:
            self.fade_out_animation = QPropertyAnimation(self, b"windowOpacity")
            self.fade_out_animation.setDuration(200)  # 淡出
            self.fade_out_animation.setStartValue(current_opacity)
            self.fade_out_animation.setEndValue(0.0)
            self.fade_out_animation.setEasingCurve(QEasingCurve.OutCubic)
            self.state_animation_group.addAnimation(self.fade_out_animation)

        def apply_state_changes():
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enable_click == '0')
            if pin_on_top == '1':  # 置顶
                new_flags = (
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.WindowDoesNotAcceptFocus
                    | Qt.BypassWindowManagerHint
                    | Qt.Tool
                )
            elif pin_on_top == '2':  # 置底
                new_flags = (
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnBottomHint
                    | Qt.WindowType.WindowDoesNotAcceptFocus
                    | Qt.Tool
                )
            elif pin_on_top == '3':  # 置于次级底部
                new_flags = (
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowDoesNotAcceptFocus
                    | Qt.Tool
                )
            else:
                new_flags = Qt.WindowType.FramelessWindowHint | Qt.Tool
            self.setWindowFlags(new_flags)

            QApplication.processEvents()
            self.update()
            if pin_on_top == '2':  # 置底
                self.show()
                parent = self.parent()
                if hasattr(parent, 'get_widget_pos'):
                    if hasattr(parent, 'get_start_pos'):
                        parent.get_start_pos()
                    pos = parent.get_widget_pos(self.path, None)
                    if pos:
                        self.move(pos[0], pos[1])
                if self.width() == 0 or self.height() == 0:
                    self.resize(self.w, self.h)
            else:
                self.show()
                if current_geometry and current_geometry.isValid():
                    self.setGeometry(current_geometry)
                else:
                    parent = self.parent()
                    if hasattr(parent, 'get_widget_pos'):
                        if hasattr(parent, 'get_start_pos'):
                            parent.get_start_pos()
                        pos = parent.get_widget_pos(self.path, None)
                        if pos:
                            self.move(pos[0], pos[1])
                self.raise_()
            self.fade_in_animation = QPropertyAnimation(self, b"windowOpacity")
            self.fade_in_animation.setDuration(250)  # 淡入
            self.fade_in_animation.setStartValue(0.0)
            self.fade_in_animation.setEndValue(current_opacity)
            self.fade_in_animation.setEasingCurve(QEasingCurve.OutCubic)
            self.fade_in_animation.start()

            if pin_on_top == '1':  # 置顶
                if os.name == 'nt' and not self._is_topmost_callback_added:
                    try:
                        if hasattr(utils, 'update_timer') and utils.update_timer:
                            utils.update_timer.add_callback(self._ensure_topmost, 0.5)
                            self._is_topmost_callback_added = True
                            self._ensure_topmost()
                        else:
                            logger.warning("utils.update_timer 不可用，无法添加置顶回调。")
                    except Exception as e:
                        logger.error(f"添加置顶回调时出错: {e}")

            elif pin_on_top == '2':  # 置底
                self.lower()

            elif pin_on_top == '3':  # 置于次级底部
                if os.name == 'nt':

                    def set_window_pos_secondary():
                        try:
                            if self.isVisible() and self.width() > 0 and self.height() > 0:
                                hwnd = self.winId().__int__()
                                SWP_NOSIZE = 0x0001
                                SWP_NOMOVE = 0x0002
                                SWP_NOACTIVATE = 0x0010
                                SWP_SHOWWINDOW = 0x0040
                                HWND_NOTOPMOST = 2
                                ctypes.windll.user32.SetWindowPos(
                                    hwnd,
                                    HWND_NOTOPMOST,
                                    0,
                                    0,
                                    0,
                                    0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                                )
                                self.lower()
                        except Exception as e:
                            logger.error(f"设置窗口次级置底时出错: {e}")

                    if self.width() == 0 or self.height() == 0:
                        self.resize(self.w, self.h)
                    set_window_pos_secondary()
                else:
                    self.lower()

        if was_visible:
            self.state_animation_group.finished.connect(apply_state_changes)
            self.state_animation_group.start()
        else:
            apply_state_changes()

    def _ensure_topmost(self) -> None:
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
                    ctypes.windll.user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOSIZE | SWP_SHOWWINDOW,
                    )
                    self.raise_()
                elif self._is_topmost_callback_added:
                    try:
                        utils.update_timer.remove_callback(self._ensure_topmost)
                    except ValueError:
                        pass  # 可能已经被移除了
                    self._is_topmost_callback_added = False
                    logger.debug(f"窗口句柄 {hwnd} 无效，已自动移除置顶回调。")
            except RuntimeError as e:
                if 'Internal C++ object' in str(e) and 'already deleted' in str(e):
                    logger.debug(f"尝试访问已删除的 DesktopWidget 时出错，移除回调: {e}")
                    if self._is_topmost_callback_added:
                        try:
                            utils.update_timer.remove_callback(self._ensure_topmost)
                        except ValueError:
                            pass  # 可能已经被移除了
                        self._is_topmost_callback_added = False
                else:
                    logger.error(f"检查或设置窗口置顶时发生运行时错误: {e}")
            except Exception as e:
                logger.error(f"检查或设置窗口置顶时出错: {e}")
                if self._is_topmost_callback_added:
                    with contextlib.suppress(ValueError):
                        utils.update_timer.remove_callback(self._ensure_topmost)
                    self._is_topmost_callback_added = False
                    logger.debug(f"因错误 {e} 移除置顶回调。")

    def closeEvent(self, event):
        try:
            if hasattr(self, 'weather_thread') and self.weather_thread.isRunning():
                self.weather_thread.stop()
                self.weather_thread.wait(1000)
            if hasattr(self, 'reminder_thread') and self.reminder_thread.isRunning():
                self.reminder_thread.stop()
                self.reminder_thread.wait(1000)
        except Exception as e:
            logger.error(f"清理天气线程时出错: {e}")

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
        if conf.load_theme_config(
            str('default' if theme is None else theme)
        ).config.shadow:  # 修改阴影问题
            shadow_effect = QGraphicsDropShadowEffect(self)
            shadow_effect.setBlurRadius(28)
            shadow_effect.setXOffset(0)
            shadow_effect.setYOffset(6)
            shadow_effect.setColor(QColor(0, 0, 0, 75))

            self.backgnd.setGraphicsEffect(shadow_effect)

        if utils.focus_manager:
            QTimer.singleShot(
                500,
                lambda: (
                    utils.focus_manager.remove_ignore.emit(ctypes.c_void_p(int(self.winId())).value)
                ),
            )

    def init_font(self):
        font_path = str(CW_HOME / 'font/HarmonyOS_Sans_SC_Bold.ttf')
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(
                f"""
                QLabel, QPushButton{{
                    font-family: "{font_family}";
                    }}
                """
            )

    def animate_expand(self, target_geometry: QRect) -> None:
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(400)
        self.animation.setStartValue(
            QRect(target_geometry.x(), -self.height(), self.width(), self.height())
        )
        self.animation.setEndValue(target_geometry)
        self.animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self.raise_()
        self.show()

    def init_tray_menu(self) -> None:
        if not first_start:
            return

        utils.tray_icon = utils.TrayIcon(self)
        utils.tray_icon.setToolTip(f"Class Widgets - {config_center.schedule_name[:-5]}")
        self.tray_menu = SystemTrayMenu(title='Class Widgets', parent=self)
        self.tray_menu.addActions(
            [
                Action(
                    fIcon.HIDE,
                    self.tr('完全隐藏/显示小组件'),
                    triggered=lambda: self.hide_show_widgets(),
                ),
                Action(
                    fIcon.BACK_TO_WINDOW,
                    self.tr('最小化为浮窗'),
                    triggered=lambda: self.minimize_to_floating(),
                ),
            ]
        )
        self.tray_menu.addSeparator()
        self.tray_menu.addActions(
            [
                Action(fIcon.SHOPPING_CART, self.tr('插件广场'), triggered=open_plaza),
                Action(fIcon.DEVELOPER_TOOLS, self.tr('额外选项'), triggered=self.open_extra_menu),
                Action(fIcon.SETTING, self.tr('设置'), triggered=lambda: open_settings(self)),
            ]
        )
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(Action(fIcon.SYNC, self.tr('重新启动'), triggered=restart))
        self.tray_menu.addAction(Action(fIcon.CLOSE, self.tr('退出'), triggered=stop))
        utils.tray_icon.setContextMenu(self.tray_menu)

        utils.tray_icon.activated.connect(self.on_tray_icon_clicked)
        utils.tray_icon.show()

    @staticmethod
    def on_tray_icon_clicked(reason: QSystemTrayIcon.ActivationReason) -> None:  # 点击托盘图标隐藏
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

    def rightReleaseEvent(self, event: QMouseEvent) -> None:  # 右键事件
        event.ignore()
        if event.button() == Qt.MouseButton.RightButton:
            self.open_extra_menu()
        if utils.focus_manager:
            utils.focus_manager.restore_requested.emit()

    def update_data(self, path: str = '') -> None:
        global current_time, current_week, start_y, today

        today = TimeManagerFactory.get_instance().get_today()
        current_time = TimeManagerFactory.get_instance().get_current_time_str('%H:%M:%S')
        get_start_time()
        get_current_lessons()
        get_current_lesson_name()
        get_excluded_lessons()
        get_next_lessons()
        hide_status = get_hide_status()

        if (hide_mode := config_center.read_conf('General', 'hide')) in ['1', '2']:  # 上课自动隐藏
            if mgr.state == hide_status:
                if hide_status:
                    mgr.decide_to_hide()
                else:
                    mgr.show_windows()
        elif hide_mode == '3':  # 灵活隐藏
            if mgr.hide_status is None or mgr.hide_status[0] != current_state:
                mgr.hide_status = (-1, hide_status)
            if mgr.state == mgr.hide_status[1]:
                if mgr.hide_status[1]:
                    mgr.decide_to_hide()
                else:
                    mgr.show_windows()

        if conf.is_temp_week():  # 调休日
            current_week = config_center.read_conf('Temp', 'set_week')
        else:
            current_week = TimeManagerFactory.get_instance().get_current_weekday()

        cd_list = get_countdown()

        if path == 'widget-time.ui':  # 日期显示
            self.date_text.setText(
                self.tr('{year} 年 {month}').format(
                    year=today.year, month=list_.month[today.month - 1]
                )
            )
            self.day_text.setText(
                self.tr('{day}日  {week}').format(day=today.day, week=list_.week[today.weekday()])
            )

        if path == 'widget-current-activity.ui':  # 当前活动
            self.current_subject.setText(f'  {current_lesson_name}')

            if current_state != 2:  # 非休息段
                icon_path = list_.get_subject_icon(current_lesson_name)
                self.blur_effect_label.setStyleSheet(
                    f'background-color: rgba{list_.subject_color(current_lesson_name)}, 200);'
                )
            else:  # 休息段
                icon_path = list_.get_subject_icon('课间')
                self.blur_effect_label.setStyleSheet(
                    f'background-color: rgba{list_.subject_color("课间")}, 200);'
                )

            renderer = QSvgRenderer(icon_path)
            if not renderer.isValid():
                raise ValueError(f"无效的SVG文件: {icon_path}")

            svg_size = renderer.defaultSize()
            if svg_size.isEmpty():
                svg_size = QSize(100, 100)  # 默认尺寸
            target_size = 100
            aspect_ratio = svg_size.width() / svg_size.height()
            if aspect_ratio > 1:
                final_width = target_size
                final_height = int(target_size / aspect_ratio)
            else:
                final_height = target_size
                final_width = int(target_size * aspect_ratio)
            final_size = QSize(final_width, final_height)
            high_res_size = final_size * 2
            pixmap = QPixmap(high_res_size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHints(
                QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
            )
            renderer.render(painter)
            theme_config = conf.load_theme_config(str('default' if theme is None else theme)).config
            if (isDarkTheme() and theme_config.support_dark_mode) or (
                isDarkTheme() and theme_config.default_theme == 'dark'
            ):
                # 在暗色模式显示亮色图标
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor("#FFFFFF"))
            painter.end()
            icon_pixmap = pixmap.scaled(final_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.current_subject.setIcon(QIcon(icon_pixmap))

            self.blur_effect.setBlurRadius(25)
            self.blur_effect_label.setGraphicsEffect(self.blur_effect)

        elif path == 'widget-next-activity.ui':  # 接下来的活动
            self.nl_text.setText(get_next_lessons_text())

        if path == 'widget-countdown.ui':  # 活动倒计时
            if cd_list:
                if config_center.read_conf('General', 'blur_countdown') == '1':  # 模糊倒计时
                    if cd_list[1] == '00:00':
                        self.activity_countdown.setText(self.tr("< - 分钟"))
                    else:
                        self.activity_countdown.setText(
                            self.tr("< {minutes} 分钟").format(
                                minutes=int(cd_list[1].split(':')[0]) + 1
                            )
                        )
                else:
                    self.activity_countdown.setText(cd_list[1])
                self.ac_title.setText(cd_list[0])
                self.countdown_progress_bar.setValue(cd_list[2])

        if path == 'widget-countdown-day.ui':  # 自定义倒计时
            conf.update_countdown(self.cnt)
            self.custom_title.setText(
                self.tr('距离 {cd_text} 还有').format(cd_text=conf.get_cd_text_custom())
            )
            self.custom_countdown.setText(conf.get_custom_countdown())
        self.update()

    def get_weather_data(self) -> None:
        logger.info('获取天气数据')
        if hasattr(weather_manager, 'get_weather_reminders') and hasattr(
            weather_manager.get_weather_reminders, 'clear_cache'
        ):
            weather_manager.get_weather_reminders.clear_cache()
        if hasattr(weather_manager, 'fetch_weather_data') and hasattr(
            weather_manager.fetch_weather_data, 'clear_cache'
        ):
            weather_manager.fetch_weather_data.clear_cache()
        self._reset_weather_alert_state()
        # 停止旧的天气线程
        if hasattr(self, 'weather_thread') and self.weather_thread.isRunning():
            self.weather_thread.stop()
            self.weather_thread.wait(1000)  # 等待线程结束

        if not hasattr(self, 'weather_thread') or not self.weather_thread.isRunning():
            self.weather_thread = weatherReportThread()
            self.weather_thread.weather_signal.connect(self.update_weather_data)
            self.weather_thread.start()

    def _on_reminders_ready(self, reminders: list) -> None:
        """获取的天气提醒数据"""
        try:
            self.current_reminders = reminders
            self.current_reminder_index = 0

            if self.current_reminders:
                logger.debug(f'获取到 {len(self.current_reminders)} 个天气提醒')
                for i, reminder in enumerate(self.current_reminders):
                    logger.debug(f'提醒 {i+1}: {reminder.get("title", "未知")}')
            self._update_weather_alert_display()
        except Exception as e:
            logger.error(f'处理天气提醒数据失败: {e}')

    def _on_alerts_ready(self, alerts: list) -> None:
        """处理获取的天气预警数据"""
        try:
            self.current_alerts = alerts
            self.current_alert_index = 0
            if self.current_alerts:
                logger.debug(f'获取到 {len(self.current_alerts)} 个天气预警')
                for i, alert in enumerate(self.current_alerts):
                    logger.debug(f'预警 {i+1}: {alert.get("title", "未知")}')
            self._update_weather_alert_display()
        except Exception as e:
            logger.error(f'处理天气预警数据失败: {e}')

    def _update_weather_alert_display(self) -> None:
        """更新天气预警和提醒的UI显示"""
        try:
            if self.current_alerts or self.current_reminders:
                self.weather_alert_text.setFixedWidth(80)
                self.weather_alert_text.setFixedHeight(40)
                self._display_current_alert()
                if not hasattr(self, 'weather_alert_timer') or not self.weather_alert_timer:
                    self.weather_alert_timer = QTimer(self)
                    self.weather_alert_timer.timeout.connect(self.toggle_weather_alert)
                self.weather_alert_timer.start(6000)  # 6秒切换间隔
            else:
                self.weather_alert_text.hide()
                self.alert_icon.hide()
                self.weather_icon.show()
                self.temperature.show()
                self.showing_temperature = True
                self.showing_alert = False
                self.showing_reminder = False
                if hasattr(self, 'weather_alert_timer') and self.weather_alert_timer:
                    self.weather_alert_timer.stop()
                    self._reset_weather_alert_state()
        except Exception as e:
            logger.error(f'更新天气预警显示失败: {e}')

    def detect_weather_code_changed(self) -> None:
        current_api = config_center.read_conf('Weather', 'api')
        current_city = config_center.read_conf('Weather', 'city')
        current_key_config = f"{current_api}|{current_city}"

        if current_key_config != self.last_code:
            last_api = self.last_code.split('|')[0] if '|' in self.last_code else ''
            if current_api != last_api:
                # logger.debug(f'检测到天气API变化: {last_api} -> {current_api}，等待城市代码稳定')
                self.last_code = current_key_config
                from weather import on_weather_api_changed

                on_weather_api_changed(current_api)
            else:
                # logger.debug(f'检测到城市配置变化: {self.last_code} -> {current_key_config}')
                self.last_code = current_key_config
                self.get_weather_data()

    def toggle_weather_alert(self) -> None:
        """按照配置顺序循环显示天气信息"""
        SWITCH_INTERVAL = 6000  # 6秒切换间隔
        widget_display_config = (
            config_center.read_conf('Weather', 'widget_display') or 'temperature,alert,reminder'
        )
        widget_display_config = widget_display_config.strip('"\'')
        display_order = [
            item.strip().strip('"\'') for item in widget_display_config.split(',') if item.strip()
        ]
        if not display_order:
            display_order = ['temperature', 'alert', 'reminder']

        current_mode = self._get_current_display_mode()
        next_mode = self._get_next_display_mode(current_mode, display_order)
        self._switch_to_mode(next_mode)
        if hasattr(self, 'weather_alert_timer'):
            self.weather_alert_timer.start(SWITCH_INTERVAL)

    def _get_current_display_mode(self) -> str:
        """获取当前显示模式"""
        if getattr(self, 'showing_temperature', True):
            return 'temperature'
        if getattr(self, 'showing_alert', False):
            return 'alert'
        if getattr(self, 'showing_reminder', False):
            return 'reminder'
        return 'temperature'  # 默认

    def _get_next_display_mode(self, current_mode: str, display_order: list) -> str:
        """获取下一个显示模式"""
        if current_mode == 'alert' and hasattr(self, 'current_alerts') and self.current_alerts:
            if self.current_alert_index < len(self.current_alerts) - 1:
                self.current_alert_index += 1
                return 'alert'  # 继续显示下一个预警
        if (
            current_mode == 'reminder'
            and hasattr(self, 'current_reminders')
            and self.current_reminders
        ) and self.current_reminder_index < len(self.current_reminders) - 1:
            self.current_reminder_index += 1
            return 'reminder'  # 继续显示下一个提醒
        if current_mode == 'alert':
            self.current_alert_index = 0
        elif current_mode == 'reminder':
            self.current_reminder_index = 0

        try:
            current_index = display_order.index(current_mode)
        except ValueError:
            current_index = -1
        for i in range(len(display_order)):
            next_index = (current_index + 1 + i) % len(display_order)
            next_mode = display_order[next_index]
            if self._has_content_for_mode(next_mode):
                return next_mode

        return 'temperature'

    def _has_content_for_mode(self, mode: str) -> bool:
        """检查是否有内容可显示"""
        if mode == 'temperature':
            return True
        if mode == 'alert':
            return hasattr(self, 'current_alerts') and bool(self.current_alerts)
        if mode == 'reminder':
            return hasattr(self, 'current_reminders') and bool(self.current_reminders)
        return False

    def _switch_to_mode(self, target_mode: str) -> None:
        """切换到指定的显示模式"""
        current_mode = self._get_current_display_mode()
        if current_mode == target_mode:
            # 同类项切换
            if target_mode == 'alert':
                self._cycle_to_next_alert_with_animation()
            elif target_mode == 'reminder':
                self._cycle_to_next_reminder_with_animation()
            return

        # 不同类型之间切换
        self._unified_fade_transition(current_mode, target_mode)

    def _unified_fade_transition(self, from_mode: str, to_mode: str) -> None:
        """统一切换动画组"""
        fade_out_group = QParallelAnimationGroup(self)
        if from_mode == 'temperature':
            self._add_temperature_fade_out(fade_out_group)
        elif from_mode == 'alert':
            self._add_alert_fade_out(fade_out_group)
        elif from_mode == 'reminder':
            self._add_reminder_fade_out(fade_out_group)

        def on_fade_out_finished():
            self._hide_current_mode(from_mode)
            self._show_target_mode(to_mode)

        with contextlib.suppress(TypeError):
            fade_out_group.finished.disconnect()

        fade_out_group.finished.connect(on_fade_out_finished)
        fade_out_group.start()

    def _add_temperature_fade_out(self, fade_out_group: QParallelAnimationGroup) -> None:
        """温度控件淡出动画"""
        try:
            if self.weather_icon and self.weather_icon.parent() is not None:
                self.weather_opacity = QGraphicsOpacityEffect(self.weather_icon)
                self.weather_icon.setGraphicsEffect(self.weather_opacity)
            else:
                return
            if self.temperature and self.temperature.parent() is not None:
                self.temperature_opacity = QGraphicsOpacityEffect(self.temperature)
                self.temperature.setGraphicsEffect(self.temperature_opacity)
            else:
                return
            weather_fade_out = QPropertyAnimation(self.weather_opacity, b'opacity')
            temp_fade_out = QPropertyAnimation(self.temperature_opacity, b'opacity')
            self._setup_animation(weather_fade_out, 1.0, 0.0)
            self._setup_animation(temp_fade_out, 1.0, 0.0)
            fade_out_group.addAnimation(weather_fade_out)
            fade_out_group.addAnimation(temp_fade_out)
        except RuntimeError as e:
            logger.warning(f'创建温度淡出动画失败: {e}')
            self.weather_icon.hide()
            self.temperature.hide()

    def _add_alert_fade_out(self, fade_out_group: QParallelAnimationGroup) -> None:
        """预警控件的淡出动画"""
        try:
            if (
                not hasattr(self, 'weather_alert_opacity')
                or not self.weather_alert_opacity
                or not self.weather_alert_opacity.parent()
            ):
                self.weather_alert_opacity = QGraphicsOpacityEffect(self.weather_alert_text)
                self.weather_alert_text.setGraphicsEffect(self.weather_alert_opacity)
            if (
                not hasattr(self, 'alert_icon_opacity')
                or not self.alert_icon_opacity
                or not self.alert_icon_opacity.parent()
            ):
                self.alert_icon_opacity = QGraphicsOpacityEffect(self.alert_icon)
                self.alert_icon.setGraphicsEffect(self.alert_icon_opacity)

            alert_text_fade_out = QPropertyAnimation(self.weather_alert_opacity, b'opacity')
            alert_icon_fade_out = QPropertyAnimation(self.alert_icon_opacity, b'opacity')
            self._setup_animation(alert_text_fade_out, 1.0, 0.0)
            self._setup_animation(alert_icon_fade_out, 1.0, 0.0)
            fade_out_group.addAnimation(alert_text_fade_out)
            fade_out_group.addAnimation(alert_icon_fade_out)
        except RuntimeError as e:
            logger.warning(f'创建预警淡出动画失败: {e}')
            self.weather_alert_text.hide()
            self.alert_icon.hide()

    def _add_reminder_fade_out(self, fade_out_group: QParallelAnimationGroup) -> None:
        """提醒控件的淡出动画"""
        try:
            if hasattr(self, 'reminder_opacity') and self.reminder_opacity:
                if self.reminder_opacity.parent():
                    reminder_text_fade_out = QPropertyAnimation(self.reminder_opacity, b'opacity')
                    self._setup_animation(reminder_text_fade_out, 1.0, 0.0)
                    fade_out_group.addAnimation(reminder_text_fade_out)
            if hasattr(self, 'reminder_icon_opacity') and self.reminder_icon_opacity:
                if self.reminder_icon_opacity.parent():
                    reminder_icon_fade_out = QPropertyAnimation(
                        self.reminder_icon_opacity, b'opacity'
                    )
                    self._setup_animation(reminder_icon_fade_out, 1.0, 0.0)
                    fade_out_group.addAnimation(reminder_icon_fade_out)
        except RuntimeError as e:
            logger.warning(f'创建提醒淡出动画失败: {e}')
            if hasattr(self, 'reminder_text'):
                self.reminder_text.hide()
            if hasattr(self, 'reminder_icon'):
                self.reminder_icon.hide()

    def _setup_animation(
        self, animation: QPropertyAnimation, start_value: float, end_value: float, time: float = 500
    ) -> None:
        """动画属性"""
        animation.setDuration(time)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(start_value)
        animation.setEndValue(end_value)

    def _hide_current_mode(self, mode: str) -> None:
        """隐藏当前模式控件"""
        if mode == 'temperature':
            self._hide_temperature()
        elif mode == 'alert':
            self._hide_alert()
        elif mode == 'reminder':
            self._hide_reminder()

    def _show_target_mode(self, mode: str) -> None:
        """显示目标模式控件"""
        if mode == 'temperature':
            self._fade_in_temperature()
        elif mode == 'alert':
            self._fade_in_alert()
        elif mode == 'reminder':
            self._fade_in_reminder()

    def _fade_in_temperature(self) -> None:
        """淡入温度控件"""
        # 设置状态
        self.showing_temperature = True
        self.showing_alert = False
        self.showing_reminder = False
        if not hasattr(self, 'weather_opacity') or not self.weather_opacity:
            self.weather_opacity = QGraphicsOpacityEffect(self.weather_icon)
            self.weather_icon.setGraphicsEffect(self.weather_opacity)
        if not hasattr(self, 'temperature_opacity') or not self.temperature_opacity:
            self.temperature_opacity = QGraphicsOpacityEffect(self.temperature)
            self.temperature.setGraphicsEffect(self.temperature_opacity)
        try:
            if self.weather_opacity and hasattr(self.weather_opacity, 'opacity'):
                weather_fade_in = QPropertyAnimation(self.weather_opacity, b'opacity')
                self._setup_animation(weather_fade_in, 0.0, 1.0)
            else:
                self.weather_opacity = QGraphicsOpacityEffect(self.weather_icon)
                self.weather_icon.setGraphicsEffect(self.weather_opacity)
                weather_fade_in = QPropertyAnimation(self.weather_opacity, b'opacity')
                self._setup_animation(weather_fade_in, 0.0, 1.0)
        except RuntimeError:
            self.weather_opacity = QGraphicsOpacityEffect(self.weather_icon)
            self.weather_icon.setGraphicsEffect(self.weather_opacity)
            weather_fade_in = QPropertyAnimation(self.weather_opacity, b'opacity')
            self._setup_animation(weather_fade_in, 0.0, 1.0)

        try:
            if self.temperature_opacity and hasattr(self.temperature_opacity, 'opacity'):
                temp_fade_in = QPropertyAnimation(self.temperature_opacity, b'opacity')
                self._setup_animation(temp_fade_in, 0.0, 1.0)
            else:
                self.temperature_opacity = QGraphicsOpacityEffect(self.temperature)
                self.temperature.setGraphicsEffect(self.temperature_opacity)
                temp_fade_in = QPropertyAnimation(self.temperature_opacity, b'opacity')
                self._setup_animation(temp_fade_in, 0.0, 1.0)
        except RuntimeError:
            self.temperature_opacity = QGraphicsOpacityEffect(self.temperature)
            self.temperature.setGraphicsEffect(self.temperature_opacity)
            temp_fade_in = QPropertyAnimation(self.temperature_opacity, b'opacity')
            self._setup_animation(temp_fade_in, 0.0, 1.0)
        fade_in_group = QParallelAnimationGroup(self)
        fade_in_group.addAnimation(weather_fade_in)
        fade_in_group.addAnimation(temp_fade_in)
        try:
            self.weather_opacity.setOpacity(0.0)
            self.temperature_opacity.setOpacity(0.0)
        except RuntimeError:
            pass
        self.weather_icon.show()
        self.temperature.show()
        fade_in_group.start()

    def _fade_in_alert(self) -> None:
        """淡入预警控件"""
        if not self._has_content_for_mode('alert'):
            self._fade_in_temperature()
            return
        self.showing_temperature = False
        self.showing_alert = True
        self.showing_reminder = False
        if not hasattr(self, 'weather_alert_opacity') or not self.weather_alert_opacity:
            self.weather_alert_opacity = QGraphicsOpacityEffect(self.weather_alert_text)
            self.weather_alert_text.setGraphicsEffect(self.weather_alert_opacity)
        if not hasattr(self, 'alert_icon_opacity') or not self.alert_icon_opacity:
            self.alert_icon_opacity = QGraphicsOpacityEffect(self.alert_icon)
            self.alert_icon.setGraphicsEffect(self.alert_icon_opacity)
        self._display_current_alert()
        alert_text_fade_in = QPropertyAnimation(self.weather_alert_opacity, b'opacity')
        alert_icon_fade_in = QPropertyAnimation(self.alert_icon_opacity, b'opacity')
        self._setup_animation(alert_text_fade_in, 0.0, 1.0)
        self._setup_animation(alert_icon_fade_in, 0.0, 1.0)
        fade_in_group = QParallelAnimationGroup(self)
        fade_in_group.addAnimation(alert_text_fade_in)
        fade_in_group.addAnimation(alert_icon_fade_in)
        self.weather_alert_opacity.setOpacity(0.0)
        self.alert_icon_opacity.setOpacity(0.0)
        self.weather_alert_text.show()
        self.alert_icon.show()
        fade_in_group.start()

    def _fade_in_reminder(self) -> None:
        """淡入提醒控件"""
        if not self._has_content_for_mode('reminder'):
            self._fade_in_temperature()
            return
        self.showing_temperature = False
        self.showing_alert = False
        self.showing_reminder = True
        if not hasattr(self, 'reminder_opacity') or not self.reminder_opacity:
            self.reminder_opacity = QGraphicsOpacityEffect(self.weather_reminder_text)
            self.weather_reminder_text.setGraphicsEffect(self.reminder_opacity)
        if not hasattr(self, 'reminder_icon_opacity') or not self.reminder_icon_opacity:
            self.reminder_icon_opacity = QGraphicsOpacityEffect(self.reminder_icon)
            self.reminder_icon.setGraphicsEffect(self.reminder_icon_opacity)
        self._display_current_reminder()
        reminder_text_fade_in = QPropertyAnimation(self.reminder_opacity, b'opacity')
        reminder_icon_fade_in = QPropertyAnimation(self.reminder_icon_opacity, b'opacity')
        self._setup_animation(reminder_text_fade_in, 0.0, 1.0)
        self._setup_animation(reminder_icon_fade_in, 0.0, 1.0)
        fade_in_group = QParallelAnimationGroup(self)
        fade_in_group.addAnimation(reminder_text_fade_in)
        fade_in_group.addAnimation(reminder_icon_fade_in)
        self.reminder_opacity.setOpacity(0.0)
        self.reminder_icon_opacity.setOpacity(0.0)
        self.weather_reminder_text.show()
        self.reminder_icon.show()
        fade_in_group.start()

    def _cycle_to_next_alert_with_animation(self) -> None:
        """在多个预警之间循环切换的动画"""
        if not self.current_alerts or self.current_alert_index >= len(self.current_alerts):
            return
        if not hasattr(self, 'weather_alert_opacity') or not self.weather_alert_opacity:
            self.weather_alert_opacity = QGraphicsOpacityEffect(self.weather_alert_text)
            self.weather_alert_text.setGraphicsEffect(self.weather_alert_opacity)
        if not hasattr(self, 'alert_icon_opacity') or not self.alert_icon_opacity:
            self.alert_icon_opacity = QGraphicsOpacityEffect(self.alert_icon)
            self.alert_icon.setGraphicsEffect(self.alert_icon_opacity)
        alert_text_fade_out = QPropertyAnimation(self.weather_alert_opacity, b'opacity')
        alert_icon_fade_out = QPropertyAnimation(self.alert_icon_opacity, b'opacity')
        self._setup_animation(alert_text_fade_out, 1.0, 0.0, 300)
        self._setup_animation(alert_icon_fade_out, 1.0, 0.0, 300)
        fade_out_group = QParallelAnimationGroup(self)
        fade_out_group.addAnimation(alert_text_fade_out)
        fade_out_group.addAnimation(alert_icon_fade_out)

        def _start_next_alert_fade_in():
            self._display_current_alert()
            alert_text_fade_in = QPropertyAnimation(self.weather_alert_opacity, b'opacity')
            alert_icon_fade_in = QPropertyAnimation(self.alert_icon_opacity, b'opacity')
            self._setup_animation(alert_text_fade_in, 0.0, 1.0, 300)
            self._setup_animation(alert_icon_fade_in, 0.0, 1.0, 300)
            fade_in_group = QParallelAnimationGroup(self)
            fade_in_group.addAnimation(alert_text_fade_in)
            fade_in_group.addAnimation(alert_icon_fade_in)
            self.weather_alert_opacity.setOpacity(0.0)
            self.alert_icon_opacity.setOpacity(0.0)
            fade_in_group.start()

        with contextlib.suppress(TypeError):
            fade_out_group.finished.disconnect()
        fade_out_group.finished.connect(_start_next_alert_fade_in)
        fade_out_group.start()

    def _cycle_to_next_reminder_with_animation(self) -> None:
        """提醒循环切换动画"""
        if not self.current_reminders or self.current_reminder_index >= len(self.current_reminders):
            return
        if not hasattr(self, 'reminder_opacity') or not self.reminder_opacity:
            self.reminder_opacity = QGraphicsOpacityEffect(self.weather_reminder_text)
            self.weather_reminder_text.setGraphicsEffect(self.reminder_opacity)
        if not hasattr(self, 'reminder_icon_opacity') or not self.reminder_icon_opacity:
            self.reminder_icon_opacity = QGraphicsOpacityEffect(self.reminder_icon)
            self.reminder_icon.setGraphicsEffect(self.reminder_icon_opacity)
        reminder_text_fade_out = QPropertyAnimation(self.reminder_opacity, b'opacity')
        reminder_icon_fade_out = QPropertyAnimation(self.reminder_icon_opacity, b'opacity')
        self._setup_animation(reminder_text_fade_out, 1.0, 0.0, 300)
        self._setup_animation(reminder_icon_fade_out, 1.0, 0.0, 300)
        fade_out_group = QParallelAnimationGroup(self)
        fade_out_group.addAnimation(reminder_text_fade_out)
        fade_out_group.addAnimation(reminder_icon_fade_out)

        def _start_next_reminder_fade_in():
            # 下一个提醒
            self._display_current_reminder()
            reminder_text_fade_in = QPropertyAnimation(self.reminder_opacity, b'opacity')
            reminder_icon_fade_in = QPropertyAnimation(self.reminder_icon_opacity, b'opacity')
            self._setup_animation(reminder_text_fade_in, 0.0, 1.0, 300)
            self._setup_animation(reminder_icon_fade_in, 0.0, 1.0, 300)
            fade_in_group = QParallelAnimationGroup(self)
            fade_in_group.addAnimation(reminder_text_fade_in)
            fade_in_group.addAnimation(reminder_icon_fade_in)
            self.reminder_opacity.setOpacity(0.0)
            self.reminder_icon_opacity.setOpacity(0.0)
            fade_in_group.start()

        with contextlib.suppress(TypeError):
            fade_out_group.finished.disconnect()
        fade_out_group.finished.connect(_start_next_reminder_fade_in)
        fade_out_group.start()

    def _hide_reminder(self) -> None:
        """隐藏提醒控件"""
        self.weather_reminder_text.hide()
        self.reminder_icon.hide()
        self.showing_reminder = False

    def _hide_temperature(self) -> None:
        """隐藏温度控件"""
        self.weather_icon.hide()
        self.temperature.hide()
        self.showing_temperature = False

    def _hide_alert(self) -> None:
        """隐藏预警控件"""
        self.weather_alert_text.hide()
        self.alert_icon.hide()
        self.showing_alert = False

    def _display_current_alert(self) -> None:
        """显示当前索引的预警信息"""
        if not hasattr(self, 'current_alerts') or not self.current_alerts:
            return
        if not hasattr(self, 'current_alert_index'):
            self.current_alert_index = 0
        if self.current_alert_index >= len(self.current_alerts):
            self.current_alert_index = 0
        current_alert = self.current_alerts[self.current_alert_index]

        alert_title = db.simplify_alert_text(current_alert.get('title'))
        if len(alert_title) > 6:
            alert_text = alert_title  # 极端情况去除预警二字
        else:
            alert_text = alert_title + '预警'
        char_count = len(alert_text)
        font = self.weather_alert_text.font()
        if char_count <= 4:
            font.setPointSize(14)
            self.weather_alert_text.setFixedWidth(76)
        elif char_count == 5:
            font.setPointSize(13)
            self.weather_alert_text.setFixedWidth(85)
        elif char_count == 6:
            font.setPointSize(12)
            self.weather_alert_text.setFixedWidth(95)
        elif char_count == 7:
            font.setPointSize(11)
            self.weather_alert_text.setFixedWidth(105)
        elif char_count == 8:
            font.setPointSize(10)
            self.weather_alert_text.setFixedWidth(115)
        else:
            font.setPointSize(9)
            self.weather_alert_text.setFixedWidth(min(125, 76 + char_count * 8))
        self.weather_alert_text.setFont(font)
        self.weather_alert_text.setText(alert_text)
        self.weather_alert_text.setAlignment(Qt.AlignCenter)
        severity = current_alert.get('severity', 'unknown')
        if hasattr(self, 'alert_icon'):
            icon_path = db.get_alert_icon_by_severity(severity)
            if icon_path and os.path.exists(icon_path):
                try:
                    icon = QIcon(icon_path)
                    if not icon.isNull():
                        self.alert_icon.setIcon(icon)
                    else:
                        logger.warning(f'无法创建图标对象: {icon_path}')
                except Exception as e:
                    logger.error(f'设置预警图标失败: {e}')
            else:
                logger.warning(f'预警图标文件不存在: {icon_path}')

    def _reset_weather_alert_state(self) -> None:
        """重置天气预警、提醒显示状态"""
        for timer_name in ['weather_alert_timer']:
            timer = getattr(self, timer_name, None)
            if timer:
                timer.stop()
        self.showing_temperature = True
        self.showing_alert = False
        self.showing_reminder = False

        self.current_alerts = getattr(self, 'current_alerts', [])
        self.current_alerts.clear()
        self.current_alert_index = 0

        self.current_reminders = []
        self.current_reminder_index = 0

        for element_name in ['weather_alert_text', 'alert_icon']:
            element = getattr(self, element_name, None)
            if element:
                element.hide()
        for element_name in [
            'weather_icon',
            'temperature',
            'weather_reminder_text',
            'reminder_icon',
        ]:
            element = getattr(self, element_name, None)
            if element:
                element.hide()
        for element_name in ['weather_icon', 'temperature']:
            element = getattr(self, element_name, None)
            if element:
                element.show()
                if hasattr(element, 'graphicsEffect') and element.graphicsEffect():
                    element.setGraphicsEffect(None)

    def _display_current_reminder(self) -> None:
        """显示当前索引的提醒信息"""
        if not self.current_reminders or self.current_reminder_index >= len(self.current_reminders):
            return
        reminder = self.current_reminders[self.current_reminder_index]
        # 提醒文本
        self.weather_reminder_text.setText(reminder['title'])
        # 调整字号
        char_count = len(reminder['title'])
        if char_count <= 5:
            font_size = 14
        elif char_count <= 10:
            font_size = 13
        elif char_count <= 12:
            font_size = 12
        else:
            font_size = 11
        font = self.weather_reminder_text.font()
        font.setPointSize(font_size)
        self.weather_reminder_text.setFont(font)

        # 设置图标, 布局
        content_layout = self.findChild(QHBoxLayout, 'horizontalLayout_2')
        if char_count <= 6:
            if content_layout.indexOf(self.reminder_icon) == -1:
                text_index = content_layout.indexOf(self.weather_reminder_text)
                if text_index != -1:
                    content_layout.insertWidget(text_index, self.reminder_icon)
                else:
                    content_layout.addWidget(self.reminder_icon)
            try:
                icon_path = CW_HOME / "img/weather/reminders" / f"{reminder['icon']}.svg"
                if icon_path.exists():
                    self.reminder_icon.setIcon(str(icon_path))
                    self.reminder_icon.show()
                else:
                    logger.warning(f'天气提醒图标不存在: {icon_path}')
                    self.reminder_icon.hide()
            except Exception as e:
                logger.warning(f'设置天气提醒图标失败: {e}')
                self.reminder_icon.hide()

            if char_count == 6:
                self.weather_reminder_text.setFixedWidth(102)
            else:
                self.weather_reminder_text.setFixedWidth(96)
        else:
            if content_layout.indexOf(self.reminder_icon) != -1:
                content_layout.removeWidget(self.reminder_icon)
                self.reminder_icon.hide()
            self.weather_reminder_text.setFixedWidth(138)

    def detect_theme_changed(self) -> None:
        theme_ = config_center.read_conf('General', 'theme')
        color_mode = config_center.read_conf('General', 'color_mode')
        widgets = list_.get_widget_config()
        if (
            theme_ != self.last_theme
            or color_mode != self.last_color_mode
            or widgets != self.last_widgets
        ):
            self.last_theme = theme_
            self.last_color_mode = color_mode
            self.last_widgets = widgets
            logger.info(f'切换主题：{theme_}，颜色模式{color_mode}')
            mgr.clear_widgets()

    def update_weather_data(
        self, weather_data: Dict[str, Any]
    ) -> None:  # 更新天气数据(已兼容多api)
        global weather_name, temperature, weather_data_temp
        if (
            type(weather_data) is dict
            and hasattr(self, 'weather_icon')
            and 'error' not in weather_data
        ):
            logger.success('已获取天气数据')
            original_weather_data = weather_data.copy()
            weather_data = weather_data.get('now')
            weather_data_temp = weather_data
            self._reset_weather_alert_state()
            try:
                # 更新数据
                weather_manager.current_weather_data = original_weather_data
                # 初始化预警和提醒数据
                self.current_alerts = []
                self.current_alert_index = 0
                self.current_reminders = []
                self.current_reminder_index = 0
                if hasattr(self, 'reminder_thread') and self.reminder_thread.isRunning():
                    self.reminder_thread.stop()
                    self.reminder_thread.wait(1000)  # 等待线程结束

                if not hasattr(self, 'reminder_thread') or not self.reminder_thread.isRunning():
                    from weather import WeatherReminderThread

                    self.reminder_thread = WeatherReminderThread(
                        weather_manager, original_weather_data
                    )
                    self.reminder_thread.reminders_ready.connect(self._on_reminders_ready)
                    self.reminder_thread.alerts_ready.connect(self._on_alerts_ready)
                    self.reminder_thread.start()

            except Exception as e:
                logger.warning(f'初始化预警和提醒数据失败：{e}')
                self.current_alerts = []
                self.current_alert_index = 0
                self.current_reminders = []
                self.current_reminder_index = 0

            weather_name = db.get_weather_by_code(db.get_weather_data('icon', weather_data))
            temp_data = db.get_weather_data('temp', weather_data)
            if temp_data and temp_data.lower() != 'none':
                temperature = db.weather_processor.convert_temperature_unit(temp_data)
            else:
                temperature = f'--{get_default_temperature_unit()}'
            current_city = self.findChild(QLabel, 'current_city')
            try:
                path = db.get_weather_icon_by_code(db.get_weather_data('icon', weather_data))
                self.weather_icon.setIcon(QIcon(path))
                self.alert_icon.hide()
                if settings and hasattr(settings, '_on_weather_data_ready'):
                    settings._on_weather_data_ready(original_weather_data)

                temp_data = db.get_weather_data('temp', weather_data)
                if temp_data and temp_data.lower() != 'none':
                    converted_temp = db.weather_processor.convert_temperature_unit(temp_data)
                    self.temperature.setText(converted_temp)
                else:
                    self.temperature.setText(f'--{get_default_temperature_unit()}')
                location_key = config_center.read_conf('Weather', 'city')
                city_name = db.search_by_num(location_key)
                if city_name != 'coordinates':
                    font_metrics = current_city.fontMetrics()
                    text_full = f"{city_name} · {weather_name}"
                    full_width = font_metrics.horizontalAdvance(text_full)
                    max_width = current_city.width()
                    if full_width > max_width:
                        current_city.setText(weather_name)
                    else:
                        current_city.setText(text_full)
                else:
                    current_city.setText(f'{weather_name}')
                    if ',' in location_key:
                        try:
                            lon, lat = location_key.split(',')
                            if lat and lon:
                                if not hasattr(self, '_city_threads'):
                                    self._city_threads = []
                                city_thread = getCity('city_from_coordinates')
                                city_thread.set_coordinates(lat, lon)

                                def update_city_name(name, key):
                                    if name:
                                        font_metrics = current_city.fontMetrics()
                                        text_full = f"{name} · {weather_name}"
                                        full_width = font_metrics.horizontalAdvance(text_full)
                                        max_width = current_city.width()
                                        if full_width > max_width:
                                            current_city.setText(weather_name)
                                        else:
                                            current_city.setText(text_full)

                                def cleanup_thread():
                                    if (
                                        hasattr(self, '_city_threads')
                                        and city_thread in self._city_threads
                                    ):
                                        self._city_threads.remove(city_thread)

                                city_thread.city_info_signal.connect(update_city_name)
                                city_thread.finished_signal.connect(cleanup_thread)
                                city_thread.start()
                                self._city_threads.append(city_thread)
                        except Exception as e:
                            logger.error(f"获取城市名称失败: {e}")
                icon_code = db.get_weather_data('icon', weather_data)
                path = db.get_weather_stylesheet(icon_code).replace('\\', '/')
                update_stylesheet = re.sub(
                    r'border-image: url\([^)]*\);',
                    f"border-image: url({path});",
                    self.backgnd.styleSheet(),
                )
                self.backgnd.setStyleSheet(update_stylesheet)
            except Exception as e:
                logger.error(f'天气组件出错：{e}')
        else:
            logger.error(f'获取天气数据出错：{weather_data}')
            try:
                if hasattr(self, 'weather_icon'):
                    self.weather_icon.setIcon(QIcon(f'{CW_HOME / "img/weather/99.svg"}'))
                    self.alert_icon.hide()
                    self.weather_alert_text.hide()
                    self.temperature.setText(f'--{get_default_temperature_unit()}')
                    self.current_alerts = []
                    self.current_alert_index = 0
                    self.current_reminders = []
                    self.current_reminder_index = 0
                    if hasattr(self, 'weather_alert_timer') and self.weather_alert_timer:
                        self.weather_alert_timer.stop()
                        self._reset_weather_alert_state()
                    current_city = self.findChild(QLabel, 'current_city')
                    if current_city:
                        city_name = db.search_by_num(config_center.read_conf('Weather', 'city'))
                        if city_name != 'coordinates':
                            current_city.setText(self.tr("{city} · 未知").format(city=city_name))
                        else:
                            current_city.setText(self.tr("未知"))
                    if hasattr(self, 'backgnd'):
                        path = db.get_weather_stylesheet('99').replace('\\', '/')
                        update_stylesheet = re.sub(
                            r'border-image: url\([^)]*\);',
                            f"border-image: url({path});",
                            self.backgnd.styleSheet(),
                        )
                        self.backgnd.setStyleSheet(update_stylesheet)
            except Exception as e:
                logger.error(f'天气图标设置失败：{e}')

    def update_weather_timer_interval(self, minutes: int) -> None:
        """更新天气定时器间隔"""
        try:
            if hasattr(self, 'weather_callback_id') and self.weather_callback_id:
                update_timer.remove_callback_by_id(self.weather_callback_id)
            self.weather_callback_id = update_timer.add_callback(
                self.get_weather_data, interval=minutes * 60  # 转换为秒
            )
            # logger.debug(f'天气定时器间隔已更新为 {minutes} 分钟')
        except Exception as e:
            logger.error(f'更新天气定时器间隔失败: {e}')

    def open_extra_menu(self) -> None:
        global ex_menu
        if ex_menu is None or not ex_menu.isVisible():
            ex_menu = ExtraMenu()
            ex_menu.main_window = self
            ex_menu.show()
            ex_menu.destroyed.connect(self.cleanup_extra_menu)
            logger.info('打开"额外选项"')
        else:
            ex_menu.raise_()
            ex_menu.activateWindow()

    @staticmethod
    def cleanup_extra_menu() -> None:
        global ex_menu
        ex_menu = None

    @staticmethod
    def hide_show_widgets() -> None:  # 隐藏/显示主界面（全部隐藏）
        hide_mode = config_center.read_conf('General', 'hide')
        if hide_mode in {'1', '2'}:
            hide_mode_text = (
                QCoreApplication.translate('main', "上课时自动隐藏")
                if hide_mode == '1'
                else QCoreApplication.translate('main', "窗口最大化时隐藏")
            )
            w = Dialog(
                QCoreApplication.translate('main', "暂时无法变更“状态”"),
                QCoreApplication.translate(
                    'main',
                    "您正在使用 {hide_mode_text} 模式，无法变更隐藏状态\n"
                    "若变更状态，将修改隐藏模式“灵活隐藏” (您稍后可以在“设置”中更改此选项)\n"
                    "您确定要隐藏组件吗?",
                ).format(hide_mode_text=hide_mode_text),
                None,
            )
            w.yesButton.setText(QCoreApplication.translate('main', "确定"))
            w.yesButton.clicked.connect(lambda: config_center.write_conf('General', 'hide', '3'))
            w.cancelButton.setText(QCoreApplication.translate('main', "取消"))
            w.buttonLayout.insertStretch(1)
            w.setFixedWidth(550)
            if w.exec():
                if mgr.state:
                    mgr.full_hide_windows()
                else:
                    mgr.show_windows()
        elif mgr.state:
            mgr.full_hide_windows()
        else:
            mgr.show_windows()

    @staticmethod
    def minimize_to_floating() -> None:  # 最小化到浮窗
        hide_mode = config_center.read_conf('General', 'hide')
        if hide_mode in {'1', '2'}:
            hide_mode_text = (
                QCoreApplication.translate('main', "上课时自动隐藏")
                if hide_mode == '1'
                else QCoreApplication.translate('main', "窗口最大化时隐藏")
            )
            w = Dialog(
                QCoreApplication.translate('main', "暂时无法变更“状态”"),
                QCoreApplication.translate(
                    'main',
                    "您正在使用 {hide_mode_text} 模式，无法变更隐藏状态\n"
                    "若变更状态，将修改隐藏模式“灵活隐藏” (您可以在“设置”中更改此选项)\n"
                    "您确定要隐藏组件吗?",
                ).format(hide_mode_text=hide_mode_text),
                None,
            )
            w.yesButton.setText(QCoreApplication.translate('main', "确定"))
            w.yesButton.clicked.connect(lambda: config_center.write_conf('General', 'hide', '3'))
            w.cancelButton.setText(QCoreApplication.translate('main', "取消"))
            w.buttonLayout.insertStretch(1)
            w.setFixedWidth(550)
            if w.exec():
                if mgr.state:
                    fw.show()
                    if utils.focus_manager:
                        QTimer.singleShot(
                            0,
                            lambda w=fw: utils.focus_manager.ignore.emit(
                                ctypes.c_void_p(int(w.winId())).value
                            ),
                        )
                    mgr.full_hide_windows()
                else:
                    mgr.show_windows()
        elif mgr.state:
            fw.show()
            if utils.focus_manager:
                QTimer.singleShot(
                    0,
                    lambda w=fw: utils.focus_manager.ignore.emit(
                        ctypes.c_void_p(int(w.winId())).value
                    ),
                )
            mgr.full_hide_windows()
        else:
            mgr.show_windows()

    def clear_animation(self) -> None:  # 清除动画
        self.animation = None

    def animate_window(self, target_pos: Tuple[int, int]) -> None:  # **初次**启动动画
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

    def animate_hide(self, full: bool = False) -> None:  # 隐藏窗口
        global theme

        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(625)  # 持续时间
        height = self.height()
        self.setFixedHeight(height)  # 防止连续打断窗口高度变小

        theme_info = conf.load_theme_config(str('default' if theme is None else theme))

        if full and os.name == 'nt':
            '''全隐藏 windows'''
            self.animation.setEndValue(QRect(self.x(), -height, self.width(), self.height()))
        elif os.name == 'nt':
            '''半隐藏 windows'''
            self.animation.setEndValue(
                QRect(self.x(), -height + theme_info.config.delta, self.width(), self.height())
            )
        else:
            '''其他系统'''
            self.animation.setEndValue(QRect(self.x(), 0, self.width(), self.height()))
            self.animation.finished.connect(lambda: self.hide())

        self.animation.setEasingCurve(QEasingCurve.Type.OutExpo)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_hide_opacity(self) -> None:  # 隐藏窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)  # 持续时间
        self.animation.setStartValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.close)

    def animate_show_opacity(self) -> None:  # 显示窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(350)  # 持续时间
        self.animation.setStartValue(0)
        self.animation.setEndValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_show(self) -> None:  # 显示窗口
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(525)  # 持续时间
        # 获取当前窗口的宽度和高度，确保动画过程中保持一致
        margin = max(0, int(config_center.read_conf('General', 'margin')))
        self.animation.setEndValue(QRect(self.x(), margin, self.width(), self.height()))
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.finished.connect(self.clear_animation)

        if os.name != 'nt':
            self.show()

        self.animation.start()

    def widget_transition(
        self, pos_x: int, width: int, height: int, opacity: float = 1, pos_y: Optional[int] = None
    ) -> None:  # 窗口形变
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(525)  # 持续时间
        self.animation.setStartValue(QRect(self.x(), self.y(), self.width(), self.height()))
        if pos_y is None:
            pos_y = max(0, int(config_center.read_conf('General', 'margin')))
        self.animation.setEndValue(QRect(pos_x, pos_y, width, height))
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
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            return  # 右键不执行
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
        if utils.focus_manager:
            utils.focus_manager.restore_requested.emit()

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


# 正则表达式和排除列表(预编译)
_EXCLUDED_TITLES = {
    'residentsidebar',  # 希沃侧边栏
    'program manager',  # Windows桌面
    'desktop',  # Windows桌面 (备用)
    'snippingtool',  # 系统截图工具
}
_EXCLUDED_KEYWORDS = {
    'overlay',
    'snipping',
    'sidebar',
    'flyout',
}
_EXCLUDED_PROCESSES = {
    'shellexperiencehost.exe',
    'searchui.exe',
    'startmenuexperiencehost.exe',
    'applicationframehost.exe',
    'systemsettings.exe',
    'taskmgr.exe',
}
_IGNORED_PROCESSES = {'easinote.exe'}


@lru_cache(maxsize=256)  # O(n)正则
def _should_exclude_window(title: str, process_name: str) -> bool:
    """检查窗口是否应该被排除"""
    title_lower = title.lower()
    if process_name in _IGNORED_PROCESSES:
        return True
    if process_name in _EXCLUDED_PROCESSES:
        return True
    if title_lower in _EXCLUDED_TITLES:
        return True
    if any(keyword in title_lower for keyword in _EXCLUDED_KEYWORDS):
        return True
    if process_name == 'explorer.exe':
        return title_lower in _EXCLUDED_TITLES or any(k in title_lower for k in _EXCLUDED_KEYWORDS)
    return False


def check_windows_maximize() -> bool:
    """检查是否有窗口最大化"""
    if os.name != 'nt':
        return False
    current_pid = os.getpid()
    try:
        all_windows = pygetwindow.getAllWindows()
    except Exception as e:
        logger.warning(f"获取窗口列表时发生错误 (pygetwindow): {e!s}")
        return False

    for window in all_windows:
        try:
            if not all([window._hWnd, window.visible, window.isMaximized]):
                continue
            try:
                hwnd_int = window._hWnd
                pid_val = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd_int, ctypes.byref(pid_val))
                win_pid = pid_val.value  # 获取进程信息
                if win_pid in (0, current_pid):
                    continue
                process_name = psutil.Process(win_pid).name().lower()
                title = window.title.strip()
                if not _should_exclude_window(title, process_name):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, ValueError, OSError):
                continue

        except Exception as e:
            title = getattr(window, 'title', 'N/A') if window else '未知窗口'
            logger.debug(f"处理窗口 '{title}' 时发生错误: {e!s}")
            continue

    return False


def get_default_temperature_unit() -> str:
    """获取配置的温度单位"""
    return config_center.read_conf('Weather', 'temperature_unit', '℃')


def init_config() -> None:  # 重设配置文件
    config_center.write_conf('Temp', 'set_week', '')
    config_center.write_conf('Temp', 'set_schedule', '')
    if config_center.read_conf('Temp', 'temp_schedule') != '':  # 修复换课重置
        copy(SCHEDULE_DIR / "backup.json", SCHEDULE_DIR / str(config_center.schedule_name))
        config_center.write_conf('Temp', 'temp_schedule', '')


def init() -> None:
    global theme, radius, mgr, screen_width, first_start, fw, was_floating_mode
    update_timer.remove_all_callbacks()
    if utils.focus_manager:
        utils.focus_manager.update_callback()

    global_i18n_manager.scan_available_languages()

    theme = load_theme_config(config_center.read_conf('General', 'theme')).path.name  # 主题
    logger.info(f'应用主题：{theme}')
    setTheme_()

    mgr = WidgetsManager()
    utils.main_mgr = mgr
    fw = FloatingWidget()

    widgets = list_.get_widget_config()

    for widget in widgets:  # 检查组件
        if widget not in list_.widget_name:
            widgets.remove(widget)  # 移除不存在的组件(确保移除插件后不会出错)

    mgr.init_widgets()
    if not first_start and was_floating_mode and fw:
        fw.show()
        if utils.focus_manager:
            QTimer.singleShot(
                0,
                lambda w=fw: utils.focus_manager.ignore.emit(ctypes.c_void_p(int(w.winId())).value),
            )
        mgr.full_hide_windows()

    update_timer.add_callback(mgr.update_widgets, interval=0.25)
    update_timer.add_callback(p_loader.update_plugins, interval=1)
    update_timer.start()

    version = config_center.read_conf("Version", "version")
    if version == "__BUILD_VERSION__":
        version = "DEBUG"
    build_uuid = config_center.read_conf("Version", "build_runid") or "(Debug)"
    build_type = config_center.read_conf("Version", "build_type")
    logger.debug('Class Widgets 版本信息:')
    if "__BUILD_RUNID__" in build_uuid or "__BUILD_TYPE__" in build_type:
        logger.debug(f'├── 版本号: {version}')
        logger.debug('├── 构建ID: Debug')
        logger.debug('└── 构建类型: Debug')
    else:
        logger.debug(f'├── 版本号: {version}')
        logger.debug(f'├── 构建ID: {build_uuid}')
        logger.debug(f'└── 构建类型: {build_type}')
    logger.success('Class Widgets 初始化完成!')
    p_loader.run_plugins()  # 运行插件

    first_start = False


def setup_signal_handlers_optimized(app: QApplication) -> None:
    """退出信号处理器"""

    def signal_handler(signum, frame):
        logger.debug(f'收到信号 {signal.Signals(signum).name},退出...')
        # utils.stop 处理退出
        utils.stop(0)

    signal.signal(signal.SIGTERM, signal_handler)  # taskkill
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    if os.name == 'posix':
        signal.signal(signal.SIGQUIT, signal_handler)  # 终端退出
        signal.signal(signal.SIGHUP, signal_handler)  # 终端挂起


if __name__ == '__main__':
    splash_window.update_status((10, QCoreApplication.translate('main', '检查多开...')))
    utils.guard = utils.SingleInstanceGuard("ClassWidgets.lock")

    old_config_file = CW_HOME / "config.ini"
    if old_config_file.exists():
        old_config_file.replace(CONFIG_HOME / "config.ini")

    if config_center.read_conf('Other', 'multiple_programs') != '1':
        if not utils.guard.try_acquire() and (info := utils.guard.get_lock_info()):
            splash_window.error()
            logger.debug(f'不允许多开实例，{info}')
            from qfluentwidgets import Dialog

            app = QApplication.instance() or QApplication(sys.argv)
            dlg = Dialog(
                QCoreApplication.translate('main', 'Class Widgets 正在运行'),
                QCoreApplication.translate(
                    'main',
                    'Class Widgets 正在运行！请勿打开多个实例，否则将会出现不可预知的问题。'
                    '\n(若您需要打开多个实例，请在“设置”->“高级选项”中启用“允许程序多开”)',
                ),
            )
            dlg.yesButton.setText(QCoreApplication.translate('main', '好'))
            dlg.cancelButton.hide()
            dlg.buttonLayout.insertStretch(0, 1)
            dlg.setFixedWidth(550)
            dlg.exec()
            sys.exit(0)

    scale_factor = float(config_center.read_conf('General', 'scale'))
    logger.info(f"当前缩放系数：{scale_factor * 100}%")
    app.setQuitOnLastWindowClosed(False)

    logger.debug(
        f"i18n加载,界面: {global_i18n_manager.get_current_language_view_name()},组件: {global_i18n_manager.get_current_language_widgets_name()}"
    )
    menu.global_i18n_manager = global_i18n_manager

    logger.debug(f"是否允许多开实例：{config_center.read_conf('Other', 'multiple_programs')}")

    splash_window.update_status((20, QCoreApplication.translate('main', '初始化颜色监视器...')))

    try:
        dark_mode_watcher = DarkModeWatcher()
        dark_mode_watcher.dark_mode_changed.connect(handle_dark_mode_change)  # 连接信号
        # 初始主题设置依赖于 dark_mode_changed 信号
    except Exception as e:
        logger.error(f"初始化颜色模式监测器时出错: {e}")
        dark_mode_watcher = None

    splash_window.update_status((30, QCoreApplication.translate('main', '检查缩放...')))

    if scale_factor > 1.8 or scale_factor < 1.0:
        splash_window.error()
        logger.warning("当前缩放系数可能导致显示异常，建议使缩放系数在 100% 到 180% 之间")
        msg_box = Dialog(
            QCoreApplication.translate('main', '缩放系数过大'),
            QCoreApplication.translate(
                'main',
                "当前缩放系数为 {scale_factor}%，可能导致显示异常。\n建议将缩放系数设置为 100% 到 180% 之间。",
            ).format(scale_factor=scale_factor * 100),
        )
        msg_box.yesButton.setText(QCoreApplication.translate('main', '好'))
        msg_box.cancelButton.hide()
        msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()
        splash_window.unerror()

    splash_window.update_status((40, QCoreApplication.translate('main', '获取系统版本...')))

    system = platform.system()
    arch = platform.machine()
    python_version = platform.python_version()
    os_release = platform.release()
    os_version = platform.version()

    if system == 'Windows':
        os_release = f"Windows {os_release}"
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
            ) as key:
                build_number = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
                display_version = winreg.QueryValueEx(key, "DisplayVersion")[0]
                os_version = f"Build {build_number} ({display_version}) ({os_version})"
        except Exception:
            pass
    elif system == 'Darwin':
        system = 'macOS'
        os_release = f"Darwin Kernel Version {os_release}"
        os_version = f"macOS {platform.mac_ver()[0]}"
    elif system == 'Linux':
        try:
            import distro

            name = distro.name()
            version = distro.version()
            id_ = distro.id()
            os_version = f"{name} {version} ({id_})"
        except ImportError:
            pass
    logger.debug("系统环境信息:")
    logger.debug(f"├─操作系统: {system} {arch}")
    logger.debug(f"├─系统版本: {os_release}")
    logger.debug(f"├─详细版本: {os_version}")
    logger.debug(f"└─Python版本: {python_version} ({platform.python_implementation()})")

    if system == 'Windows':
        splash_window.update_status(
            (45, QCoreApplication.translate('main', '初始化窗口焦点监视器...'))
        )
        utils.focus_manager = utils.PreviousWindowFocusManager()

    # list_pyttsx3_voices()

    splash_window.update_status((50, QCoreApplication.translate('main', '初始化窗口管理器...')))

    mgr = WidgetsManager()
    app.aboutToQuit.connect(mgr.cleanup_resources)
    setup_signal_handlers_optimized(app)
    utils.main_mgr = mgr

    splash_window.update_status((55, QCoreApplication.translate('main', '检查初次启动...')))

    if config_center.read_conf('Other', 'initialstartup') == '1':  # 首次启动
        try:
            utils.add_shortcut('ClassWidgets.exe', str(CW_HOME / 'img/favicon.ico'))
            utils.add_shortcut_to_startmenu(
                str(CW_HOME / 'ClassWidgets.exe'), str(CW_HOME / 'img/favicon.ico')
            )
            config_center.write_conf('Other', 'initialstartup', '')
        except Exception as e:
            logger.error(f'添加快捷方式失败：{e}')

    splash_window.update_status((60, QCoreApplication.translate('main', '初始化插件管理器...')))

    p_mgr = PluginManager()
    p_loader.set_manager(p_mgr)
    p_loader.load_plugins()

    splash_window.update_status((70, QCoreApplication.translate('main', '检查临时课表...')))

    if conf.is_temp_week():
        splash_window.error()
        w = Dialog(
            QCoreApplication.translate('main', "存在临时课表"),
            QCoreApplication.translate('main', "当前存在临时课表，是否沿用"),
        )
        w.buttonLayout.insertStretch(0, 1)
        w.setFixedWidth(550)
        if not w.exec():
            init_config()
            splash_window.schedule_updater()
        splash_window.unerror()
    else:
        splash_window.schedule_updater()

    schedule_center.update_schedule()

    splash_window.update_status((91, QCoreApplication.translate('main', '加载窗口...')))

    init()

    splash_window.update_status((95, QCoreApplication.translate('main', '加载课程...')))

    get_start_time()
    get_current_lessons()
    get_current_lesson_name()
    get_next_lessons()

    splash_window.update_status((98, QCoreApplication.translate('main', '加载隐藏状态...')))

    hide_mode = config_center.read_conf('General', 'hide')
    should_hide = False
    if hide_mode == '1':  # 上课自动隐藏
        should_hide = current_state == 1  # 判断是否为上课状态
    elif hide_mode == '2':  # 全屏自动隐藏
        should_hide = check_windows_maximize() or check_fullscreen()  # 检查是否全屏
    elif hide_mode == '3':  # 灵活隐藏
        should_hide = current_state == 1

    if should_hide:
        mgr.decide_to_hide()

    if current_state == 1:
        setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}")
    else:
        setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")

    splash_window.update_status((100, QCoreApplication.translate('main', '检查更新...')))

    # w = ErrorDialog()
    # w.exec()
    if config_center.read_conf('Version', 'auto_check_update', '1') == '1':
        check_update()

    splash_window.close()

    status = app.exec()

    utils.stop(status)
