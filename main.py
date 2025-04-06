import ctypes
import datetime as dt
import json
import os
import platform
import re
import subprocess
import sys
import psutil
import signal
import traceback
from shutil import copy
from typing import Optional

from PyQt5 import uic
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QParallelAnimationGroup, QRect, QEasingCurve, QSize, QPoint, QUrl, QObject
from PyQt5.QtGui import QColor, QIcon, QPixmap, QPainter, QDesktopServices
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QProgressBar, QGraphicsBlurEffect, QPushButton, \
    QGraphicsDropShadowEffect, QSystemTrayIcon, QFrame, QGraphicsOpacityEffect, QHBoxLayout
from loguru import logger
from packaging.version import Version
from qfluentwidgets import Theme, setTheme, setThemeColor, SystemTrayMenu, Action, FluentIcon as fIcon, isDarkTheme, \
    Dialog, ProgressRing, PlainTextEdit, ImageLabel, PushButton, InfoBarIcon, Flyout, FlyoutAnimationType, CheckBox, \
    PrimaryPushButton, IconWidget

import conf
import list_
import tip_toast
import utils
import weather_db as db
from conf import base_directory
from extra_menu import ExtraMenu, open_settings
from generate_speech import generate_speech_sync, list_pyttsx3_voices
from menu import open_plaza
from network_thread import check_update, weatherReportThread
from play_audio import play_audio
from plugin import p_loader
from utils import restart, stop, share, update_timer
from file import config_center, schedule_center

if os.name == 'nt':
    import pygetwindow

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

today = dt.date.today()

# 存储窗口对象
windows = []
order = []
error_dialog = None

current_lesson_name = '课程表未加载'
current_state = 0  # 0：课间 1：上课 2: 休息段
current_time = dt.datetime.now().strftime('%H:%M:%S')
current_week = dt.datetime.now().weekday()
current_lessons = {}
loaded_data = {}
parts_type = []
notification = tip_toast
excluded_lessons = []
last_notify_time = None
notify_cooldown = 2  # 2秒内仅能触发一次通知(防止触发114514个通知导致爆炸

timeline_data = {}
next_lessons = []
parts_start_time = []

temperature = '未设置'
weather_icon = 0
weather_name = ''
weather_data_temp = None
city = 101010100  # 默认城市
theme = None

time_offset = 0  # 时差偏移
first_start = True
error_cooldown = dt.timedelta(seconds=2)  # 冷却时间(s)
ignore_errors = []
last_error_time = dt.datetime.now() - error_cooldown  # 上一次错误

ex_menu = None

if config_center.read_conf('Other', 'do_not_log') != '1':
    logger.add(f"{base_directory}/log/ClassWidgets_main_{{time}}.log", rotation="1 MB", encoding="utf-8",
               retention="1 minute")
    logger.info('未禁用日志输出')
else:
    logger.info('已禁用日志输出功能，若需保存日志，请在“设置”->“高级选项”中关闭禁用日志功能')


def global_exceptHook(exc_type, exc_value, exc_tb):  # 全局异常捕获
    if config_center.read_conf('Other', 'safe_mode') == '1':  # 安全模式
        return

    error_details = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))  # 异常详情
    if error_details in ignore_errors:  # 忽略重复错误
        return

    global last_error_time, error_dialog, error_cooldown

    current_time = dt.datetime.now()
    if current_time - last_error_time > error_cooldown:  # 冷却时间
        last_error_time = current_time
        logger.error(f"全局异常捕获：{exc_type} {exc_value} {exc_tb}")
        logger.error(f"详细堆栈信息：\n{error_details}")
        if not error_dialog:
            w = ErrorDialog(error_details)
            w.exec()
    else:
        # 忽略冷却时间
        pass


sys.excepthook = global_exceptHook  # 设置全局异常捕获


def setTheme_():  # 设置主题
    if config_center.read_conf('General', 'color_mode') == '2':  # 自动
        if platform.system() == 'Darwin' and Version(platform.mac_ver()[0]) < Version('10.14'):
            return
        if platform.system() == 'Windows':
            # 检查Windows版本是否支持深色模式（Windows 10 build 14393及以上）
            try:
                win_build = sys.getwindowsversion().build
                if win_build < 14393:  # 不支持深色模式的最低版本
                    return
            except AttributeError:
                # 无法获取版本信息，保守返回
                return
        if platform.system() == 'Linux':
            return
        setTheme(Theme.AUTO)
    elif config_center.read_conf('General', 'color_mode') == '1':
        setTheme(Theme.DARK)
    else:
        setTheme(Theme.LIGHT)


def get_timeline_data():
    if len(loaded_data['timeline']) == 1:
        return loaded_data['timeline']['default']
    else:
        if str(current_week) in loaded_data['timeline'] and loaded_data['timeline'][str(current_week)]:  # 如果此周有时间线
            return loaded_data['timeline'][str(current_week)]
        else:
            return loaded_data['timeline']['default']


# 获取Part开始时间
def get_start_time():
    global parts_start_time, timeline_data, loaded_data, order, parts_type
    loaded_data = schedule_center.schedule_data
    timeline = get_timeline_data()
    part = loaded_data['part']
    parts_start_time = []
    timeline_data = {}
    order = []

    for item_name, item_value in part.items():
        try:
            h, m = item_value[:2]
            try:
                part_type = item_value[2]
            except IndexError:
                part_type = 'part'
            except Exception as e:
                logger.error(f'加载课程表文件[节点类型]出错：{e}')
                part_type = 'part'

            # 应用时差偏移到课程表时间
            start_time = dt.datetime.combine(today, dt.time(h, m)) + dt.timedelta(seconds=time_offset)
            parts_start_time.append(start_time)
            order.append(item_name)
            parts_type.append(part_type)
        except Exception as e:
            logger.error(f'加载课程表文件[起始时间]出错：{e}')

    paired = zip(parts_start_time, order)
    paired_sorted = sorted(paired, key=lambda x: x[0])  # 按时间大小排序
    if paired_sorted:
        parts_start_time, order = zip(*paired_sorted)

    def sort_timeline_key(item):
        item_name = item[0]
        prefix = item_name[0]
        if len(item_name) > 1:
            try:
                # 提取节点序数
                part_num = int(item_name[1])
                # 提取课程序数
                class_num = 0
                if len(item_name) > 2:
                    class_num = int(item_name[2:])
                if prefix == 'a':
                    return part_num, class_num, 0
                else:
                    return part_num, class_num, 1
            except ValueError:
                # 如果转换失败，返回原始字符串
                return item_name
        return item_name
    
    # 对timeline排序后添加到timeline_data
    sorted_timeline = sorted(timeline.items(), key=sort_timeline_key)
    for item_name, item_time in sorted_timeline:
        try:
            timeline_data[item_name] = item_time
        except Exception as e:
            logger.error(f'加载课程表文件[课程数据]出错：{e}')


def get_part():
    if not parts_start_time:
        return None

    def return_data():
        c_time = parts_start_time[i]
        return c_time, int(order[i])  # 返回开始时间、Part序号

    current_dt = dt.datetime.now() # 当前时间

    for i in range(len(parts_start_time)):  # 遍历每个Part
        time_len = dt.timedelta(minutes=0)  # Part长度

        for item_name, item_time in timeline_data.items():
            if item_name.startswith(f'a{str(order[i])}') or item_name.startswith(f'f{str(order[i])}'):
                time_len += dt.timedelta(minutes=int(item_time))  # 累计Part的时间点总长度
            time_len += dt.timedelta(seconds=1)

        if time_len != dt.timedelta(seconds=1):  # 有课程
            if i == len(parts_start_time) - 1:  # 最后一个Part
                return return_data()
            else:
                if current_dt <= parts_start_time[i] + time_len:
                    return return_data()

    return parts_start_time[0] + dt.timedelta(seconds=time_offset), 0, 'part'

def get_excluded_lessons():
    global excluded_lessons
    if config_center.read_conf('General', 'excluded_lesson') == "0":
        excluded_lessons = []
        return 
    excluded_lessons_raw = config_center.read_conf('General', 'excluded_lessons')
    excluded_lessons = excluded_lessons_raw.split(',') if excluded_lessons_raw != '' else []

# 获取当前活动
def get_current_lessons():  # 获取当前课程
    global current_lessons
    timeline = get_timeline_data()
    if config_center.read_conf('General', 'enable_alt_schedule') == '1' or conf.is_temp_week():
        try:
            if conf.get_week_type():
                schedule = loaded_data.get('schedule_even')
            else:
                schedule = loaded_data.get('schedule')
        except Exception as e:
            logger.error(f'加载课程表文件[单双周]出错：{e}')
            schedule = loaded_data.get('schedule')
    else:
        schedule = loaded_data.get('schedule')
    class_count = 0
    for item_name, _ in timeline.items():
        if item_name.startswith('a'):
            if schedule[str(current_week)]:
                try:
                    if schedule[str(current_week)][class_count] != '未添加':
                        current_lessons[item_name] = schedule[str(current_week)][class_count]
                    else:
                        current_lessons[item_name] = '暂无课程'
                except IndexError:
                    current_lessons[item_name] = '暂无课程'
                except Exception as e:
                    current_lessons[item_name] = '暂无课程'
                    logger.debug(f'加载课程表文件出错：{e}')
                class_count += 1
            else:
                current_lessons[item_name] = '暂无课程'
                class_count += 1


