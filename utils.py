import asyncio
import atexit
import datetime as dt
import gc
import inspect
import os
import re
import signal
import sys
import threading
import time
import weakref
from abc import ABC, abstractmethod
from heapq import heapify, heappop, heappush
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple, Type, Union

if os.name == 'nt':
    import win32gui
    from win32com.client import Dispatch

import darkdetect
import ntplib
import psutil
import pytz
from loguru import logger
from PyQt5.QtCore import (
    QDir,
    QLockFile,
    QObject,
    QTimer,
    QtMsgType,
    pyqtSignal,
    qInstallMessageHandler,
)
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon

from basic_dirs import CW_HOME, LOG_HOME
from file import config_center
from generate_speech import get_tts_service


class StreamToLogger:
    """重定向 print() 到 loguru"""

    def write(self, message):
        msg = message.strip()
        if msg:
            logger.opt(depth=1).info(msg)

    def flush(self):
        pass


def qt_message_handler(mode, context, message):  # noqa
    """Qt 消息转发到 loguru"""
    msg = message.strip()
    if not msg:
        return
    if mode == QtMsgType.QtCriticalMsg:
        logger.error(msg)
        logger.complete()
    elif mode == QtMsgType.QtFatalMsg:
        logger.critical(msg)
        logger.complete()
    else:
        logger.complete()


if config_center.read_conf("Other", "do_not_log") == "0":
    log_file = LOG_HOME / "ClassWidgets_main_{time}.log"
    logger.add(
        log_file,
        rotation="1 MB",
        retention="1 minute",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )
    sys.stdout = StreamToLogger()
    sys.stderr = StreamToLogger()
    qInstallMessageHandler(qt_message_handler)
    atexit.register(logger.complete)
    logger.debug("未禁用日志输出")
else:
    logger.info("已禁用日志输出功能, 若需保存日志, 请在“设置”->“高级选项”中关闭禁用日志功能")


def run_once(func: Callable) -> Callable:
    """装饰器: 只执行一次"""

    def wrapper(*args, **kwargs):
        if not wrapper.has_run:
            wrapper.has_run = True
            return func(*args, **kwargs)
        return None

    wrapper.has_run = False
    return wrapper


LOGO_PATH = CW_HOME / "img" / "logo"
CallbackInfoType = Dict[str, Union[float, dt.datetime]]
TaskHeapType = List[Tuple[dt.datetime, int, Callable[[], Any], float]]


def _reset_signal_handlers() -> None:
    """重置信号处理器为默认状态"""
    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass


def _terminate_child_processes() -> None:
    """终止所有子进程"""
    try:
        parent = psutil.Process(os.getpid())
        children = parent.children(recursive=True)
        if not children:
            return
        logger.debug(f"尝试终止 {len(children)} 个子进程...")
        for child in children:
            try:
                logger.debug(f"终止子进程 {child.pid}...")
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.debug(f"子进程 {child.pid}: {e}")
            except Exception as e:
                logger.warning(f"终止子进程 {child.pid} 时出错: {e}")
        _gone, alive = psutil.wait_procs(children, timeout=1.5)
        if alive:
            logger.warning(f"{len(alive)} 个子进程未在规定时间内终止,将强制终止...")
            for p in alive:
                try:
                    logger.debug(f"强制终止子进程 {p.pid}...")
                    p.kill()
                except psutil.NoSuchProcess:
                    logger.debug(f"子进程 {p.pid} 在强制终止前已消失.")
                except Exception as e:
                    logger.error(f"强制终止子进程 {p.pid} 失败: {e}")

    except psutil.NoSuchProcess:
        logger.warning("无法获取当前进程信息,跳过子进程终止。")
    except Exception as e:
        logger.error(f"终止子进程时出现意外错误: {e}")


def restart() -> None:
    """重启程序"""
    logger.debug('重启程序')

    app = QApplication.instance()
    if app:
        _reset_signal_handlers()
        app.quit()
        app.processEvents()

    guard.release()

    os.execl(sys.executable, sys.executable, *sys.argv)


@run_once
def stop(status: int = 0) -> None:
    """
    退出程序

    :param status: 退出状态码,0=正常退出,!=0表示异常退出
    """
    logger.debug('退出程序...')

    try:
        tts_service = get_tts_service()
        if hasattr(tts_service, '_manager') and tts_service._manager:
            tts_service._manager.stop()
    except Exception as e:
        logger.warning(f"清理TTS管理器时出错: {e}")

    if update_timer:
        try:
            update_timer.stop()
        except Exception as e:
            logger.warning(f"停止全局更新定时器时出错: {e}")
    gc.collect()
    try:
        asyncio.set_event_loop(None)
    except Exception as e:
        logger.warning(f"清理异步引用时出错: {e}")
    app = QApplication.instance()
    guard.release()
    if app:
        _reset_signal_handlers()
        app.quit()
        app.processEvents()

    _terminate_child_processes()
    logger.debug(f"程序退出({status})")
    if not app:
        os._exit(status)


