import os
import time
import pathlib
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any, Union # Added for type hints

from PyQt5 import uic
from PyQt5.QtCore import Qt, QPropertyAnimation, QRect, QEasingCurve, QTimer, QPoint, pyqtProperty, QThread, QObject, pyqtSignal # Added QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QBrush, QPixmap, QPaintEvent, QCloseEvent # Added QPaintEvent, QCloseEvent
from PyQt5.QtWidgets import QWidget, QApplication, QLabel, QFrame, QGraphicsBlurEffect
from loguru import logger
from qfluentwidgets import setThemeColor, InfoBarPosition, FluentIcon # For InfoBarPosition and FluentIcon if needed by tip_toast directly

import conf
from conf import base_directory # base_directory is Path
import list_ # list_ has various list/dict attributes
from file import config_center # config_center is ConfigCenter instance
from play_audio import PlayAudio, play_audio # PlayAudio is QThread, play_audio is function
from generate_speech import TTSEngine, on_audio_played, generate_speech_sync # TTSEngine is class, on_audio_played is function
import platform

# 适配高DPI缩放
if platform.system() == 'Windows' and platform.release() not in ['7', 'XP', 'Vista']:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough) # type: ignore[attr-defined]
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling) # type: ignore[attr-defined]
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps) # type: ignore[attr-defined]
else:
    logger.warning('不兼容的系统,跳过高DPI标识')

prepare_class: Optional[str] = config_center.read_conf('Audio', 'prepare_class') # type: ignore[no-untyped-call]
attend_class: Optional[str] = config_center.read_conf('Audio', 'attend_class') # type: ignore[no-untyped-call]
finish_class: Optional[str] = config_center.read_conf('Audio', 'finish_class') # type: ignore[no-untyped-call]

pushed_notification: bool = False
notification_contents: Dict[str, Optional[str]] = {"state": None, "lesson_name": None, "title": None, "subtitle": None, "content": None}

# 波纹效果
normal_color: str = '#56CFD8'

window_list: List[QWidget] = []  # 窗口列表
active_windows: List[QWidget] = [] # List of active tip_toast or wave_Effect windows
tts_is_playing: bool = False  # TTS播放状态标志