# 获取倒计时、弹窗提示
def get_countdown(toast=False):  # 重构好累aaaa
    global last_notify_time
    current_dt = dt.datetime.now()
    if last_notify_time and (current_dt - last_notify_time).seconds < notify_cooldown:
        return
    def after_school():  # 放学
        if parts_type[part] == 'break':  # 休息段
            notification.push_notification(0, current_lesson_name)  # 下课
        else:
            notification.push_notification(2)  # 放学

    current_dt = dt.datetime.combine(today, dt.datetime.strptime(current_time, '%H:%M:%S').time())  # 当前时间
    return_text = []
    got_return_data = False

    if parts_start_time:
        c_time, part = get_part()

        if current_dt >= c_time:
            for item_name, item_time in timeline_data.items():
                if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                    # 判断时间是否上下课，发送通知
                    if current_dt == c_time and toast:
                        if item_name.startswith('a'):
                            notification.push_notification(1, current_lesson_name)  # 上课
                            last_notify_time = current_dt
                        else:
                            if next_lessons:  # 下课/放学
                                notification.push_notification(0, next_lessons[0])  # 下课
                                last_notify_time = current_dt
                            else:
                                after_school()

                    if current_dt == c_time - dt.timedelta(
                            minutes=int(config_center.read_conf('Toast', 'prepare_minutes'))):
                        if config_center.read_conf('Toast',
                                                   'prepare_minutes') != '0' and toast and item_name.startswith('a'):
                            if not current_state:  # 课间
                                notification.push_notification(3, next_lessons[0])  # 准备上课（预备铃）
                                last_notify_time = current_dt

                    # 放学
                    if (c_time + dt.timedelta(minutes=int(item_time)) == current_dt and not next_lessons and
                            not current_state and toast):
                        after_school()
                        last_notify_time = current_dt

                    add_time = int(item_time)
                    c_time += dt.timedelta(minutes=add_time)

                    if got_return_data:
                        break

                    if c_time >= current_dt:
                        # 根据所在时间段使用不同标语
                        if item_name.startswith('a'):
                            return_text.append('当前活动结束还有')
                        else:
                            return_text.append('课间时长还有')
                        # 返回倒计时、进度条
                        time_diff = c_time - current_dt
                        minute, sec = divmod(time_diff.seconds, 60)
                        return_text.append(f'{minute:02d}:{sec:02d}')
                        # 进度条
                        seconds = time_diff.seconds
                        return_text.append(int(100 - seconds / (int(item_time) * 60) * 100))
                        got_return_data = True
            if not return_text:
                return_text = ['目前课程已结束', f'00:00', 100]
        else:
            if f'a{part}1' in timeline_data:
                time_diff = c_time - current_dt
                minute, sec = divmod(time_diff.seconds, 60)
                return_text = ['距离上课还有', f'{minute:02d}:{sec:02d}', 100]
            else:
                return_text = ['目前课程已结束', f'00:00', 100]
        return return_text


# 获取将发生的活动
def get_next_lessons():
    global current_lesson_name
    global next_lessons
    next_lessons = []
    part = 0
    current_dt = dt.datetime.combine(today, dt.datetime.strptime(current_time, '%H:%M:%S').time())  # 当前时间

    if parts_start_time:
        c_time, part = get_part()

        def before_class():
            if part == 0:
                return True
            else:
                if current_dt >= parts_start_time[part] - dt.timedelta(minutes=60):
                    return True
                else:
                    return False

        if before_class():
            for item_name, item_time in timeline_data.items():
                if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                    add_time = int(item_time)
                    if c_time > current_dt and item_name.startswith('a'):
                        next_lessons.append(current_lessons[item_name])
                    c_time += dt.timedelta(minutes=add_time)


def get_next_lessons_text():
    if not next_lessons:
        cache_text = '当前暂无课程'
    else:
        cache_text = ''
        if len(next_lessons) >= 5:
            range_time = 5
        else:
            range_time = len(next_lessons)
        for i in range(range_time):
            if range_time > 2:
                if next_lessons[i] != '暂无课程':
                    cache_text += f'{list_.get_subject_abbreviation(next_lessons[i])}  '  # 获取课程简称
                else:
                    cache_text += f'无  '
            else:
                if next_lessons[i] != '暂无课程':
                    cache_text += f'{next_lessons[i]}  '
                else:
                    cache_text += f'暂无  '
    return cache_text


# 获取当前活动
def get_current_lesson_name():
    global current_lesson_name, current_state
    current_dt = dt.datetime.combine(today, dt.datetime.strptime(current_time, '%H:%M:%S').time())  # 当前时间
    current_lesson_name = '暂无课程'
    current_state = 0

    if parts_start_time:
        c_time, part = get_part()

        if current_dt >= c_time:
            if parts_type[part] == 'break':  # 休息段
                current_lesson_name = loaded_data['part_name'][str(part)]
                current_state = 2

            for item_name, item_time in timeline_data.items():
                if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                    add_time = int(item_time)
                    c_time += dt.timedelta(minutes=add_time)
                    if c_time > current_dt:
                        if item_name.startswith('a'):
                            current_lesson_name = current_lessons[item_name]
                            current_state = 1
                        else:
                            current_lesson_name = '课间'
                            current_state = 0
                        return


# 定义 RECT 结构体
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long)]

def get_process_name(pid): # 获取进程名称
    try:
        if isinstance(pid, int):
            pid = ctypes.windll.user32.GetWindowThreadProcessId(pid, None)
        return psutil.Process(pid).name().lower()
    except (psutil.NoSuchProcess, AttributeError, ValueError):
        return "unknown"

def check_fullscreen():  # 检查是否全屏
    if os.name != 'nt':
        return False
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if hwnd == 0 or hwnd == user32.GetDesktopWindow() or hwnd == user32.GetShellWindow():
        return False
    # 获取窗口标题
    title_buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buffer, 256)
    window_title = title_buffer.value.strip()
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_name = get_process_name(pid.value).lower()
    # 排除系统进程
    system_processes = {
        'explorer.exe',  # 桌面
        'shellexperiencehost.exe',
        'searchui.exe',  # 搜索
        'applicationframehost.exe'  # UWP组件
    }
    if process_name in system_processes:
        return False
    # 排除系统窗口
    system_windows = {
        "",  # 无标题窗口
        "program manager",  # 桌面窗口
        "windows input experience",  # 输入面板
        "msctfmonitor window",
        "startmenuexperiencehost"  # 开始菜单
    }
    if window_title.lower() in system_windows:
        return False
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    screen_rect = RECT()
    user32.GetWindowRect(user32.GetDesktopWindow(), ctypes.byref(screen_rect))
    is_fullscreen = (
        rect.left <= screen_rect.left and
        rect.top <= screen_rect.top and
        rect.right >= screen_rect.right and
        rect.bottom >= screen_rect.bottom
    )
    if fw.focusing:
        return False
    # 排除窗口大小必须占用屏幕95%,避免诈骗()
    if is_fullscreen:
        screen_area = (screen_rect.right - screen_rect.left) * (screen_rect.bottom - screen_rect.top)
        window_area = (rect.right - rect.left) * (rect.bottom - rect.top)
        return window_area >= screen_area * 0.95

    return False


class ErrorDialog(Dialog):  # 重大错误提示框
    def __init__(self, error_details='Traceback (most recent call last):', parent=None):
        # KeyboardInterrupt 直接 exit
        if error_details.endswith('KeyboardInterrupt') or error_details.endswith('KeyboardInterrupt\n'):
            stop()
        
        super().__init__(
            'Class Widgets 崩溃报告',
            '抱歉！Class Widgets 发生了严重的错误从而无法正常运行。您可以保存下方的错误信息并向他人求助。'
            '若您认为这是程序的Bug，请点击“报告此问题”或联系开发者。',
            parent
        )
        global error_dialog
        error_dialog = True

        self.is_dragging = False
        self.drag_position = QPoint()
        self.title_bar_height = 30

        self.title_layout = QHBoxLayout()

        self.iconLabel = ImageLabel()
        self.iconLabel.setImage(f"{base_directory}/img/logo/favicon-error.ico")
        self.error_log = PlainTextEdit()
        self.report_problem = PushButton(fIcon.FEEDBACK, '报告此问题')
        self.copy_log_btn = PushButton(fIcon.COPY, '复制日志')
        self.ignore_error_btn = PushButton(fIcon.INFO, '忽略错误')
        self.ignore_same_error = CheckBox()
        self.ignore_same_error.setText('在下次启动之前，忽略此错误')
        self.restart_btn = PrimaryPushButton(fIcon.SYNC, '重新启动')

        self.iconLabel.setScaledContents(True)
        self.iconLabel.setFixedSize(50, 50)
        self.titleLabel.setText('出错啦！ヽ(*。>Д<)o゜')
        self.titleLabel.setStyleSheet("font-family: Microsoft YaHei UI; font-size: 25px; font-weight: 500;")
        self.error_log.setReadOnly(True)
        self.error_log.setPlainText(error_details)
        self.error_log.setFixedHeight(200)
        self.restart_btn.setFixedWidth(150)
        self.yesButton.hide()
        self.cancelButton.hide()  # 隐藏取消按钮
        self.title_layout.setSpacing(12)

        # 按钮事件
        self.report_problem.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(
                'https://github.com/Class-Widgets/Class-Widgets/issues/'
                'new?assignees=&labels=Bug&projects=&template=BugReport.yml&title=[Bug]:'))
        )
        self.copy_log_btn.clicked.connect(self.copy_log)
        self.ignore_error_btn.clicked.connect(self.ignore_error)
        self.restart_btn.clicked.connect(restart)

        self.title_layout.addWidget(self.iconLabel)  # 标题布局
        self.title_layout.addWidget(self.titleLabel)
        self.textLayout.insertLayout(0, self.title_layout)  # 页面
        self.textLayout.addWidget(self.error_log)
        self.textLayout.addWidget(self.ignore_same_error)
        self.buttonLayout.insertStretch(0, 1)  # 按钮布局
        self.buttonLayout.insertWidget(0, self.copy_log_btn)
        self.buttonLayout.insertWidget(1, self.report_problem)
        self.buttonLayout.insertStretch(1)
        self.buttonLayout.insertWidget(4, self.ignore_error_btn)
        self.buttonLayout.insertWidget(5, self.restart_btn)

    def copy_log(self):  # 复制日志
        QApplication.clipboard().setText(self.error_log.toPlainText())
        Flyout.create(
            icon=InfoBarIcon.SUCCESS,
            title='复制成功！ヾ(^▽^*)))',
            content="日志已成功复制到剪贴板。",
            target=self.copy_log_btn,
            parent=self,
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP
        )

    def ignore_error(self):
        global ignore_errors
        if self.ignore_same_error.isChecked():
            ignore_errors.append(self.error_log.toPlainText())
        self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.y() <= self.title_bar_height:
            self.is_dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self.move(event.globalPos() - self.drag_position)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False

    def closeEvent(self, event):
        global error_dialog
        error_dialog = False
        event.ignore()
        self.hide()
        self.deleteLater()