def calculate_size(
    p_w: float = 0.6, p_h: float = 0.7
) -> Tuple[Tuple[int, int], Tuple[int, int]]:  # 计算尺寸
    """计算尺寸"""
    screen_geometry = QApplication.primaryScreen().geometry()
    screen_width = screen_geometry.width()
    screen_height = screen_geometry.height()

    scale_factor = float(config_center.read_conf('General', 'scale'))
    base_width = int(screen_width * p_w / scale_factor)
    base_height = int(screen_height * p_h / scale_factor)
    max_width = min(1200, int(screen_width * 0.8))
    max_height = min(800, int(screen_height * 0.8))
    width = min(max(base_width, 850), max_width)
    height = min(max(base_height, 500), max_height)

    return (width, height), (int(screen_width / 2 - width / 2), 150)


class DarkModeWatcher(QObject):
    """
    颜色(暗黑)模式监听器
    """

    dark_mode_changed = pyqtSignal(bool)  # 发出暗黑模式变化信号

    def __init__(self, interval: int = 500, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._isDarkMode: bool = bool(darkdetect.isDark())  # 初始状态
        self._callback_id = update_timer.add_callback(self._check_theme, interval=interval / 1000)

    def _check_theme(self) -> None:
        current_mode: bool = bool(darkdetect.isDark())
        if current_mode != self._isDarkMode:
            self._isDarkMode = current_mode
            self.dark_mode_changed.emit(current_mode)  # 发出变化信号

    def is_dark(self) -> bool:
        """返回当前是否暗黑模式"""
        return self._isDarkMode

    def stop(self) -> None:
        """停止监听"""
        if hasattr(self, '_callback_id') and self._callback_id:
            update_timer.remove_callback(self._callback_id)
            self._callback_id = None

    def start(self, interval: Optional[int] = None) -> None:
        """开始监听"""
        if hasattr(self, '_callback_id') and self._callback_id:
            update_timer.remove_callback(self._callback_id)
        interval_seconds = (interval / 1000) if interval else 0.5  # 默认0.5秒
        self._callback_id = update_timer.add_callback(self._check_theme, interval=interval_seconds)


class TrayIcon(QSystemTrayIcon):
    """托盘图标"""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.setIcon(QIcon(str(LOGO_PATH / "favicon.png")))

    def update_tooltip(self) -> None:
        """更新托盘文字"""
        schedule_name_from_conf = config_center.read_conf('General', 'schedule')
        if schedule_name_from_conf:
            try:
                schedule_display_name = schedule_name_from_conf
                if schedule_display_name.endswith('.json'):
                    schedule_display_name = schedule_display_name[:-5]
                self.setToolTip(f'Class Widgets - "{schedule_display_name}"')
                logger.debug(f'托盘文字更新: "Class Widgets - {schedule_display_name}"')
            except Exception as e:
                logger.error(f"更新托盘提示时发生错误: {e}")
        else:
            self.setToolTip("Class Widgets - 未加载课表")
            logger.debug('托盘文字更新: "Class Widgets - 未加载课表"')

    def push_update_notification(self, text: str = '') -> None:
        self.setIcon(QIcon(str(LOGO_PATH / "favicon-update.png")))  # tray
        self.showMessage(
            "发现 Class Widgets 新版本!", text, QIcon(str(LOGO_PATH / "favicon-update.png")), 5000
        )

    def push_error_notification(self, title: str = '检查更新失败!', text: str = '') -> None:
        self.setIcon(QIcon(str(LOGO_PATH / "favicon-update.png")))  # tray
        self.showMessage(title, text, QIcon(str(LOGO_PATH / "favicon-error.ico")), 5000)


class UnionUpdateTimer(QObject):
    """
    统一更新计时器
    """

    def __init__(self, parent: Optional[QObject] = None, base_interval: float = 0.1) -> None:
        super().__init__(parent)
        self.timer: QTimer = QTimer(self)
        self.timer.timeout.connect(self._on_timeout)
        self.task_heap: TaskHeapType = []  # [(next_run, id(callback), callback, interval), ...]
        heapify(self.task_heap)
        self.callback_info: Dict[int, CallbackInfoType] = {}  # 使用id作为键
        self._callback_refs: Dict[int, weakref.ReferenceType] = {}  # 弱引用存储
        self._callback_hashes: Dict[int, int] = {}  # 回调函数哈希值验证
        self._callback_error_count: Dict[int, int] = {}  # 错误计数
        self._max_error_count: int = 5  # 最大错误次数
        self._is_running: bool = False
        self._base_interval: float = max(0.01, base_interval)  # 基础间隔,最小10ms
        self._next_check_time: Optional[dt.datetime] = None  # 下次检查时间

    def _on_timeout(self) -> None:
        app = QApplication.instance()
        if not app or app.closingDown():
            self._safe_stop_timer()
            return

        try:
            current_time = TimeManagerFactory.get_instance().get_current_time()
        except Exception as e:
            logger.error(f"获取当前时间失败: {e}")
            raise RuntimeError("无法获得当前时间") from e

        if not self.task_heap:
            self._is_running = False
            self._safe_stop_timer()
            return

        executed_count = 0
        while self.task_heap and (self.task_heap[0][0] <= current_time):
            _next_run, cb_id, callback, interval = heappop(self.task_heap)
            if cb_id not in self._callback_refs or self._callback_refs[cb_id]() is None:
                self._cleanup_dead_callback(cb_id)
                continue
            actual_callback = self._callback_refs[cb_id]()
            if actual_callback is None or hash(actual_callback) != self._callback_hashes.get(cb_id):
                self._cleanup_dead_callback(cb_id)
                continue
            try:
                actual_callback()
                if cb_id in self._callback_error_count:
                    del self._callback_error_count[cb_id]
                executed_count += 1
            except Exception as e:
                logger.error(
                    f"回调执行失败: {e}, 回调: {actual_callback.__name__ if hasattr(actual_callback, '__name__') else str(actual_callback)}"
                )
                self._increment_error_count(cb_id)
                if self._should_remove_callback(cb_id):
                    self._cleanup_dead_callback(cb_id)
                    continue
            # 重新调度回调
            self.callback_info[cb_id]['last_run'] = current_time
            next_time = current_time + dt.timedelta(seconds=interval)
            self.callback_info[cb_id]['next_run'] = next_time
            heappush(self.task_heap, (next_time, cb_id, actual_callback, interval))
        # if executed_count > 0:
        #     logger.debug(f"执行了 {executed_count} 个回调")

        if self._is_running:
            self._schedule_next()

    def _schedule_next(self) -> None:
        """调度器"""
        if not self.task_heap:
            return

        try:
            current_time = TimeManagerFactory.get_instance().get_current_time()
        except Exception as e:
            logger.error(f"获取当前时间失败: {e}")
            raise RuntimeError("无法获得当前时间") from e
        next_task_time = self.task_heap[0][0]
        delay_seconds = (next_task_time - current_time).total_seconds()
        if delay_seconds <= 0:
            delay_ms = 1  # 立即执行已到期任务
        elif delay_seconds > 60.0:
            delay_ms = 60000  # 最大60秒
        else:
            delay_ms = delay_seconds * 1000
        delay = max(1, min(int(delay_ms), 60000))
        self._next_check_time = current_time + dt.timedelta(milliseconds=delay)

        try:
            self.timer.start(delay)
            # logger.debug(f"延迟={delay}ms, 全局任务数: {len(self.task_heap)}")
        except Exception as e:
            logger.error(f"启动定时器失败, 延迟={delay}ms: {e}")
            fallback_delay = max(1, int(self._base_interval * 1000))
            try:
                self.timer.start(fallback_delay)
                logger.debug(f"使用回退延迟={fallback_delay}ms")
            except Exception as fallback_e:
                logger.critical(f"回退定时器启动失败: {fallback_e}")
                self._is_running = False
                self._safe_stop_timer()

    def _cleanup_dead_callback(self, cb_id: int) -> None:
        """清理失效的回调函数"""
        self.callback_info.pop(cb_id, None)
        self._callback_refs.pop(cb_id, None)
        self._callback_hashes.pop(cb_id, None)
        self._callback_error_count.pop(cb_id, None)

    def _increment_error_count(self, cb_id: int) -> None:
        """增加回调错误计数"""
        self._callback_error_count[cb_id] = self._callback_error_count.get(cb_id, 0) + 1

    def _should_remove_callback(self, cb_id: int) -> bool:
        """判断是否应该移除回调"""
        return self._callback_error_count.get(cb_id, 0) >= self._max_error_count

    def _safe_stop_timer(self) -> None:
        """安全停止定时器"""
        if self.timer and self.timer.isActive():
            try:
                self.timer.stop()
            except RuntimeError as e:
                logger.warning(f"停止 QTimer 时发生运行时错误: {e}")
            except Exception as e:
                logger.error(f"停止 QTimer 时发生未知错误: {e}")

    def add_callback(self, callback: Callable[[], Any], interval: float = 1.0) -> int:
        """添加回调函数到定时器

        Args:
            callback: 要执行的回调函数
            interval: 执行间隔(秒), 默认1秒, 最小0.1秒

        Returns:
            int: 回调函数的唯一ID

        Raises:
            TypeError: 当callback不是可调用对象时
        """
        if not callable(callback):
            raise TypeError("回调必须是可调用对象") from None
        try:
            callback_hash = hash(callback)
        except TypeError as err:
            raise TypeError("回调函数必须是可哈希的") from err

        interval = max(0.1, interval)
        current_time: dt.datetime = TimeManagerFactory.get_instance().get_current_time()
        next_run = current_time + dt.timedelta(seconds=interval)
        cb_id = id(callback)

        if cb_id in self.callback_info:
            self._cleanup_dead_callback(cb_id)
        self.callback_info[cb_id] = {
            'interval': interval,
            'last_run': current_time,
            'next_run': next_run,
        }

        def cleanup_callback(ref: weakref.ReferenceType) -> None:  # noqa
            self._cleanup_dead_callback(cb_id)

        self._callback_refs[cb_id] = weakref.ref(callback, cleanup_callback)
        self._callback_hashes[cb_id] = callback_hash
        heappush(self.task_heap, (next_run, cb_id, callback, interval))
        should_start = not self._is_running
        if should_start:
            self.start()
        return cb_id

    def remove_callback(self, callback: Callable[[], Any]) -> None:
        """移除回调函数

        Args:
            callback: 要移除的回调函数
        """
        cb_id = id(callback)
        self.remove_callback_by_id(cb_id)

    def remove_callback_by_id(self, callback_id: int) -> None:
        """通过回调ID移除回调函数

        Args:
            callback_id: 回调函数的ID
        """
        if callback_id in self.callback_info:
            self._cleanup_dead_callback(callback_id)
            new_heap = []  # 重建堆
            for next_run, cb_id, callback, interval in self.task_heap:
                if cb_id != callback_id:
                    new_heap.append((next_run, cb_id, callback, interval))
            self.task_heap = new_heap
            heapify(self.task_heap)
            if not self.task_heap:  # 如果没有任务, 停止定时器
                self._is_running = False
                self._safe_stop_timer()

    def remove_all_callbacks(self) -> None:
        """移除所有已注册的回调函数"""
        self.callback_info.clear()
        self._callback_refs.clear()
        self._callback_hashes.clear()
        self.task_heap.clear()
        self._callback_error_count.clear()
        self._is_running = False
        self._safe_stop_timer()

    def start(self) -> None:
        """启动定时器"""
        if self._is_running:
            return
        if not self.task_heap:
            logger.debug("任务堆为空")
            return
        self._is_running = True
        logger.debug("启动 UnionUpdateTimer...")
        self._schedule_next()

    def stop(self) -> None:
        """停止定时器"""
        if self._is_running:
            self._is_running = False
        else:
            logger.debug("定时器未运行")
        self._safe_stop_timer()
        logger.debug("UnionUpdateTimer 已停止")

    def set_callback_interval(self, callback: Callable[[], Any], interval: float) -> bool:
        """设置特定回调函数的执行间隔(s)

        Args:
            callback: 目标回调函数
            interval: 新的执行间隔(秒), 最小0.1秒

        Returns:
            bool: 成功True, 不存在False
        """
        interval = max(0.1, interval)
        current_time = TimeManagerFactory.get_instance().get_current_time()
        next_run = current_time + dt.timedelta(seconds=interval)
        cb_id = id(callback)

        if cb_id in self.callback_info:
            self.callback_info[cb_id]['interval'] = interval
            self.callback_info[cb_id]['next_run'] = next_run
            new_heap = []
            for next_run_time, heap_cb_id, heap_callback, heap_interval in self.task_heap:
                if heap_cb_id == cb_id:
                    new_heap.append((next_run, cb_id, callback, interval))
                else:
                    new_heap.append((next_run_time, heap_cb_id, heap_callback, heap_interval))
            self.task_heap = new_heap
            heapify(self.task_heap)
            return True
        return False

    def get_callback_interval(self, callback: Callable[[], Any]) -> Optional[float]:
        """获取特定回调函数的执行间隔(s)

        Args:
            callback: 目标回调函数

        Returns:
            Optional[float]: 回调间隔(秒), 不存在则返回None
        """
        cb_id = id(callback)
        if cb_id in self.callback_info:
            interval = self.callback_info[cb_id]['interval']
            return float(interval) if isinstance(interval, (int, float)) else None
        return None

    def set_base_interval(self, interval: float) -> None:
        """设置基础检查间隔时间(s)

        Args:
            interval: 新的基础间隔时间, 最小值为0.05秒
        """
        new_interval: float = max(0.05, interval)
        self._base_interval = new_interval
        was_running: bool = self._is_running
        if was_running:
            self.stop()
            self.start()

    def get_base_interval(self) -> float:
        """获取当前基础检查间隔"""
        return self._base_interval

    def get_callback_count(self) -> int:
        """获取当前已注册的回调函数数量

        Returns:
            int: 回调函数的总数
        """
        return len(self.callback_info)

    def get_callback_info(self) -> Dict[Callable[[], Any], CallbackInfoType]:
        """获取所有回调函数的详细信息

        Returns:
            Dict: 回调函数到其信息的映射,包含间隔时间和下次执行时间
        """
        info: Dict[Callable[[], Any], CallbackInfoType] = {}
        current_time: dt.datetime = TimeManagerFactory.get_instance().get_current_time()
        for cb_id, data in self.callback_info.items():
            if cb_id in self._callback_refs:
                callback = self._callback_refs[cb_id]()
                if callback is not None:
                    callback_info: CallbackInfoType = {
                        'interval': data['interval'],
                        'last_run': data['last_run'],
                        'next_run': data['next_run'],
                        'time_until_next': (
                            (data['next_run'] - current_time).total_seconds()
                            if isinstance(data['next_run'], dt.datetime)
                            else 0.0
                        ),
                    }
                    info[callback] = callback_info
        return info

    def get_next_check_time(self) -> Optional[dt.datetime]:
        """获取下次检查时间"""
        return self._next_check_time

    def get_heap_size(self) -> int:
        """获取当前任务堆中的任务数量

        Returns:
            int: 堆中待执行任务的数量
        """
        return len(self.task_heap)

    def is_running(self) -> bool:
        """检查定时器是否正在运行"""
        return self._is_running


# 匹配中文字符(预编译)
_CHINESE_CHAR_PATTERN = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\u20000-\u2a6df\u2a700-\u2b73f\u2b740-\u2b81f\u2b820-\u2ceaf\u2ceb0-\u2ebef]"
)


