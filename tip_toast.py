import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from PyQt5 import uic
from PyQt5.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QThread,
    QTimer,
    pyqtProperty,
)
from PyQt5.QtGui import QBrush, QColor, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QFrame, QGraphicsBlurEffect, QLabel, QWidget
from qfluentwidgets import setThemeColor

import conf
import list_
from basic_dirs import CW_HOME
from file import config_center
from generate_speech import get_tts_service
from play_audio import PlayAudio

prepare_class = config_center.read_conf('Audio', 'prepare_class')
attend_class = config_center.read_conf('Audio', 'attend_class')
finish_class = config_center.read_conf('Audio', 'finish_class')

pushed_notification = False
notification_contents = {
    "state": None,
    "lesson_name": None,
    "title": None,
    "subtitle": None,
    "content": None,
}

# 波纹效果
normal_color = '#56CFD8'

window_list = []  # 窗口列表
active_windows = []
tts_service = None  # TTS实例


class tip_toast(QWidget):
    def __init__(
        self,
        pos: Tuple[int, int],
        width: int,
        state: int = 1,
        lesson_name: Optional[str] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        content: Optional[str] = None,
        icon: Optional[str] = None,
        duration: int = 2000,
    ) -> None:
        super().__init__()
        for w in active_windows[:]:
            w.close()
        active_windows.append(self)
        self.audio_thread = None
        global tts_service
        if tts_service is None:
            tts_service = get_tts_service()

        uic.loadUi(str(CW_HOME / "view" / "widget-toast-bar.ui"), self)

        try:
            dpr = (
                self.screen().devicePixelRatio()
                if self.screen()
                else QApplication.primaryScreen().devicePixelRatio()
            )
        except AttributeError:
            dpr = QApplication.primaryScreen().devicePixelRatio()
        dpr = max(1.0, dpr)

        # 窗口位置
        if config_center.read_conf('Toast', 'pin_on_top') == '1':
            self.setWindowFlags(
                Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.FramelessWindowHint
                | Qt.BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
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

        sound_to_play = None
        tts_text = None  # TTS文本
        tts_enabled = config_center.read_conf('TTS', 'enable')
        if tts_enabled is None:
            tts_enabled = ''
        tts_enabled = tts_enabled == '1'
        tts_voice_id = config_center.read_conf('TTS', 'voice_id')
        if tts_voice_id is None:
            tts_voice_id = ''

        if icon:
            pixmap = QPixmap(icon)
            icon_size = int(48 * dpr)
            pixmap = pixmap.scaled(
                icon_size,
                icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_label.setPixmap(pixmap)
            icon_label.setFixedSize(icon_size, icon_size)

        prepare_minutes = config_center.read_conf('Toast', 'prepare_minutes')
        format_values = defaultdict(
            str, {'lesson_name': '', 'minutes': '', 'title': '', 'content': ''}
        )

        if state == 1:
            logger.info('上课铃声显示')
            title_label.setText(self.tr('活动开始'))  # 修正文本，以适应不同场景
            subtitle_label.setText(self.tr('当前课程'))
            lesson.setText(lesson_name)  # 课程名
            sound_to_play = attend_class
            format_values['lesson_name'] = lesson_name
            tts_text = config_center.read_conf('TTS', 'attend_class').format_map(format_values)
            # 使用 QTimer.singleShot 延迟设置主题色，避免 WeakKeyDictionary 并发修改错误
            QTimer.singleShot(
                0, lambda: setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}")
            )
        elif state == 0:
            logger.info(self.tr('下课铃声显示'))
            title_label.setText(self.tr('下课'))
            if lesson_name:
                subtitle_label.setText(self.tr('即将进行'))
            else:
                subtitle_label.hide()
            lesson.setText(lesson_name)  # 课程名
            sound_to_play = finish_class
            format_values['lesson_name'] = lesson_name
            tts_text = config_center.read_conf('TTS', 'finish_class').format_map(format_values)
            # 使用 QTimer.singleShot 延迟设置主题色，避免 WeakKeyDictionary 并发修改错误
            QTimer.singleShot(
                0, lambda: setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")
            )
        elif state == 2:
            logger.info(self.tr('放学铃声显示'))
            title_label.setText(self.tr('放学'))
            subtitle_label.setText(self.tr('当前课程已结束'))
            lesson.setText('')  # 课程名
            sound_to_play = finish_class
            tts_text = config_center.read_conf('TTS', 'after_school').format_map(format_values)
            # 使用 QTimer.singleShot 延迟设置主题色，避免 WeakKeyDictionary 并发修改错误
            QTimer.singleShot(
                0, lambda: setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")
            )
        elif state == 3:
            logger.info(self.tr('预备铃声显示'))
            title_label.setText(self.tr('即将开始'))  # 同上
            subtitle_label.setText(self.tr('下一节'))
            lesson.setText(lesson_name)
            sound_to_play = prepare_class
            format_values['lesson_name'] = lesson_name
            format_values['minutes'] = prepare_minutes
            tts_text = config_center.read_conf('TTS', 'prepare_class').format_map(format_values)
            # 使用 QTimer.singleShot 延迟设置主题色，避免 WeakKeyDictionary 并发修改错误
            QTimer.singleShot(
                0, lambda: setThemeColor(f"#{config_center.read_conf('Color', 'prepare_class')}")
            )
        elif state == 4:
            logger.info(self.tr('通知显示: {title}').format(title=title))
            title_label.setText(title)
            subtitle_label.setText(subtitle)
            lesson.setText(content)
            sound_to_play = prepare_class
            format_values['title'] = title
            format_values['content'] = content
            tts_text = config_center.read_conf('TTS', 'otherwise').format_map(format_values)

        # 检查 TTS 文本是否为空或仅包含空白字符
        if tts_enabled and tts_text and tts_text.strip() and tts_voice_id:
            logger.info(f"播放TTS: '{tts_text}', 语音ID: {tts_voice_id}")
            try:
                from generate_speech import is_tts_playing, stop_tts

                if is_tts_playing():
                    logger.warning("TTS正在播放中，停止当前播放")
                    stop_tts()
            except ImportError as e:
                logger.warning(f"导入TTS失败: {e}")
            task_id = tts_service.play_tts(
                text=tts_text,
                voice_id=tts_voice_id,
                auto_fallback=True,
                on_complete=lambda file_path: logger.info(f"TTS播放完成: {file_path}"),
                on_error=lambda error: logger.error(f"TTS播放失败: {error}"),
            )

            if task_id:
                logger.info(f"TTS任务已启动: {task_id}")
            else:
                logger.warning("TTS任务启动失败")
        elif tts_enabled and tts_text and not tts_voice_id:
            logger.warning(f"TTS已启用，但未找到有效的语音ID: '{tts_voice_id}'")
        elif tts_enabled and (not tts_text or not tts_text.strip()):
            logger.warning("TTS已启用，但文本内容为空，跳过TTS生成")

        # 设置样式表
        if state == 1:  # 上课铃声
            bg_color = [  # 1为正常、2为渐变亮色部分、3为渐变暗色部分
                generate_gradient_color(attend_class_color)[0],
                generate_gradient_color(attend_class_color)[1],
                generate_gradient_color(attend_class_color)[2],
            ]
        elif state in {0, 2}:  # 下课铃声
            bg_color = [
                generate_gradient_color(finish_class_color)[0],
                generate_gradient_color(finish_class_color)[1],
                generate_gradient_color(finish_class_color)[2],
            ]
        elif state == 3:  # 预备铃声
            bg_color = [
                generate_gradient_color(prepare_class_color)[0],
                generate_gradient_color(prepare_class_color)[1],
                generate_gradient_color(prepare_class_color)[2],
            ]
        elif state == 4:  # 通知铃声
            bg_color = [
                'rgba(110, 190, 210, 255)',
                'rgba(110, 190, 210, 255)',
                'rgba(90, 210, 215, 255)',
            ]
        else:
            bg_color = [
                'rgba(110, 190, 210, 255)',
                'rgba(110, 190, 210, 255)',
                'rgba(90, 210, 215, 255)',
            ]

        backgnd.setStyleSheet(
            f'font-weight: bold; border-radius: {radius}; '
            'background-color: qlineargradient('
            'spread:pad, x1:0, y1:0, x2:1, y2:1,'
            f' stop:0 {bg_color[1]}, stop:0.5 {bg_color[0]}, stop:1 {bg_color[2]}'
            ');'
        )

        # 模糊效果
        self.blur_effect = QGraphicsBlurEffect(self)
        if config_center.read_conf('Toast', 'wave') == '1':
            backgnd.setGraphicsEffect(self.blur_effect)

        mini_size_x = 150 / dpr
        mini_size_y = 50 / dpr

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(duration)
        self.timer.timeout.connect(self.close_window)

        # 放大效果
        self.geometry_animation = QPropertyAnimation(self, b"geometry")
        self.geometry_animation.setDuration(750)  # 动画持续时间
        start_rect = QRect(
            int(start_x + mini_size_x / 2),
            int(start_y + mini_size_y / 2),
            int(total_width - mini_size_x),
            int(height - mini_size_y),
        )
        self.geometry_animation.setStartValue(start_rect)
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
        self.opacity_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        if sound_to_play:
            self.playsound(sound_to_play)

        self.geometry_animation.start()
        self.opacity_animation.start()
        self.blur_animation.start()

    def close_window(self) -> None:
        try:
            dpr = (
                self.screen().devicePixelRatio()
                if self.screen()
                else QApplication.primaryScreen().devicePixelRatio()
            )
        except AttributeError:
            dpr = QApplication.primaryScreen().devicePixelRatio()
        dpr = max(1.0, dpr)
        mini_size_x = 120 / dpr
        mini_size_y = 20 / dpr

        # 放大效果
        self.geometry_animation_close = QPropertyAnimation(self, b"geometry")
        self.geometry_animation_close.setDuration(500)  # 动画持续时间
        self.geometry_animation_close.setStartValue(QRect(start_x, start_y, total_width, height))
        end_rect = QRect(
            int(start_x + mini_size_x / 2),
            int(start_y + mini_size_y / 2),
            int(total_width - mini_size_x),
            int(height - mini_size_y),
        )
        self.geometry_animation_close.setEndValue(end_rect)
        self.geometry_animation_close.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.blur_animation_close = QPropertyAnimation(self.blur_effect, b"blurRadius")
        self.blur_animation_close.setDuration(500)
        self.blur_animation_close.setStartValue(0)
        self.blur_animation_close.setEndValue(30)

        self.opacity_animation_close = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation_close.setDuration(500)
        self.opacity_animation_close.setStartValue(1)
        self.opacity_animation_close.setEndValue(0)

        self.geometry_animation_close.start()
        self.opacity_animation_close.start()
        self.blur_animation_close.start()
        self.opacity_animation_close.finished.connect(self.close)

    def closeEvent(self, event) -> None:
        if self in active_windows:
            active_windows.remove(self)
        global window_list
        # window_list.remove(self)
        self.hide()
        self.deleteLater()
        event.ignore()

    def playsound(self, filename: str) -> None:
        try:
            file_path = CW_HOME / "audio" / filename
            if self.audio_thread and self.audio_thread.isRunning():
                self.audio_thread.quit()
                self.audio_thread.wait()
            self.audio_thread = PlayAudio(
                file_path=str(file_path), volume=1.0, cleanup_callback=None, blocking=False
            )
            self.audio_thread.start()
            self.audio_thread.setPriority(QThread.Priority.HighestPriority)  # 设置优先级
        except Exception as e:
            logger.error(f'播放音频文件失败：{e}')


class wave_Effect(QWidget):
    def __init__(self, state: int = 1) -> None:
        super().__init__()

        if config_center.read_conf('Toast', 'pin_on_top') == '1':
            self.setWindowFlags(
                Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.FramelessWindowHint
                | Qt.BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.WindowStaysOnBottomHint
                | Qt.WindowType.FramelessWindowHint
                | Qt.BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._radius = 0
        self.duration = 1200

        if state == 1:
            self.color = QColor(attend_class_color)
        elif state in {0, 2}:
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
    def radius(self) -> int:
        return self._radius

    @radius.setter
    def radius(self, value: int) -> None:
        self._radius = value
        self.update()

    def showAnimation(self) -> None:
        self.animation = QPropertyAnimation(self, b'radius')
        self.animation.setDuration(self.duration)
        self.animation.setStartValue(50)
        try:
            dpr = (
                self.screen().devicePixelRatio()
                if self.screen()
                else QApplication.primaryScreen().devicePixelRatio()
            )
        except AttributeError:
            dpr = QApplication.primaryScreen().devicePixelRatio()
        dpr = max(1.0, dpr)
        fixed_end_radius = 1000 * dpr  # 动画效果值
        self.animation.setEndValue(fixed_end_radius)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.animation.start()

        self.fade_animation = QPropertyAnimation(self, b'windowOpacity')
        self.fade_animation.setDuration(self.duration - 150)

        self.fade_animation.setKeyValues([(0, 0), (0.06, 0.9), (1, 0)])  # 关键帧

        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_animation.finished.connect(self.close)
        self.fade_animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self.color))
        painter.setPen(Qt.PenStyle.NoPen)
        center = self.rect().center()
        loc = QPoint(center.x(), self.rect().top() + start_y + 50)
        painter.drawEllipse(loc, self._radius, self._radius)

    def closeEvent(self, event) -> None:
        if self in active_windows:
            active_windows.remove(self)
        global window_list
        # window_list.remove(self)
        self.deleteLater()
        self.hide()
        event.ignore()