class PluginManager:  # 插件管理器
    def __init__(self):
        self.cw_contexts = {}
        self.get_app_contexts()
        self.temp_window = []
        self.method = PluginMethod(self.cw_contexts)

    def get_app_contexts(self, path=None):
        self.cw_contexts = {
            "Widgets_Width": list_.widget_width,
            "Widgets_Name": list_.widget_name,
            "Widgets_Code": list_.widget_conf,  # 小组件列表

            "Current_Lesson": current_lesson_name,  # 当前课程名
            "State": current_state,  # 0：课间 1：上课（上下课状态）
            "Current_Part": get_part(),  # 返回开始时间、Part序号
            "Next_Lessons_text": get_next_lessons_text(),  # 下节课程

            "Weather": weather_name,  # 天气情况
            "Temp": temperature,  # 温度
            "Weather_Data": weather_data_temp,  # 天气数据
            "Weather_API": config_center.read_conf('Weather', 'api'),  # 天气API
            "Notification": notification.notification_contents,  # 检测到的通知内容

            "PLUGIN_PATH": os.path.normpath(os.path.join(conf.PLUGINS_DIR, path)) if path else conf.PLUGINS_DIR,  # 传递插件目录
            "Config_Center": config_center,  # 配置中心实例
            "Schedule_Center": schedule_center,  # 课程表中心实例
            "Base_Directory": base_directory,  # 资源目录
            "Widgets_Mgr": mgr,  # 组件管理器实例
        }
        return self.cw_contexts


class PluginMethod:  # 插件方法
    def __init__(self, app_context):
        self.app_contexts = app_context

    def register_widget(self, widget_code, widget_name, widget_width):  # 注册小组件
        self.app_contexts['Widgets_Width'][widget_code] = widget_width
        self.app_contexts['Widgets_Name'][widget_code] = widget_name
        self.app_contexts['Widgets_Code'][widget_name] = widget_code

    def adjust_widget_width(self, widget_code, width):  # 调整小组件宽度
        self.app_contexts['Widgets_Width'][widget_code] = width

    @staticmethod
    def get_widget(widget_code):  # 获取小组件实例
        for widget in mgr.widgets:
            if widget.path == widget_code:
                return widget
        return None

    @staticmethod
    def change_widget_content(widget_code, title, content):  # 修改小组件内容
        for widget in mgr.widgets:
            if widget.path == widget_code:
                widget.update_widget_for_plugin([title, content])

    @staticmethod
    def is_get_notification():  # 检查是否有通知
        if notification.pushed_notification:
            return True
        else:
            return False

    @staticmethod
    def send_notification(state=1, lesson_name='示例课程', title='通知示例', subtitle='副标题',
                          content='这是一条通知示例', icon=None, duration=2000):  # 发送通知
        notification.main(state, lesson_name, title, subtitle, content, icon, duration)

    @staticmethod
    def subprocess_exec(title, action):  # 执行系统命令
        w = openProgressDialog(title, action)
        p_mgr.temp_window = [w]
        w.show()

    @staticmethod
    def read_config(path, section, option):  # 读取配置文件
        try:
            with open(path, 'r', encoding='utf-8') as r:
                config = json.load(r)
            return config.get(section, option)
        except Exception as e:
            logger.error(f"插件读取配置文件失败：{e}")

    @staticmethod
    def generate_speech(
            text: str,
            engine: str = "edge",
            voice: Optional[str] = None,
            timeout: float = 10.0,
            auto_fallback: bool = True

    ) -> str:
        """
        同步生成语音文件（供插件调用）

        参数：
        text (str): 要转换的文本（支持中英文混合）
        engine (str): 首选的TTS引擎（默认edge）
        voice (str): 指定语音ID（可选，默认自动选择）
        timeout (float): 超时时间（秒，默认10）
        auto_fallback (bool): 是否自动回退引擎（默认True）

        返回：
        str: 生成的音频文件路径
        """
        return generate_speech_sync(
            text=text,
            engine=engine,
            voice=voice,
            auto_fallback=auto_fallback,
            timeout=timeout
        )

    @staticmethod
    def play_audio(file_path: str, tts_delete_after: bool = True):
        """
        播放音频文件

        参数：
        file_path (str): 要播放的音频文件路径
        tts_delete_after (bool): 播放后是否删除文件（默认True）

        说明：
        - 删除操作有重试机制（3次尝试）
        """
        play_audio(file_path, tts_delete_after)


class WidgetsManager:
    def __init__(self):
        self.widgets = []  # 小组件实例
        self.widgets_list = []  # 小组件列表配置
        self.state = 1

        self.widgets_width = 0  # 小组件总宽度
        self.spacing = 0  # 小组件间隔

        self.start_pos_x = 0  # 小组件起始位置
        self.start_pos_y = 0

        self.hide_status = None

    def sync_widget_animation(self, target_pos):
        for widget in self.widgets:
            if widget.path == 'widget-current-activity.ui':
                widget.animate_expand(target_pos) # 主组件形变动画

    def init_widgets(self):  # 初始化小组件
        self.widgets_list = list_.get_widget_config()
        self.check_widgets_exist()
        self.spacing = conf.load_theme_config(theme)['spacing']

        self.get_start_pos()
        cnt_all = {}

        # 添加小组件实例
        for w in range(len(self.widgets_list)):
            cnt_all[self.widgets_list[w]] = cnt_all.get(self.widgets_list[w], -1) + 1
            widget = DesktopWidget(self, self.widgets_list[w], True if w == 0 else False,cnt = cnt_all[self.widgets_list[w]], position=self.get_widget_pos("", w), widget_cnt = w)
            self.widgets.append(widget)

        self.create_widgets()

    def close_all_widgets(self):
        # 统一关闭所有组件
        if hasattr(self, '_closing'):
            return
        self._closing = True
        for widget in self.widgets:
            widget.close()  # 触发各个widget的closeEvent

    def check_widgets_exist(self):
        for widget in self.widgets_list:
            if widget not in list_.widget_width.keys():
                self.widgets_list.remove(widget)

    @staticmethod
    def get_widget_width(path):
        try:
            width = conf.load_theme_width(theme)[path]
        except KeyError:
            width = list_.widget_width[path]
        return int(width)

    @staticmethod
    def get_widgets_height():
        return int(conf.load_theme_config(theme)['height'])

    def create_widgets(self):
        for widget in self.widgets:
            widget.show()
            logger.info(f'显示小组件：{widget.path, widget.windowTitle()}')

    def adjust_ui(self):  # 更新小组件UI
        for widget in self.widgets:
            # 调整窗口尺寸
            width = self.get_widget_width(widget.path)
            height = self.get_widgets_height()
            pos_x = self.get_widget_pos(widget.path, widget.widget_cnt)[0]
            op = int(config_center.read_conf('General', 'opacity')) / 100

            if widget.animation is None:
                widget.widget_transition(pos_x, width, height, op)

    def get_widget_pos(self, path, cnt=None):  # 获取小组件位置
        num = self.widgets_list.index(path) if cnt is None else cnt
        self.get_start_pos()
        pos_x = self.start_pos_x + self.spacing * num
        for i in range(num):
            try:
                pos_x += conf.load_theme_width(theme)[self.widgets_list[i]]
            except KeyError:
                pos_x += list_.widget_width[self.widgets_list[i]]
            except:
                pos_x += 0
        return [int(pos_x), int(self.start_pos_y)]

    def get_start_pos(self):
        self.calculate_widgets_width()
        screen_geometry = app.primaryScreen().availableGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        margin = max(0, int(config_center.read_conf('General', 'margin')))
        self.start_pos_y = margin
        self.start_pos_x = (screen_width - self.widgets_width) // 2

    def calculate_widgets_width(self):  # 计算小组件占用宽度
        self.widgets_width = 0
        # 累加小组件宽度
        for widget in self.widgets_list:
            try:
                self.widgets_width += self.get_widget_width(widget)
            except Exception as e:
                logger.warning(f'计算小组件宽度发生错误：{e}')
                self.widgets_width += 0

        self.widgets_width += self.spacing * (len(self.widgets_list) - 1)

    def hide_windows(self):
        self.state = 0
        for widget in self.widgets:
            widget.animate_hide()

    def full_hide_windows(self):
        self.state = 0
        for widget in self.widgets:
            widget.animate_hide(True)

    def show_windows(self):
        if fw.animating:  # 避免动画Bug
            return
        if fw.isVisible():
            fw.close()
        self.state = 1
        for widget in self.widgets:
            widget.animate_show()

    def clear_widgets(self):
        if fw.isVisible():
            fw.close()
        for widget in self.widgets:
            widget.animate_hide_opacity()
        for widget in self.widgets:
            self.widgets.remove(widget)
        init()

    def update_widgets(self):
        c = 0
        self.adjust_ui()

        for widget in self.widgets:
            if c == 0:
                get_countdown(True)
            widget.update_data(path=widget.path)
            c += 1
        p_loader.update_plugins()

        if notification.pushed_notification:
            notification.pushed_notification = False

    def decide_to_hide(self):
        if config_center.read_conf('General', 'hide_method') == '0':  # 正常
            self.hide_windows()
        elif config_center.read_conf('General', 'hide_method') == '1':  # 单击即完全隐藏
            self.full_hide_windows()
        elif config_center.read_conf('General', 'hide_method') == '2':  # 最小化为浮窗
            if not fw.animating:
                self.full_hide_windows()
                fw.show()
        else:
            self.hide_windows()

    def cleanup_resources(self):
        for widget in self.widgets:
            try:
                widget.deleteLater()

                if hasattr(widget, 'weather_timer') and widget.weather_timer:
                    try:
                        widget.weather_timer.stop()
                    except RuntimeError:
                        logger.warning(f"组件: {widget.path} 的天气定时器已被销毁，跳过操作")

                if hasattr(widget, 'weather_thread') and widget.weather_thread:
                    try:
                        if widget.weather_thread.isRunning():
                            widget.weather_thread.terminate()
                            widget.weather_thread.quit()
                            widget.weather_thread.wait()
                        else:
                            logger.debug(f"组件: {widget.path} 的天气线程已完成任务并销毁，无需终止")
                    except RuntimeError:
                        logger.warning(f"组件: {widget.path} 的天气线程终止时发生异常，可能已被销毁")
            except Exception as ex:
                widget_path = getattr(widget, 'path', 'unknown')
                logger.error(f"清理组件 {widget_path} 时发生异常: {ex}")
        self.widgets.clear()

    def __del__(self):
        self.cleanup_resources()
        if hasattr(self, 'timer'):
            self.timer.stop()
            del self.timer

    def stop(self):
        if mgr:
            mgr.cleanup_resources()
        for widget in self.widgets:
            widget.stop()
        if self.animation:
            self.animation.stop()
        if self.opacity_animation:
            self.opacity_animation.stop()
        self.close()

