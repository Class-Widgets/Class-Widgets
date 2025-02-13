import os
import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QSystemTrayIcon, QApplication
from loguru import logger
from PyQt5.QtCore import QSharedMemory, QTimer, QObject
import datetime as dt

from file import base_directory, config_center

share = QSharedMemory('ClassWidgets')


def restart():
    logger.debug('重启程序')
    share.detach()  # 释放共享内存
    os.execl(sys.executable, sys.executable, *sys.argv)


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
        for callback in self.callbacks:
            callback()

    def _schedule_next(self):  # 调整下一次触发时间
        next_second = (dt.datetime.now() + dt.timedelta(seconds=1)).replace(microsecond=0)
        delay = (next_second - dt.datetime.now()).total_seconds() * 1000  # 转换为毫秒
        self.timer.start(int(delay))  # 设定下一次触发时间

    def add_callback(self, callback):  # 添加回调
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def remove_callback(self, callback):
        """ 移除回调函数 """
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def remove_all_callbacks(self):
        """ 移除所有回调函数 """
        self.callbacks = [config_center.update_conf]

    def start(self):  # 启动定时器
        self._schedule_next()  # 计算下次触发时间


tray_icon = None
update_timer = UnionUpdateTimer()