def get_str_length(text: str) -> int:
    """
    计算字符串长度,汉字计为2,英文和数字计为1

    Args:
        text: 要计算的字符串

    Returns:
        int: 字符串长度
    """
    chinese_count = len(_CHINESE_CHAR_PATTERN.findall(text))
    # 总长度 = 非中文字符数 + 中文字符数 * 2
    return len(text) - chinese_count + chinese_count * 2


def slice_str_by_length(text: str, max_length: int) -> str:
    """
    根据指定长度切割字符串,汉字计为2,英文和数字计为1

    Args:
        text: 要切割的字符串
        max_length: 最大长度

    Returns:
        str: 切割后的字符串
    """
    if not text or max_length <= 0:
        return ""

    if get_str_length(text) <= max_length:
        return text

    chars = _CHINESE_CHAR_PATTERN.split(text)
    chinese_chars = _CHINESE_CHAR_PATTERN.findall(text)
    result = []
    current_length = 0
    char_index = 0
    chinese_index = 0
    # 交替处理非中文和中文字符
    while char_index < len(chars):
        # 添加非中文部分
        part = chars[char_index]
        if current_length + len(part) > max_length:
            # 若超出长度限制,只取部分
            space_left = max_length - current_length
            result.append(part[:space_left])
            break
        result.append(part)
        current_length += len(part)
        # 添加中文部分
        if chinese_index < len(chinese_chars):
            if current_length + 2 > max_length:
                break
            result.append(chinese_chars[chinese_index])
            current_length += 2
            chinese_index += 1
        char_index += 1

    return ''.join(result)


