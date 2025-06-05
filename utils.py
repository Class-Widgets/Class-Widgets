import os
import sys
import psutil
from typing import List, Tuple, Optional, Callable, Any # Added for type hints

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QSystemTrayIcon, QApplication
from loguru import logger
from PyQt5.QtCore import QSharedMemory, QTimer, QObject, pyqtSignal, QEvent # Added QObject, QEvent
import darkdetect
import datetime as dt

from file import base_directory, config_center # base_directory is Path, config_center is ConfigCenter
import signal

share: QSharedMemory = QSharedMemory('ClassWidgets')
_stop_in_progress: bool = False
tray_icon: Optional['TrayIcon'] = None # Forward declaration for TrayIcon
update_timer: 'UnionUpdateTimer' # Forward declaration for UnionUpdateTimer


def restart() -> None: # Added return type
    logger.debug('重启程序')
    app: Optional[QApplication] = QApplication.instance()
    if app:
        try:
            # Resetting signal handlers to default before quitting
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (AttributeError, ValueError, OSError): # OSError for when not in main thread
            pass # Ignore errors if signal handling fails (e.g. not in main thread)
        app.quit()
        app.processEvents()

    if share.isAttached():
        share.detach()  # 释放共享内存

    # Ensure sys.executable and sys.argv are valid strings/list of strings
    executable: str = sys.executable or ""
    argv: List[str] = sys.argv or []
    os.execl(executable, executable, *argv)

def stop(status: int = 0) -> None: # Added types
    global share, update_timer, _stop_in_progress # update_timer is UnionUpdateTimer
    if _stop_in_progress:
        return
    _stop_in_progress = True

    logger.debug('退出程序...')

    if 'update_timer' in globals() and update_timer and isinstance(update_timer, UnionUpdateTimer):
        try:
            update_timer.stop()
            # update_timer = None # Keep instance for potential re-start if needed, or properly del
        except Exception as e:
            logger.warning(f"停止全局更新定时器时出错: {e}")

    app: Optional[QApplication] = QApplication.instance()
    if app:
        try:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (AttributeError, ValueError, OSError):
            pass
        app.quit() # Politely ask Qt app to quit
        # app.processEvents() # Process events to allow cleanup, but be careful with re-entry to stop()

    try:
        current_pid: int = os.getpid()
        parent: psutil.Process = psutil.Process(current_pid)
        children: List[psutil.Process] = parent.children(recursive=True)
        if children:
            logger.debug(f"尝试终止 {len(children)} 个子进程...")
            child: psutil.Process
            for child in children:
                try:
                    logger.debug(f"终止子进程 {child.pid}...")
                    child.terminate()
                except psutil.NoSuchProcess:
                    logger.debug(f"子进程 {child.pid} 已不存在.")
                    continue
                except psutil.AccessDenied:
                    logger.warning(f"无权限终止子进程 {child.pid}.")
                    continue
                except Exception as e:
                    logger.warning(f"终止子进程 {child.pid} 时出错: {e}")

            gone: List[psutil.Process]
            alive: List[psutil.Process]
            gone, alive = psutil.wait_procs(children, timeout=1.5)
            if alive:
                logger.warning(f"{len(alive)} 个子进程未在规定时间内终止，将强制终止...")
                p: psutil.Process
                for p in alive:
                    try:
                        logger.debug(f"强制终止子进程 {p.pid}...")
                        p.kill()
                    except psutil.NoSuchProcess:
                        logger.debug(f"子进程 {p.pid} 在强制终止前已消失.")
                    except Exception as e:
                        logger.error(f"强制终止子进程 {p.pid} 失败: {e}")
    except psutil.NoSuchProcess:
        logger.warning("无法获取当前进程信息，跳过子进程终止。")
    except Exception as e:
        logger.error(f"终止子进程时出现意外错误: {e}")

    if 'share' in globals() and isinstance(share, QSharedMemory):
        try:
            if share.isAttached():
                share.detach()
                logger.debug("共享内存已分离")
        except Exception as e:
            logger.error(f"分离共享内存时出错: {e}")

    logger.debug(f"程序退出({status})")
    # If QApplication didn't exit the process (e.g. if not started or quit failed)
    # os._exit is a hard exit, use sys.exit for cleaner Python exit if possible
    if app is None or not app.closingDown(): # Check if Qt is managing exit
        sys.exit(status) # Prefer sys.exit
    # If app.quit() was called, it should handle process exit. os._exit as last resort.
    # os._exit(status)


