import time
from typing import Optional, Tuple

from loguru import logger
from PyQt5 import uic
from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QWidget
from qfluentwidgets import ProgressBar, Theme, theme

from basic_dirs import CW_HOME
from i18n_manager import app


class DarkModeWatcherThread(QThread):
    darkModeChanged = pyqtSignal(bool)  # 发出暗黑模式变化信号

    def __init__(self, interval: int = 500, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.interval = interval / 1000
        self._isDarkMode: bool = bool(theme() == Theme.DARK)  # 初始状态
        self._running = True

    def _checkTheme(self) -> None:
        currentMode: bool = bool(theme() == Theme.DARK)
        if currentMode != self._isDarkMode:
            self._isDarkMode = currentMode
            self.darkModeChanged.emit(currentMode)  # 发出变化信号

    def isDark(self) -> bool:
        """返回当前是否暗黑模式"""
        return self._isDarkMode

    def run(self) -> None:
        """开始监听"""
        while self._running:
            if self.interval is not None:
                time.sleep(self.interval)
            self._checkTheme()  # 检查主题变化

    def stop(self):
        """停止监听"""
        self._running = False


dark_mode_watcher = DarkModeWatcherThread(200, app)


class Splash:
    def __init__(self):
        super().__init__()
        self.init()
        self.apply_theme_stylesheet()

    def init(self):
        self.splash_window: QWidget = uic.loadUi(CW_HOME / 'view/splash.ui')
        self.statusLabel = self.splash_window.findChild(QLabel, 'statusLabel')
        self.statusBar = self.splash_window.findChild(ProgressBar, 'statusBar')
        self.appInitials = self.splash_window.findChild(QLabel, 'appInitials')
        self.splash_window.setAttribute(Qt.WA_TranslucentBackground)
        self.splash_window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.BypassWindowManagerHint
            | Qt.Tool
        )
        self.splash_window.show()

    def update_status(self, status: Tuple[int, str]):
        if self.splash_window is None:
            return
        self.statusBar.setValue(status[0])
        self.statusLabel.setText(status[1])

    def apply_theme_stylesheet(self):
        if self.splash_window is None:
            return
        if theme() == Theme.DARK:
            # 暗色主题样式
            dark_stylesheet = """
            QWidget{ background:#2c2c2c; }
            #logoBox{ background:#202020; border:1px solid #0a0a0a; border-radius:12px; }
            #logo{ background:transparent; }
            """
            self.splash_window.setStyleSheet(dark_stylesheet)
        else:
            # 亮色主题样式
            light_stylesheet = """
            QWidget{ background:#ffffff; }
            #logoBox{ background:#f7f7f9; border:1px solid #e9e9ec; border-radius:12px; }
            #logo{ background:transparent; }
            """
            self.splash_window.setStyleSheet(light_stylesheet)

    def run(self):
        logger.info("Splash 启动")
        dark_mode_watcher.start()
        self.dark_mode_watcher_connection = dark_mode_watcher.darkModeChanged.connect(
            self.apply_theme_stylesheet
        )
        self.update_status((0, app.translate('main', 'Class Widgets 启动中...')))
        app.processEvents()

    def close(self):
        logger.info("Splash 关闭")
        dark_mode_watcher.darkModeChanged.disconnect(self.dark_mode_watcher_connection)
        dark_mode_watcher.stop()
        self.splash_window.close()
        self.splash_window.deleteLater()
        self.splash_window = None

    def error(self):
        if self.splash_window is None:
            return
        logger.info("Splash 接收到错误")
        self.appInitials.setPixmap(QPixmap(f'{CW_HOME}/img/logo/favicon-error.ico'))
        self.splash_window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.BypassWindowManagerHint | Qt.Tool
        )
        self.splash_window.show()

    def unerror(self):
        if self.splash_window is None:
            return
        logger.info("Splash 恢复正常")
        self.appInitials.setPixmap(QPixmap(f'{CW_HOME}/img/logo/favicon.ico'))
        self.splash_window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.BypassWindowManagerHint
            | Qt.Tool
        )
        self.splash_window.show()


if __name__ == '__main__':
    splash = Splash()
    splash.run()
    app.exec_()