class openProgressDialog(QWidget):
    def __init__(self, action_title='打开 记事本', action='notepad'):
        super().__init__()
        time = int(config_center.read_conf('Plugin', 'auto_delay'))
        self.action = action

        screen_geometry = app.primaryScreen().availableGeometry()
        self.screen_width = screen_geometry.width()
        self.screen_height = screen_geometry.height()
        self.init_ui()
        self.init_font()
        self.move((self.screen_width - self.width()) // 2, self.screen_height - self.height() - 100)

        self.action_name = self.findChild(QLabel, 'action_name')
        self.action_name.setText(action_title)

        self.opening_countdown = self.findChild(ProgressRing, 'opening_countdown')
        self.opening_countdown.setRange(0, time - 1)
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(1000)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.execute_action)
        self.timer.start(time * 1000)

        self.cancel_opening = self.findChild(QPushButton, 'cancel_opening')
        self.cancel_opening.clicked.connect(self.cancel_action)

        self.intro_animation()

    def update_progress(self):
        self.opening_countdown.setValue(self.opening_countdown.value() + 1)

    def execute_action(self):
        self.timer.stop()
        subprocess.Popen(self.action)
        self.close()

    def cancel_action(self):
        self.timer.stop()
        self.close()

    def save_position(self):
        pass

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
            Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if isDarkTheme():
            uic.loadUi(f'{base_directory}/ui/default/dark/toast-open_dialog.ui', self)
        else:
            uic.loadUi(f'{base_directory}/ui/default/toast-open_dialog.ui', self)

        backgnd = self.findChild(QFrame, 'backgnd')
        shadow_effect = QGraphicsDropShadowEffect(self)
        shadow_effect.setBlurRadius(28)
        shadow_effect.setXOffset(0)
        shadow_effect.setYOffset(6)
        shadow_effect.setColor(QColor(0, 0, 0, 80))
        backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = f'{base_directory}/font/HarmonyOS_Sans_SC_Bold.ttf'
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(f"""
                QLabel, ProgressRing, PushButton{{
                    font-family: "{font_family}";
                    font-weight: bold
                    }}
                """)

    def intro_animation(self):  # 弹出动画
        self.setMinimumWidth(300)
        label_width = self.action_name.sizeHint().width() - 120
        self.animation = QPropertyAnimation(self, b'windowOpacity')
        self.animation.setDuration(400)
        self.animation.setStartValue(0)
        self.animation.setEndValue(1)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animation_rect = QPropertyAnimation(self, b'geometry')
        self.animation_rect.setDuration(450)
        self.animation_rect.setStartValue(
            QRect(self.x(), self.screen_height, self.width(), self.height())
        )
        self.animation_rect.setEndValue(
            QRect((self.screen_width - (self.width() + label_width)) // 2,
                  self.screen_height - 250,
                  self.width() + label_width,
                  self.height())
        )
        self.animation_rect.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animation.start()
        self.animation_rect.start()

    def closeEvent(self, event):
        event.ignore()
        self.setMinimumWidth(0)
        self.position = self.pos()
        # 关闭时保存一次位置
        self.save_position()
        self.deleteLater()
        self.hide()
        p_mgr.temp_window.clear()


class FloatingWidget(QWidget):  # 浮窗
    def __init__(self):
        super().__init__()
        self.animation_rect = None
        self.animation = None
        self.m_Position = None
        self.p_Position = None
        self.m_flag = None
        self.r_Position = None
        self.init_ui()
        self.init_font()
        self.position = None
        self.animating = False
        self.focusing = False
        self.text_changed = False

        self.current_lesson_name_text = self.findChild(QLabel, 'subject')
        self.activity_countdown = self.findChild(QLabel, 'activity_countdown')
        self.countdown_progress_bar = self.findChild(ProgressRing, 'progressBar')

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 检查焦点

        # 动态获取屏幕尺寸
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        # 加载保存的位置
        saved_pos = self.load_position()
        if saved_pos:
            # 边界检查
            saved_pos = self.adjust_position_to_screen(saved_pos)
            self.position = saved_pos
        else:
            # 使用动态计算的默认位置
            self.position = QPoint(
                (screen_width - self.width()) // 2,  # 居中横向
                50  # 距离顶部 50px
            )

        update_timer.add_callback(self.update_data)

    def adjust_position_to_screen(self, pos):
        screen = QApplication.screenAt(pos)
        if not screen:
            screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        window_width = self.width()
        window_height = self.height()
        # 计算屏幕边界
        screen_left = screen_geometry.x()
        screen_right = screen_geometry.x() + screen_geometry.width()
        screen_top = screen_geometry.y()
        screen_bottom = screen_geometry.y() + screen_geometry.height()

        new_x, new_y = pos.x(), pos.y()
        if pos.x() < screen_left:
        # 当窗口可见部分不足50%时调整
            visible_width = (pos.x() + window_width) - screen_left
            if visible_width < window_width / 2:
                new_x = screen_left
        elif (pos.x() + window_width) > screen_right:
            visible_width = screen_right - pos.x()
            if visible_width < window_width / 2:
                new_x = screen_right - window_width
        if pos.y() < screen_top:
            visible_height = (pos.y() + window_height) - screen_top
            if visible_height < window_height / 2:
                new_y = screen_top
        elif (pos.y() + window_height) > screen_bottom:
            visible_height = screen_bottom - pos.y()
            if visible_height < window_height / 2:
                new_y = screen_bottom - window_height
        return QPoint(new_x, new_y)
    
    def save_position(self):
        current_screen = QApplication.screenAt(self.pos())
        if not current_screen:
            current_screen = QApplication.primaryScreen()
        screen_geometry = current_screen.availableGeometry()
        pos = self.pos()
        x = pos.x()
        window_width = self.width()
        if mgr.state:
            return
        screen_left = screen_geometry.left()
        screen_right = screen_geometry.right()
        if x < screen_left:
            visible_width = (x + window_width) - screen_left
            if visible_width < window_width / 2:
                x = screen_left
        elif (x + window_width) > screen_right:
            if self.animating:
                return
            visible_width = screen_right - x
            if visible_width < window_width / 2:
                x = screen_right - window_width
        y = min(max(pos.y(), screen_geometry.top()), screen_geometry.bottom())
        pos = QPoint(x, y)
        config_center.write_conf('FloatingWidget', 'pos_x', str(pos.x()))
        if not self.animating:
            config_center.write_conf('FloatingWidget', 'pos_y', str(pos.y()))

    def load_position(self):
        x = config_center.read_conf('FloatingWidget', 'pos_x')
        y = config_center.read_conf('FloatingWidget', 'pos_y')
        if x and y:
            return QPoint(int(x), int(y))
        return None

    def init_ui(self):
        setTheme_()
        if os.path.exists(f'{base_directory}/ui/{theme}/widget-floating.ui'):
            if isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']:
                uic.loadUi(f'{base_directory}/ui/{theme}/dark/widget-floating.ui', self)
            else:
                uic.loadUi(f'{base_directory}/ui/{theme}/widget-floating.ui', self)
        else:
            if isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']:
                uic.loadUi(f'{base_directory}/ui/default/dark/widget-floating.ui', self)
            else:
                uic.loadUi(f'{base_directory}/ui/default/widget-floating.ui', self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if sys.platform == 'darwin':
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Widget |  # macOS 失焦时仍然显示
                Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )
        else:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                                Qt.WindowType.Tool |
                                Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
                                )

        backgnd = self.findChild(QFrame, 'backgnd')
        shadow_effect = QGraphicsDropShadowEffect(self)
        shadow_effect.setBlurRadius(28)
        shadow_effect.setXOffset(0)
        shadow_effect.setYOffset(6)
        shadow_effect.setColor(QColor(0, 0, 0, 75))
        backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = f'{base_directory}/font/HarmonyOS_Sans_SC_Bold.ttf'
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(f"""
                QLabel, ProgressRing{{
                    font-family: "{font_family}";
                    }}
                """)

    def update_data(self):
        time_color = QColor(f'#{config_center.read_conf("Color", "floating_time")}')
        self.activity_countdown.setStyleSheet(f"color: {time_color.name()};")
        if self.animating:  # 执行动画时跳过更新
            return
        self.setWindowOpacity(int(config_center.read_conf('General', 'opacity')) / 100)  # 设置窗口透明度
        cd_list = get_countdown()
        self.text_changed = False
        if self.current_lesson_name_text.text() != current_lesson_name:
            self.text_changed = True

        self.current_lesson_name_text.setText(current_lesson_name)

        if cd_list:  # 模糊倒计时
            blur_floating = config_center.read_conf('General', 'blur_floating_countdown') == '1'
            if blur_floating:  # 模糊显示
                if cd_list[1] == '00:00':
                    self.activity_countdown.setText(f"< - 分钟")
                else:
                    minutes = int(cd_list[1].split(':')[0]) + 1
                    self.activity_countdown.setText(f"< {minutes} 分钟")
            else:  # 精确显示
                self.activity_countdown.setText(cd_list[1])
            self.countdown_progress_bar.setValue(cd_list[2])

        self.adjustSize_animation()

        self.update()

    def showEvent(self, event):  # 窗口显示
        logger.info('显示浮窗')
        current_screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        screen_geometry = current_screen.availableGeometry()
        
        if self.position:
            if self.position.y() > screen_geometry.center().y():
                # 下半屏
                start_pos = QPoint(
                    self.position.x(),
                    screen_geometry.bottom() + self.height()
                )
            else:
                # 上半屏
                start_pos = QPoint(
                    self.position.x(),
                    screen_geometry.top() - self.height()
                )
        else:
            # 默认:顶部中央滑入
            start_pos = QPoint(
                (screen_geometry.width() - self.width()) // 2,
                screen_geometry.top() - self.height()
            )
            self.position = QPoint(
                (screen_geometry.width() - self.width()) // 2,
                max(50, int(config_center.read_conf('General', 'margin')))
            )

        self.animation = QPropertyAnimation(self, b'windowOpacity')
        self.animation.setDuration(450)
        self.animation.setStartValue(0)
        self.animation.setEndValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.animation_rect = QPropertyAnimation(self, b'geometry')
        self.animation_rect.setDuration(600)
        self.animation_rect.setStartValue(QRect(start_pos, self.size()))
        self.animation_rect.setEndValue(QRect(self.position, self.size()))
        
        if platform.system() == 'Darwin':
            self.animation_rect.setEasingCurve(QEasingCurve.Type.OutQuad)
        elif platform.system() == 'Windows':
            self.animation_rect.setEasingCurve(QEasingCurve.Type.OutBack)
        else:
            self.animation_rect.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.animating = True
        self.animation.start()
        self.animation_rect.start()
        self.animation_rect.finished.connect(self.animation_done)

    def animation_done(self):
        self.animating = False

    def closeEvent(self, event):
        # 跳过动画
        if QApplication.instance().closingDown():
            self.save_position()
            event.accept()
            return
        event.ignore()
        self.setMinimumWidth(0)
        self.position = self.pos()
        self.save_position()
        current_screen = QApplication.screenAt(self.pos())
        if not current_screen:
            current_screen = QApplication.primaryScreen()
        screen_geometry = current_screen.availableGeometry()
        screen_center_y = screen_geometry.y() + (screen_geometry.height() // 2)
        # 动态动画
        current_pos = self.pos()
        base_duration = 350  # 基础
        max_duration = 550   # 最大
        min_duration = 250   # 最小
        # 获取主组件位置
        main_widget = next(
            (w for w in mgr.widgets if w.path == 'widget-current-activity.ui'),
            None
        )
        if main_widget:
            if current_pos.y() > screen_center_y:  # 下半屏
                # 屏幕底部
                target_y = screen_geometry.bottom() + self.height() + 10
                # 任务栏补偿
                if platform.system() == "Windows":
                    target_y += 30
                
                target_pos = QPoint(
                    main_widget.x(),
                    target_y
                )
                distance = abs(current_pos.y() - target_y)
            else:  # 上半屏
                target_pos = main_widget.pos()
                distance = abs(current_pos.y() - target_pos.y())
        else:
            target_pos = QPoint(
                screen_geometry.center().x() - self.width() // 2,
                int(config_center.read_conf('General', 'margin'))
            )
            distance = abs(current_pos.y() - target_pos.y())
        
        max_distance = screen_geometry.height()
        distance_ratio = min(distance / max_distance, 1.0)
        duration = int(base_duration + (max_duration - base_duration) * (distance_ratio ** 0.7))
        duration = max(min_duration, min(duration, max_duration))
        # 多平台兼容
        if platform.system() == "Darwin":
            curve = QEasingCurve.Type.OutQuad
            duration = int(duration * 0.85)
        elif platform.system() == "Windows":
            curve = QEasingCurve.Type.OutCubic
            if current_pos.y() > screen_center_y:
                duration += 50  # 底部移动稍慢
            curve = QEasingCurve.Type.InOutQuad
        
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(int(duration * 1.15))
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(0.0)
        
        self.animation_rect = QPropertyAnimation(self, b"geometry")
        self.animation_rect.setDuration(duration)
        self.animation_rect.setStartValue(self.geometry())
        self.animation_rect.setEndValue(QRect(target_pos, self.size()))
        self.animation_rect.setEasingCurve(curve)
        
        self.animating = True
        self.animation.start()
        self.animation_rect.start()
        
        def cleanup():
            self.hide()
            self.save_position()
            self.animating = False
            
        self.animation_rect.finished.connect(cleanup)

    def hideEvent(self, event):
        event.accept()
        logger.info('隐藏浮窗')
        self.animating = False
        self.setMinimumSize(QSize(self.width(), self.height()))

    def adjustSize_animation(self):
        if not self.text_changed:
            return
        self.setMinimumWidth(200)
        current_geometry = self.geometry()
        label_width = self.current_lesson_name_text.sizeHint().width() + 120
        offset = label_width - current_geometry.width()
        target_geometry = current_geometry.adjusted(0, 0, offset, 0)
        self.animation = QPropertyAnimation(self, b'geometry')
        self.animation.setDuration(450)
        self.animation.setStartValue(current_geometry)
        self.animation.setEndValue(target_geometry)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)
        self.animating = True  # 避免动画Bug x114514
        self.animation.start()
        self.animation.finished.connect(self.animation_done)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.m_flag = True
            self.m_Position = event.globalPos() - self.pos()  # 获取鼠标相对窗口的位置
            self.p_Position = event.globalPos()  # 获取鼠标相对屏幕的位置
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.m_flag:
            self.move(event.globalPos() - self.m_Position)  # 更改窗口位置
            event.accept()

    def mouseReleaseEvent(self, event):
        self.r_Position = event.globalPos()  # 获取鼠标相对窗口的位置
        self.m_flag = False
        # 保存位置到配置文件
        self.save_position()
        if (
                hasattr(self, "p_Position")
                and self.r_Position == self.p_Position
                and not self.animating

        ):  # 开启自动隐藏忽略点击事件
            mgr.show_windows()
            self.close()

    def focusInEvent(self, event):
        self.focusing = True

    def focusOutEvent(self, event):
        self.focusing = False

    def stop(self):
        if mgr:
            mgr.cleanup_resources()
        for widget in self.widgets:
            widget.stop()
        if self.animation:
            self.animation.stop()
        if self.opacity_animation:
            self.opacity_animation.stop()
        self.close()