def calculate_size(p_w: float = 0.6, p_h: float = 0.7) -> Tuple[Tuple[int, int], Tuple[int, int]]:  # 计算尺寸. Added types
    primary_screen = QApplication.primaryScreen()
    screen_geometry: QRect = primary_screen.geometry() if primary_screen else QRect(0,0,1920,1080) # type: ignore[union-attr] # Fallback

    screen_width: int = screen_geometry.width()
    screen_height: int = screen_geometry.height()

    width: int = int(screen_width * p_w)
    height: int = int(screen_height * p_h)

    # Position: centered horizontally, 150px from top
    pos_x: int = int(screen_width / 2 - width / 2)
    pos_y: int = 150

    return (width, height), (pos_x, pos_y)

def update_tray_tooltip() -> None: # Added return type
    """更新托盘文字"""
    # tray_icon is Optional[TrayIcon]
    if hasattr(sys.modules[__name__], 'tray_icon') and tray_icon is not None:
        schedule_name_from_conf: Optional[str] = config_center.read_conf('General', 'schedule') # type: ignore[no-untyped-call]
        if schedule_name_from_conf:
            try:
                schedule_display_name: str = schedule_name_from_conf
                if schedule_display_name.endswith('.json'):
                    schedule_display_name = schedule_display_name[:-5]
                tray_icon.setToolTip(f'Class Widgets - "{schedule_display_name}"')
                logger.info(f'托盘文字更新: "Class Widgets - {schedule_display_name}"')
            except Exception as e:
                logger.error(f"更新托盘提示时发生错误: {e}")
        else:
            tray_icon.setToolTip("Class Widgets - 未加载课表")
            logger.info(f'托盘文字更新: "Class Widgets - 未加载课表"')

class DarkModeWatcher(QObject):
    darkModeChanged = pyqtSignal(bool)  # 发出暗黑模式变化信号

    def __init__(self, interval: int = 500, parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self._isDarkMode: Optional[bool] = darkdetect.isDark() # type: ignore[no-untyped-call] # Initial state
        self._timer: QTimer = QTimer(self)
        self._timer.timeout.connect(self._checkTheme)
        self._timer.start(interval)  # 轮询间隔（毫秒）

    def _checkTheme(self) -> None: # Added return type
        currentMode: Optional[bool] = darkdetect.isDark() # type: ignore[no-untyped-call]
        if currentMode is not None and currentMode != self._isDarkMode:
            self._isDarkMode = currentMode
            self.darkModeChanged.emit(currentMode)  # 发出变化信号

    def isDark(self) -> Optional[bool]: # Added return type
        """返回当前是否暗黑模式"""
        return self._isDarkMode

    def stop(self) -> None: # Added return type
        """停止监听"""
        self._timer.stop()

    def start(self, interval: Optional[int] = None) -> None: # Added types
        """开始监听"""
        if interval is not None: # Check if interval is provided
            self._timer.setInterval(interval)
        self._timer.start()


class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent: Optional[QWidget] = None) -> None: # Added parent type and return type
        super().__init__(parent)
        # base_directory is Path
        icon_path = str(Path(base_directory) / "img" / "logo" / "favicon.png") # type: ignore[attr-defined]
        self.setIcon(QIcon(icon_path))

    def push_update_notification(self, text: str = '') -> None: # Added types
        # base_directory is Path
        icon_path_update = str(Path(base_directory) / "img" / "logo" / "favicon-update.png") # type: ignore[attr-defined]
        self.setIcon(QIcon(icon_path_update))
        self.showMessage(
            "发现 Class Widgets 新版本！",
            text,
            QIcon(icon_path_update),
            5000 # milliseconds
        )

    def push_error_notification(self, title: str = '检查更新失败！', text: str = '') -> None: # Added types
        # base_directory is Path
        icon_path_error = str(Path(base_directory) / "img" / "logo" / "favicon-error.ico") # type: ignore[attr-defined]
        self.setIcon(QIcon(icon_path_error))
        self.showMessage(
            title,
            text,
            QIcon(icon_path_error),
            5000 # milliseconds
        )