class TimeManagerInterface(ABC):
    """时间管理器接口"""

    @abstractmethod
    def get_real_time(self) -> dt.datetime:
        """获取真实当前时间(无偏移)"""
        pass  # noqa

    @abstractmethod
    def get_current_time(self) -> dt.datetime:
        """获取程序内时间 (偏移后)"""
        pass  # noqa

    @abstractmethod
    def get_current_time_without_ms(self) -> dt.datetime:
        """获取程序内时间 (偏移后, 舍去毫秒)"""
        pass  # noqa

    @abstractmethod
    def get_current_time_str(self, format_str: str = '%H:%M:%S') -> str:
        """获取格式化时间字符串"""
        pass  # noqa

    @abstractmethod
    def get_today(self) -> dt.date:
        """获取今天日期 (偏移后)"""
        pass  # noqa

    @abstractmethod
    def get_current_weekday(self) -> int:
        """获取当前星期几 (0=周一, 6=周日)"""
        pass  # noqa

    @abstractmethod
    def sync_with_ntp(self) -> bool:
        """同步NTP时间"""
        pass  # noqa


class LocalTimeManager(TimeManagerInterface):
    """本地时间管理器"""

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config_center = config or config_center

    def get_real_time(self) -> dt.datetime:
        """获取真实当前时间"""
        return dt.datetime.now()

    def get_current_time(self) -> dt.datetime:
        """获取程序时间(含偏移)"""
        time_offset = float(self._config_center.read_conf('Time', 'time_offset', 0))
        return self.get_real_time() - dt.timedelta(seconds=time_offset)

    def get_current_time_without_ms(self) -> dt.datetime:
        """获取程序时间(含偏移, 舍去毫秒)"""
        return self.get_current_time().replace(microsecond=0)

    def get_current_time_str(self, format_str: str = '%H:%M:%S') -> str:
        """获取格式化时间字符串"""
        return self.get_current_time().strftime(format_str)

    def get_today(self) -> dt.date:
        """获取今天日期"""
        return self.get_current_time().date()

    def get_current_weekday(self) -> int:
        """获取当前星期几(0=周一, 6=周日)"""
        return self.get_current_time().weekday()

    def get_time_offset(self) -> float:
        """获取时差偏移(秒)"""
        return float(self._config_center.read_conf('Time', 'time_offset', 0))

    def sync_with_ntp(self) -> bool:
        """为什么"""
        logger.warning("本地时间管理器不支持NTP同步")
        return False