class TTSAudioThread(QThread):
    """TTS线程"""
    def __init__(self, text: str, voice_id: Optional[str], parent: Optional[QObject] = None) -> None: # Added parent and types
        super().__init__(parent)
        self.text: str = text
        self.voice_id: Optional[str] = voice_id

    def run(self) -> None: # Added return type
        self.setPriority(QThread.Priority.LowPriority)
        global tts_is_playing
        if tts_is_playing:
            logger.warning("TTS 已经播放")
            return

        engine_type: Optional[str] = self.voice_id.split(':')[0] if self.voice_id else None
        if engine_type == "pyttsx3" and platform.system() != "Windows":
            logger.warning("当前系统不是Windows,pyttsx3跳过TTS生成")
            return

        try:
            tts_is_playing = True
            # generate_speech_sync returns str (filepath)
            audio_path: Optional[str] = generate_speech_sync(self.text, voice=self.voice_id, auto_fallback=True) # type: ignore[no-untyped-call]
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
    # active_tts_thread: Optional[TTSAudioThread] = None # Class attribute to hold the single TTS thread

    # Define instance variables used across methods
    audio_thread: Optional[PlayAudio]
    tts_audio_thread: Optional[TTSAudioThread]
    blur_effect: QGraphicsBlurEffect
    timer: QTimer
    geometry_animation: QPropertyAnimation
    opacity_animation: QPropertyAnimation
    blur_animation: Optional[QPropertyAnimation] # Can be None if wave effect is off
    geometry_animation_close: QPropertyAnimation
    opacity_animation_close: QPropertyAnimation
    blur_animation_close: Optional[QPropertyAnimation]


    def __init__(self,
                 pos: Tuple[int, int],
                 width: int,
                 state: int = 1,
                 lesson_name: Optional[str] = None,
                 title: Optional[str] = None,
                 subtitle: Optional[str] = None,
                 content: Optional[str] = None,
                 icon: Optional[Union[str, QPixmap]] = None,
                 duration: int = 2000
                 ) -> None: # Added types
        super().__init__()

        # Close existing active windows
        # Create a copy for iteration as closing modifies active_windows
        for w in list(active_windows): # Use list copy for safe iteration
            w.close() # This should trigger their closeEvent and remove from active_windows
        active_windows.append(self)

        self.audio_thread = None # For notification sound

        # TTS Thread Management
        # Using a class attribute on tip_toast to manage a single TTS thread instance
        if hasattr(tip_toast, 'active_tts_thread') and \
           isinstance(tip_toast.active_tts_thread, QThread) and \
           tip_toast.active_tts_thread.isRunning():
            logger.debug("已有TTS线程正在运行,新的TTS请求将不被处理或排队(当前未实现排队)")
            self.tts_audio_thread = None # Don't create a new one if one is active
        else:
            self.tts_audio_thread = None
            setattr(tip_toast, 'active_tts_thread', None) # Reset class attribute if no thread is active

        uic.loadUi(f'{base_directory}/view/widget-toast-bar.ui', self) # type: ignore[attr-defined]

        try:
            current_screen = self.screen()
            dpr: float = current_screen.devicePixelRatio() if current_screen else QApplication.primaryScreen().devicePixelRatio() # type: ignore[union-attr]
        except AttributeError: # Fallback if screen() is not available early
            dpr = QApplication.primaryScreen().devicePixelRatio() # type: ignore[union-attr]
        dpr = max(1.0, dpr)

        # Window position and flags
        pin_on_top_conf: Optional[str] = config_center.read_conf('Toast', 'pin_on_top') # type: ignore[no-untyped-call]
        window_flags: Qt.WindowFlags = Qt.WindowType.FramelessWindowHint | Qt.X11BypassWindowManagerHint # type: ignore[attr-defined]
        if pin_on_top_conf == '1':
            window_flags |= Qt.WindowType.WindowStaysOnTopHint # type: ignore[attr-defined]
        else:
            window_flags |= Qt.WindowType.WindowStaysOnBottomHint # type: ignore[attr-defined]
        self.setWindowFlags(window_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # type: ignore[attr-defined]

        # UI elements
        title_label_widget: Optional[QLabel] = self.findChild(QLabel, 'title')
        backgnd_widget: Optional[QFrame] = self.findChild(QFrame, 'backgnd')
        lesson_label_widget: Optional[QLabel] = self.findChild(QLabel, 'lesson')
        subtitle_label_widget: Optional[QLabel] = self.findChild(QLabel, 'subtitle')
        icon_label_widget: Optional[QLabel] = self.findChild(QLabel, 'icon')

        sound_to_play: Optional[str] = None
        tts_text: Optional[str] = None
        tts_enabled_conf: Optional[str] = config_center.read_conf('TTS', 'enable') # type: ignore[no-untyped-call]
        tts_enabled: bool = tts_enabled_conf == '1'
        tts_voice_id_conf: Optional[str] = config_center.read_conf('TTS', 'voice_id') # type: ignore[no-untyped-call]
        tts_voice_id: str = tts_voice_id_conf if tts_voice_id_conf else ""


        if icon_label_widget and icon:
            pixmap: QPixmap
            if isinstance(icon, str): pixmap = QPixmap(icon)
            elif isinstance(icon, QPixmap): pixmap = icon
            else: pixmap = QPixmap() # Default empty

            icon_size = int(48 * dpr)
            pixmap = pixmap.scaled(icon_size, icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) # type: ignore[attr-defined]
            icon_label_widget.setPixmap(pixmap)
            icon_label_widget.setFixedSize(icon_size, icon_size)

        prepare_minutes_conf: Optional[str] = config_center.read_conf('Toast', 'prepare_minutes') # type: ignore[no-untyped-call]
        prepare_minutes_str: str = prepare_minutes_conf if prepare_minutes_conf else "0"

        format_values = defaultdict(str, {
            'lesson_name': lesson_name or "",
            'minutes': prepare_minutes_str,
            'title': title or "",
            'content': content or ""
        })

        # Logic based on state
        bg_color_tuple: Tuple[str, str, str]
        # Default color
        default_bg_color_tuple: Tuple[str, str, str] = ('rgba(110, 190, 210, 255)', 'rgba(110, 190, 210, 255)', 'rgba(90, 210, 215, 255)')


        if state == 1: # 上课
            logger.info('上课铃声显示')
            if title_label_widget: title_label_widget.setText('活动开始')
            if subtitle_label_widget: subtitle_label_widget.setText('当前课程')
            if lesson_label_widget: lesson_label_widget.setText(lesson_name or "")
            sound_to_play = attend_class
            tts_template: Optional[str] = config_center.read_conf('TTS', 'attend_class') # type: ignore[no-untyped-call]
            if tts_template: tts_text = tts_template.format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}") # type: ignore[no-untyped-call]
            bg_color_tuple = generate_gradient_color(f"#{config_center.read_conf('Color', 'attend_class')}") # type: ignore[no-untyped-call]
        elif state == 0: # 下课
            logger.info('下课铃声显示')
            if title_label_widget: title_label_widget.setText('下课')
            if subtitle_label_widget:
                subtitle_label_widget.setText('即将进行' if lesson_name else '')
                if not lesson_name: subtitle_label_widget.hide()
            if lesson_label_widget: lesson_label_widget.setText(lesson_name or "")
            sound_to_play = finish_class
            tts_template = config_center.read_conf('TTS', 'finish_class') # type: ignore[no-untyped-call]
            if tts_template: tts_text = tts_template.format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}") # type: ignore[no-untyped-call]
            bg_color_tuple = generate_gradient_color(f"#{config_center.read_conf('Color', 'finish_class')}") # type: ignore[no-untyped-call]
        elif state == 2: # 放学
            logger.info('放学铃声显示')
            if title_label_widget: title_label_widget.setText('放学')
            if subtitle_label_widget: subtitle_label_widget.setText('当前课程已结束')
            if lesson_label_widget: lesson_label_widget.setText('')
            sound_to_play = finish_class
            tts_template = config_center.read_conf('TTS', 'after_school') # type: ignore[no-untyped-call]
            if tts_template: tts_text = tts_template.format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}") # type: ignore[no-untyped-call]
            bg_color_tuple = generate_gradient_color(f"#{config_center.read_conf('Color', 'finish_class')}") # type: ignore[no-untyped-call]
        elif state == 3: # 预备
            logger.info('预备铃声显示')
            if title_label_widget: title_label_widget.setText('即将开始')
            if subtitle_label_widget: subtitle_label_widget.setText('下一节')
            if lesson_label_widget: lesson_label_widget.setText(lesson_name or "")
            sound_to_play = prepare_class
            tts_template = config_center.read_conf('TTS', 'prepare_class') # type: ignore[no-untyped-call]
            if tts_template: tts_text = tts_template.format_map(format_values)
            setThemeColor(f"#{config_center.read_conf('Color', 'prepare_class')}") # type: ignore[no-untyped-call]
            bg_color_tuple = generate_gradient_color(f"#{config_center.read_conf('Color', 'prepare_class')}") # type: ignore[no-untyped-call]
        elif state == 4: # 其他通知
            logger.info(f'通知显示: {title}')
            if title_label_widget: title_label_widget.setText(title or "通知")
            if subtitle_label_widget: subtitle_label_widget.setText(subtitle or "")
            if lesson_label_widget: lesson_label_widget.setText(content or "")
            sound_to_play = prepare_class # Default sound for other notifications
            tts_template = config_center.read_conf('TTS', 'otherwise') # type: ignore[no-untyped-call]
            if tts_template: tts_text = tts_template.format_map(format_values)
            bg_color_tuple = default_bg_color_tuple
        else: # Default case
            bg_color_tuple = default_bg_color_tuple

        if backgnd_widget:
            radius_conf: Optional[str] = conf.load_theme_config(get_theme_name()).get('radius') # type: ignore[no-untyped-call]
            radius_val: int = int(radius_conf) if radius_conf and radius_conf.isdigit() else 8 # Default radius
            backgnd_widget.setStyleSheet(f'font-weight: bold; border-radius: {radius_val}px; '
                                  'background-color: qlineargradient('
                                  'spread:pad, x1:0, y1:0, x2:1, y2:1,'
                                  f' stop:0 {bg_color_tuple[1]}, stop:0.5 {bg_color_tuple[0]}, stop:1 {bg_color_tuple[2]}'
                                  ');')

        self.blur_effect = QGraphicsBlurEffect(self)
        wave_conf: Optional[str] = config_center.read_conf('Toast', 'wave') # type: ignore[no-untyped-call]
        if wave_conf == '1' and backgnd_widget:
            backgnd_widget.setGraphicsEffect(self.blur_effect)

        # Calculate geometry for animations
        # These globals (start_x, start_y, total_width, height) are set in main() function of tip_toast.
        # This class might be instantiated outside of that main(), so they might not be set.
        # It's safer to get these from parent or screen geometry if possible.
        # For now, assuming they are available if this class is used as intended by the main() func.
        # Default values if globals are not found (should not happen in normal flow)
        current_start_x = getattr(sys.modules[__name__], 'start_x', pos[0])
        current_start_y = getattr(sys.modules[__name__], 'start_y', pos[1])
        current_total_width = getattr(sys.modules[__name__], 'total_width', width)
        current_height = getattr(sys.modules[__name__], 'height', self.height())


        mini_size_x: float = 150 / dpr
        mini_size_y: float = 50 / dpr

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(duration)
        self.timer.timeout.connect(self.close_window)

        self.geometry_animation = QPropertyAnimation(self, b"geometry") # type: ignore[misc]
        self.geometry_animation.setDuration(750)

        start_rect = QRect(int(current_start_x + mini_size_x / 2), int(current_start_y + mini_size_y / 2),
                           int(current_total_width - mini_size_x), int(current_height - mini_size_y))
        self.geometry_animation.setStartValue(start_rect)
        self.geometry_animation.setEndValue(QRect(current_start_x, current_start_y, current_total_width, current_height))
        self.geometry_animation.setEasingCurve(QEasingCurve.Type.OutCirc) # type: ignore[attr-defined]
        self.geometry_animation.finished.connect(self.timer.start)

        self.blur_animation = QPropertyAnimation(self.blur_effect, b"blurRadius") # type: ignore[misc]
        self.blur_animation.setDuration(550)
        self.blur_animation.setStartValue(25)
        self.blur_animation.setEndValue(0)

        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity") # type: ignore[misc]
        self.opacity_animation.setDuration(450)
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.opacity_animation.setEasingCurve(QEasingCurve.Type.InOutQuad) # type: ignore[attr-defined]

        if sound_to_play:
            self.playsound(sound_to_play)

        if tts_enabled and tts_text:
            logger.info(f"生成TTS: '{tts_text}',语音ID: {tts_voice_id}")
            if hasattr(tip_toast, 'active_tts_thread') and \
               isinstance(tip_toast.active_tts_thread, QThread) and \
               tip_toast.active_tts_thread.isRunning(): # type: ignore[attr-defined] # Check if class attr exists and is running
                 logger.warning("TTS已经在播放 (from tip_toast init)")
            else:
                self.tts_audio_thread = TTSAudioThread(tts_text, tts_voice_id, self) # Parent to self
                setattr(tip_toast, 'active_tts_thread', self.tts_audio_thread) # Store as class attribute
                QTimer.singleShot(500, self.tts_audio_thread.start) # Slight delay
        elif tts_enabled and tts_text and not tts_voice_id:
             logger.warning(f"TTS已启用,但未能根据 '{tts_voice_id}' 找到有效的语音ID")
        elif tts_enabled and not tts_text:
             logger.warning("TTS已启用,但当前没有文本供生成")

        self.geometry_animation.start()
        self.opacity_animation.start()
        if wave_conf == '1': # Only start blur animation if wave effect is on
             self.blur_animation.start()

    def close_window(self) -> None: # Added return type
        try:
            current_screen_close = self.screen()
            dpr_close: float = current_screen_close.devicePixelRatio() if current_screen_close else QApplication.primaryScreen().devicePixelRatio() # type: ignore[union-attr]
        except AttributeError:
            dpr_close = QApplication.primaryScreen().devicePixelRatio() # type: ignore[union-attr]
        dpr_close = max(1.0, dpr_close)

        mini_size_x_close: float = 120 / dpr_close
        mini_size_y_close: float = 20 / dpr_close

        # Assuming globals are set from main() call context
        current_start_x_close = getattr(sys.modules[__name__], 'start_x', self.x())
        current_start_y_close = getattr(sys.modules[__name__], 'start_y', self.y())
        current_total_width_close = getattr(sys.modules[__name__], 'total_width', self.width())
        current_height_close = getattr(sys.modules[__name__], 'height', self.height())


        self.geometry_animation_close = QPropertyAnimation(self, b"geometry") # type: ignore[misc]
        self.geometry_animation_close.setDuration(500)
        self.geometry_animation_close.setStartValue(QRect(current_start_x_close, current_start_y_close, current_total_width_close, current_height_close))
        end_rect = QRect(int(current_start_x_close + mini_size_x_close / 2),
                         int(current_start_y_close + mini_size_y_close / 2),
                         int(current_total_width_close - mini_size_x_close),
                         int(current_height_close - mini_size_y_close))
        self.geometry_animation_close.setEndValue(end_rect)
        self.geometry_animation_close.setEasingCurve(QEasingCurve.Type.InOutQuad) # type: ignore[attr-defined]

        self.blur_animation_close = QPropertyAnimation(self.blur_effect, b"blurRadius") # type: ignore[misc]
        self.blur_animation_close.setDuration(500)
        self.blur_animation_close.setStartValue(0)
        self.blur_animation_close.setEndValue(30)

        self.opacity_animation_close = QPropertyAnimation(self, b"windowOpacity") # type: ignore[misc]
        self.opacity_animation_close.setDuration(500)
        self.opacity_animation_close.setStartValue(self.windowOpacity()) # Use current opacity
        self.opacity_animation_close.setEndValue(0.0)

        self.geometry_animation_close.start()
        self.opacity_animation_close.start()
        wave_conf_close: Optional[str] = config_center.read_conf('Toast', 'wave') # type: ignore[no-untyped-call]
        if wave_conf_close == '1':
            self.blur_animation_close.start()
        self.opacity_animation_close.finished.connect(self.close) # QWidget.close

    def closeEvent(self, event: QCloseEvent) -> None: # Added QCloseEvent and return type
        if self.audio_thread and self.audio_thread.isRunning():
            try:
                self.audio_thread.quit()
                self.audio_thread.wait(500) # milliseconds
            except Exception as e:
                 logger.warning(f"关闭窗口时停止提示音线程出错: {e}")

        if self.tts_audio_thread and self.tts_audio_thread.isRunning():
            try:
                self.tts_audio_thread.requestInterruption() # Request interruption
                self.tts_audio_thread.quit()
                if not self.tts_audio_thread.wait(1000): # Wait up to 1 sec
                    logger.warning("TTS线程未能及时停止，可能仍在后台运行。")
            except Exception as e:
                 logger.warning(f"关闭窗口时停止TTS线程出错: {e}")

        # Reset class attribute if this was the active TTS thread
        if hasattr(tip_toast, 'active_tts_thread') and tip_toast.active_tts_thread == self.tts_audio_thread: # type: ignore[attr-defined]
            setattr(tip_toast, 'active_tts_thread', None)


        if self in active_windows:
            active_windows.remove(self)

        # global window_list # window_list is not modified in original code here
        # if self in window_list: window_list.remove(self) # If it were to be modified

        self.hide() # Hide first
        self.deleteLater() # Schedule for deletion
        event.accept() # Accept the event if overridden from QWidget

    def playsound(self, filename: str) -> None: # Added types
        try:
            # base_directory is Path
            file_path_abs: str = str(Path(base_directory) / 'audio' / filename) # type: ignore[attr-defined]
            if self.audio_thread and self.audio_thread.isRunning():
                self.audio_thread.quit()
                self.audio_thread.wait() # Wait for thread to finish
            self.audio_thread = PlayAudio(file_path_abs, parent=self) # Parent thread to self
            self.audio_thread.start()
            self.audio_thread.setPriority(QThread.Priority.HighestPriority)
        except Exception as e:
            logger.error(f'播放音频文件失败：{e}')