class UnionUpdateTimer(QObject):
    """
    统一更新计时器
    """
    def __init__(self, parent: Optional[QObject] = None) -> None: # Added parent type and return type
        super().__init__(parent)
        self.timer: QTimer = QTimer(self)
        self.timer.timeout.connect(self._on_timeout)
        self.callbacks: List[Callable[[], None]] = []  # 存储所有的回调函数
        self._is_running: bool = False

    def _on_timeout(self) -> None:  # 超时. Added return type
        app: Optional[QApplication] = QApplication.instance()
        # Check if app is closing down
        if not app or (hasattr(app, 'closingDown') and app.closingDown()): # closingDown might not exist on all Qt versions if app is None
            if self.timer.isActive():
                self.timer.stop()
            return

        # 使用最初的备份列表，防止遍历时修改
        callbacks_copy: List[Callable[[], None]] = self.callbacks[:]
        callback_func: Callable[[], None]
        for callback_func in callbacks_copy:
            if callback_func in self.callbacks: # Check if still in original list (not removed by another callback)
                try:
                    callback_func()
                except RuntimeError as e: # Typically for "wrapped C/C++ object of type ... has been deleted"
                    logger.error(f"回调调用错误 (可能对象已删除): {e}")
                    try:
                        self.callbacks.remove(callback_func)
                    except ValueError: # Should not happen if check `in self.callbacks` is reliable
                        pass
                except Exception as e:
                    logger.error(f"执行回调时发生未知错误: {e}")

        if self._is_running: # If still supposed to be running, schedule next tick
            self._schedule_next()

    def _schedule_next(self) -> None: # Added return type
        now: dt.datetime = dt.datetime.now()
        next_tick: dt.datetime = now.replace(microsecond=0) + dt.timedelta(seconds=1)
        delay_ms: int = max(0, int((next_tick - now).total_seconds() * 1000))
        self.timer.start(delay_ms)

    def add_callback(self, callback: Callable[[], None]) -> None: # Added type for callback
        if callback not in self.callbacks:
            self.callbacks.append(callback)
            if not self._is_running: # Start if not already running
                self.start()

    def remove_callback(self, callback: Callable[[], None]) -> None: # Added type for callback
        try:
            self.callbacks.remove(callback)
        except ValueError: # Callback not in list
            pass
        # Original code had logic to stop timer if no callbacks, but this might be undesirable
        # if callbacks are expected to be added again soon.
        # if not self.callbacks and self._is_running:
        #     self.stop()

    def remove_all_callbacks(self) -> None: # Added return type
        self.callbacks = []
        # self.stop() # Consider if stopping is desired when all callbacks are removed.

    def start(self) -> None: # Added return type
        if not self._is_running:
            logger.debug("启动 UnionUpdateTimer...")
            self._is_running = True
            self._schedule_next()

    def stop(self) -> None: # Added return type
        logger.debug("停止 UnionUpdateTimer...")
        self._is_running = False
        if self.timer: # Check if timer exists
            try:
                if self.timer.isActive():
                    self.timer.stop()
            except RuntimeError as e: # e.g. QTimer has been deleted
                logger.warning(f"停止 QTimer 时发生运行时错误: {e}")
            except Exception as e: # Other potential errors
                logger.error(f"停止 QTimer 时发生未知错误: {e}")

# Initialize global instances
tray_icon = None # Will be initialized as TrayIcon when app starts
update_timer = UnionUpdateTimer()