class DesktopWidget(QWidget):  # 主要小组件
    def __init__(self, parent=WidgetsManager, path='widget-time.ui', enable_tray=False, cnt=0, position=None, widget_cnt = None):
        super().__init__()

        self.cnt = cnt
        self.widget_cnt = widget_cnt

        self.tray_menu = None

        self.last_widgets = list_.get_widget_config()
        self.path = path

        self.last_code = 101010100
        self.radius = conf.load_theme_config(theme)['radius']
        self.last_theme = config_center.read_conf('General', 'theme')
        self.last_color_mode = config_center.read_conf('General', 'color_mode')
        self.w = 100

        self.position = parent.get_widget_pos(self.path) if position is None else position
        self.animation = None
        self.opacity_animation = None
        mgr.hide_status = None

        try:
            self.w = conf.load_theme_config(theme)['widget_width'][self.path]
        except KeyError:
            self.w = list_.widget_width[self.path]
        self.h = conf.load_theme_config(theme)['height']

        init_config()
        self.init_ui(path)
        self.init_font()

        if enable_tray:
            self.init_tray_menu()  # 初始化托盘菜单

        # 样式
        self.backgnd = self.findChild(QFrame, 'backgnd')
        if self.backgnd is None:
            self.backgnd = self.findChild(QLabel, 'backgnd')

        stylesheet = self.backgnd.styleSheet()  # 应用圆角
        updated_stylesheet = re.sub(r'border-radius:\d+px;', f'border-radius:{self.radius}px;', stylesheet)
        self.backgnd.setStyleSheet(updated_stylesheet)

        if path == 'widget-time.ui':  # 日期显示
            self.date_text = self.findChild(QLabel, 'date_text')
            self.date_text.setText(f'{today.year} 年 {today.month} 月')
            self.day_text = self.findChild(QLabel, 'day_text')
            self.day_text.setText(f'{today.day}日  {list_.week[today.weekday()]}')

        elif path == 'widget-countdown.ui':  # 活动倒计时
            self.countdown_progress_bar = self.findChild(QProgressBar, 'progressBar')
            self.activity_countdown = self.findChild(QLabel, 'activity_countdown')
            self.ac_title = self.findChild(QLabel, 'activity_countdown_title')

        elif path == 'widget-current-activity.ui':  # 当前活动
            self.current_subject = self.findChild(QPushButton, 'subject')
            self.blur_effect_label = self.findChild(QLabel, 'blurEffect')
            # 模糊效果
            self.blur_effect = QGraphicsBlurEffect()
            self.current_subject.mouseReleaseEvent = self.rightReleaseEvent

            update_timer.add_callback(self.detect_theme_changed)

        elif path == 'widget-next-activity.ui':  # 接下来的活动
            self.nl_text = self.findChild(QLabel, 'next_lesson_text')

        elif path == 'widget-countdown-day.ui':  # 自定义倒计时
            self.custom_title = self.findChild(QLabel, 'countdown_custom_title')
            self.custom_countdown = self.findChild(QLabel, 'custom_countdown')
            
            # 添加透明度效果支持
            self.custom_title_effect = QGraphicsOpacityEffect(self.custom_title)
            self.custom_title_effect.setOpacity(1.0)
            self.custom_title.setGraphicsEffect(self.custom_title_effect)
            self.custom_title.__setattr__("opacity", property(
                lambda self: self.graphicsEffect().opacity(),
                lambda self, value: self.graphicsEffect().setOpacity(value)
            ))

            self.custom_countdown_effect = QGraphicsOpacityEffect(self.custom_countdown)
            self.custom_countdown_effect.setOpacity(1.0) 
            self.custom_countdown.setGraphicsEffect(self.custom_countdown_effect)
            self.custom_countdown.__setattr__("opacity", property(
                lambda self: self.graphicsEffect().opacity(),
                lambda self, value: self.graphicsEffect().setOpacity(value)
            ))
            
            # 记录上一次显示的内容
            self.last_countdown_title = ""
            self.last_countdown_value = ""
            
            # 动画标记
            self._countdown_animating = False

        elif path == 'widget-weather.ui':  # 天气组件
            content_layout = self.findChild(QHBoxLayout, 'horizontalLayout_2')
            content_layout.setSpacing(16)
            self.temperature = self.findChild(QLabel, 'temperature')
            self.weather_icon = self.findChild(QLabel, 'weather_icon')
            self.alert_icon = IconWidget()
            self.alert_icon.setFixedSize(24, 24)
            content_layout.insertWidget(0, self.alert_icon)

            self.get_weather_data()
            self.weather_timer = QTimer(self)
            self.weather_timer.setInterval(30 * 60 * 1000)  # 30分钟更新一次
            self.weather_timer.timeout.connect(self.get_weather_data)
            self.weather_timer.start()
            update_timer.add_callback(self.detect_weather_code_changed)

        if hasattr(self, 'img'):  # 自定义图片主题兼容
            img = self.findChild(QLabel, 'img')
            opacity = QGraphicsOpacityEffect(self)
            opacity.setOpacity(0.65)
            img.setGraphicsEffect(opacity)

        self.resize(self.w, self.height())

        # 设置窗口位置
        if first_start:
            self.animate_window(self.position)
            self.setWindowOpacity(int(config_center.read_conf('General', 'opacity')) / 100)
        else:
            self.setWindowOpacity(0)
            self.animate_show_opacity()
            self.move(self.position[0], self.position[1])
            self.resize(self.w, self.height())

        self.update_data('')

    @staticmethod
    def _onThemeChangedFinished():
        print('theme_changed')

    def update_widget_for_plugin(self, context=None):
        if context is None:
            context = ['title', 'desc']
        try:
            title = self.findChild(QLabel, 'title')
            desc = self.findChild(QLabel, 'content')
            if title is not None:
                title.setText(context[0])
            if desc is not None:
                desc.setText(context[1])
        except Exception as e:
            logger.error(f"更新插件小组件时出错：{e}")

    def init_ui(self, path):
        if conf.load_theme_config(theme)['support_dark_mode']:
            if os.path.exists(f'{base_directory}/ui/{theme}/{path}'):
                if isDarkTheme():
                    uic.loadUi(f'{base_directory}/ui/{theme}/dark/{path}', self)
                else:
                    uic.loadUi(f'{base_directory}/ui/{theme}/{path}', self)
            else:
                if isDarkTheme():
                    uic.loadUi(f'{base_directory}/ui/{theme}/dark/widget-base.ui', self)
                else:
                    uic.loadUi(f'{base_directory}/ui/{theme}/widget-base.ui', self)
        else:
            if os.path.exists(f'{base_directory}/ui/{theme}/{path}'):
                uic.loadUi(f'{base_directory}/ui/{theme}/{path}', self)
            else:
                uic.loadUi(f'{base_directory}/ui/{theme}/widget-base.ui', self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if config_center.read_conf('General', 'hide') == '2' or (not int(config_center.read_conf('General', 'enable_click'))):
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        if config_center.read_conf('General', 'pin_on_top') == '1':  # 置顶
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.WindowDoesNotAcceptFocus | Qt.X11BypassWindowManagerHint  # 绕过窗口管理器以在全屏显示通知
            )

        elif config_center.read_conf('General', 'pin_on_top') == '2':  # 置底
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnBottomHint |
                Qt.WindowType.WindowDoesNotAcceptFocus
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
            )

        if sys.platform == 'darwin':
            self.setWindowFlag(Qt.WindowType.Widget, True)
        else:
            self.setWindowFlag(Qt.WindowType.Tool, True)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 添加阴影效果
        if conf.load_theme_config(theme)['shadow']:  # 修改阴影问题
            shadow_effect = QGraphicsDropShadowEffect(self)
            shadow_effect.setBlurRadius(28)
            shadow_effect.setXOffset(0)
            shadow_effect.setYOffset(6)
            shadow_effect.setColor(QColor(0, 0, 0, 75))

            self.backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = f'{base_directory}/font/HarmonyOS_Sans_SC_Bold.ttf'
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(f"""
                QLabel, QPushButton{{
                    font-family: "{font_family}";
                    }}
                """)

    def animate_expand(self, target_geometry):
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(400)
        self.animation.setStartValue(QRect(target_geometry.x(), -self.height(), 
                                          self.width(), self.height()))
        self.animation.setEndValue(target_geometry)
        self.animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self.raise_()
        self.show()

    def init_tray_menu(self):
        if not first_start:
            return

        utils.tray_icon = utils.TrayIcon(self)
        self.tray_menu = SystemTrayMenu(title='Class Widgets', parent=self)
        self.tray_menu.addActions([
            Action(fIcon.HIDE, '完全隐藏/显示小组件', triggered=lambda: self.hide_show_widgets()),
            Action(fIcon.BACK_TO_WINDOW, '最小化为浮窗', triggered=lambda: self.minimize_to_floating()),
        ])
        self.tray_menu.addSeparator()
        self.tray_menu.addActions([
            Action(fIcon.SHOPPING_CART, '插件广场', triggered=open_plaza),
            Action(fIcon.DEVELOPER_TOOLS, '额外选项', triggered=self.open_extra_menu),
            Action(fIcon.SETTING, '设置', triggered=open_settings)
        ])
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(Action(fIcon.SYNC, '重新启动', triggered=restart))
        self.tray_menu.addAction(Action(fIcon.CLOSE, '退出', triggered=stop))
        utils.tray_icon.setContextMenu(self.tray_menu)

        utils.tray_icon.activated.connect(self.on_tray_icon_clicked)
        utils.tray_icon.show()

    @staticmethod
    def on_tray_icon_clicked(reason):  # 点击托盘图标隐藏
        if config_center.read_conf('General', 'hide') == '0':
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                if mgr.state:
                    mgr.decide_to_hide()
                else:
                    mgr.show_windows()
        elif config_center.read_conf('General', 'hide') == '3':
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                if mgr.state:
                    mgr.decide_to_hide()
                    mgr.hide_status = (True, 1)
                else:
                    mgr.show_windows()
                    mgr.hide_status = (True, 0)
                


    def rightReleaseEvent(self, event):  # 右键事件
        event.ignore()
        if event.button() == Qt.MouseButton.RightButton:
            self.open_extra_menu()

    def update_data(self, path=''):
        global current_time, current_week, start_y, time_offset, today

        today = dt.date.today()
        current_time = dt.datetime.now().strftime('%H:%M:%S')
        time_offset = conf.get_time_offset()

        get_start_time()
        get_current_lessons()
        get_current_lesson_name()
        get_excluded_lessons()
        get_next_lessons()

        if (hide_mode:=config_center.read_conf('General', 'hide')) == '1':  # 上课自动隐藏
            if current_state:
                if not current_lesson_name in excluded_lessons:
                    mgr.decide_to_hide()
                else:
                    mgr.show_windows()
            else:
                mgr.show_windows()
        elif hide_mode == '2': # 最大化/全屏自动隐藏
            if check_windows_maximize() or check_fullscreen():
                mgr.decide_to_hide()
            else:
                mgr.show_windows()
        elif hide_mode == '3': # 灵活隐藏
            if mgr.hide_status is None:
                mgr.hide_status = (False, current_state)
            elif mgr.hide_status[0] and mgr.hide_status[1] == current_state:
                mgr.hide_status = (False, current_state)
            elif not mgr.hide_status[0]:
                mgr.hide_status = (False, current_state)
            if mgr.hide_status[1]:
                if not current_lesson_name in excluded_lessons:
                    mgr.decide_to_hide()
                else:
                    mgr.show_windows()
            else:
                mgr.show_windows()

            

        if conf.is_temp_week():  # 调休日
            current_week = config_center.read_conf('Temp', 'set_week')
        else:
            current_week = dt.datetime.now().weekday()
        
        cd_list = get_countdown()

        if path == 'widget-time.ui':  # 日期显示
            self.date_text.setText(f'{today.year} 年 {today.month} 月')
            self.day_text.setText(f'{today.day} 日 {list_.week[today.weekday()]}')

        if path == 'widget-current-activity.ui':  # 当前活动
            self.current_subject.setText(f'  {current_lesson_name}')

            if current_state != 2:  # 非休息段
                render = QSvgRenderer(list_.get_subject_icon(current_lesson_name))
                self.blur_effect_label.setStyleSheet(
                    f'background-color: rgba{list_.subject_color(current_lesson_name)}, 200);'
                )
            else:  # 休息段
                render = QSvgRenderer(list_.get_subject_icon('课间'))
                self.blur_effect_label.setStyleSheet(
                    f'background-color: rgba{list_.subject_color("课间")}, 200);'
                )
            pixmap = QPixmap(render.defaultSize())
            pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(pixmap)
            render.render(painter)
            if (isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']
                    or isDarkTheme() and conf.load_theme_config(theme)['default_theme'] == 'dark'):  # 在暗色模式显示亮色图标
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor("#FFFFFF"))
            painter.end()

            self.current_subject.setIcon(QIcon(pixmap))
            self.blur_effect.setBlurRadius(25)  # 模糊半径
            self.blur_effect_label.setGraphicsEffect(self.blur_effect)

        elif path == 'widget-next-activity.ui':  # 接下来的活动
            self.nl_text.setText(get_next_lessons_text())

        if path == 'widget-countdown.ui':  # 活动倒计时
            if cd_list:
                if config_center.read_conf('General', 'blur_countdown') == '1':  # 模糊倒计时
                    if cd_list[1] == '00:00':
                        self.activity_countdown.setText(f"< - 分钟")
                    else:
                        self.activity_countdown.setText(f"< {int(cd_list[1].split(':')[0]) + 1} 分钟")
                else:
                    self.activity_countdown.setText(cd_list[1])
                self.ac_title.setText(cd_list[0])
                self.countdown_progress_bar.setValue(cd_list[2])

        if path == 'widget-countdown-day.ui':  # 自定义倒计时
            conf.update_countdown(self.cnt)
            new_title = f'距离 {conf.get_cd_text_custom()} 还有'
            new_value = conf.get_custom_countdown()
            
            # 如果内容有变化且不在动画中,执行过渡动画
            if ((new_title != self.last_countdown_title or new_value != self.last_countdown_value) and
                not self._countdown_animating):
                self._animate_countdown_transition(new_title, new_value)
                self.last_countdown_title = new_title
                self.last_countdown_value = new_value

    def get_weather_data(self):
        logger.info('获取天气数据')
        self.weather_thread = weatherReportThread()
        self.weather_thread.weather_signal.connect(self.update_weather_data)
        self.weather_thread.start()

    def detect_weather_code_changed(self):
        current_code = config_center.read_conf('Weather')
        if current_code != self.last_code:
            self.last_code = current_code
            self.get_weather_data()

    def detect_theme_changed(self):
        theme_ = config_center.read_conf('General', 'theme')
        color_mode = config_center.read_conf('General', 'color_mode')
        widgets = list_.get_widget_config()
        if theme_ != self.last_theme or color_mode != self.last_color_mode or widgets != self.last_widgets:
            self.last_theme = theme_
            self.last_color_mode = color_mode
            self.last_widgets = widgets
            logger.info(f'切换主题：{theme_}，颜色模式{color_mode}')
            mgr.clear_widgets()

    def update_weather_data(self, weather_data):  # 更新天气数据(已兼容多api)
        global weather_name, temperature, weather_data_temp
        if type(weather_data) is dict and hasattr(self, 'weather_icon') and 'error' not in weather_data:
            logger.success('已获取天气数据')
            alert_data = weather_data.get('alert')
            weather_data = weather_data.get('now')
            weather_data_temp = weather_data

            weather_name = db.get_weather_by_code(db.get_weather_data('icon', weather_data))
            current_city = self.findChild(QLabel, 'current_city')
            try:  # 天气组件
                self.weather_icon.setPixmap(
                    QPixmap(db.get_weather_icon_by_code(db.get_weather_data('icon', weather_data)))
                )
                self.alert_icon.hide()
                if db.is_supported_alert():
                    # print(alert_data if alert_data else weather_data)
                    alert_type = db.get_weather_data('alert', alert_data if alert_data else weather_data)
                    if alert_type:
                        self.alert_icon.setIcon(
                            db.get_alert_image(alert_type)
                        )
                        self.alert_icon.show()

                self.temperature.setText(f"{db.get_weather_data('temp', weather_data)}")
                current_city.setText(f"{db.search_by_num(config_center.read_conf('Weather', 'city'))} · "
                                     f"{weather_name}")
                update_stylesheet = re.sub(
                    r'border-image: url\((.*?)\);',
                    f"border-image: url({db.get_weather_stylesheet(db.get_weather_data('icon', weather_data))});",
                    self.backgnd.styleSheet()
                )
                self.backgnd.setStyleSheet(update_stylesheet)
            except Exception as e:
                logger.error(f'天气组件出错：{e}')
        else:
            logger.error(f'获取天气数据出错：{weather_data}')
            try: 
                if hasattr(self, 'weather_icon'):
                    self.weather_icon.setPixmap(QPixmap(f'{base_directory}/img/weather/99.svg'))
                    self.alert_icon.hide()
                    self.temperature.setText('--°')
                    current_city = self.findChild(QLabel, 'current_city')
                    if current_city:
                        current_city.setText(f"{db.search_by_num(config_center.read_conf('Weather', 'city'))} · 未知")
                    if hasattr(self, 'backgnd'):
                        update_stylesheet = re.sub(
                            r'border-image: url\((.*?)\);',
                            f"border-image: url({db.get_weather_stylesheet('99')});",
                            self.backgnd.styleSheet()
                        )
                        self.backgnd.setStyleSheet(update_stylesheet)
            except Exception as e:
                logger.error(f'天气图标设置失败：{e}')

    def open_extra_menu(self):
        global ex_menu
        if ex_menu is None or not ex_menu.isVisible():
            ex_menu = ExtraMenu()
            ex_menu.show()
            ex_menu.destroyed.connect(self.cleanup_extra_menu)
            logger.info('打开“额外选项”')
        else:
            ex_menu.raise_()
            ex_menu.activateWindow()

    def _animate_countdown_transition(self, new_title, new_value): #倒数日过渡动画
        if self._countdown_animating:
            return
        
        self._countdown_animating = True
        
        # 获取当前位置
        title_pos = self.custom_title.pos()
        countdown_pos = self.custom_countdown.pos()
        
        self.countdown_animation_group = QParallelAnimationGroup()
        
        # 标题淡出动画
        self.title_fade_out = QPropertyAnimation(self.custom_title_effect, b"opacity")
        self.title_fade_out.setDuration(400)
        self.title_fade_out.setStartValue(1.0)
        self.title_fade_out.setEndValue(0.0)
        self.title_fade_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.countdown_animation_group.addAnimation(self.title_fade_out)
        
        # 标题位移动画
        self.title_pos_out = QPropertyAnimation(self.custom_title, b"pos")
        self.title_pos_out.setDuration(400) 
        self.title_pos_out.setStartValue(title_pos)
        self.title_pos_out.setEndValue(QPoint(title_pos.x() + 6, title_pos.y()))
        self.title_pos_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.countdown_animation_group.addAnimation(self.title_pos_out)
        
        # 倒计时数值淡出动画
        self.countdown_fade_out = QPropertyAnimation(self.custom_countdown_effect, b"opacity")
        self.countdown_fade_out.setDuration(400)
        self.countdown_fade_out.setStartValue(1.0)
        self.countdown_fade_out.setEndValue(0.0)
        self.countdown_fade_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.countdown_animation_group.addAnimation(self.countdown_fade_out)
        
        # 倒计时数值位移动画
        self.countdown_pos_out = QPropertyAnimation(self.custom_countdown, b"pos") 
        self.countdown_pos_out.setDuration(400)
        self.countdown_pos_out.setStartValue(countdown_pos)
        self.countdown_pos_out.setEndValue(QPoint(countdown_pos.x() + 6, countdown_pos.y()))
        self.countdown_pos_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.countdown_animation_group.addAnimation(self.countdown_pos_out)
        
        def update_contents():
            # 更新内容
            self.custom_title.setText(new_title)
            self.custom_countdown.setText(new_value)
            
            # 准备位置
            self.custom_title.move(title_pos.x() - 6, title_pos.y())
            self.custom_countdown.move(countdown_pos.x() - 6, countdown_pos.y())
            
            # 创建淡入动画组
            self.fade_in_group = QParallelAnimationGroup()
            
            # 标题淡入动画
            self.title_fade_in = QPropertyAnimation(self.custom_title_effect, b"opacity")
            self.title_fade_in.setDuration(450)
            self.title_fade_in.setStartValue(0.0)
            self.title_fade_in.setEndValue(1.0)
            self.title_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.fade_in_group.addAnimation(self.title_fade_in)
            
            # 标题位移动画
            self.title_pos_in = QPropertyAnimation(self.custom_title, b"pos")
            self.title_pos_in.setDuration(450)
            self.title_pos_in.setStartValue(QPoint(title_pos.x() - 6, title_pos.y()))
            self.title_pos_in.setEndValue(title_pos)
            self.title_pos_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.fade_in_group.addAnimation(self.title_pos_in)
            
            # 倒计时数值淡入动画
            self.countdown_fade_in = QPropertyAnimation(self.custom_countdown_effect, b"opacity")
            self.countdown_fade_in.setDuration(450)
            self.countdown_fade_in.setStartValue(0.0)
            self.countdown_fade_in.setEndValue(1.0)
            self.countdown_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.fade_in_group.addAnimation(self.countdown_fade_in)
            
            # 倒计时数值位移动画
            self.countdown_pos_in = QPropertyAnimation(self.custom_countdown, b"pos")
            self.countdown_pos_in.setDuration(450)
            self.countdown_pos_in.setStartValue(QPoint(countdown_pos.x() - 6, countdown_pos.y()))
            self.countdown_pos_in.setEndValue(countdown_pos)
            self.countdown_pos_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.fade_in_group.addAnimation(self.countdown_pos_in)
            
            # 清理动画
            def finish_animation():
                self._countdown_animating = False
                if hasattr(self, 'countdown_animation_group'):
                    del self.countdown_animation_group
                if hasattr(self, 'fade_in_group'):
                    del self.fade_in_group
            
            self.fade_in_group.finished.connect(finish_animation)
            self.fade_in_group.start()

        self.countdown_animation_group.finished.connect(update_contents)
        self.countdown_animation_group.start()
    
    @staticmethod
    def cleanup_extra_menu():
        global ex_menu
        ex_menu = None

    @staticmethod
    def hide_show_widgets():  # 隐藏/显示主界面（全部隐藏）
        if mgr.state:
            mgr.full_hide_windows()
        else:
            mgr.show_windows()

    @staticmethod
    def minimize_to_floating():  # 最小化到浮窗
        if mgr.state:
            fw.show()
            mgr.full_hide_windows()
        else:
            mgr.show_windows()

    def clear_animation(self):  # 清除动画
        self.animation = None

    def animate_window(self, target_pos):  # **初次**启动动画
        # 创建位置动画
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(300)  # 持续时间
        if os.name == 'nt':
            self.animation.setStartValue(QRect(target_pos[0], -self.height(), self.w, self.h))
        else:
            self.animation.setStartValue(QRect(target_pos[0], 0, self.w, self.h))
        self.animation.setEndValue(QRect(target_pos[0], target_pos[1], self.w, self.h))
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_hide(self, full=False):  # 隐藏窗口
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(625)  # 持续时间
        height = self.height()
        self.setFixedHeight(height)  # 防止连续打断窗口高度变小

        if full and os.name == 'nt':
            '''全隐藏 windows'''
            self.animation.setEndValue(QRect(self.x(), -height, self.width(), self.height()))
        elif os.name == 'nt':
            '''半隐藏 windows'''
            self.animation.setEndValue(QRect(self.x(), -height + 40, self.width(), self.height()))
        else:
            '''其他系统'''
            self.animation.setEndValue(QRect(self.x(), 0, self.width(), self.height()))
            self.animation.finished.connect(lambda: self.hide())

        self.animation.setEasingCurve(QEasingCurve.Type.OutExpo)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_hide_opacity(self):  # 隐藏窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)  # 持续时间
        self.animation.setStartValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.close)

    def animate_show_opacity(self):  # 显示窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(350)  # 持续时间
        self.animation.setStartValue(0)
        self.animation.setEndValue(int(config_center.read_conf('General', 'opacity')) / 100)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.clear_animation)

    def animate_show(self):  # 显示窗口
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(525)  # 持续时间
        # 获取当前窗口的宽度和高度，确保动画过程中保持一致
        self.animation.setEndValue(
        QRect(self.x(), int(config_center.read_conf('General', 'margin')), self.width(), self.height()))
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.finished.connect(self.clear_animation)

        if os.name != 'nt':
            self.show()

        self.animation.start()

    def widget_transition(self, pos_x, width, height, opacity=1):  # 窗口形变
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(525)  # 持续时间
        self.animation.setStartValue(QRect(self.x(), self.y(), self.width(), self.height()))
        self.animation.setEndValue(QRect(pos_x, self.y(), width, height))
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)  # 设置动画效果
        self.animation.start()

        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(525)  # 持续时间
        self.opacity_animation.setStartValue(self.windowOpacity())
        self.opacity_animation.setEndValue(opacity)
        self.opacity_animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.opacity_animation.start()

        self.animation.finished.connect(self.clear_animation)

    # 点击自动隐藏
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            return  # 右键不执行
        if config_center.read_conf('General', 'pin_on_top') == '2':  # 置底
            return  # 置底不执行
        if config_center.read_conf('General', 'hide') == '0':  # 置顶
            if mgr.state:
                mgr.decide_to_hide()
            else:
                mgr.show_windows()
        elif config_center.read_conf('General', 'hide') == '3':  # 隐藏
            if mgr.state:
                mgr.decide_to_hide()
                mgr.hide_status = (True, 1)
            else:
                mgr.show_windows()
                mgr.hide_status = (True, 0)
            
        else:
            event.ignore()

    def stop(self):
        if mgr:
            mgr.cleanup_resources()
        for widget in self.widgets:
            widget.stop()
        if self.animation:
            self.animation.stop()
        if self.opacity_animation:
            self.opacity_animation.stop()
        self.close()

