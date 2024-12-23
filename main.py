import ctypes
import json
import os
from shutil import copy
import requests
from PyQt5 import uic
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QProgressBar, QGraphicsBlurEffect, QPushButton, \
    QGraphicsDropShadowEffect, QSystemTrayIcon, QFrame, QGraphicsOpacityEffect
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QEasingCurve, QSharedMemory, QThread, pyqtSignal, \
    QSize
from PyQt5.QtGui import QColor, QIcon, QPixmap, QPainter
from loguru import logger
import sys
from qfluentwidgets import Theme, setTheme, setThemeColor, SystemTrayMenu, Action, FluentIcon as FIcon, isDarkTheme, \
    Dialog, ProgressRing
import datetime as dt
import list
import conf
import tip_toast
from PyQt5.QtGui import QFontDatabase

from menu import SettingsMenu
from menu import open_plaza
from exact_menu import ExactMenu
import weather_db as db
import importlib
import subprocess
from pathlib import Path


if os.name == 'nt':
    import pygetwindow

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

today = dt.date.today()
filename = conf.read_conf('General', 'schedule')

# 存储窗口对象
windows = []
order = []

current_lesson_name = '课程表未加载'
current_state = 0  # 0：课间 1：上课
current_time = dt.datetime.now().strftime('%H:%M:%S')
current_week = dt.datetime.now().weekday()
current_lessons = {}
loaded_data = {}
notification = tip_toast
update_timer = QTimer()

timeline_data = {}
next_lessons = []
parts_start_time = []

temperature = '未设置'
weather_icon = 0
weather_name = ''
city = 101010100  # 默认城市

time_offset = 0  # 时差偏移
first_start = True

settings = None
ex_menu = None

if conf.read_conf('Other', 'do_not_log') != '1':
    logger.add("log/ClassWidgets_main_{time}.log", rotation="1 MB", encoding="utf-8", retention="1 minute")
    logger.info('未禁用日志输出')
else:
    logger.info('已禁用日志输出功能，若需保存日志，请在“设置”->“高级选项”中关闭禁用日志功能')


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
    global parts_start_time, timeline_data, loaded_data, order
    loaded_data = conf.load_from_json(filename)
    timeline = get_timeline_data()
    part = loaded_data['part']
    parts_start_time = []
    timeline_data = {}
    order = []

    for item_name, item_value in part.items():
        try:
            h, m = item_value
            parts_start_time.append(dt.datetime.combine(today, dt.time(h, m)))
            order.append(item_name)
        except Exception as e:
            logger.error(f'加载课程表文件[起始时间]出错：{e}')

    paired = zip(parts_start_time, order)
    paired_sorted = sorted(paired, key=lambda x: x[0])  # 按时间大小排序
    if paired_sorted:
        parts_start_time, order = zip(*paired_sorted)

    for item_name, item_time in timeline.items():
        try:
            timeline_data[item_name] = item_time
        except Exception as e:
            logger.error(f'加载课程表文件[课程数据]出错：{e}')


def get_part():
    def return_data():
        c_time = parts_start_time[i] + dt.timedelta(seconds=time_offset)
        # if any(f'a{int(order[i])}' in key or f'f{int(order[i])}' in key for key in timeline_data.keys()):
        return c_time, int(order[i])
        # else:
        #     return c_time, 0  # 默认

    current_dt = dt.datetime.now()
    for i in range(len(parts_start_time)):  # 遍历每个Part
        if i == len(parts_start_time) - 1:  # 最后一个Part
            if parts_start_time[i] - dt.timedelta(minutes=30) <= current_dt or current_dt > parts_start_time[i]:
                return return_data()
        else:
            if (parts_start_time[i] - dt.timedelta(minutes=30) <= current_dt < parts_start_time[i + 1]
                    - dt.timedelta(minutes=30)):
                return return_data()
    return parts_start_time[0] + dt.timedelta(seconds=time_offset), 0


# 获取当前活动
def get_current_lessons():  # 获取当前课程
    global current_lessons
    timeline = get_timeline_data()
    if conf.read_conf('General', 'enable_alt_schedule') == '1':
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
    current_dt = dt.datetime.combine(today, dt.datetime.strptime(current_time, '%H:%M:%S').time())  # 当前时间
    return_text = []
    got_return_data = False

    if parts_start_time:
        c_time, part = get_part()
        print(c_time, part)

        if current_dt >= c_time:
            for item_name, item_time in timeline_data.items():
                if item_name.startswith(f'a{str(part)}') or item_name.startswith(f'f{str(part)}'):
                    # 判断时间是否上下课，发送通知
                    if current_dt == c_time and toast:
                        if item_name.startswith('a'):
                            notification.push_notification(1, current_lesson_name)  # 上课
                        else:
                            if next_lessons:  # 下课/放学
                                notification.push_notification(0, next_lessons[0])  # 下课
                            else:
                                notification.push_notification(2)  # 放学

                    if current_dt == c_time - dt.timedelta(minutes=int(conf.read_conf('Toast', 'prepare_minutes'))):
                        if conf.read_conf('Toast', 'prepare_minutes') != '0' and toast and item_name.startswith('a'):
                            if not current_state:  # 课间
                                notification.push_notification(3, next_lessons[0])  # 准备上课（预备铃）

                    if c_time + dt.timedelta(minutes=int(item_time)) == current_dt and not next_lessons and toast:
                        notification.push_notification(2)  # 放学

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
                if current_dt >= parts_start_time[part] - dt.timedelta(minutes=30):
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
                    cache_text += f'{list.get_subject_abbreviation(next_lessons[i])}  '  # 获取课程简称
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
                        break