class NTPTimeManager(TimeManagerInterface):
    """NTP时间管理器"""

    _config_center: Any
    _ntp_reference_time: Optional[dt.datetime]
    _ntp_reference_timestamp: Optional[float]
    _lock: threading.Lock
    _use_fallback: bool
    _last_sync_time: float
    _sync_debounce_interval: float
    _pending_sync_timer: Optional[Any]
    _sync_thread: Optional[threading.Thread]
    _running: bool

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config_center = config or config_center
        self._ntp_reference_time = None
        self._ntp_reference_timestamp = None
        self._lock = threading.Lock()
        self._use_fallback = True
        self._last_sync_time = 0
        self._sync_debounce_interval = 3.5
        self._pending_sync_timer = None
        self._sync_thread = None
        self._running = True
        self._start_sync_thread()
        # logger.debug("NTP时间管理器初始化完成")

    def _start_sync_thread(self) -> None:
        """启动后台同步线程"""
        self._sync_thread = threading.Thread(target=self._background_sync, daemon=True)
        self._sync_thread.start()

    def _background_sync(self) -> None:
        """后台NTP同步"""
        try:
            # 初始同步
            if self.sync_with_ntp():
                with self._lock:
                    self._use_fallback = False
            else:
                logger.warning("NTP同步失败,继续使用系统时间")

            # 周期性同步 (每小时一次)
            while self._running:
                time.sleep(3600)  # 1小时
                if not self._running:
                    break
                try:
                    self.sync_with_ntp()
                except Exception as e:
                    logger.error(f"周期性NTP同步异常: {e}")
        except Exception as e:
            logger.error(f"NTP同步线程异常: {e}")

    def _sync_ntp_internal(self, timeout: float = 5.0) -> bool:
        """执行NTP同步"""
        ntp_server = self._config_center.read_conf('Time', 'ntp_server', 'ntp.aliyun.com')
        try:
            ntp_client = ntplib.NTPClient()
            response = ntp_client.request(ntp_server, version=3, timeout=timeout)
            ntp_timestamp = response.tx_time
            ntp_time_utc = dt.datetime.fromtimestamp(ntp_timestamp, dt.timezone.utc)

            timezone_setting = self._config_center.read_conf('Time', 'timezone', 'local')
            ntp_time_local = self._convert_to_local_time(ntp_time_utc, timezone_setting)

            with self._lock:
                self._ntp_reference_time = ntp_time_local
                self._ntp_reference_timestamp = time.time()
            logger.debug(
                f"NTP同步成功: 服务器={ntp_server},时间={ntp_time_local}(local),延迟={response.delay:.3f}秒"
            )
            return True
        except Exception as e:
            logger.error(f"NTP同步失败: {e}")
            return False

    def _convert_to_local_time(self, utc_time: dt.datetime, timezone_setting: str) -> dt.datetime:
        """将UTC时间转换为本地时间"""
        if not timezone_setting or timezone_setting == 'local':
            local_tz = dt.datetime.now().astimezone().tzinfo
            if utc_time.tzinfo is None:
                utc_time_with_tz = utc_time.replace(tzinfo=dt.timezone.utc)
            else:
                utc_time_with_tz = utc_time
            local_time = utc_time_with_tz.astimezone(local_tz)
            return local_time.replace(tzinfo=None)
        try:
            utc_tz = pytz.UTC
            target_tz = pytz.timezone(timezone_setting)
            if utc_time.tzinfo is None:
                utc_time = utc_tz.localize(utc_time)
            local_time = utc_time.astimezone(target_tz)
            return local_time.replace(tzinfo=None)
        except Exception as e:
            logger.warning(f"时区转换失败,回退系统时区: {e}")
            local_tz = dt.datetime.now().astimezone().tzinfo
            if utc_time.tzinfo is None:
                utc_time_with_tz = utc_time.replace(tzinfo=dt.timezone.utc)
            else:
                utc_time_with_tz = utc_time
            local_time = utc_time_with_tz.astimezone(local_tz)
            return local_time.replace(tzinfo=None)

    def get_real_time(self) -> dt.datetime:
        """获取真实当前时间"""
        with self._lock:
            if self._use_fallback or self._ntp_reference_time is None:
                return dt.datetime.now()
            elapsed_seconds = time.time() - (self._ntp_reference_timestamp or 0)
            return self._ntp_reference_time + dt.timedelta(seconds=elapsed_seconds)

    def get_current_time(self) -> dt.datetime:
        """获取程序时间(含偏移)"""
        time_offset = float(self._config_center.read_conf('Time', 'time_offset', 0))
        return self.get_real_time() - dt.timedelta(seconds=time_offset)

    def get_current_time_without_ms(self) -> dt.datetime:
        """获取程序时间(含偏移, 舍去毫秒)"""
        return self.get_current_time().replace(microsecond=0)

    def get_current_time_str(self, format_str: str = '%H:%M:%S') -> str:
        """获取格式化时间字符串"""
        return self.get_current_time().strftime(format_str)

    def get_today(self) -> dt.date:
        """获取今天日期"""
        return self.get_current_time().date()

    def get_current_weekday(self) -> int:
        """获取当前星期几(0=周一, 6=周日)"""
        return self.get_current_time().weekday()

    def get_time_offset(self) -> float:
        """获取时差偏移(秒)"""
        return float(self._config_center.read_conf('Time', 'time_offset', 0))

    def sync_with_ntp(self) -> bool:
        """进行NTP同步"""
        current_time = time.time()
        if current_time - self._last_sync_time < self._sync_debounce_interval:
            # logger.debug(f"NTP同步防抖({current_time - self._last_sync_time:.1f}秒),延迟执行同步")
            if self._pending_sync_timer:
                self._pending_sync_timer.cancel()
            remaining_time = self._sync_debounce_interval - (current_time - self._last_sync_time)
            self._pending_sync_timer = threading.Timer(remaining_time, self._delayed_sync)
            self._pending_sync_timer.start()
            return True
        if self._pending_sync_timer:
            self._pending_sync_timer.cancel()
            self._pending_sync_timer = None
        return self._execute_sync()

    def _delayed_sync(self) -> None:
        """延迟执行的同步"""
        self._pending_sync_timer = None
        self._execute_sync()

    def _execute_sync(self) -> bool:
        """执行实际的NTP同步"""
        success = self._sync_ntp_internal(timeout=5.0)
        if success:
            with self._lock:
                self._use_fallback = False
                self._last_sync_time = time.time()
        return success

    def get_last_ntp_sync(self) -> Optional[dt.datetime]:
        """获取上次NTP同步时间"""
        with self._lock:
            return self._ntp_reference_time

    def shutdown(self) -> None:
        """关闭NTP管理器"""
        self._running = False
        if self._pending_sync_timer:
            self._pending_sync_timer.cancel()
            self._pending_sync_timer = None