class wave_Effect(QWidget):
    _radius: float # For pyqtProperty
    animation: Optional[QPropertyAnimation]
    fade_animation: Optional[QPropertyAnimation]
    timer: QTimer # For delayed start of animation

    def __init__(self, state: int = 1, parent: Optional[QWidget] = None) -> None: # Added parent and types
        super().__init__(parent)

        pin_on_top_conf_wave: Optional[str] = config_center.read_conf('Toast', 'pin_on_top') # type: ignore[no-untyped-call]
        wave_window_flags: Qt.WindowFlags = Qt.WindowType.FramelessWindowHint | Qt.X11BypassWindowManagerHint # type: ignore[attr-defined]
        if pin_on_top_conf_wave == '1':
            wave_window_flags |= Qt.WindowType.WindowStaysOnTopHint # type: ignore[attr-defined]
        else:
            wave_window_flags |= Qt.WindowType.WindowStaysOnBottomHint # type: ignore[attr-defined]
        self.setWindowFlags(wave_window_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # type: ignore[attr-defined]

        self._radius = 0.0 # Initialize before property access
        self.duration: int = 1200
        self.animation = None
        self.fade_animation = None

        # Determine color based on state
        # These globals (attend_class_color, etc.) are set in main() of tip_toast
        # Need to ensure they are accessible or passed if this class is used elsewhere.
        # For now, assume they are available in the module scope.
        color_hex: str
        if state == 1:
            color_hex = getattr(sys.modules[__name__], 'attend_class_color', normal_color)
        elif state == 0 or state == 2:
            color_hex = getattr(sys.modules[__name__], 'finish_class_color', normal_color)
        elif state == 3:
            color_hex = getattr(sys.modules[__name__], 'prepare_class_color', normal_color)
        else: # state == 4 or other
            color_hex = normal_color
        self.color: QColor = QColor(color_hex)

        screen_geom = QApplication.primaryScreen()
        if screen_geom:
             self.setGeometry(screen_geom.geometry()) # type: ignore[union-attr]
        else: # Fallback
             self.setGeometry(0,0,1920,1080)


        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(275) # milliseconds
        self.timer.timeout.connect(self.showAnimation)
        self.timer.start()

    @pyqtProperty(float) # Changed to float for smoother animation if radius can be float
    def radius(self) -> float:
        return self._radius

    @radius.setter
    def radius(self, value: float) -> None:
        self._radius = value
        self.update() # Trigger repaint

    def showAnimation(self) -> None: # Added return type
        self.animation = QPropertyAnimation(self, b'radius') # type: ignore[misc]
        self.animation.setDuration(self.duration)
        self.animation.setStartValue(50.0) # Start radius

        dpr_anim: float = 1.0
        try:
            current_screen_anim = self.screen()
            dpr_anim = current_screen_anim.devicePixelRatio() if current_screen_anim else QApplication.primaryScreen().devicePixelRatio() # type: ignore[union-attr]
        except AttributeError:
            dpr_anim = QApplication.primaryScreen().devicePixelRatio() # type: ignore[union-attr]
        dpr_anim = max(1.0, dpr_anim)

        fixed_end_radius: float = 1000.0 * dpr_anim
        self.animation.setEndValue(fixed_end_radius)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad) # type: ignore[attr-defined]
        self.animation.start()

        self.fade_animation = QPropertyAnimation(self, b"windowOpacity") # type: ignore[misc]
        self.fade_animation.setDuration(self.duration - 150)
        self.fade_animation.setKeyValueAt(0, 0.0)     # Start fully transparent
        self.fade_animation.setKeyValueAt(0.06, 0.9) # Fade in quickly
        self.fade_animation.setKeyValueAt(1, 0.0)     # Fade out at the end
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad) # type: ignore[attr-defined]
        self.fade_animation.finished.connect(self.close) # QWidget.close
        self.fade_animation.start()

    def paintEvent(self, event: QPaintEvent) -> None: # Added QPaintEvent and return type
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing) # type: ignore[attr-defined]
        painter.setBrush(QBrush(self.color))
        painter.setPen(Qt.PenStyle.NoPen) # type: ignore[attr-defined]

        center: QPoint = self.rect().center()
        # start_y_global is needed here, assume it's set by main() call context
        current_start_y_paint = getattr(sys.modules[__name__], 'start_y', self.rect().top() + 50) # Fallback
        loc = QPoint(center.x(), current_start_y_paint + 50) # Position ellipse relative to where toast appears
        painter.drawEllipse(loc, self._radius, self._radius)

    def closeEvent(self, event: QCloseEvent) -> None: # Added QCloseEvent and return type
        if self in active_windows: # active_windows is List[QWidget]
            active_windows.remove(self)
        # global window_list # window_list is not modified in original code here
        # if self in window_list: window_list.remove(self)
        self.hide()
        self.deleteLater()
        event.accept() # Accept the close event properly