def closeEvent(self, event):
    if QApplication.instance().closingDown():
        if hasattr(self, 'weather_thread') and self.weather_thread:
            try:
                if self.weather_thread.isRunning():
                    self.weather_thread.terminate()  # 终止天气线程
                    self.weather_thread.quit()      # 退出天气线程
                    self.weather_thread.wait()      # 等待线程结束
                else:
                    logger.debug("天气线程已完成任务并销毁，无需终止")
            except RuntimeError:
                logger.warning("天气线程终止过程中发生异常，可能已被销毁")
            finally:
                del self.weather_thread  # 删除引用以避免重复操作

        if hasattr(self, 'weather_timer') and self.weather_timer:
            try:
                self.weather_timer.stop()  # 停止定时器
            except RuntimeError:
                logger.warning("天气定时器已被销毁，跳过停止操作")
            finally:
                del self.weather_timer  # 删除引用以避免重复操作
        event.accept()
        stop(0)

    for child in self.findChildren(QObject):
        child.deleteLater()
    super().closeEvent(event)
    self.deleteLater()
    self.destroy()

def check_windows_maximize():  # 检查窗口是否最大化
    if os.name != 'nt':
        return False
    # 全字匹配以下关键词排除
    excluded_titles = {
        'ResidentSideBar', # 希沃侧边栏
        'Program Manager', # Windows桌面
        'Desktop', # Windows桌面
        '', #空标题
        'SnippingTool', # 系统截图工具
    }
    # 包含以下关键词排除
    excluded_keywords = {
        'Overlay',
        'Snipping',
        'SideBar'
    }
    excluded_process_patterns = {
        'shellexperiencehost', 
        'searchui', 
        'startmenuexperiencehost'
    }
    max_windows = []
    for window in pygetwindow.getAllWindows():
        try:
            if window.isMaximized and window.visible:
                title = window.title.strip()
                pid = window._hWnd  # 获取窗口句柄
                process_name = get_process_name(pid).lower()
                title_lower = title.lower()
                is_system_explorer = (
                    process_name == "explorer.exe" 
                    and (title in excluded_titles 
                         or any(kw in title_lower for kw in excluded_keywords))
                )
                is_system_process = any(
                    pattern in process_name 
                    for pattern in excluded_process_patterns
                )
                # 标题匹配
                has_excluded_keyword = any(
                    kw in title_lower for kw in excluded_keywords
                )
                if not (title in excluded_titles or is_system_explorer or is_system_process or has_excluded_keyword):
                    max_windows.append({
                        'title': title,
                        'process': process_name,
                        'pid': pid,
                        'rect': window.box
                    })
        except Exception as e:
            logger.error(f"窗口异常: {str(e)}")
    return max_windows