def generate_gradient_color(theme_color: str) -> List[str]:  # 计算渐变色
    def adjust_color(color: QColor, factor: float) -> str:
        r = max(0, min(255, int(color.red() * (1 + factor))))
        g = max(0, min(255, int(color.green() * (1 + factor))))
        b = max(0, min(255, int(color.blue() * (1 + factor))))
        # return QColor(r, g, b)
        return f'rgba({r}, {g}, {b}, 255)'

    color = QColor(theme_color)
    return [adjust_color(color, 0), adjust_color(color, 0.24), adjust_color(color, -0.11)]


def main(
    state: int = 1,
    lesson_name: str = '',
    title: str = '通知示例',
    subtitle: str = '副标题',
    content: str = '这是一条通知示例',
    icon: Optional[str] = None,
    duration: int = 2000,
) -> None:  # 0:下课铃声 1:上课铃声 2:放学铃声 3:预备铃 4:其他
    if detect_enable_toast(state):
        return

    global \
        start_x, \
        start_y, \
        total_width, \
        height, \
        radius, \
        attend_class_color, \
        finish_class_color, \
        prepare_class_color

    widgets = list_.get_widget_config()
    for widget in widgets:  # 检查组件
        if widget not in list_.widget_name:
            widgets.remove(widget)  # 移除不存在的组件(确保移除插件后不会出错)

    attend_class_color = f"#{config_center.read_conf('Color', 'attend_class')}"
    finish_class_color = f"#{config_center.read_conf('Color', 'finish_class')}"
    prepare_class_color = f"#{config_center.read_conf('Color', 'prepare_class')}"

    theme = config_center.read_conf('General', 'theme')
    theme_config = conf.load_theme_config(theme).config
    height = theme_config.height
    radius = theme_config.radius

    screen_geometry = QApplication.primaryScreen().geometry()
    screen_width = screen_geometry.width()
    spacing = theme_config.spacing
    try:
        dpr = QApplication.primaryScreen().devicePixelRatio()
    except AttributeError:
        dpr = 1.0
    dpr = max(1.0, dpr)

    widgets_width = 0
    for widget in widgets:  # 计算总宽度(兼容插件)
        widgets_width += theme_config.widget_width.get(widget, list_.widget_width.get(widget, 0))

    total_width = widgets_width + spacing * (len(widgets) - 1)

    start_x = int((screen_width - total_width) / 2)
    margin_base = int(config_center.read_conf('General', 'margin'))
    start_y = int(margin_base * dpr)

    if state != 4:
        window = tip_toast((start_x, start_y), total_width, state, lesson_name, duration=duration)
    else:
        window = tip_toast(
            (start_x, start_y),
            total_width,
            state,
            '',
            title,
            subtitle,
            content,
            icon,
            duration=duration,
        )

    window.show()
    window_list.append(window)

    if config_center.read_conf('Toast', 'wave') == '1':
        wave = wave_Effect(state)
        wave.show()
        window_list.append(wave)


def detect_enable_toast(state: int = 0) -> bool:
    if config_center.read_conf('Toast', 'attend_class') != '1' and state == 1:
        return True
    if (config_center.read_conf('Toast', 'finish_class') != '1') and (state in [0, 2]):
        return True
    return bool(config_center.read_conf('Toast', 'prepare_class') != '1' and state == 3)


def push_notification(
    state: int = 1,
    lesson_name: str = '',
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    content: Optional[str] = None,
    icon: Optional[str] = None,
    duration: int = 2000,
) -> Dict[str, Any]:  # 推送通知
    global pushed_notification, notification_contents
    pushed_notification = True
    notification_contents = {
        "state": state,
        "lesson_name": lesson_name,
        "title": title,
        "subtitle": subtitle,
        "content": content,
    }
    main(state, lesson_name, title, subtitle, content, icon, duration)
    return notification_contents


if __name__ == '__main__':
    from i18n_manager import app

    main(
        state=4,  # 自定义通知
        title='天气预报',
        subtitle='',
        content='1°~-3° | 3°~-3° | 9°~1°',
        icon='img/favicon.ico',
        duration=2000,
    )
    sys.exit(app.exec())
