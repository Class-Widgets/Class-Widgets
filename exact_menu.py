import datetime as dt
import sys
from shutil import copy

from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication
from loguru import logger
from qfluentwidgets import FluentWindow, FluentIcon as fIcon, ComboBox, \
    PrimaryPushButton, Flyout, FlyoutAnimationType, InfoBarIcon, ListWidget, LineEdit, ToolButton, HyperlinkButton

import conf
import list
import menu

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

filename = conf.read_conf('General', 'schedule')
current_week = dt.datetime.today().weekday()
temp_schedule = {'schedule': {}, 'schedule_even': {}}


class ExactMenu(FluentWindow):
    def __init__(self):
        super().__init__()
        self.menu = None
        self.interface = uic.loadUi('exact_menu.ui')
        self.initUI()
        self.init_interface()

    def init_interface(self):
        select_temp_week = self.findChild(ComboBox, 'select_temp_week')  # 选择替换日期
        select_temp_week.addItems(list.week)
        select_temp_week.setCurrentIndex(current_week)
        select_temp_week.currentIndexChanged.connect(self.refresh_schedule_list)  # 日期选择变化

        tmp_schedule_list = self.findChild(ListWidget, 'schedule_list')  # 换课列表
        tmp_schedule_list.addItems(self.load_schedule())
        tmp_schedule_list.itemChanged.connect(self.upload_item)

        class_kind_combo = self.findChild(ComboBox, 'class_combo')  # 课程类型
        class_kind_combo.addItems(list.class_kind)

        set_button = self.findChild(ToolButton, 'set_button')
        set_button.setIcon(fIcon.EDIT)
        set_button.clicked.connect(self.edit_item)

        save_temp_conf = self.findChild(PrimaryPushButton, 'save_temp_conf')  # 保存设置
        save_temp_conf.clicked.connect(self.save_temp_conf)

        redirect_to_settings = self.findChild(HyperlinkButton, 'redirect_to_settings')
        redirect_to_settings.clicked.connect(self.open_settings)

    def open_settings(self):
        if self.menu is None or not self.menu.isVisible():  # 防多开
            self.menu = menu.SettingsMenu()
            self.menu.show()
        else:
            self.menu.raise_()
            self.menu.activateWindow()

    def load_schedule(self):
        global filename
        filename = conf.read_conf('General', 'schedule')
        if conf.get_week_type():
            return conf.load_from_json(filename)['schedule_even'][str(current_week)]
        else:
            return conf.load_from_json(filename)['schedule'][str(current_week)]

    def save_temp_conf(self):
        try:
            temp_week = self.findChild(ComboBox, 'select_temp_week')
            if temp_schedule != {'schedule': {}, 'schedule_even': {}}:
                if conf.read_conf('Temp', 'temp_schedule') == '':  # 备份检测
                    copy(f'config/schedule/{filename}', f'config/schedule/backup.json')  # 备份课表配置
                    logger.info(f'备份课表配置成功：已将 {filename} -备份至-> backup.json')
                    conf.write_conf('Temp', 'temp_schedule', filename)
                conf.save_data_to_json(temp_schedule, filename)
            conf.write_conf('Temp', 'set_week', str(temp_week.currentIndex()))
            Flyout.create(
                icon=InfoBarIcon.SUCCESS,
                title='保存成功',
                content=f"已保存至 ./config.ini \n重启后恢复。",
                target=self.findChild(PrimaryPushButton, 'save_temp_conf'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
        except Exception as e:
            Flyout.create(
                icon=InfoBarIcon.ERROR,
                title='保存失败',
                content=f"错误信息：{e}",
                target=self.findChild(PrimaryPushButton, 'save_temp_conf'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )

    def refresh_schedule_list(self):
        global current_week
        current_week = self.findChild(ComboBox, 'select_temp_week').currentIndex()
        tmp_schedule_list = self.findChild(ListWidget, 'schedule_list')  # 换课列表
        tmp_schedule_list.clear()
        tmp_schedule_list.clearSelection()
        if conf.read_conf('Temp', 'temp_schedule') == '':
            if conf.get_week_type():
                tmp_schedule_list.addItems(conf.load_from_json(filename)['schedule_even'][str(current_week)])
            else:
                tmp_schedule_list.addItems(conf.load_from_json(filename)['schedule'][str(current_week)])
        else:
            if conf.get_week_type():
                tmp_schedule_list.addItems(conf.load_from_json('backup.json')['schedule_even'][str(current_week)])
            else:
                tmp_schedule_list.addItems(conf.load_from_json('backup.json')['schedule'][str(current_week)])

    def upload_item(self):
        global temp_schedule
        se_schedule_list = self.findChild(ListWidget, 'schedule_list')
        cache_list = []
        for i in range(se_schedule_list.count()):  # 缓存ListWidget数据至列表
            item_text = se_schedule_list.item(i).text()
            cache_list.append(item_text)
        if conf.get_week_type():
            temp_schedule['schedule_even'][str(current_week)] = cache_list
        else:
            temp_schedule['schedule'][str(current_week)] = cache_list

    def edit_item(self):
        tmp_schedule_list = self.findChild(ListWidget, 'schedule_list')
        class_combo = self.findChild(ComboBox, 'class_combo')
        custom_class = self.findChild(LineEdit, 'custom_class')
        selected_items = tmp_schedule_list.selectedItems()

        if selected_items:
            selected_item = selected_items[0]
            if class_combo.currentIndex() != 0:
                selected_item.setText(class_combo.currentText())
            else:
                if custom_class.text() != '':
                    selected_item.setText(custom_class.text())

    def initUI(self):
        # 修复设置窗口在各个屏幕分辨率DPI下的窗口大小
        screen_geometry = QApplication.primaryScreen().geometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        width = int(screen_width * 0.55)
        height = int(screen_height * 0.65)

        self.move(int(screen_width / 2 - width / 2), 150)
        self.resize(width, height)

        self.setWindowTitle('Class Widgets - 更多功能')
        self.setWindowIcon(QIcon('img/logo/favicon-exmenu.ico'))

        self.addSubInterface(self.interface, fIcon.INFO, '更多设置')

    def closeEvent(self, event):
        event.ignore()
        # self.deleteLater()
        self.hide()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ExactMenu()
    ex.show()
    sys.exit(app.exec())