# 定义 RECT 结构体
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long)]


def check_fullscreen():  # 检查是否全屏
    if os.name != 'nt':
        return
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    # 获取桌面窗口的矩形
    desktop_rect = RECT()
    user32.GetWindowRect(user32.GetDesktopWindow(), ctypes.byref(desktop_rect))
    # 获取当前窗口的矩形
    app_rect = RECT()
    title_buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buffer, 256)
    if title_buffer.value == "Application Frame Host":
        return False
    user32.GetWindowRect(hwnd, ctypes.byref(app_rect))
    if hwnd == user32.GetDesktopWindow():
        return False
    if user32.GetForegroundWindow() == 0 or user32.GetForegroundWindow() == 65972:  # 聚焦桌面则判断否
        return False
    if hwnd != user32.GetDesktopWindow() and hwnd != user32.GetShellWindow():
        if (app_rect.left <= desktop_rect.left and
                app_rect.top <= desktop_rect.top and
                app_rect.right >= desktop_rect.right and
                app_rect.bottom >= desktop_rect.bottom):
            return True
    if fw.focusing:  # 拖动浮窗时返回t
        return True
    return False


class PluginLoader:  # 插件加载器
    def __init__(self):
        self.plugins = []

    def load_plugins(self):
        try:
            for folder in Path(conf.PLUGINS_DIR).iterdir():
                if folder.is_dir() and (folder / 'plugin.json').exists():
                    if folder.name not in conf.load_plugin_config()['enabled_plugins']:
                        continue
                    module_name = f"{conf.PLUGINS_DIR}.{folder.name}"
                    try:
                        module = importlib.import_module(module_name)
                        if hasattr(module, 'Plugin'):
                            plugin_class = getattr(module, "Plugin")  # 获取 Plugin 类
                            # 实例化插件
                            self.plugins.append(plugin_class(p_mgr.get_app_contexts(folder.name), p_mgr.method))
                        logger.success(f"加载插件成功：{module_name}")
                    except Exception as e:
                        logger.error(f"加载插件失败：{e}")
        except Exception as e:
            logger.error(f"加载插件失败!：{e}")
        return self.plugins

    def run_plugins(self):
        for plugin in self.plugins:
            plugin.execute()

    def update_plugins(self):
        for plugin in self.plugins:
            if hasattr(plugin, 'update'):
                plugin.update(p_mgr.get_app_contexts())


class PluginManager:  # 插件管理器
    def __init__(self):
        self.cw_contexts = {}
        self.get_app_contexts()
        self.temp_window = []
        self.method = PluginMethod(self.cw_contexts)

    def get_app_contexts(self, path=None):
        self.cw_contexts = {
            "Widgets_Width": list.widget_width,
            "Widgets_Name": list.widget_name,
            "Widgets_Code": list.widget_conf,  # 小组件列表

            "Current_Lesson": current_lesson_name,  # 当前课程名
            "State": current_state,  # 0：课间 1：上课（上下课状态）

            "Weather": weather_name,
            "Temp": temperature,  # 天气数据
            "Notification": notification.notification_contents,  # 通知内容

            "PLUGIN_PATH": f'{conf.PLUGINS_DIR}/{path}',  # 插件目录
        }
        return self.cw_contexts


