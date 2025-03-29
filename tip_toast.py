import sys

import os
from PyQt5 import uic
from PyQt5.QtCore import Qt, QPropertyAnimation, QRect, QEasingCurve, QTimer, QPoint, pyqtProperty, QThread
from PyQt5.QtGui import QColor, QPainter, QBrush, QPixmap
from PyQt5.QtWidgets import QWidget, QApplication, QLabel, QFrame, QGraphicsBlurEffect
from loguru import logger
from qfluentwidgets import setThemeColor

import conf
from conf import base_directory
import list_
from file import config_center
from play_audio import PlayAudio

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

prepare_class = config_center.read_conf('Audio', 'prepare_class')
attend_class = config_center.read_conf('Audio', 'attend_class')
finish_class = config_center.read_conf('Audio', 'finish_class')

pushed_notification = False
notification_contents = {"state": None, "lesson_name": None, "title": None, "subtitle": None, "content": None}

# 波纹效果
normal_color = '#56CFD8'

window_list = []  # 窗口列表
active_windows = []


class tip_toast(QWidget):
    def __init__(self, pos, width, state=1, lesson_name=None, title=None, subtitle=None, content=None, icon=None, duration=2000):
        super().__init__()
        for w in active_windows[:]:
            w.close()
        active_windows.append(self)
        self.audio_thread = None
        uic.loadUi(f"{base_directory}/view/widget-toast-bar.ui", self)

        # 窗口位置
        if config_center.read_conf('Toast', 'pin_on_top') == '1':
            self.setWindowFlags(
                Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint |
                Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.WindowStaysOnBottomHint | Qt.WindowType.FramelessWindowHint
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.move(pos[0], pos[1])
        self.resize(width, height)

        # 标题
        title_label = self.findChild(QLabel, 'title')
        backgnd = self.findChild(QFrame, 'backgnd')
        lesson = self.findChild(QLabel, 'lesson')
        subtitle_label = self.findChild(QLabel, 'subtitle')
        icon_label = self.findChild(QLabel, 'icon')

        if icon:
            pixmap = QPixmap(icon)
            pixmap = pixmap.scaled(48, 48)
            icon_label.setPixmap(pixmap)

        if state == 1:
            logger.info('上课铃声显示')
            title_label.setText('活动开始')  # 修正文本，以适应不同场景
            subtitle_label.setText('当前课程')
            lesson.setText(lesson_name)  # 课程名
            self.playsound(attend_class)
            setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}")  # 主题色
        elif state == 0:
            logger.info('下课铃声显示')
            title_label.setText('下课')
            if lesson_name:
                subtitle_label.setText('即将进行')
            else:
                subtitle_label.hide()
            lesson.setText(lesson_name)  # 课程名
            self.playsound(finish_class)
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")
        elif state == 2:
            logger.info('放学铃声显示')
            title_label.setText('放学')
            subtitle_label.setText('当前课程已结束')
            lesson.setText('')  # 课程名
            self.playsound(finish_class)
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")
        elif state == 3:
            logger.info('预备铃声显示')
            title_label.setText('即将开始')  # 同上
            subtitle_label.setText('下一节')
            lesson.setText(lesson_name)
            self.playsound(prepare_class)
            setThemeColor(f"#{config_center.read_conf('Color', 'prepare_class')}")
        elif state == 4:
            logger.info(f'通知显示: {title}')
            title_label.setText(title)
            subtitle_label.setText(subtitle)
            lesson.setText(content)
            self.playsound(prepare_class)

        # 设置样式表
        if state == 1:  # 上课铃声
            bg_color = [  # 1为正常、2为渐变亮色部分、3为渐变暗色部分
                generate_gradient_color(attend_class_color)[0],
                generate_gradient_color(attend_class_color)[1],
                generate_gradient_color(attend_class_color)[2]
            ]
        elif state == 0 or state == 2:  # 下课铃声
            bg_color = [
                generate_gradient_color(finish_class_color)[0],
                generate_gradient_color(finish_class_color)[1],
                generate_gradient_color(finish_class_color)[2]
            ]
        elif state == 3:  # 预备铃声
            bg_color = [
                generate_gradient_color(prepare_class_color)[0],
                generate_gradient_color(prepare_class_color)[1],
                generate_gradient_color(prepare_class_color)[2]
            ]
        elif state == 4:  # 通知铃声
            bg_color = ['rgba(110, 190, 210, 255)', 'rgba(110, 190, 210, 255)', 'rgba(90, 210, 215, 255)']
        else:
            bg_color = ['rgba(110, 190, 210, 255)', 'rgba(110, 190, 210, 255)', 'rgba(90, 210, 215, 255)']

        backgnd.setStyleSheet(f'font-weight: bold; border-radius: {radius}; '
                              'background-color: qlineargradient('
                              'spread:pad, x1:0, y1:0, x2:1, y2:1,'
                              f' stop:0 {bg_color[1]}, stop:0.5 {bg_color[0]}, stop:1 {bg_color[2]}'
                              ');'
                              )

        # 模糊效果
        self.blur_effect = QGraphicsBlurEffect(self)
        if config_center.read_conf('Toast', 'wave') == '1':
            backgnd.setGraphicsEffect(self.blur_effect)

        # 设置窗口初始大小
        mini_size_x = 150
        mini_size_y = 50

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(duration)
        self.timer.timeout.connect(self.close_window)

        # 放大效果
        self.geometry_animation = QPropertyAnimation(self, b"geometry")
        self.geometry_animation.setDuration(750)  # 动画持续时间
        self.geometry_animation.setStartValue(
            QRect(int(start_x + mini_size_x / 2), int(start_y + mini_size_y / 2),
                  total_width - mini_size_x, height - mini_size_y)
        )
        self.geometry_animation.setEndValue(QRect(start_x, start_y, total_width, height))
        self.geometry_animation.setEasingCurve(QEasingCurve.Type.OutCirc)
        self.geometry_animation.finished.connect(self.timer.start)

        self.blur_animation = QPropertyAnimation(self.blur_effect, b"blurRadius")
        self.blur_animation.setDuration(550)
        self.blur_animation.setStartValue(25)
        self.blur_animation.setEndValue(0)

        # 渐显
        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(450)
        self.opacity_animation.setStartValue(0)
        self.opacity_animation.setEndValue(1)

        self.geometry_animation.start()
        self.opacity_animation.start()
        self.blur_animation.start()

    def close_window(self):
        mini_size_x = 120
        mini_size_y = 20
        # 放大效果
        self.geometry_animation_close = QPropertyAnimation(self, b"geometry")
        self.geometry_animation_close.setDuration(400)  # 动画持续时间
        self.geometry_animation_close.setStartValue(QRect(start_x, start_y, total_width, height))
        self.geometry_animation_close.setEndValue(
            QRect(int(start_x + mini_size_x / 2), int(start_y + mini_size_y / 2),
                  total_width - mini_size_x, height - mini_size_y))
        self.geometry_animation_close.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.blur_animation_close = QPropertyAnimation(self.blur_effect, b"blurRadius")
        self.blur_animation_close.setDuration(450)
        self.blur_animation_close.setStartValue(0)
        self.blur_animation_close.setEndValue(30)

        self.opacity_animation_close = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation_close.setDuration(400)
        self.opacity_animation_close.setStartValue(1)
        self.opacity_animation_close.setEndValue(0)

        self.geometry_animation_close.start()
        self.opacity_animation_close.start()
        self.blur_animation_close.start()
        self.opacity_animation_close.finished.connect(self.close)

    def closeEvent(self, event):
        if self in active_windows:
            active_windows.remove(self)
        global window_list
        # window_list.remove(self)
        self.hide()
        self.deleteLater()
        event.ignore()

    def playsound(self, filename):
        try:
            file_path = os.path.join(base_directory, 'audio', filename)
            self.audio_thread = PlayAudio(str(file_path))
            self.audio_thread.start()
            if self.audio_thread.isRunning():
                self.audio_thread.setPriority(QThread.HighestPriority)
        except Exception as e:
            logger.error(f'播放音频文件失败：{e}')


