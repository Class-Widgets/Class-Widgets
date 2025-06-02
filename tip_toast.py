import sys

import os
from collections import defaultdict
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
from play_audio import PlayAudio, play_audio
from generate_speech import generate_speech_sync, get_voice_id_by_name
import platform

# 适配高DPI缩放
if platform.system() == 'Windows' and platform.release() not in ['7', 'XP', 'Vista']:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
else:
    logger.warning('不兼容的系统,跳过高DPI标识')

prepare_class = config_center.read_conf('Audio', 'prepare_class')
attend_class = config_center.read_conf('Audio', 'attend_class')
finish_class = config_center.read_conf('Audio', 'finish_class')

pushed_notification = False
notification_contents = {"state": None, "lesson_name": None, "title": None, "subtitle": None, "content": None}

# 波纹效果
normal_color = '#56CFD8'

window_list = []  # 窗口列表
active_windows = []
tts_is_playing = False  # TTS播放状态标志


class TTSAudioThread(QThread):
    """TTS线程"""
    def __init__(self, text, voice_id):
        super().__init__()
        self.text = text
        self.voice_id = voice_id

    def run(self):
        self.setPriority(QThread.Priority.LowPriority) # TTS优先级可以低一些
        global tts_is_playing
        if tts_is_playing:
            logger.warning("TTS 已经播放")
            return

        engine_type = self.voice_id.split(':')[0] if self.voice_id else None
        if engine_type == "pyttsx3" and platform.system() != "Windows":
            logger.warning("当前系统不是Windows,pyttsx3跳过TTS生成")
            return

        try:
            tts_is_playing = True
            audio_path = generate_speech_sync(self.text, voice=self.voice_id, auto_fallback=True)
            if audio_path and os.path.exists(audio_path):
                logger.info(f"TTS生成成功")
                play_audio(audio_path, tts_delete_after=True)
            else:
                logger.error("TTS生成失败或文件未找到")
        except Exception as e:
            logger.error(f"TTS处理失败: {e}")
        finally:
            tts_is_playing = False