class PluginMethod:  # 插件方法
    def __init__(self, app_context):
        self.app_contexts = app_context

    def register_widget(self, widget_code, widget_name, widget_width):  # 注册小组件
        self.app_contexts['Widgets_Width'][widget_code] = widget_width
        self.app_contexts['Widgets_Name'][widget_code] = widget_name
        self.app_contexts['Widgets_Code'][widget_name] = widget_code

    def get_widget(self, widget_code):  # 获取小组件实例
        for widget in mgr.widgets:
            if widget.path == widget_code:
                return widget

    def change_widget_content(self, widget_code, title, content):  # 修改小组件内容
        for widget in mgr.widgets:
            if widget.path == widget_code:
                widget.update_widget_for_plugin([title, content])

    def is_get_notification(self):  # 检查是否有通知
        if notification.pushed_notification:
            return True
        else:
            return False

    def send_notification(self, state=1, lesson_name='示例课程', title='通知示例', subtitle='副标题',
                          content='这是一条通知示例', icon=None):  # 发送通知
        notification.main(state, lesson_name, title, subtitle, content, icon)

    def subprocess_exec(self, title, action):  # 执行系统命令
        w = openProgressDialog(title, action)
        p_mgr.temp_window = [w]
        w.show()

    def read_config(self, path, section, option):  # 读取配置文件
        try:
            with open(path, 'r', encoding='utf-8') as r:
                config = json.load(r)
            return config.get(section, option)
        except Exception as e:
            logger.error(f"插件读取配置文件失败：{e}")


class weatherReportThread(QThread):  # 获取最新天气信息
    weather_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

    def run(self):
        try:
            weather_data = self.get_weather_data()
            self.weather_signal.emit(weather_data)
        except Exception as e:
            logger.error(f"触发天气信息失败: {e}")

    def get_weather_data(self):
        location_key = conf.read_conf('Weather', 'city')
        days = 1
        key = conf.read_conf('Weather', 'api_key')
        url = db.get_weather_url().format(location_key=location_key, days=days, key=key)
        try:
            response = requests.get(url, proxies={'http': None, 'https': None})  # 禁用代理
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                logger.error(f"获取天气信息失败：{response.status_code}")
                return {'error': {'info': {'value': '错误', 'unit': response.status_code}}}
        except requests.exceptions.RequestException as e:  # 请求失败
            logger.error(f"获取天气信息失败：{e}")
            return {'error': {'info': {'value': '错误', 'unit': ''}}}
        except Exception as e:
            logger.error(f"获取天气信息失败：{e}")
            return {'error': {'info': {'value': '错误', 'unit': ''}}}


class WidgetsManager:
    def __init__(self):
        self.widgets = []
        self.state = 1

    def add_widget(self, widget):
        self.widgets.append(widget)

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
        init()

    def update_widgets(self):
        c = 0
        for widget in self.widgets:
            if c == 0:
                get_countdown(True)
            widget.update_data(path=widget.path)
            c += 1
        p_loader.update_plugins()
        if notification.pushed_notification:
            notification.pushed_notification = False

    def decide_to_hide(self):
        if conf.read_conf('General', 'hide_method') == '0':  # 正常
            self.hide_windows()
        elif conf.read_conf('General', 'hide_method') == '1':  # 单击即完全隐藏
            self.full_hide_windows()
        elif conf.read_conf('General', 'hide_method') == '2':  # 最小化为浮窗
            if not fw.animating:
                self.full_hide_windows()
                fw.show()
        else:
            self.hide_windows()


class openProgressDialog(QWidget):
    def __init__(self, action_title='打开 记事本', action='notepad'):
        super().__init__()
        time = int(conf.read_conf('Plugin', 'auto_delay'))
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
        self.opening_countdown.setRange(0, time-1)
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(1000)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.execute_action)
        self.timer.start(time*1000)

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

    def init_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if isDarkTheme():
            uic.loadUi('ui/default/dark/toast-open_dialog.ui', self)
        else:
            uic.loadUi('ui/default/toast-open_dialog.ui', self)

        backgnd = self.findChild(QFrame, 'backgnd')
        shadow_effect = QGraphicsDropShadowEffect(self)
        shadow_effect.setBlurRadius(28)
        shadow_effect.setXOffset(0)
        shadow_effect.setYOffset(6)
        shadow_effect.setColor(QColor(0, 0, 0, 80))
        backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = 'font/HarmonyOS_Sans_SC_Bold.ttf'
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
            QRect((self.screen_width - (self.width()+label_width)) // 2,
                  self.screen_height - 250,
                  self.width()+label_width,
                  self.height())
        )
        self.animation_rect.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animation.start()
        self.animation_rect.start()

    def closeEvent(self, event):
        event.ignore()
        self.deleteLater()
        self.hide()
        p_mgr.temp_window.clear()