def generate_gradient_color(theme_color_hex: str) -> Tuple[str, str, str]:  # 计算渐变色, Added types
    def adjust_color(color: QColor, factor: float) -> str: # Added types
        r = max(0, min(255, int(color.red() * (1 + factor))))
        g = max(0, min(255, int(color.green() * (1 + factor))))
        b = max(0, min(255, int(color.blue() * (1 + factor))))
        return f'rgba({r}, {g}, {b}, 255)'

    color = QColor(theme_color_hex) # Expecting hex string like "#RRGGBB"
    gradient: Tuple[str, str, str] = (adjust_color(color, 0), adjust_color(color, 0.24), adjust_color(color, -0.11))
    return gradient

# These globals are set before tip_toast instances are created by this main function
# They are used by tip_toast and wave_Effect instances for positioning and styling.
start_x: int = 0
start_y: int = 0
total_width: int = 0
height: int = 0 # This height is for the toast bar itself
radius: int = 0
attend_class_color: str = "#000000"
finish_class_color: str = "#000000"
prepare_class_color: str = "#000000"


def main(state: int = 1,
         lesson_name: str = '',
         title: str = '通知示例',
         subtitle: str = '副标题',
         content: str = '这是一条测试通知示例',
         icon: Optional[Union[str, QPixmap]] = None,
         duration: int = 2000
         ) -> None:  # 0:下课铃声 1:上课铃声 2:放学铃声 3:预备铃 4:其他. Added types

    if detect_enable_toast(state): # detect_enable_toast returns bool
        return

    global start_x, start_y, total_width, height, radius, attend_class_color, finish_class_color, prepare_class_color

    # list_.get_widget_config returns List[str]
    widgets_paths: List[str] = list_.get_widget_config() # type: ignore[no-untyped-call]
    # Filter out non-existent widgets (though this might be redundant if list_ is managed well)
    # widgets = [w for w in widgets_paths if w in list_.widget_name] # type: ignore[attr-defined]

    attend_class_color_conf: Optional[str] = config_center.read_conf('Color', 'attend_class') # type: ignore[no-untyped-call]
    attend_class_color = f"#{attend_class_color_conf}" if attend_class_color_conf else "#0078D4" # Default color

    finish_class_color_conf: Optional[str] = config_center.read_conf('Color', 'finish_class') # type: ignore[no-untyped-call]
    finish_class_color = f"#{finish_class_color_conf}" if finish_class_color_conf else "#56CFD8"

    prepare_class_color_conf: Optional[str] = config_center.read_conf('Color', 'prepare_class') # type: ignore[no-untyped-call]
    prepare_class_color = f"#{prepare_class_color_conf}" if prepare_class_color_conf else "#FFB900"


    theme_name: str = config_center.read_conf('General', 'theme') or "default" # type: ignore[no-untyped-call]
    theme_config_data: Dict[str, Any] = conf.load_theme_config(theme_name) # type: ignore[no-untyped-call]

    height_conf: Any = theme_config_data.get('height')
    height = int(height_conf) if isinstance(height_conf, (str, int)) and str(height_conf).isdigit() else 100 # Default height

    radius_conf: Any = theme_config_data.get('radius')
    radius = int(radius_conf) if isinstance(radius_conf, (str, int)) and str(radius_conf).isdigit() else 8 # Default radius

    current_screen_main = QApplication.primaryScreen()
    screen_geometry: QRect = current_screen_main.geometry() if current_screen_main else QRect(0,0,1920,1080) # type: ignore[union-attr]
    screen_width: int = screen_geometry.width()

    spacing_conf: Any = theme_config_data.get('spacing')
    spacing: int = int(spacing_conf) if isinstance(spacing_conf, (str, int)) and str(spacing_conf).isdigit() else 5 # Default spacing

    dpr_main: float = 1.0
    try:
        if current_screen_main: dpr_main = current_screen_main.devicePixelRatio() # type: ignore[union-attr]
    except AttributeError: pass # Use default 1.0
    dpr_main = max(1.0, dpr_main)

    widgets_total_width_calc: int = 0
    # list_.widget_width is Dict[str, int]
    # conf.load_theme_width returns Dict[str, int]
    theme_widths: Dict[str, int] = conf.load_theme_width(theme_name) # type: ignore[no-untyped-call]

    widget_path: str
    for widget_path in widgets_paths:
        try:
            widgets_total_width_calc += theme_widths.get(widget_path, list_.widget_width.get(widget_path, 0)) # type: ignore[attr-defined]
        except KeyError: # Should not happen if list_.widget_width is comprehensive
            logger.warning(f"Width not found for widget {widget_path}")
        except Exception: # Catch any other errors during width calculation
            logger.error(f"Error calculating width for widget {widget_path}")

    total_width = widgets_total_width_calc + spacing * (len(widgets_paths) - 1) if widgets_paths else 0

    start_x = int((screen_width - total_width) / 2)
    margin_base_conf: Optional[str] = config_center.read_conf('General', 'margin') # type: ignore[no-untyped-call]
    margin_base_int: int = int(margin_base_conf) if margin_base_conf and margin_base_conf.isdigit() else 10 # Default margin
    start_y = int(margin_base_int * dpr_main)

    window: tip_toast # Declare type of window
    if state != 4: # Standard states
        window = tip_toast((start_x, start_y), total_width, state, lesson_name, duration=duration)
    else: # Custom notification (state 4)
        window = tip_toast(
            (start_x, start_y),
            total_width,
            state, # Should be 4
            lesson_name, # Usually empty for state 4 as per original logic
            title,
            subtitle,
            content,
            icon,
            duration=duration
        )

    window.show()
    window_list.append(window) # window_list is List[QWidget]

    wave_conf_main: Optional[str] = config_center.read_conf('Toast', 'wave') # type: ignore[no-untyped-call]
    if wave_conf_main == '1':
        wave = wave_Effect(state, parent=None) # wave_Effect is QWidget, parent can be None for top-level
        wave.show()
        window_list.append(wave)


