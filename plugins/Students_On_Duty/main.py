from .ClassWidgets.base import PluginBase, SettingsBase, PluginConfig  # 导入CW的基类

from PyQt5 import uic
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QWidget, QVBoxLayout, QScrollBar
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
from loguru import logger
import os
import csv
from datetime import datetime, timedelta
from PyQt5 import uic
from loguru import logger
from datetime import datetime
from qfluentwidgets import ComboBox, PrimaryPushButton, Flyout, InfoBarIcon, \
    FlyoutAnimationType
from qfluentwidgets import isDarkTheme



from PyQt5.QtWidgets import QHBoxLayout
from qfluentwidgets import ImageLabel, LineEdit

import json
from datetime import datetime, timedelta

WIDGET_CODE = 'cw-swtdents-on-duty.ui'  # 插件代号
WIDGET_NAME = '今日值日生'  # 您的插件显示的名称
WIDGET_WIDTH = 245

class SmoothScrollBar(QScrollBar):

    scrollFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ani = QPropertyAnimation(self, b"value")
        self.ani.setEasingCurve(QEasingCurve.OutCubic)
        self.ani.setDuration(400)
        self.ani.finished.connect(self.scrollFinished)

    def setValue(self, value: int):
        if value != self.value():
            self.ani.stop()
            self.scrollFinished.emit()
            self.ani.setStartValue(self.value())
            self.ani.setEndValue(value)
            self.ani.start()

    def wheelEvent(self, e):
        e.ignore()

class SmoothScrollArea(QScrollArea):


    def __init__(self, parent=None):
        super().__init__(parent)
        self.vScrollBar = SmoothScrollBar()
        self.setVerticalScrollBar(self.vScrollBar)
        self.setStyleSheet("QScrollBar:vertical { width: 0px; }")

    def wheelEvent(self, e):
        if hasattr(self.vScrollBar, 'setValue'):
            self.vScrollBar.setValue(self.vScrollBar.value() - e.angleDelta().y())


class Plugin(PluginBase):  # 插件类
    def __init__(self, cw_contexts, method):  # 初始化
        super().__init__(cw_contexts, method)  # 调用父类初始化方法

        self.method = method

        self.cfg = PluginConfig(self.PATH, 'config.json')  # 实例化配置类
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.json_file_path = os.path.join(self.script_dir, "duty.json")
        self.cw_contexts = cw_contexts

        self.method.register_widget(WIDGET_CODE, WIDGET_NAME, WIDGET_WIDTH)  # 注册小组件到CW

        self.load_data_from_json(self.json_file_path)  # 加载值日生信息

        self.scroll_position = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.auto_scroll)
        self.timer.start(30)  # 设置滚动速度

        self.duty_widget = ""




    def load_data_from_json(self, file_path):
        try:
            with open(file_path, 'r') as file:
                self.data_dict = json.load(file)
            return self.data_dict['start_date'], self.data_dict['data']
        except (FileNotFoundError):
            logger.error("未找到 duty.json 文件，请先设置duty.json!")

    def get_current_day_index(self, start_date_str):
        self.start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        self.current_date = datetime.now()
        self.delta_days = (self.current_date - self.start_date).days
        return self.delta_days % len(self.data_dict['data'])

    def update_duty_info(self, ):
        self.duty = self.load_data_from_json(self.json_file_path)
        self.start_date_str = self.data_dict['start_date']
        self.current_day_index = self.get_current_day_index(self.start_date_str)
        data = self.data_dict['data']
        self.today_duty_list = data[self.current_day_index]
        self.today_duty_list2 = []

        for i in self.today_duty_list:
            self.today_duty_list2.append(i)

        self.duty_1 = self.today_duty_list2[0]
        self.duty_2 = self.today_duty_list2[1]
        self.duty_3 = self.today_duty_list2[2]
        self.duty_4 = self.today_duty_list2[3]
        self.duty_names = f"""{self.duty_1}
{self.duty_2}
{self.duty_3}
{self.duty_4}"""
        self.update_widget_content(self.duty_names)

    def update_widget_content(self, duty_names):
        """更新小组件内容"""
        self.duty_widget = self.method.get_widget(WIDGET_CODE)
        if not self.duty_widget:
            logger.error(f"未找到小组件，WIDGET_CODE: {WIDGET_CODE}")
            return

        content_layout = self.find_child_layout(self.duty_widget, 'contentLayout')
        if not content_layout:
            logger.error("未能找到小组件的'contentLayout'布局")
            return

        content_layout.setSpacing(5)
        self.method.change_widget_content(WIDGET_CODE, WIDGET_NAME, WIDGET_NAME)
        self.clear_existing_content(content_layout)

        scroll_area = self.create_scroll_area(duty_names)
        if scroll_area:
            content_layout.addWidget(scroll_area)
            logger.success('值日生信息更新成功！')
        else:
            logger.error("滚动区域创建失败")

    @staticmethod
    def find_child_layout(widget, layout_name):
        """根据名称查找并返回布局"""
        return widget.findChild(QHBoxLayout, layout_name)

    def create_scroll_area(self, duty_names):
        scroll_area = SmoothScrollArea()
        scroll_area.setWidgetResizable(True)

        scroll_content = QWidget()
        scroll_content_layout = QVBoxLayout()
        scroll_content.setLayout(scroll_content_layout)
        self.clear_existing_content(scroll_content_layout)

        font_color = "#FFFFFF" if isDarkTheme() else "#000000"
        content_label = QLabel(duty_names)
        content_label.setAlignment(Qt.AlignCenter)
        content_label.setWordWrap(True)
        content_label.setStyleSheet(f"""
               font-size: 25px;
               color: {font_color};
               padding: 10px;
               font-weight: bold;
               background: none;
           """)
        scroll_content_layout.addWidget(content_label)

        scroll_area.setWidget(scroll_content)
        return scroll_area

    @staticmethod
    def clear_existing_content(content_layout):
        """清除布局中的旧内容"""
        while content_layout.count() > 0:
            item = content_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()  # 确保子组件被销毁

    def auto_scroll(self):
        """自动滚动功能"""
        if not self.duty_widget:
            return

        scroll_area = self.duty_widget.findChild(SmoothScrollArea)
        if not scroll_area:
            logger.warning("无法找到 SmoothScrollArea，停止自动滚动")
            return

        vertical_scrollbar = scroll_area.verticalScrollBar()
        if not vertical_scrollbar:
            logger.warning("无法找到垂直滚动条，停止自动滚动")
            return

        max_value = vertical_scrollbar.maximum()
        self.scroll_position = 0 if self.scroll_position >= max_value else self.scroll_position + 1
        vertical_scrollbar.setValue(self.scroll_position)


    def update(self, cw_contexts):  # 自动更新部分
        super().update(cw_contexts)  # 调用父类更新方法
        self.cfg.update_config()



    def execute(self):  # 自启动执行部分
        self.update_duty_info()


        logger.success('值日生插件加载成功！本插件开发者：月下的桃子')
        logger.success('小萝莉rinlit正在热卖中！详询https://hub.rinlit.cn/')

class Settings(SettingsBase):  # 设置类
    def __init__(self, plugin_path, parent=None):  # 初始化
        super().__init__(plugin_path, parent)
        """
        在这里写设置页面
        """
    # 其他代码……