class FloatingWidget(QWidget):  # 浮窗
    def __init__(self):
        super().__init__()
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

        self.update_data()
        timer = QTimer(self)
        timer.timeout.connect(self.update_data)
        timer.start(1000)

    def init_ui(self):
        if conf.read_conf('General', 'color_mode') == '2':
            setTheme(Theme.AUTO)
        elif conf.read_conf('General', 'color_mode') == '1':
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)

        if os.path.exists(f'ui/{theme}/widget-floating.ui'):
            if isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']:
                uic.loadUi(f'ui/{theme}/dark/widget-floating.ui', self)
            else:
                uic.loadUi(f'ui/{theme}/widget-floating.ui', self)
        else:
            if isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']:
                uic.loadUi('ui/default/dark/widget-floating.ui', self)
            else:
                uic.loadUi('ui/default/widget-floating.ui', self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )

        backgnd = self.findChild(QFrame, 'backgnd')
        shadow_effect = QGraphicsDropShadowEffect(self)
        shadow_effect.setBlurRadius(28)
        shadow_effect.setXOffset(0)
        shadow_effect.setYOffset(6)
        shadow_effect.setColor(QColor(0, 0, 0, 75))
        backgnd.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = 'font/HarmonyOS_Sans_SC_Bold.ttf'
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(f"""
                QLabel, ProgressRing{{
                    font-family: "{font_family}";
                    }}
                """)

    def update_data(self):
        self.setWindowOpacity(int(conf.read_conf('General', 'opacity')) / 100)  # 设置窗口透明度
        cd_list = get_countdown()
        self.text_changed = False
        if self.current_lesson_name_text.text() != current_lesson_name:
            self.text_changed = True

        self.current_lesson_name_text.setText(current_lesson_name)

        if cd_list:  # 模糊倒计时
            if cd_list[1] == '00:00':
                self.activity_countdown.setText(f"< - 分钟")
            else:
                self.activity_countdown.setText(f"< {int(cd_list[1].split(':')[0]) + 1} 分钟")
            self.countdown_progress_bar.setValue(cd_list[2])

        self.adjustSize_animation()

        self.update()

    def showEvent(self, event):  # 窗口显示
        logger.info('显示浮窗')
        self.move((screen_width - self.width()) // 2, 50)
        if self.position:  # 位置配置
            self.move(self.position)
        self.animation = QPropertyAnimation(self, b'windowOpacity')  # 透明度
        self.animation.setDuration(400)
        self.animation.setStartValue(0)
        self.animation.setEndValue(int(conf.read_conf('General', 'opacity')) / 100)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animation_rect = QPropertyAnimation(self, b'geometry')  # 位置
        self.animation_rect.setDuration(500)
        self.animation_rect.setStartValue(
            QRect((screen_width - self.width()) // 2, 0, self.width(), self.height()))
        self.animation_rect.setEndValue(self.geometry())
        self.animation_rect.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animating = True
        self.animation.start()
        self.animation_rect.start()
        self.animation_rect.finished.connect(self.animation_done)

    def animation_done(self):
        self.animating = False

    def closeEvent(self, event):
        event.ignore()
        self.setMinimumWidth(0)
        self.position = self.pos()
        self.animation = QPropertyAnimation(self, b'windowOpacity')
        self.animation.setDuration(350)
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animation_rect = QPropertyAnimation(self, b'geometry')
        self.animation_rect.setDuration(400)
        self.animation_rect.setEndValue(
            QRect((screen_width - self.width()) // 2, 0, self.width(),
                  self.height()))
        self.animation_rect.setEasingCurve(QEasingCurve.Type.InOutCirc)

        self.animating = True
        self.animation.start()
        self.animation_rect.start()
        self.animation_rect.finished.connect(self.hide)

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
        if Qt.MouseButton.LeftButton and self.m_flag:
            self.move(event.globalPos() - self.m_Position)  # 更改窗口位置
            event.accept()

    def mouseReleaseEvent(self, event):
        self.r_Position = event.globalPos()  # 获取鼠标相对窗口的位置
        self.m_flag = False
        if (self.r_Position == self.p_Position and not self.animating and
                conf.read_conf('General', 'hide') == '0'):  # 开启自动隐藏忽略点击事件
            mgr.show_windows()
            self.close()

    def focusInEvent(self, event):
        self.focusing = True

    def focusOutEvent(self, event):
        self.focusing = False


class DesktopWidget(QWidget):  # 主要小组件
    def __init__(self, path='widget-time.ui', pos=(100, 50), enable_tray=False):
        super().__init__()
        self.path = path
        self.last_code = 101010100
        self.last_theme = conf.read_conf('General', 'theme')
        self.last_color_mode = conf.read_conf('General', 'color_mode')
        self.w = 100

        try:
            self.w = conf.load_theme_config(theme)['widget_width'][self.path]
        except KeyError:
            self.w = list.widget_width[self.path]
        self.h = conf.load_theme_config(theme)['height']

        init_config()
        self.init_ui(path)
        if enable_tray:
            self.init_tray_menu()  # 初始化托盘菜单
        self.init_font()

        if path == 'widget-time.ui':  # 日期显示
            self.date_text = self.findChild(QLabel, 'date_text')
            self.date_text.setText(f'{today.year} 年 {today.month} 月')
            self.day_text = self.findChild(QLabel, 'day_text')
            self.day_text.setText(f'{today.day}日  {list.week[today.weekday()]}')
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

            self.d_t_timer = QTimer(self)
            self.d_t_timer.setInterval(500)
            self.d_t_timer.timeout.connect(self.detect_theme_changed)
            self.d_t_timer.start()
        elif path == 'widget-next-activity.ui':  # 接下来的活动
            self.nl_text = self.findChild(QLabel, 'next_lesson_text')
        elif path == 'widget-countdown-custom.ui':  # 自定义倒计时
            self.custom_title = self.findChild(QLabel, 'countdown_custom_title')
            self.custom_countdown = self.findChild(QLabel, 'custom_countdown')
        elif path == 'widget-weather.ui':  # 天气组件
            self.get_weather_data()
            self.weather_timer = QTimer(self)
            self.weather_timer.setInterval(30 * 60 * 1000)  # 30分钟更新一次
            self.weather_timer.timeout.connect(self.get_weather_data)
            self.weather_timer.start()
            self.w_d_timer = QTimer(self)
            self.w_d_timer.setInterval(1000)  # 1s 检测一次
            self.w_d_timer.timeout.connect(self.detect_weather_code_changed)
            self.w_d_timer.start()

        if hasattr(self, 'img'):  # 自定义图片主题兼容
            img = self.findChild(QLabel, 'img')
            opacity = QGraphicsOpacityEffect(self)
            opacity.setOpacity(0.65)
            img.setGraphicsEffect(opacity)

        # 设置窗口位置
        if first_start:
            self.animate_window(pos)
            self.setWindowOpacity(int(conf.read_conf('General', 'opacity')) / 100)
        else:
            self.setWindowOpacity(0)
            self.animate_show_opacity()
            self.move(pos[0], pos[1])
            self.resize(self.w, self.h)

        self.update_data('')

    def update_widget_for_plugin(self, context=['title', 'desc']):
        title = self.findChild(QLabel, 'title')
        desc = self.findChild(QLabel, 'content')
        title.setText(context[0])
        desc.setText(context[1])

    def init_ui(self, path):
        if conf.read_conf('General', 'color_mode') == '2':
            setTheme(Theme.AUTO)
        elif conf.read_conf('General', 'color_mode') == '1':
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)

        if conf.load_theme_config(theme)['support_dark_mode']:
            if os.path.exists(f'ui/{theme}/{path}'):
                if isDarkTheme():
                    uic.loadUi(f'ui/{theme}/dark/{path}', self)
                else:
                    uic.loadUi(f'ui/{theme}/{path}', self)
            else:
                if isDarkTheme():
                    uic.loadUi(f'ui/{theme}/dark/widget-base.ui', self)
                else:
                    uic.loadUi(f'ui/{theme}/widget-base.ui', self)
        else:
            if os.path.exists(f'ui/{theme}/{path}'):
                uic.loadUi(f'ui/{theme}/{path}', self)
            else:
                uic.loadUi(f'ui/{theme}/widget-base.ui', self)

        # 设置窗口无边框和透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if (conf.read_conf('General', 'hide') == '2'
                or conf.read_conf('General', 'hide') == '1'):
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        if int(conf.read_conf('General', 'pin_on_top')):  # 置顶
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool |
                Qt.WindowType.WindowDoesNotAcceptFocus
            )
        else:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 添加阴影效果
        if conf.load_theme_config(theme)['shadow']:  # 修改阴影问题
            backgnd = self.findChild(QLabel, 'backgnd')
            backgnd_frame = self.findChild(QFrame, 'backgnd')
            shadow_effect = QGraphicsDropShadowEffect(self)
            shadow_effect.setBlurRadius(28)
            shadow_effect.setXOffset(0)
            shadow_effect.setYOffset(6)
            shadow_effect.setColor(QColor(0, 0, 0, 75))
            try:
                backgnd.setGraphicsEffect(shadow_effect)
            except:
                backgnd_frame.setGraphicsEffect(shadow_effect)

    def init_font(self):
        font_path = 'font/HarmonyOS_Sans_SC_Bold.ttf'
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

            self.setStyleSheet(f"""
                QLabel, QPushButton{{
                    font-family: "{font_family}";
                    }}
                """)

    def init_tray_menu(self):
        self.tray_icon = QSystemTrayIcon(QIcon("img/favicon.png"), self)

        self.tray_menu = SystemTrayMenu(title='Class Widgets', parent=self)
        self.tray_menu.addActions([
            Action(FIcon.HIDE, '完全隐藏/显示小组件', triggered=lambda: self.hide_show_widgets()),
            Action(FIcon.BACK_TO_WINDOW, '最小化为浮窗', triggered=lambda: self.minimize_to_floating()),
        ])
        self.tray_menu.addSeparator()
        self.tray_menu.addActions([
            Action(FIcon.SHOPPING_CART, '插件广场', triggered=open_plaza),
            Action(FIcon.DEVELOPER_TOOLS, '额外选项', triggered=self.open_exact_menu),
            Action(FIcon.SETTING, '设置', triggered=self.open_settings)
        ])
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(Action(FIcon.CLOSE, '退出', triggered=lambda: sys.exit()))
        self.tray_icon.setContextMenu(self.tray_menu)

        self.tray_icon.activated.connect(self.on_tray_icon_clicked)
        # 显示托盘图标
        self.tray_icon.show()

    def on_tray_icon_clicked(self, reason):  # 点击托盘图标隐藏
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if mgr.state:
                mgr.decide_to_hide()
            else:
                mgr.show_windows()

    def rightReleaseEvent(self, event):  # 右键事件
        event.ignore()
        if event.button() == Qt.MouseButton.RightButton:
            self.open_exact_menu()

    def update_data(self, path=''):
        global current_time, current_week, filename, start_y, time_offset, today

        today = dt.date.today()
        current_time = dt.datetime.now().strftime('%H:%M:%S')
        filename = conf.read_conf('General', 'schedule')
        time_offset = conf.get_time_offset()
        filename = conf.read_conf('General', 'schedule')

        if conf.read_conf('General', 'hide') == '1':  # 上课自动隐藏
            if current_state:
                mgr.decide_to_hide()
            else:
                mgr.show_windows()
        elif conf.read_conf('General', 'hide') == '2':  # 最大化/全屏自动隐藏
            if check_windows_maximize() or check_fullscreen():
                mgr.decide_to_hide()
            else:
                mgr.show_windows()

        if conf.is_temp_week():  # 调休日
            current_week = conf.read_conf('Temp', 'set_week')
        else:
            current_week = dt.datetime.now().weekday()

        get_start_time()
        get_current_lessons()
        get_current_lesson_name()
        get_next_lessons()

        if not self.animation:
            self.setWindowOpacity(int(conf.read_conf('General', 'opacity')) / 100)  # 设置窗口透明度

        cd_list = get_countdown()

        if path == 'widget-time.ui':  # 日期显示
            self.date_text.setText(f'{today.year} 年 {today.month} 月')
            self.day_text.setText(f'{today.day} 日 {list.week[today.weekday()]}')

        elif path == 'widget-current-activity.ui':  # 当前活动
            self.current_subject.setText(f'  {current_lesson_name}')
            render = QSvgRenderer(list.get_subject_icon(current_lesson_name))
            pixmap = QPixmap(render.defaultSize())
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            render.render(painter)
            if isDarkTheme() and conf.load_theme_config(theme)['support_dark_mode']:  # 在暗色模式显示亮色图标
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor("#FFFFFF"))
            painter.end()
            self.current_subject.setIcon(QIcon(pixmap))
            self.blur_effect.setBlurRadius(25)  # 模糊半径
            self.blur_effect_label.setStyleSheet(
                f'background-color: rgba{list.subject_color(current_lesson_name)}, 200);'
            )
            self.blur_effect_label.setGraphicsEffect(self.blur_effect)

        elif path == 'widget-next-activity.ui':  # 接下来的活动
            self.nl_text.setText(get_next_lessons_text())

        elif path == 'widget-countdown.ui':  # 活动倒计时
            if cd_list:
                if conf.read_conf('General', 'blur_countdown') == '1':  # 模糊倒计时
                    if cd_list[1] == '00:00':
                        self.activity_countdown.setText(f"< - 分钟")
                    else:
                        self.activity_countdown.setText(f"< {int(cd_list[1].split(':')[0]) + 1} 分钟")
                else:
                    self.activity_countdown.setText(cd_list[1])
                self.ac_title.setText(cd_list[0])
                self.countdown_progress_bar.setValue(cd_list[2])

        elif path == 'widget-countdown-custom.ui':  # 自定义倒计时
            self.custom_title.setText(f'距离 {conf.read_conf("Date", "cd_text_custom")} 还有')
            self.custom_countdown.setText(conf.get_custom_countdown())
        self.update()

    def get_weather_data(self):
        logger.info('获取天气数据')
        self.weather_thread = weatherReportThread()
        self.weather_thread.weather_signal.connect(self.update_weather_data)
        self.weather_thread.start()

    def detect_weather_code_changed(self):
        current_code = conf.read_conf('Weather')
        if current_code != self.last_code:
            self.last_code = current_code
            self.get_weather_data()

    def detect_theme_changed(self):
        theme = conf.read_conf('General', 'theme')
        color_mode = conf.read_conf('General', 'color_mode')
        if theme != self.last_theme or color_mode != self.last_color_mode:
            self.last_theme = theme
            self.last_color_mode = color_mode
            logger.info(f'切换主题：{theme}，颜色模式{color_mode}')
            mgr.clear_widgets()

    def update_weather_data(self, weather_data):  # 更新天气数据(已兼容多api)
        global weather_name, temperature
        if type(weather_data) is dict and hasattr(self, 'weather_icon'):
            logger.success('已获取天气数据')
            temperature = self.findChild(QLabel, 'temperature')
            weather_icon = self.findChild(QLabel, 'weather_icon')
            weather_name = db.get_weather_by_code(db.get_weather_data('icon', weather_data))
            current_city = self.findChild(QLabel, 'current_city')
            backgnd = self.findChild(QLabel, 'backgnd')
            try:  # 天气组件
                temperature.setText(f"{db.get_weather_data('temp', weather_data)}")
                weather_icon.setPixmap(QPixmap(db.get_weather_icon_by_code(db.get_weather_data('icon', weather_data))))
                current_city.setText(f"{db.search_by_num(conf.read_conf('Weather', 'city'))} · "
                                     f"{weather_name}")
                backgnd.setStyleSheet('background-color: qlineargradient('
                                      f"{db.get_weather_stylesheet(db.get_weather_data('icon', weather_data))}); "
                                      f'border-radius: {radius}')
            except Exception as e:
                logger.error(f'天气组件出错：{e}')
        else:
            logger.error(f'获取天气数据出错：{weather_data}')

    def open_settings(self):
        global settings
        try:
            if settings is None or not settings.isVisible():
                settings = SettingsMenu()
                settings.show()
                logger.info('打开“设置”')
            else:
                settings.raise_()
                settings.activateWindow()
        except Exception as e:
            settings = SettingsMenu()
            settings.show()
            logger.info('打开“设置”')

    def open_exact_menu(self):
        global ex_menu
        try:
            if ex_menu is None or not ex_menu.isVisible():
                ex_menu = ExactMenu()
                ex_menu.show()
                logger.info('打开“额外选项”')
            else:
                ex_menu.raise_()
                ex_menu.activateWindow()
        except Exception as e:
            ex_menu = ExactMenu()
            ex_menu.show()
            logger.info('打开“额外选项”')

    def hide_show_widgets(self):  # 隐藏/显示主界面（全部隐藏）
        if mgr.state:
            mgr.full_hide_windows()
        else:
            mgr.show_windows()

    def minimize_to_floating(self):  # 最小化到浮窗
        if mgr.state:
            fw.show()
            mgr.full_hide_windows()
        else:
            mgr.show_windows()

    def animate_window(self, target_pos):  # 窗口动画！
        # 创建位置动画
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(525)  # 持续时间
        if os.name == 'nt':
            self.animation.setStartValue(QRect(target_pos[0], -self.height(), self.w, self.h))
        else:
            self.animation.setStartValue(QRect(target_pos[0], 0, self.w, self.h))
        self.animation.setEndValue(QRect(target_pos[0], target_pos[1], self.w, self.h))
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()

    def animate_hide(self, full=False):  # 隐藏窗口
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(625)  # 持续时间
        width = self.width()
        height = self.height()
        self.setFixedSize(width, height)  # 防止连续打断窗口高度变小

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

        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()

    def animate_hide_opacity(self):  # 隐藏窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)  # 持续时间
        self.animation.setStartValue(int(conf.read_conf('General', 'opacity')) / 100)
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()
        self.animation.finished.connect(self.close)

    def animate_show_opacity(self):  # 显示窗口透明度
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(350)  # 持续时间
        self.animation.setStartValue(0)
        self.animation.setEndValue(int(conf.read_conf('General', 'opacity')) / 100)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        self.animation.start()

    def animate_show(self):  # 显示窗口
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(625)  # 持续时间
        # 获取当前窗口的宽度和高度，确保动画过程中保持一致
        width = self.width()
        height = self.height()
        self.setFixedSize(width, height)  # 防止连续打断窗口高度变小
        self.animation.setEndValue(
            QRect(self.x(), int(conf.read_conf('General', 'margin')), self.width(), self.height()))
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCirc)  # 设置动画效果
        if os.name != 'nt':
            self.show()

        self.animation.start()

    # 点击自动隐藏
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            return  # 右键不执行
        if conf.read_conf('General', 'hide') != '2':  # 置顶
            if mgr.state:
                mgr.decide_to_hide()
            else:
                mgr.show_windows()
        else:

            event.ignore()

    def closeEvent(self, event):
        try:
            self.tray_icon.hide()
            self.tray_icon = None
        except:
            pass
        self.deleteLater()  # 销毁内存
        event.accept()