class TimeManagerFactory:
    """时间管理器工厂"""

    _managers: ClassVar[Dict[str, Type[TimeManagerInterface]]] = {
        'local': LocalTimeManager,
        'ntp': NTPTimeManager,
    }
    _instance: Optional[TimeManagerInterface] = None
    _instance_lock = threading.Lock()

    @classmethod
    def create_manager(cls, config_provider=None) -> TimeManagerInterface:
        """创建时间管理器

        Args:
            config_provider: 配置提供者, 默认使用全局config_center
        """
        conf = config_provider or config_center
        try:
            time_type = conf.read_conf('Time', 'type')
            manager_type = 'ntp' if time_type == 'ntp' else 'local'
        except Exception:
            manager_type = 'local'

        manager_class = cls._managers[manager_type]
        if 'config' in inspect.signature(manager_class.__init__).parameters:
            return manager_class(config=conf)
        return manager_class()

    @classmethod
    def get_instance(cls, config_provider=None) -> TimeManagerInterface:
        """获取管理器实例

        Args:
            config_provider: 配置提供者,默认使用全局config_center
        """
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls.create_manager(config_provider)
            return cls._instance

    @classmethod
    def reset_instance(cls, config_provider=None) -> TimeManagerInterface:
        """重置实例(配置变更时使用)"""
        with cls._instance_lock:
            if cls._instance and hasattr(cls._instance, 'shutdown'):
                try:
                    cls._instance.shutdown()
                except Exception as e:
                    logger.warning(f"关闭旧时间管理器实例失败: {e}")
            cls._instance = cls.create_manager(config_provider)
            # Note: 不再修改其他模块的引用
            globals()['time_manager'] = cls._instance

        return cls._instance