class wave_Effect(QWidget):
    def __init__(self, state=1):
        super().__init__()

        if config_center.read_conf('Toast', 'pin_on_top') == '1':
            self.setWindowFlags(
                Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint |
                Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.WindowStaysOnBottomHint | Qt.WindowType.FramelessWindowHint |
                Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._radius = 0
        self.duration = 1150

        if state == 1:
            self.color = QColor(attend_class_color)
        elif state == 0 or state == 2:
            self.color = QColor(finish_class_color)
        elif state == 3:
            self.color = QColor(prepare_class_color)
        elif state == 4:
            self.color = QColor(normal_color)
        else:
            self.color = QColor(normal_color)

        screen_geometry = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geometry)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(275)
        self.timer.timeout.connect(self.showAnimation)
        self.timer.start()

    @pyqtProperty(int)
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        self._radius = value
        self.update()

    def showAnimation(self):
        self.animation = QPropertyAnimation(self, b'radius')
        self.animation.setDuration(self.duration)
        self.animation.setStartValue(50)
        self.animation.setEndValue(max(self.width(), self.height()) * 1.7)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)
        self.animation.start()

        self.fade_animation = QPropertyAnimation(self, b'windowOpacity')
        self.fade_animation.setDuration(self.duration - self.duration // 5)

        self.fade_animation.setKeyValues([  # 关键帧
            (0, 0),
            (0.06, 0.9),
            (1, 0)
        ])

        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutCirc)
        self.fade_animation.finished.connect(self.close)
        self.fade_animation.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self.color))
        painter.setPen(Qt.PenStyle.NoPen)
        center = self.rect().center()
        loc = QPoint(center.x(), self.rect().top() + start_y + 50)
        painter.drawEllipse(loc, self._radius, self._radius)

    def closeEvent(self, event):
        if self in active_windows:
            active_windows.remove(self)
        global window_list
        # window_list.remove(self)
        self.deleteLater()
        self.hide()
        event.ignore()