def check_windows_maximize():  # 检查窗口是否最大化
    if os.name != 'nt':
        return
    for window in pygetwindow.getAllWindows():
        if window.isMaximized:  # 最大化或全屏(修复
            if window.title != 'ResidentSideBar':  # 修复了误检测希沃侧边栏的Bug
                return True
    return False


def init_config():  # 重设配置文件
    conf.write_conf('Temp', 'set_week', '')
    if conf.read_conf('Temp', 'temp_schedule') != '':  # 修复换课重置
        copy('config/schedule/backup.json', f'config/schedule/{filename}')
        conf.write_conf('Temp', 'temp_schedule', '')


def show_window(path, pos, enable_tray=False):
    application = DesktopWidget(path, pos, enable_tray)
    mgr.add_widget(application)  # 将窗口对象添加到列表


def init():
    global theme, radius, mgr, screen_width, first_start, fw, update_timer
    update_timer.timeout.connect(update_time)
    update_timer.setInterval(1000)
    update_time()

    mgr = WidgetsManager()
    fw = FloatingWidget()

    theme = conf.read_conf('General', 'theme')  # 主题
    logger.info(f'应用主题：{theme}')
    # 获取屏幕横向分辨率
    screen_geometry = app.primaryScreen().availableGeometry()
    screen_width = screen_geometry.width()

    widgets = list.get_widget_config()

    for widget in widgets:  # 检查组件
        if widget not in list.widget_name:
            widgets.remove(widget)  # 移除不存在的组件(确保移除插件后不会出错)

    # 所有组件窗口的宽度
    spacing = conf.load_theme_config(theme)['spacing']
    radius = conf.load_theme_config(theme)['radius']
    widgets_width = 0
    for widget in widgets:  # 计算总宽度(兼容插件)
        try:
            widgets_width += conf.load_theme_width(theme)[widget]
        except KeyError:
            widgets_width += list.widget_width[widget]
        except:
            widgets_width += 0

    total_width = widgets_width + spacing * (len(widgets) - 1)

    start_x = (screen_width - total_width) // 2
    start_y = int(conf.read_conf('General', 'margin'))

    def cal_start_width(num):
        try:
            return int(start_x + spacing * num + sum(conf.load_theme_width(theme)[widgets[i]] for i in range(num)))
        except KeyError:
            return int(start_x + spacing * num + sum(list.widget_width[widgets[i]] for i in range(num)))
        except Exception as e:
            logger.error(f'计算窗口位置出错：{e}')
            return 0

    for w in range(len(widgets)):
        show_window(widgets[w], (cal_start_width(w), start_y), w == 0)

    for application in mgr.widgets:  # 显示所有窗口
        logger.info(f'显示窗口：{application.windowTitle()}')
        application.show()

    logger.info(f'Class Widgets 启动。版本: {conf.read_conf("Other", "version")}')
    p_loader.run_plugins()  # 运行插件

    first_start = False