main_mgr = None


class SingleInstanceGuard:
    def __init__(self, lock_name="ClassWidgets.lock"):
        lock_path = QDir.temp().absoluteFilePath(lock_name)
        self.lock_file = QLockFile(lock_path)
        self.lock_acquired = False

    def try_acquire(self, timeout: int = 100):
        self.lock_acquired = self.lock_file.tryLock(timeout)
        return self.lock_acquired

    def release(self):
        if self.lock_acquired:
            self.lock_file.unlock()

    def get_lock_info(self):
        ok, pid, hostname, appname = self.lock_file.getLockInfo()
        if ok:
            return {"pid": pid, "hostname": hostname, "appname": appname}
        return None


class PreviousWindowFocusManager(QObject):

    restore_requested = pyqtSignal()  # 请求恢复焦点信号
    ignore = pyqtSignal(int)  # 忽略特定窗口句柄信号
    remove_ignore = pyqtSignal(int)  # 移除忽略窗口句柄信号

    def __init__(self, parent: Optional[QObject] = None) -> None:
        if os.name != 'nt':
            raise OSError("仅支持 Windows")
        super().__init__(parent)
        self._last_hwnd = None
        self.ignore_hwnds = {0}  # 忽略的句柄
        if parent:
            # 添加父窗口句柄到忽略列表
            self.ignore_hwnds.add(parent.winId().__int__())
        self.restore_requested.connect(self.restore)
        self.ignore.connect(self.ignore_hwnds.add)
        self.remove_ignore.connect(self.ignore_hwnds.discard)
        self._callback_id = update_timer.add_callback(self.store, interval=0.2)

    def store(self):
        """记录当前前台窗口句柄"""
        hwnd = win32gui.GetForegroundWindow()
        if hwnd in self.ignore_hwnds:
            return
        self._last_hwnd = hwnd
        # logger.debug(f"记录前台窗口句柄: {self._last_hwnd}")

    def restore(self, delay_ms=0):
        """
        恢复焦点到上一个窗口

        Args:
            delay_ms: 延迟执行毫秒数 (部分系统需要延迟才能成功)
        """
        # logger.debug(f"请求恢复焦点,延迟 {delay_ms} ms")
        QTimer.singleShot(delay_ms, self._do_restore)

    def _do_restore(self):
        # logger.debug(f"尝试恢复焦点到窗口句柄: {self._last_hwnd}")
        if self._last_hwnd and win32gui.IsWindow(self._last_hwnd):
            try:
                current_hwnd = win32gui.GetForegroundWindow()
                if current_hwnd not in self.ignore_hwnds:
                    return
                win32gui.SetForegroundWindow(self._last_hwnd)
            except Exception as e:
                logger.warning(f"恢复焦点失败: {e}")

    def stop(self):
        """停止焦点管理器"""
        if hasattr(self, '_callback_id') and self._callback_id:
            update_timer.remove_callback(self._callback_id)
            self._callback_id = None
        self._last_hwnd = None


