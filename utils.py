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


def restart():
    logger.debug('重启程序')
    if share.isAttached():
        share.detach()  # 释放共享内存
    os.execl(sys.executable, sys.executable, *sys.argv)

def stop(status=0):
    global share
    if hasattr(stop, '_called'):
        return
    stop._called = True

    def exit_application():
        logger.debug("强制退出")
        os._exit(status)

    def shutdown_handler(signum, frame):
        logger.info(f'收到关闭信号: {signum}')
        QApplication.instance().quit()

    signal.signal(signal.SIGTERM, shutdown_handler)  # taskkill
    signal.signal(signal.SIGINT, shutdown_handler)   # Ctrl+C
    signal.signal(signal.SIGABRT, shutdown_handler)  # 异常中止
    if os.name == 'posix':
        signal.signal(signal.SIGQUIT, shutdown_handler)  # POSIX退出
        signal.signal(signal.SIGHUP, shutdown_handler)   # 终端断开
    # 强制终止所有子进程
    try:
        current_pid = os.getpid()
        parent = psutil.Process(current_pid)
        for child in parent.children(recursive=True):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        gone, alive = psutil.wait_procs(parent.children(), timeout=3)
    except Exception as e:
        logger.error(f"终止子进程失败: {e}")

    if 'update_timer' in globals():
        try:
            update_timer.stop()
            update_timer.deleteLater()
        except RuntimeError as e:
            logger.error(f"停止定时器失败: {e}")
    app = QApplication.instance()
    if app:
        try:
            app.exit(status)
            for w in app.topLevelWidgets():
                w.close()
                w.deleteLater()
            app.closeAllWindows()
            app.quit()
            QTimer.singleShot(1000, exit_application)  # 1秒后强制退出
        except Exception as e:
            logger.error(f"关闭窗口时出错: {e}")
    try:
        if share.isAttached():
            share.detach()
            os.remove(share.nativeKey()) if os.name == 'posix' else None
            logger.debug("分离共享内存: 成功")
        else:
            logger.warning("共享内存未附加")
    except Exception as e:
        logger.error(f"分离共享内存失败: {e}")
        exit_application()
    finally:
        del share
    logger.debug("程序退出")
    sys.exit(status)


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

    def _on_timeout(self):  # 超时
        if QApplication.instance().closingDown():
            sys.exit(0)
            return
        for callback in self.callbacks[:]:
            try:
                callback()
            except RuntimeError as e:
                logger.error(f"回调调用错误: {e}")
                self.callbacks.remove(callback)
        self._schedule_next()

    def _schedule_next(self):
        next_tick = dt.datetime.now().replace(microsecond=0) + dt.timedelta(seconds=1)
        delay = int((next_tick - dt.datetime.now()).total_seconds() * 1000)
        if delay < 0:
            delay = 0
        self.timer.start(delay)

    def add_callback(self, callback):  # 添加回调
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def remove_callback(self, callback):
        """ 移除回调函数 """
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def remove_all_callbacks(self):
        """ 移除所有回调函数 """
        self.callbacks = []

    def start(self):  # 启动定时器
        self.timer.start(1000)
        self._schedule_next()  # 计算下次触发时间

    def stop(self):  # 停止
        if self.timer:
            try:
                self.timer.stop()
                self.timer.deleteLater()
            except RuntimeError:
                logger.warning("计时器已被销毁，跳过停止操作")
        self.remove_all_callbacks()  # 移除所有回调函数


tray_icon = None
update_timer = UnionUpdateTimer()
