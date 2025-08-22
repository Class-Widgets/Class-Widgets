from typing import Any, List, Optional, Tuple
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QTimer
from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, ProgressBar, theme, Theme, setTheme
import time

from i18n_manager import app
from conf import base_directory

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
        setTheme(Theme.DARK)
        self.init()
        self.apply_theme_stylesheet()

    def init(self):
        self.splash_window : QWidget = uic.loadUi(base_directory / 'view/splash.ui')
        self.splash_window.setWindowFlags(Qt.FramelessWindowHint)
        self.statusLabel = self.splash_window.findChild(BodyLabel, 'statusLabel')
        self.statusBar = self.splash_window.findChild(ProgressBar, 'statusBar')
        print(self.statusLabel.styleSheet())
        self.splash_window.setWindowModality(Qt.ApplicationModal)
        self.splash_window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                    Qt.WindowType.WindowDoesNotAcceptFocus | Qt.BypassWindowManagerHint | Qt.Tool)
        self.splash_window.show()
        
    def update_status(self, status: Tuple[int, str]):
        self.statusBar.setValue(status[0])
        self.statusLabel.setText(status[1])

    def apply_theme_stylesheet(self):
        if theme() == Theme.DARK:
            print("dark")
            # 暗色主题样式
            dark_stylesheet = """
            QWidget#SplashWelcomePage { 
                background: #1f1f1f; 
                background-image: url("./img/splash_right.svg");
                background-repeat: no-repeat;
                background-position: center right; 
            }
            #leftPanel {
                background: qlineargradient(x1:0, y1:0, x2:0.7, y2:1,
                                            stop:0 #1f2630, stop:0.5 #1c2230, stop:1 #161a24);
                border: none;
            }
            #sectionTitle {
                color: #e6e6e6;
                font-weight: 600;
            }
            #card {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 10px;
            }
            """
            self.splash_window.setStyleSheet(dark_stylesheet)
        else:
            print("light")
            # 亮色主题样式
            light_stylesheet = """
            QWidget#SplashWelcomePage { 
                background: #1f1f1f; 
                background-image: url("./img/splash_right.svg");
                background-repeat: no-repeat;
                background-position: center right; 
            }
            #leftPanel {
                background: qlineargradient(x1:0, y1:0, x2:0.7, y2:1,
                                            stop:0 #f0f0f0, stop:0.5 #e8e8e8, stop:1 #e0e0e0);
                border: none;
            }
            #card {
                background: rgba(0,0,0,0.04);
                border: 1px solid rgba(0,0,0,0.06);
                border-radius: 10px;
            }
            """
            self.splash_window.setStyleSheet(light_stylesheet)

    def run(self):
        dark_mode_watcher.start()
        self.dark_mode_watcher_connection = dark_mode_watcher.darkModeChanged.connect(lambda: self.apply_theme_stylesheet())
        self.update_status((0, app.translate('main', 'Class Widgets 启动中...')))
        app.processEvents()

    def close(self):
        dark_mode_watcher.darkModeChanged.disconnect(self.dark_mode_watcher_connection)
        dark_mode_watcher.stop()
        self.splash_window.close()
        self.splash_window.deleteLater()
        self.splash_window = None
  
if __name__ == '__main__':
    splash = Splash()
    splash.run()
    app.exec_()
