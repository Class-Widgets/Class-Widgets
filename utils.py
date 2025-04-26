import os
import sys
import psutil

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QSystemTrayIcon, QApplication
from loguru import logger
from PyQt5.QtCore import QSharedMemory, QTimer, QObject
import datetime as dt

from file import base_directory, config_center
import signal

share = QSharedMemory('ClassWidgets')
_stop_in_progress = False

def restart():
    logger.debug('重启程序')
    app = QApplication.instance()
    if app:
        try:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (AttributeError, ValueError):
            pass
        app.quit()
        app.processEvents()

    if share.isAttached():
        share.detach()  # 释放共享内存
    os.execl(sys.executable, sys.executable, *sys.argv)

def stop(status=0):
    global share, update_timer, _stop_in_progress
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
        try:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (AttributeError, ValueError):
            pass
        app.quit()
    try:
        current_pid = os.getpid()
        parent = psutil.Process(current_pid)
        children = parent.children(recursive=True)
        if children:
            logger.debug(f"尝试终止 {len(children)} 个子进程...")
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

            gone, alive = psutil.wait_procs(children, timeout=1.5)
            if alive:
                logger.warning(f"{len(alive)} 个子进程未在规定时间内终止，将强制终止...")
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

    if 'share' in globals() and share:
        try:
            if share.isAttached():
                share.detach()
                logger.debug("共享内存已分离")
        except Exception as e:
            logger.error(f"分离共享内存时出错: {e}")

    logger.debug(f"程序退出({status})")
    if not app:
        os._exit(status)

def calculate_size(p_w=0.6, p_h=0.7):  # 计算尺寸
    screen_geometry = QApplication.primaryScreen().geometry()
    screen_width = screen_geometry.width()
    screen_height = screen_geometry.height()

    width = int(screen_width * p_w)
    height = int(screen_height * p_h)

    return (width, height), (int(screen_width / 2 - width / 2), 150)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon.png"))

    def push_update_notification(self, text=''):
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon-update.png"))  # tray
        self.showMessage(
            "发现 Class Widgets 新版本！",
            text,
            QIcon(f"{base_directory}/img/logo/favicon-update.png"),
            5000
        )

    def push_error_notification(self, title='检查更新失败！', text=''):
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timeout)
        self.callbacks = []  # 存储所有的回调函数
        self._is_running = False

    def _on_timeout(self):  # 超时
        app = QApplication.instance()
        if not app or app.closingDown():
            if self.timer.isActive():
                self.timer.stop()
            return

        # 使用最初的备份列表，防止遍历时修改
        callbacks_copy = self.callbacks[:]
        for callback in callbacks_copy:
            if callback in self.callbacks:
                try:
                    callback()
                except RuntimeError as e:
                    logger.error(f"回调调用错误 (可能对象已删除): {e}")
                    try:
                        self.callbacks.remove(callback)
                    except ValueError:
                        pass
                except Exception as e:
                    logger.error(f"执行回调时发生未知错误: {e}")
        if self._is_running:
            self._schedule_next()

    def _schedule_next(self):
        now = dt.datetime.now()
        next_tick = now.replace(microsecond=0) + dt.timedelta(seconds=1)
        delay = max(0, int((next_tick - now).total_seconds() * 1000))
        self.timer.start(delay)

    def add_callback(self, callback):
        if callback not in self.callbacks:
            self.callbacks.append(callback)
            if not self._is_running:
                self.start()

    def remove_callback(self, callback):
        try:
            self.callbacks.remove(callback)
        except ValueError:
            pass
        # if not self.callbacks and self._is_running:
        #     self.stop() # 删除定时器

    def remove_all_callbacks(self):
        self.callbacks = []
        # self.stop() # 删除定时器

    def start(self):
        if not self._is_running:
            logger.debug("启动 UnionUpdateTimer...")
            self._is_running = True
            self._schedule_next()

    def stop(self):
        self._is_running = False
        if self.timer:
            try:
                if self.timer.isActive():
                    self.timer.stop()
            except RuntimeError as e:
                logger.warning(f"停止 QTimer 时发生运行时错误: {e}")
            except Exception as e:
                logger.error(f"停止 QTimer 时发生未知错误: {e}")


tray_icon = None
update_timer = UnionUpdateTimer()