def _create_shortcut(
    target_path: str,
    shortcut_path: Path,
    icon_path: Optional[str] = None,
    description: str = "Class Widgets",
) -> bool:
    """创建快捷方式"""
    if os.name != 'nt':
        logger.error("仅支持 Windows")
        return False
    try:
        target = Path(target_path)
        if not target.exists():
            logger.error(f"目标路径不存在: {target}")
            return False
        if shortcut_path.exists():
            shortcut_path.unlink()
            logger.info(f"已删除旧快捷方式: {shortcut_path}")
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = str(target)
        shortcut.Description = description
        shortcut.WorkingDirectory = str(CW_HOME)
        if icon_path and Path(icon_path).exists():
            shortcut.IconLocation = str(icon_path)
        shortcut.save()
        logger.success(f"快捷方式创建成功: {shortcut_path}")
        return True
    except (FileNotFoundError, PermissionError) as e:
        logger.error(f"创建快捷方式失败: {e}")
    return False


def add_shortcut(exe_name: str, icon_path: Optional[str] = None) -> bool:
    """添加桌面快捷方式"""
    if os.name != 'nt':
        logger.error("仅支持 Windows")
        return False
    desktop_path = Path.home() / 'Desktop'
    shortcut_path = desktop_path / 'Class Widgets.lnk'
    target_path = str(CW_HOME / exe_name)
    return _create_shortcut(target_path, shortcut_path, icon_path)


def add_shortcut_to_startmenu(exe_path: str, icon_path: Optional[str] = None) -> bool:
    """添加开始菜单快捷方式"""
    if os.name != 'nt':
        logger.error("仅支持 Windows")
        return False
    start_menu_path = (
        Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'
    )
    shortcut_path = start_menu_path / 'Class Widgets.lnk'
    return _create_shortcut(exe_path, shortcut_path, icon_path)


def add_to_startup() -> bool:
    """添加到开机自启动"""
    if os.name != 'nt':
        logger.error("仅支持 Windows")
        return False
    startup_path = (
        Path(os.environ['APPDATA'])
        / 'Microsoft'
        / 'Windows'
        / 'Start Menu'
        / 'Programs'
        / 'Startup'
    )
    shortcut_path = startup_path / 'Class Widgets.lnk'
    target_path = str(CW_HOME / 'ClassWidgets.exe')
    icon_path = str(CW_HOME / 'img' / 'favicon.ico')
    return _create_shortcut(target_path, shortcut_path, icon_path)


def remove_from_startup() -> bool:
    """从开机自启动中移除"""
    if os.name != 'nt':
        logger.error("仅支持 Windows")
        return False
    try:
        startup_path = (
            Path(os.environ['APPDATA'])
            / 'Microsoft'
            / 'Windows'
            / 'Start Menu'
            / 'Programs'
            / 'Startup'
        )
        shortcut_path = startup_path / 'Class Widgets.lnk'
        if shortcut_path.exists():
            shortcut_path.unlink()
            logger.success(f"快捷方式删除成功: {shortcut_path}")
            return True
        logger.warning(f"快捷方式不存在: {shortcut_path}")
        return False
    except Exception as e:
        logger.error(f"删除快捷方式失败: {e}")
        return False


tray_icon = None
update_timer = UnionUpdateTimer()
time_manager = TimeManagerFactory.get_instance()
guard: Optional[SingleInstanceGuard] = None