def setup_signal_handlers():
    def shutdown(signum, frame):
        if hasattr(shutdown, '_called'):  # 防止重复处理
            return
        shutdown._called = True
        logger.debug(f"收到终止信号: {signum}, 执行清理")
        if mgr:
            mgr.cleanup_resources()  # 清理所有小资源
        stop(0)
    
    signal.signal(signal.SIGTERM, shutdown)  # taskkill
    signal.signal(signal.SIGINT, shutdown)   # Ctrl+C
    signal.signal(signal.SIGABRT, shutdown)  # 异常中止
    if os.name == 'posix':
        signal.signal(signal.SIGQUIT, shutdown)  # POSIX退出
        signal.signal(signal.SIGHUP, shutdown)   # 终端断开

def init_config():  # 重设配置文件
    config_center.write_conf('Temp', 'set_week', '')
    config_center.write_conf('Temp', 'set_schedule', '')
    if config_center.read_conf('Temp', 'temp_schedule') != '':  # 修复换课重置
        copy(f'{base_directory}/config/schedule/backup.json',
             f'{base_directory}/config/schedule/{config_center.schedule_name}')
        config_center.write_conf('Temp', 'temp_schedule', '')


def init():
    global theme, radius, mgr, screen_width, first_start, fw
    update_timer.remove_all_callbacks()

    theme = config_center.read_conf('General', 'theme')  # 主题
    if not os.path.exists(f'{base_directory}/ui/{theme}/theme.json'):
        logger.warning(f'主题 {theme} 不存在，使用默认主题')
        theme = 'default'
    logger.info(f'应用主题：{theme}')

    mgr = WidgetsManager()
    fw = FloatingWidget()

    # 获取屏幕横向分辨率
    screen_geometry = app.primaryScreen().availableGeometry()
    screen_width = screen_geometry.width()

    widgets = list_.get_widget_config()

    for widget in widgets:  # 检查组件
        if widget not in list_.widget_name:
            widgets.remove(widget)  # 移除不存在的组件(确保移除插件后不会出错)

    mgr.init_widgets()

    update_timer.add_callback(mgr.update_widgets)
    update_timer.start()

    logger.info(f'Class Widgets 启动。版本: {config_center.read_conf("Other", "version")}')
    p_loader.run_plugins()  # 运行插件

    first_start = False


