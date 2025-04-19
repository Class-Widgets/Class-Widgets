import datetime as dt
import sys
from shutil import copy

from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QScroller
from loguru import logger
from qfluentwidgets import FluentWindow, FluentIcon as fIcon, ComboBox, \
    PrimaryPushButton, Flyout, FlyoutAnimationType, InfoBarIcon, ListWidget, LineEdit, ToolButton, HyperlinkButton, \
    SmoothScrollArea, Dialog

import conf
import file
from conf import base_directory
import list_
from file import config_center, schedule_center
from menu import SettingsMenu

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

settings = None

current_week = dt.datetime.today().weekday()
temp_schedule = {'schedule': {}, 'schedule_even': {}}


def open_settings():
    if config_center.read_conf('Temp', 'temp_schedule'):
        w = Dialog(
            "暂时无法使用“设置”",
            "由于您正在使用临时课表，将无法使用“设置”的课程表功能；\n若要启用“设置”，请重新启动 Class Widgets。"
            "\n(重启后，临时课表也将会恢复)",
            None
        )
        w.cancelButton.hide()
        w.buttonLayout.insertStretch(1)
        w.exec()

        return

    global settings
    if settings is None or not settings.isVisible():
        settings = SettingsMenu()
        settings.closed.connect(cleanup_settings)
        settings.show()
        logger.info('打开“设置”')
    else:
        settings.raise_()
        settings.activateWindow()


def cleanup_settings():
    global settings
    logger.info('关闭“设置”')
    del settings
    settings = None


class ExtraMenu(FluentWindow):
    def __init__(self):
        super().__init__()
        self.menu = None
        self.interface = uic.loadUi(f'{base_directory}/view/extra_menu.ui')
        self.initUI()
        self.init_interface()

    def init_interface(self):
        ex_scroll = self.findChild(SmoothScrollArea, 'ex_scroll')
        QScroller.grabGesture(ex_scroll, QScroller.LeftMouseButtonGesture)
        select_temp_week = self.findChild(ComboBox, 'select_temp_week')  # 选择替换日期
        select_temp_week.addItems(list_.week)
        select_temp_week.setCurrentIndex(current_week)
        select_temp_week.currentIndexChanged.connect(self.refresh_schedule_list)  # 日期选择变化

        select_temp_schedule = self.findChild(ComboBox, 'select_temp_schedule')  # 选择替换课表
        select_temp_schedule.addItems(list_.week_type)
        select_temp_schedule.setCurrentIndex(conf.get_week_type())
        select_temp_schedule.currentIndexChanged.connect(self.refresh_schedule_list) # 日期选择变化

        tmp_schedule_list = self.findChild(ListWidget, 'schedule_list')  # 换课列表
        tmp_schedule_list.addItems(self.load_schedule())
        tmp_schedule_list.itemChanged.connect(self.upload_item)

        class_kind_combo = self.findChild(ComboBox, 'class_combo')  # 课程类型
        class_kind_combo.addItems(list_.class_kind)

        set_button = self.findChild(ToolButton, 'set_button')
        set_button.setIcon(fIcon.EDIT)
        set_button.clicked.connect(self.edit_item)

        save_temp_conf = self.findChild(PrimaryPushButton, 'save_temp_conf')  # 保存设置
        save_temp_conf.clicked.connect(self.save_temp_conf)

        redirect_to_settings = self.findChild(HyperlinkButton, 'redirect_to_settings')
        redirect_to_settings.clicked.connect(open_settings)

    @staticmethod
    def load_schedule():
        if conf.get_week_type():
            return schedule_center.schedule_data['schedule_even'][str(current_week)]
        else:
            return schedule_center.schedule_data['schedule'][str(current_week)]

    def save_temp_conf(self):
        try:
            temp_week = self.findChild(ComboBox, 'select_temp_week')
            temp_schedule_set = self.findChild(ComboBox, 'select_temp_schedule')
            if temp_schedule != {'schedule': {}, 'schedule_even': {}}:
                if config_center.read_conf('Temp', 'temp_schedule') == '':  # 备份检测
                    copy(f'{base_directory}/config/schedule/{config_center.schedule_name}',
                         f'{base_directory}/config/schedule/backup.json')  # 备份课表配置
                    logger.info(f'备份课表配置成功：已将 {config_center.schedule_name} -备份至-> backup.json')
                    config_center.write_conf('Temp', 'temp_schedule', config_center.schedule_name)
                file.save_data_to_json(temp_schedule, config_center.schedule_name)
            schedule_center.update_schedule()
            config_center.write_conf('Temp', 'set_week', str(temp_week.currentIndex()))
            config_center.write_conf('Temp', 'set_schedule',str(temp_schedule_set.currentIndex()))
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
        current_schedule = self.findChild(ComboBox, 'select_temp_schedule').currentIndex()
        logger.debug(f'current_week: {current_week}, current_schedule: {current_schedule}')
        tmp_schedule_list = self.findChild(ListWidget, 'schedule_list')  # 换课列表
        tmp_schedule_list.clear()
        tmp_schedule_list.clearSelection()
        if config_center.read_conf('Temp', 'temp_schedule') == '':
            if current_schedule:
                tmp_schedule_list.addItems(
                    schedule_center.schedule_data['schedule_even'][str(current_week)]
                )
            else:
                tmp_schedule_list.addItems(
                    schedule_center.schedule_data['schedule'][str(current_week)]
                )
        else:
            if current_schedule:
                tmp_schedule_list.addItems(file.load_from_json('backup.json')['schedule_even'][str(current_week)])
            else:
                tmp_schedule_list.addItems(file.load_from_json('backup.json')['schedule'][str(current_week)])

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
        self.setWindowIcon(QIcon(f'{base_directory}/img/logo/favicon-exmenu.ico'))

        self.addSubInterface(self.interface, fIcon.INFO, '更多设置')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ExtraMenu()
    ex.show()
    sys.exit(app.exec())
