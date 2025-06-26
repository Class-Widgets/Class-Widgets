import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, Union, List, Callable
import psutil
import threading
from typing import Dict, Callable, Any, Optional, Union

from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QSystemTrayIcon, QApplication, QMenu, QAction
from loguru import logger
from PyQt5.QtCore import QSharedMemory, QTimer, QObject, pyqtSignal, QThread
from PyQt5 import QtCore
import darkdetect
import datetime as dt

from file import base_directory, config_center
import signal

from typing import Tuple

share = QSharedMemory('ClassWidgets')
_stop_in_progress = False

def _reset_signal_handlers():
    """重置信号处理器为默认状态"""
    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass

def _cleanup_shared_memory():
    """清理共享内存"""
    global share
    if share and share.isAttached():
        try:
            share.detach()
            logger.debug("共享内存已分离")
        except Exception as e:
            logger.error(f"分离共享内存时出错: {e}")

def _terminate_child_processes():
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
        gone, alive = psutil.wait_procs(children, timeout=1.5)
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
    
    _cleanup_shared_memory()
    os.execl(sys.executable, sys.executable, *sys.argv)

def stop(status: int = 0):
    """
    退出程序
    :param status: 退出状态码,0=正常退出,!=0表示异常退出
    """
    global update_timer, _stop_in_progress
    if _stop_in_progress:
        return
    _stop_in_progress = True
    
    logger.debug('退出程序...')
    if 'update_timer' in globals() and update_timer:
        try:
            update_timer.stop()
            update_timer = None
        except Exception as e:
            logger.warning(f"停止全局更新定时器时出错: {e}")
    app = QApplication.instance()
    if app:
        _reset_signal_handlers()
        app.quit()

    _terminate_child_processes()
    _cleanup_shared_memory()
    logger.debug(f"程序退出({status})")
    if not app:
        os._exit(status)

def calculate_size(p_w: float = 0.6, p_h: float = 0.7) -> Tuple[Tuple[int,int], Tuple[int,int]]:  # 计算尺寸
    """计算尺寸"""
    screen_geometry = QApplication.primaryScreen().geometry()
    screen_width = screen_geometry.width()
    screen_height = screen_geometry.height()

    width = int(screen_width * p_w)
    height = int(screen_height * p_h)

    return (width, height), (int(screen_width / 2 - width / 2), 150)


class DarkModeWatcher(QObject):
    """
    颜色(暗黑)模式监听器
    """
    darkModeChanged = pyqtSignal(bool)  # 发出暗黑模式变化信号
    def __init__(self, interval: int = 500, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._isDarkMode = darkdetect.isDark()  # 初始状态
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._checkTheme)
        self._timer.start(interval)  # 轮询间隔（毫秒）

    def _checkTheme(self) -> None:
        currentMode = darkdetect.isDark()
        if currentMode != self._isDarkMode:
            self._isDarkMode = currentMode
            self.darkModeChanged.emit(currentMode)  # 发出变化信号

    def isDark(self) -> bool:
        """返回当前是否暗黑模式"""
        return self._isDarkMode

    def stop(self) -> None:
        """停止监听"""
        self._timer.stop()

    def start(self, interval: Optional[int] = None) -> None:
        """开始监听"""
        if interval:
            self._timer.setInterval(interval)
        self._timer.start()


class TrayIcon(QSystemTrayIcon):
    """托盘图标"""
    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon.png"))

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
            logger.debug(f'托盘文字更新: "Class Widgets - 未加载课表"')
            
    def push_update_notification(self, text: str = '') -> None:
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon-update.png"))  # tray
        self.showMessage(
            "发现 Class Widgets 新版本！",
            text,
            QIcon(f"{base_directory}/img/logo/favicon-update.png"),
            5000
        )

    def push_error_notification(self, title: str = '检查更新失败！', text: str = '') -> None:
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon-update.png"))  # tray
        self.showMessage(
            title,
            text,
            QIcon(f"{base_directory}/img/logo/favicon-error.ico"),
            5000
        )


