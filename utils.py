import os
import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QSystemTrayIcon, QApplication
from loguru import logger
from PyQt5.QtCore import QSharedMemory

from basic_dirs import CW_HOME


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


tray_icon = None


class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(QIcon(str(CW_HOME / "img/logo/favicon.png")))

    def push_update_notification(self, text=''):
        self.setIcon(QIcon(str(CW_HOME / "img/logo/favicon-update.png")))  # tray
        self.showMessage(
            "发现 Class Widgets 新版本！",
            text,
            QIcon(str(CW_HOME / "img/logo/favicon-update.png")),
            5000
        )

    def push_error_notification(self, title='检查更新失败！', text=''):
        self.setIcon(QIcon(str(CW_HOME / "img/logo/favicon-update.png")))  # tray
        self.showMessage(
            title,
            text,
            QIcon(str(CW_HOME / "img/logo/favicon-error.ico")),
            5000
        )