def update_time():
    mgr.update_widgets()
    next_second = (dt.datetime.now() + dt.timedelta(seconds=1)).replace(microsecond=0)
    delay = (next_second - dt.datetime.now()).total_seconds() * 1000  # 转换为毫秒
    update_timer.singleShot(int(delay), update_time)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    share = QSharedMemory('ClassWidgets')
    share.create(1)  # 创建共享内存
    mgr = WidgetsManager()
    logger.info(f"共享内存：{share.isAttached()} 是否允许多开实例：{conf.read_conf('Other', 'multiple_programs')}")

    if share.attach() and conf.read_conf('Other', 'multiple_programs') != '1':
        msg_box = Dialog('Class Widgets 正在运行', 'Class Widgets 正在运行！请勿打开多个实例，否则将会出现不可预知的问题。'
                                                   '\n(若您需要打开多个实例，请在“设置”->“高级选项”中启用“允许程序多开”)')
        msg_box.yesButton.setText('好')
        msg_box.cancelButton.hide()
        msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()
        sys.exit(-1)
    else:
        if conf.read_conf('Other', 'initialstartup') == '1':  # 首次启动
            try:
                conf.add_shortcut('ClassWidgets.exe', 'img/favicon.ico')
                conf.add_shortcut_to_startmenu('ClassWidgets.exe', 'img/favicon.ico')
                conf.write_conf('Other', 'initialstartup', '')
            except Exception as e:
                logger.error(f'添加快捷方式失败：{e}')
            try:
                list.create_new_profile('新课表 - 1.json')
            except Exception as e:
                logger.error(f'创建新课表失败：{e}')

        theme = conf.read_conf('General', 'theme')  # 主题

        fw = FloatingWidget()
        p_loader = PluginLoader()
        p_mgr = PluginManager()

        p_loader.load_plugins()
        init()
        get_start_time()
        get_current_lessons()
        get_current_lesson_name()
        get_next_lessons()

        if current_state:
            setThemeColor(f"#{conf.read_conf('Color', 'attend_class')}")
        else:
            setThemeColor(f"#{conf.read_conf('Color', 'finish_class')}")

    sys.exit(app.exec())