class UnionUpdateTimer(QObject):
    """
    统一更新计时器
    """

    def __init__(self, parent: Optional[QObject] = None, base_interval: float = 0.1) -> None:
        super().__init__(parent)
        self.timer: QTimer = QTimer(self)
        self.timer.timeout.connect(self._on_timeout)
        self.callback_info: Dict[Callable[[], Any], Dict[str, Union[float, dt.datetime]]] = {}  # 回调函数信息: {callback: {'interval': float, 'last_run': datetime, 'next_run': datetime}}
        self._is_running: bool = False
        self._base_interval: float = max(0.05, base_interval)  # 基础间隔,最小50ms
        self._lock: threading.Lock = threading.Lock()

    def _on_timeout(self) -> None:  # 超时
        app = QApplication.instance()
        if not app or app.closingDown():
            self._safe_stop_timer()
            return

        current_time = dt.datetime.now()
        callbacks_to_run = []
        with self._lock:
            if not self.callback_info:
                self._is_running = False
                self._safe_stop_timer()
                return
            for callback, info in list(self.callback_info.items()):
                if current_time >= info['next_run']:
                    callbacks_to_run.append(callback)
                    info['last_run'] = current_time
                    info['next_run'] = current_time + dt.timedelta(seconds=info['interval'])
        invalid_callbacks = []
        for callback in callbacks_to_run:
            try:
                with self._lock:
                    if callback not in self.callback_info:
                        continue
                callback()
            except RuntimeError as e:
                logger.error(f"回调调用错误 (可能对象已删除): {e}")
                invalid_callbacks.append(callback)
            except TypeError as e:
                logger.error(f"回调函数类型错误: {e}")
                invalid_callbacks.append(callback)
            except Exception as e:
                logger.error(f"执行回调时发生未知错误: {e}")
                # 其他异常可能是临时错误,不移除
        if invalid_callbacks:
            with self._lock:
                for callback in invalid_callbacks:
                    self.callback_info.pop(callback, None)

        if self._is_running:
            self._schedule_next()

    def _schedule_next(self) -> None:
        """调度下一次执行"""
        delay: int = int(self._base_interval * 1000)
        self.timer.start(delay)
        
    def _safe_stop_timer(self) -> None:
        """安全停止定时器"""
        if self.timer and self.timer.isActive():
            try:
                self.timer.stop()
            except RuntimeError as e:
                logger.warning(f"停止 QTimer 时发生运行时错误: {e}")
            except Exception as e:
                logger.error(f"停止 QTimer 时发生未知错误: {e}")

    def add_callback(self, callback: Callable[[], Any], interval: float = 1.0) -> None:
        """添加回调函数
        
        Args:
            callback: 回调函数
            interval: 刷新间隔(s),默认1秒
        """
        if not callable(callback):
            raise TypeError("回调必须是可调用对象")
        interval = max(0.1, interval)
        current_time: dt.datetime = dt.datetime.now()
        with self._lock:
            if callback not in self.callback_info:
                self.callback_info[callback] = {
                    'interval': interval,
                    'last_run': current_time,
                    'next_run': current_time + dt.timedelta(seconds=interval)
                }
                should_start = not self._is_running
            else:
                self.callback_info[callback]['interval'] = interval
                should_start = False
        
        if should_start:
            self.start()
        #logger.debug(f"添加回调函数 {callback},间隔: {interval}s")

    def remove_callback(self, callback: Callable[[], Any]) -> None:
        """移除回调函数"""
        with self._lock:
            removed: Optional[Dict[str, Union[float, dt.datetime]]] = self.callback_info.pop(callback, None)
        if removed:
            logger.debug(f"移除回调函数,原间隔: {removed['interval']}s")
    def remove_all_callbacks(self) -> None:
        """移除所有回调函数"""
        # 意义不明
        with self._lock:
            # count: int = len(self.callback_info)
            self.callback_info = {}
        # logger.debug(f"移除所有回调函数,共 {count} 个")

    def start(self) -> None:
        """启动定时器"""
        with self._lock:
            if not self._is_running and self.callback_info:
                logger.debug(f"启动 UnionUpdateTimer...")
                self._is_running = True
                self._schedule_next()
            elif not self.callback_info:
                logger.warning("没有回调函数")

    def stop(self) -> None:
        """停止定时器"""
        with self._lock:
            self._is_running = False
        self._safe_stop_timer()
        logger.debug("UnionUpdateTimer 已停止")
    
    def set_callback_interval(self, callback: Callable[[], Any], interval: float) -> bool:
        """设置特定回调函数的间隔(s)"""
        interval = max(0.1, interval)
        current_time: dt.datetime = dt.datetime.now()
        
        with self._lock:
            if callback in self.callback_info:
                self.callback_info[callback]['interval'] = interval
                self.callback_info[callback]['next_run'] = current_time + dt.timedelta(seconds=interval)
                return True
            else:
                return False
    
    def get_callback_interval(self, callback: Callable[[], Any]) -> Optional[float]:
        """获取特定回调函数的间隔"""
        # 意义不明x2
        with self._lock:
            if callback in self.callback_info:
                return self.callback_info[callback]['interval']
            return None
    
    def set_base_interval(self, interval: float) -> None:
        """设置基础检查时间(s)"""
        # 意义不明x3
        new_interval: float = max(0.05, interval)
        with self._lock:
            self._base_interval = new_interval
            was_running: bool = self._is_running
        if was_running:
            self.stop()
            self.start()
        
    def get_base_interval(self) -> float:
        """获取当前基础检查间隔"""
        return self._base_interval
    
    def get_callback_count(self) -> int:
        """获取当前回调函数数量"""
        with self._lock:
            return len(self.callback_info)
    
    def get_callback_info(self) -> Dict[Callable[[], Any], Dict[str, Union[float, dt.datetime]]]:
        """获取所有回调函数的详细信息"""
        with self._lock:
            info: Dict[Callable[[], Any], Dict[str, Union[float, dt.datetime]]] = {}
            current_time: dt.datetime = dt.datetime.now()
            for callback, data in self.callback_info.items():
                info[callback] = {
                    'interval': data['interval'],
                    'last_run': data['last_run'],
                    'next_run': data['next_run'],
                    'time_until_next': (data['next_run'] - current_time).total_seconds()
                }
            return info
    
    def is_running(self) -> bool:
        """检查定时器是否正在运行"""
        return self._is_running

def get_str_length(text: str) -> int:
    """
    计算字符串长度,汉字计为2,英文和数字计为1
    
    Args:
        text: 要计算的字符串
    
    Returns:
        int: 字符串长度
    """
    length = 0
    for char in text:
        # 使用 ord() 获取字符的 Unicode 码点
        # 如果大于 0x4e00 (中文范围开始) 就是汉字,计为2
        if ord(char) > 0x4e00:
            length += 2
        else:
            length += 1
    return length

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

    current_length = 0
    result = []

    for char in text:
        char_length = 2 if ord(char) > 0x4e00 else 1
        if current_length + char_length > max_length:
            break
        result.append(char)
        current_length += char_length

    return ''.join(result)

tray_icon = None
update_timer = UnionUpdateTimer()