def generate_gradient_color(theme_color):  # 计算渐变色
    def adjust_color(color, factor):
        r = max(0, min(255, int(color.red() * (1 + factor))))
        g = max(0, min(255, int(color.green() * (1 + factor))))
        b = max(0, min(255, int(color.blue() * (1 + factor))))
        # return QColor(r, g, b)
        return f'rgba({r}, {g}, {b}, 255)'

    color = QColor(theme_color)
    gradient = [adjust_color(color, 0), adjust_color(color, 0.24), adjust_color(color, -0.11)]
    return gradient


def main(state=1, lesson_name='', title='通知示例', subtitle='副标题',
         content='这是一条通知示例', icon=None, duration=2000):  # 0:下课铃声 1:上课铃声 2:放学铃声 3:预备铃 4:其他
    if detect_enable_toast(state):
        return

    global start_x, start_y, total_width, height, radius, attend_class_color, finish_class_color, prepare_class_color

    widgets = list_.get_widget_config()
    for widget in widgets:  # 检查组件
        if widget not in list_.widget_name:
            widgets.remove(widget)  # 移除不存在的组件(确保移除插件后不会出错)

    attend_class_color = f"#{config_center.read_conf('Color', 'attend_class')}"
    finish_class_color = f"#{config_center.read_conf('Color', 'finish_class')}"
    prepare_class_color = f"#{config_center.read_conf('Color', 'prepare_class')}"

    theme = config_center.read_conf('General', 'theme')
    height = conf.load_theme_config(theme)['height']
    radius = conf.load_theme_config(theme)['radius']

    screen_geometry = QApplication.primaryScreen().geometry()
    screen_width = screen_geometry.width()
    spacing = conf.load_theme_config(theme)['spacing']

    widgets_width = 0
    for widget in widgets:  # 计算总宽度(兼容插件)
        try:
            widgets_width += conf.load_theme_width(theme)[widget]
        except KeyError:
            widgets_width += list_.widget_width[widget]
        except:
            widgets_width += 0

    total_width = widgets_width + spacing * (len(widgets) - 1)

    start_x = int((screen_width - total_width) / 2)
    start_y = int(config_center.read_conf('General', 'margin'))

    if state != 4:
        window = tip_toast((start_x, start_y), total_width, state, lesson_name, duration=duration)
    else:
        window = tip_toast(
            (start_x, start_y),
            total_width, state,
            '',
            title,
            subtitle,
            content,
            icon,
            duration=duration
        )

    window.show()
    window_list.append(window)

    if config_center.read_conf('Toast', 'wave') == '1':
        wave = wave_Effect(state)
        wave.show()
        window_list.append(wave)


def detect_enable_toast(state=0):
    if config_center.read_conf('Toast', 'attend_class') != '1' and state == 1:
        return True
    if (config_center.read_conf('Toast', 'finish_class') != '1') and (state in [0, 2]):
        return True
    if config_center.read_conf('Toast', 'prepare_class') != '1' and state == 3:
        return True
    else:
        return False


def push_notification(state=1, lesson_name='', title=None, subtitle=None,
                      content=None):  # 推送通知
    global pushed_notification, notification_contents
    pushed_notification = True
    notification_contents = {
        "state": state,
        "lesson_name": lesson_name,
        "title": title,
        "subtitle": subtitle,
        "content": content
    }
    main(state, lesson_name, title, subtitle, content)
    return notification_contents


if __name__ == '__main__':
    app = QApplication(sys.argv)
    main(
        state=4,  # 自定义通知
        title='天气预报',
        subtitle='',
        content='1°~-3° | 3°~-3° | 9°~1°',
        icon='img/favicon.ico',
        duration=2000
    )
    sys.exit(app.exec())