class tip_toast(QWidget):
    def __init__(self, pos, width, state=1, lesson_name=None, title=None, subtitle=None, content=None, icon=None, duration=2000):
        super().__init__()
        for w in active_windows[:]:
            w.close()
        active_windows.append(self)
        self.audio_thread = None
        if hasattr(tip_toast, 'active_tts_thread') and tip_toast.active_tts_thread and tip_toast.active_tts_thread.isRunning():
            logger.debug("已有TTS线程正在运行")
            self.tts_audio_thread = None
        else:
            self.tts_audio_thread = None 
            tip_toast.active_tts_thread = None

        uic.loadUi(f"{base_directory}/view/widget-toast-bar.ui", self)

        try:
            dpr = self.screen().devicePixelRatio() if self.screen() else QApplication.primaryScreen().devicePixelRatio()
        except AttributeError:
            dpr = QApplication.primaryScreen().devicePixelRatio()
        dpr = max(1.0, dpr)

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

        sound_to_play = None
        tts_text = None # TTS文本
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
            pixmap = pixmap.scaled(icon_size, icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pixmap)
            icon_label.setFixedSize(icon_size, icon_size)

        prepare_minutes = config_center.read_conf('Toast', 'prepare_minutes')
        format_values = defaultdict(str, {
            'lesson_name': '',
            'minutes': '',
            'title': '',
            'content': ''
        })

        if state == 1:
            logger.info('上课铃声显示')
            title_label.setText('活动开始')  # 修正文本，以适应不同场景
            subtitle_label.setText('当前课程')
            lesson.setText(lesson_name)  # 课程名
            sound_to_play = attend_class
            format_values['lesson_name'] = lesson_name
            tts_text = config_center.read_conf('TTS', 'attend_class').format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}")  # 主题色
        elif state == 0:
            logger.info('下课铃声显示')
            title_label.setText('下课')
            if lesson_name:
                subtitle_label.setText('即将进行')
            else:
                subtitle_label.hide()
            lesson.setText(lesson_name)  # 课程名
            sound_to_play = finish_class
            format_values['lesson_name'] = lesson_name
            tts_text = config_center.read_conf('TTS', 'finish_class').format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")
        elif state == 2:
            logger.info('放学铃声显示')
            title_label.setText('放学')
            subtitle_label.setText('当前课程已结束')
            lesson.setText('')  # 课程名
            sound_to_play = finish_class
            tts_text = config_center.read_conf('TTS', 'after_school').format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")
        elif state == 3:
            logger.info('预备铃声显示')
            title_label.setText('即将开始')  # 同上
            subtitle_label.setText('下一节')
            lesson.setText(lesson_name)
            sound_to_play = prepare_class
            format_values['lesson_name'] = lesson_name
            format_values['minutes'] = prepare_minutes
            tts_text = config_center.read_conf('TTS', 'prepare_class').format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'prepare_class')}")
        elif state == 4:
            logger.info(f'通知显示: {title}')
            title_label.setText(title)
            subtitle_label.setText(subtitle)
            lesson.setText(content)
            sound_to_play = prepare_class
            format_values['title'] = title
            format_values['content'] = content
            tts_text = config_center.read_conf('TTS', 'otherwise').format_map(format_values)

        global tts_is_playing
        if tts_enabled and tts_text and tts_voice_id:
            logger.info(f"生成TTS: '{tts_text}',语音ID: {tts_voice_id}")
            if tts_is_playing:
                 logger.warning("TTS已经在播放")
            else:
                self.tts_audio_thread = TTSAudioThread(tts_text, tts_voice_id)
                self.tts_audio_thread.start()
        elif tts_enabled and tts_text and not tts_voice_id:
             logger.warning(f"TTS已启用,但未能根据 '{tts_voice_id}' 找到有效的语音ID")
        elif tts_enabled and not tts_text:
             logger.warning("TTS已启用,但当前没有文本供生成")

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

        mini_size_x = 150 / dpr
        mini_size_y = 50 / dpr

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(duration)
        self.timer.timeout.connect(self.close_window)

        # 放大效果
        self.geometry_animation = QPropertyAnimation(self, b"geometry")
        self.geometry_animation.setDuration(750)  # 动画持续时间
        start_rect = QRect(int(start_x + mini_size_x / 2), int(start_y + mini_size_y / 2),
                         int(total_width - mini_size_x), int(height - mini_size_y))
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

        # 检查并播放TTS
        if config_center.read_conf('TTS', 'enable') == '1' and tts_text:
            voice_id = config_center.read_conf('TTS', 'voice_id')
            if voice_id is None:
                voice_id = ''
            if self.tts_audio_thread and self.tts_audio_thread.isRunning():
                try:
                    self.tts_audio_thread.quit()
                    self.tts_audio_thread.wait(1000) # 等待最多1秒
                except Exception as e:
                    logger.warning(f"停止旧TTS线程时出错: {e}")
            self.tts_audio_thread = TTSAudioThread(tts_text, voice_id)
            # 稍微延迟启动TTS，避免和提示音重叠太近
            QTimer.singleShot(500, self.tts_audio_thread.start)

        self.geometry_animation.start()
        self.opacity_animation.start()
        self.blur_animation.start()

    def close_window(self):
        try:
            dpr = self.screen().devicePixelRatio() if self.screen() else QApplication.primaryScreen().devicePixelRatio()
        except AttributeError:
            dpr = QApplication.primaryScreen().devicePixelRatio()
        dpr = max(1.0, dpr)
        mini_size_x = 120 / dpr
        mini_size_y = 20 / dpr

        # 放大效果
        self.geometry_animation_close = QPropertyAnimation(self, b"geometry")
        self.geometry_animation_close.setDuration(500)  # 动画持续时间
        self.geometry_animation_close.setStartValue(QRect(start_x, start_y, total_width, height))
        end_rect = QRect(int(start_x + mini_size_x / 2), int(start_y + mini_size_y / 2),
                       int(total_width - mini_size_x), int(height - mini_size_y))
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

    def closeEvent(self, event):
        if self.audio_thread and self.audio_thread.isRunning():
            try:
                self.audio_thread.quit()
                self.audio_thread.wait(500)
            except Exception as e:
                 logger.warning(f"关闭窗口时停止提示音线程出错: {e}")
        if self.tts_audio_thread and self.tts_audio_thread.isRunning():
            try:
                self.tts_audio_thread.quit()
                self.tts_audio_thread.wait(1000)
            except Exception as e:
                 logger.warning(f"关闭窗口时停止TTS线程出错: {e}")

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
            if self.audio_thread and self.audio_thread.isRunning():
                self.audio_thread.quit()
                self.audio_thread.wait()
            self.audio_thread = PlayAudio(str(file_path))
            self.audio_thread.start()
            self.audio_thread.setPriority(QThread.Priority.HighestPriority)  # 设置优先级
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
        self.duration = 1200

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
        try:
            dpr = self.screen().devicePixelRatio() if self.screen() else QApplication.primaryScreen().devicePixelRatio()
        except AttributeError:
            dpr = QApplication.primaryScreen().devicePixelRatio()
        dpr = max(1.0, dpr)
        fixed_end_radius = 1000 * dpr # 动画效果值
        self.animation.setEndValue(fixed_end_radius)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.animation.start()

        self.fade_animation = QPropertyAnimation(self, b'windowOpacity')
        self.fade_animation.setDuration(self.duration - 150)

        self.fade_animation.setKeyValues([  # 关键帧
            (0, 0),
            (0.06, 0.9),
            (1, 0)
        ])

        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
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
    try:
        dpr = QApplication.primaryScreen().devicePixelRatio()
    except AttributeError:
        dpr = 1.0
    dpr = max(1.0, dpr)
 
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
    margin_base = int(config_center.read_conf('General', 'margin'))
    start_y = int(margin_base * dpr)
 
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
                      content=None, icon=None, duration=2000):  # 推送通知
    global pushed_notification, notification_contents
    pushed_notification = True
    notification_contents = {
        "state": state,
        "lesson_name": lesson_name,
        "title": title,
        "subtitle": subtitle,
        "content": content
    }
    main(state, lesson_name, title, subtitle, content, icon, duration)
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