if __name__ == '__main__':
    setup_signal_handlers()
    scale_factor = float(config_center.read_conf('General', 'scale'))
    os.environ['QT_SCALE_FACTOR'] = str(scale_factor)
    logger.info(f"当前缩放系数：{scale_factor * 100}%")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    share.create(1)  # 创建共享内存
    logger.info(
        f"共享内存：{share.isAttached()} 是否允许多开实例：{config_center.read_conf('Other', 'multiple_programs')}")

    if scale_factor > 1.8 or scale_factor < 1.0:
        logger.warning("当前缩放系数可能导致显示异常，建议使缩放系数在 100% 到 180% 之间")
        msg_box = Dialog('缩放系数过大',
                         f"当前缩放系数为 {scale_factor * 100}%，可能导致显示异常。\n建议将缩放系数设置为 100% 到 180% 之间。")
        msg_box.yesButton.setText('好')
        msg_box.cancelButton.hide()
        msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()

    # 优化操作系统和版本输出
    system = platform.system()
    if system == 'Darwin':
        system = 'macOS'
    osRelease = platform.release()
    if system == 'Windows':
        osRelease = 'Windows ' + osRelease
    if system == 'macOS':
        osRelease = 'Darwin Kernel Version ' + osRelease
    osVersion = platform.version()
    if system == 'macOS':
        osVersion = 'macOS ' + platform.mac_ver()[0]

    logger.info(f"操作系统：{system}，版本：{osRelease}/{osVersion}")

    list_pyttsx3_voices()

    if share.attach() and config_center.read_conf('Other', 'multiple_programs') != '1':
        msg_box = Dialog(
            'Class Widgets 正在运行',
            'Class Widgets 正在运行！请勿打开多个实例，否则将会出现不可预知的问题。'
            '\n(若您需要打开多个实例，请在“设置”->“高级选项”中启用“允许程序多开”)'
        )
        msg_box.yesButton.setText('好')
        msg_box.cancelButton.hide()
        msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()
        stop(-1)
    else:
        mgr = WidgetsManager()

        if config_center.read_conf('Other', 'initialstartup') == '1':  # 首次启动
            try:
                conf.add_shortcut('ClassWidgets.exe', f'{base_directory}/img/favicon.ico')
                conf.add_shortcut_to_startmenu(f'{base_directory}/ClassWidgets.exe',
                                               f'{base_directory}/img/favicon.ico')
                config_center.write_conf('Other', 'initialstartup', '')
            except Exception as e:
                logger.error(f'添加快捷方式失败：{e}')
            try:
                list_.create_new_profile('新课表 - 1.json')
            except Exception as e:
                logger.error(f'创建新课表失败：{e}')

        p_mgr = PluginManager()
        p_loader.set_manager(p_mgr)
        p_loader.load_plugins()

        init()
        get_start_time()
        get_current_lessons()
        get_current_lesson_name()
        get_next_lessons()

        # 如果在全屏或最大化模式下启动，首先折叠主组件后显示浮动窗口动画。
        if check_windows_maximize() or check_fullscreen():
            mgr.decide_to_hide()  # 折叠动画,其实这里可用`mgr.full_hide_windows()`但是播放动画似乎更好()

        if current_state == 1:
            setThemeColor(f"#{config_center.read_conf('Color', 'attend_class')}")
        else:
            setThemeColor(f"#{config_center.read_conf('Color', 'finish_class')}")

        # w = ErrorDialog()
        # w.exec()
        if config_center.read_conf('Other', 'auto_check_update') == '1':
            check_update()

    if __name__ == '__main__':
        try:
            sys.exit(app.exec())
        finally:
            stop(0)