def detect_enable_toast(state: int = 0) -> bool: # Added types
    if config_center.read_conf('Toast', 'attend_class') != '1' and state == 1: # type: ignore[no-untyped-call]
        return True
    if (config_center.read_conf('Toast', 'finish_class') != '1') and (state in [0, 2]): # type: ignore[no-untyped-call]
        return True
    if config_center.read_conf('Toast', 'prepare_class') != '1' and state == 3: # type: ignore[no-untyped-call]
        return True
    # else: # Original code implies this, but explicit is better
    return False


def push_notification(state: int = 1,
                      lesson_name: str = '',
                      title: Optional[str] = None,
                      subtitle: Optional[str] = None,
                      content: Optional[str] = None,
                      icon: Optional[Union[str, QPixmap]] = None,
                      duration: int = 2000
                      ) -> Dict[str, Optional[Union[int, str]]]:  # 推送通知. Added types
    global pushed_notification, notification_contents # pushed_notification: bool, notification_contents: Dict
    pushed_notification = True
    notification_contents = { # Ensure keys match expected structure
        "state": state, # Store int directly
        "lesson_name": lesson_name,
        "title": title,
        "subtitle": subtitle,
        "content": content
    }
    main(state, lesson_name, title or "通知示例", subtitle or "副标题", content or "这是一条测试通知ヾ(≧▽≦*)o", icon, duration)
    return notification_contents # type: ignore[return-value] # Ensure returned dict matches Optional[Union[int, str]] for values


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

[end of tip_toast.py]
