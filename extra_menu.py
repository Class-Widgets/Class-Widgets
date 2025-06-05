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
import platform
from loguru import logger

# 适配高DPI缩放
if platform.system() == 'Windows' and platform.release() not in ['7', 'XP', 'Vista']:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
else:
    logger.warning('不兼容的系统,跳过高DPI标识')

from typing import Optional, Dict, Any, List # Added for type hinting

settings: Optional[SettingsMenu] = None # Added type hint for settings

current_week: int = dt.datetime.today().weekday() # Added type hint
temp_schedule: Dict[str, Dict[Any, Any]] = {'schedule': {}, 'schedule_even': {}} # Added type hint, assuming keys can be various types for inner dict


def open_settings() -> None: # Added return type hint
    if config_center.read_conf('Temp', 'temp_schedule'): # type: ignore[no-untyped-call]
        w = Dialog( # type: ignore[no-untyped-call]
            "暂时无法使用“设置”",
            "由于您正在使用临时课表，将无法使用“设置”的课程表功能；\n若要启用“设置”，请重新启动 Class Widgets。"
            "\n(重启后，临时课表也将会恢复)",
            None
        )
        w.cancelButton.hide() # type: ignore[no-untyped-call]
        w.buttonLayout.insertStretch(1) # type: ignore[no-untyped-call]
        w.exec() # type: ignore[no-untyped-call]

        return

    global settings
    if settings is None or not settings.isVisible():
        settings = SettingsMenu() # type: ignore[no-untyped-call]
        settings.closed.connect(cleanup_settings) # type: ignore[no-untyped-call]
        settings.show()
        logger.info('打开“设置”')
    else:
        settings.raise_()
        settings.activateWindow()


def cleanup_settings() -> None: # Added return type hint
    global settings
    logger.info('关闭“设置”')
    if settings is not None: # Check if settings is not None before deleting
        del settings
        settings = None


class ExtraMenu(FluentWindow): # type: ignore[misc] # FluentWindow might not have stubs
    def __init__(self) -> None: # Added return type hint
        super().__init__()
        self.menu: None = None # Assuming self.menu is intended to be something else later, or just None
        self.interface: Any = uic.loadUi(f'{base_directory}/view/extra_menu.ui') # uic.loadUi returns QWidget or similar
        self.initUI()
        self.init_interface()

    def init_interface(self) -> None: # Added return type hint
        ex_scroll: Optional[SmoothScrollArea] = self.findChild(SmoothScrollArea, 'ex_scroll') # findChild can return None
        if ex_scroll:
            QScroller.grabGesture(ex_scroll, QScroller.LeftMouseButtonGesture) # type: ignore[no-untyped-call]

        select_temp_week: Optional[ComboBox] = self.findChild(ComboBox, 'select_temp_week')
        if select_temp_week:
            select_temp_week.addItems(list_.week) # type: ignore[no-untyped-call]
            select_temp_week.setCurrentIndex(current_week)
            select_temp_week.currentIndexChanged.connect(self.refresh_schedule_list)

        select_temp_schedule: Optional[ComboBox] = self.findChild(ComboBox, 'select_temp_schedule')
        if select_temp_schedule:
            select_temp_schedule.addItems(list_.week_type) # type: ignore[no-untyped-call]
            select_temp_schedule.setCurrentIndex(conf.get_week_type()) # type: ignore[no-untyped-call]
            select_temp_schedule.currentIndexChanged.connect(self.refresh_schedule_list)

        tmp_schedule_list: Optional[ListWidget] = self.findChild(ListWidget, 'schedule_list')
        if tmp_schedule_list:
            # load_schedule returns List[str], addItems expects Iterable[str]
            tmp_schedule_list.addItems(self.load_schedule())
            tmp_schedule_list.itemChanged.connect(self.upload_item)

        class_kind_combo: Optional[ComboBox] = self.findChild(ComboBox, 'class_combo')
        if class_kind_combo:
            class_kind_combo.addItems(list_.class_kind) # type: ignore[no-untyped-call]

        set_button: Optional[ToolButton] = self.findChild(ToolButton, 'set_button')
        if set_button:
            set_button.setIcon(fIcon.EDIT) # type: ignore[attr-defined]
            set_button.clicked.connect(self.edit_item)

        save_temp_conf: Optional[PrimaryPushButton] = self.findChild(PrimaryPushButton, 'save_temp_conf')
        if save_temp_conf:
            save_temp_conf.clicked.connect(self.save_temp_conf)

        redirect_to_settings: Optional[HyperlinkButton] = self.findChild(HyperlinkButton, 'redirect_to_settings')
        if redirect_to_settings:
            redirect_to_settings.clicked.connect(open_settings)

    @staticmethod
    def load_schedule() -> List[str]: # Added return type hint
        # Assuming schedule_data structure matches access pattern
        # and current_week is a valid key.
        # conf.get_week_type() returns int, 0 for odd, 1 for even (based on conf.py logic)
        is_even_week: bool = bool(conf.get_week_type()) # type: ignore[no-untyped-call]

        schedule_type_key = 'schedule_even' if is_even_week else 'schedule'

        # Ensure schedule_center.schedule_data is structured as expected
        # e.g. {'schedule_even': {'0': ["ClassA", "ClassB"], ...}, 'schedule': {'0': [...], ...}}
        # Also ensure current_week (as string) is a valid key
        day_schedule: List[str] = schedule_center.schedule_data.get(schedule_type_key, {}).get(str(current_week), []) # type: ignore[attr-defined]
        return day_schedule

    def save_temp_conf(self) -> None: # Added return type hint
        try:
            temp_week_combo: Optional[ComboBox] = self.findChild(ComboBox, 'select_temp_week')
            temp_schedule_set_combo: Optional[ComboBox] = self.findChild(ComboBox, 'select_temp_schedule')

            if not temp_week_combo or not temp_schedule_set_combo:
                logger.error("Required ComboBoxes not found for saving temp config.")
                return

            current_full_schedule_data: Dict[str, Any] = schedule_center.schedule_data # type: ignore[attr-defined]

            # Ensure 'schedule' and 'schedule_even' keys exist and are dicts
            if 'schedule' not in current_full_schedule_data or not isinstance(current_full_schedule_data['schedule'], dict):
                current_full_schedule_data['schedule'] = {}
            if 'schedule_even' not in current_full_schedule_data or not isinstance(current_full_schedule_data['schedule_even'], dict):
                current_full_schedule_data['schedule_even'] = {}

            current_full_schedule_data['schedule'].update(temp_schedule.get('schedule', {}))
            current_full_schedule_data['schedule_even'].update(temp_schedule.get('schedule_even', {}))

            for key in ['timeline', 'default', 'part_name']:
                if key in temp_schedule:
                    if isinstance(temp_schedule[key], dict) and \
                       key in current_full_schedule_data and \
                       isinstance(current_full_schedule_data[key], dict):
                        current_full_schedule_data[key].update(temp_schedule[key])
                    else:
                        current_full_schedule_data[key] = temp_schedule[key]

            if temp_schedule != {'schedule': {}, 'schedule_even': {}}:
                if config_center.read_conf('Temp', 'temp_schedule') == '':  # 备份检测 type: ignore[no-untyped-call]
                    copy(f'{base_directory}/config/schedule/{config_center.schedule_name}', # type: ignore[attr-defined]
                         f'{base_directory}/config/schedule/backup.json')  # 备份课表配置
                    logger.info(f'备份课表配置成功：已将 {config_center.schedule_name} -备份至-> backup.json') # type: ignore[attr-defined]
                    config_center.write_conf('Temp', 'temp_schedule', config_center.schedule_name) # type: ignore[attr-defined,no-untyped-call]

                file.save_data_to_json(current_full_schedule_data, config_center.schedule_name) # type: ignore[attr-defined,no-untyped-call]

            schedule_center.update_schedule() # type: ignore[attr-defined,no-untyped-call]
            config_center.write_conf('Temp', 'set_week', str(temp_week_combo.currentIndex())) # type: ignore[no-untyped-call]
            config_center.write_conf('Temp', 'set_schedule', str(temp_schedule_set_combo.currentIndex())) # type: ignore[no-untyped-call]

            save_button: Optional[PrimaryPushButton] = self.findChild(PrimaryPushButton, 'save_temp_conf')
            Flyout.create( # type: ignore[no-untyped-call]
                icon=InfoBarIcon.SUCCESS, # type: ignore[attr-defined]
                title='保存成功',
                content=f"已保存至 ./config.ini \n重启后恢复。",
                target=save_button, # Target can be None, Flyout might handle it
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP # type: ignore[attr-defined]
            )
        except Exception as e:
            logger.error(f"Error in save_temp_conf: {e}") # Log the error
            save_button_error: Optional[PrimaryPushButton] = self.findChild(PrimaryPushButton, 'save_temp_conf')
            Flyout.create( # type: ignore[no-untyped-call]
                icon=InfoBarIcon.ERROR, # type: ignore[attr-defined]
                title='保存失败',
                content=f"错误信息：{e}",
                target=save_button_error,
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP # type: ignore[attr-defined]
            )

    def refresh_schedule_list(self) -> None: # Added return type hint
        global current_week

        select_temp_week_combo: Optional[ComboBox] = self.findChild(ComboBox, 'select_temp_week')
        select_temp_schedule_combo: Optional[ComboBox] = self.findChild(ComboBox, 'select_temp_schedule')
        tmp_schedule_list_widget: Optional[ListWidget] = self.findChild(ListWidget, 'schedule_list')

        if not (select_temp_week_combo and select_temp_schedule_combo and tmp_schedule_list_widget):
            logger.error("Required widgets not found for refreshing schedule list.")
            return

        current_week = select_temp_week_combo.currentIndex()
        current_schedule_idx: int = select_temp_schedule_combo.currentIndex()
        logger.debug(f'current_week: {current_week}, current_schedule: {current_schedule_idx}')

        tmp_schedule_list_widget.clear()
        tmp_schedule_list_widget.clearSelection()

        items_to_add: List[str] = []
        is_backup_mode: bool = bool(config_center.read_conf('Temp', 'temp_schedule')) # type: ignore[no-untyped-call]

        if not is_backup_mode:
            schedule_data_source: Dict[str, Any] = schedule_center.schedule_data # type: ignore[attr-defined]
            key = 'schedule_even' if current_schedule_idx else 'schedule'
            items_to_add = schedule_data_source.get(key, {}).get(str(current_week), [])
        else:
            try:
                backup_data: Dict[str, Any] = file.load_from_json('backup.json') # type: ignore[no-untyped-call]
                key = 'schedule_even' if current_schedule_idx else 'schedule'
                items_to_add = backup_data.get(key, {}).get(str(current_week), [])
            except Exception as e: # Broad exception for file loading issues
                logger.error(f"Error loading backup.json: {e}")

        tmp_schedule_list_widget.addItems(items_to_add)

    def upload_item(self) -> None: # Added return type hint
        global temp_schedule
        se_schedule_list_widget: Optional[ListWidget] = self.findChild(ListWidget, 'schedule_list')
        if not se_schedule_list_widget:
            logger.error("Schedule list widget not found for uploading item.")
            return

        cache_list: List[str] = []
        for i in range(se_schedule_list_widget.count()):
            item = se_schedule_list_widget.item(i)
            if item: # Ensure item is not None
                 cache_list.append(item.text())

        # conf.get_week_type() returns int (0 or 1)
        is_even_week_type: bool = bool(conf.get_week_type()) # type: ignore[no-untyped-call]
        schedule_key = 'schedule_even' if is_even_week_type else 'schedule'

        # Ensure the structure of temp_schedule before assignment
        if schedule_key not in temp_schedule:
            temp_schedule[schedule_key] = {}
        temp_schedule[schedule_key][str(current_week)] = cache_list

    def edit_item(self) -> None: # Added return type hint
        tmp_schedule_list_widget: Optional[ListWidget] = self.findChild(ListWidget, 'schedule_list')
        class_combo: Optional[ComboBox] = self.findChild(ComboBox, 'class_combo')
        custom_class_input: Optional[LineEdit] = self.findChild(LineEdit, 'custom_class')

        if not (tmp_schedule_list_widget and class_combo and custom_class_input):
            logger.error("Required widgets not found for editing item.")
            return

        selected_items_list = tmp_schedule_list_widget.selectedItems()

        if selected_items_list: # Check if list is not empty
            selected_item = selected_items_list[0]
            if class_combo.currentIndex() != 0: # Assuming 0 is a default/placeholder index
                selected_item.setText(class_combo.currentText())
            else:
                if custom_class_input.text() != '':
                    selected_item.setText(custom_class_input.text())

    def initUI(self) -> None: # Added return type hint
        # 修复设置窗口在各个屏幕分辨率DPI下的窗口大小
        primary_screen = QApplication.primaryScreen()
        if not primary_screen:
            logger.error("Primary screen not found.")
            return # Cannot proceed without screen info

        screen_geometry = primary_screen.geometry()
        screen_width: int = screen_geometry.width()
        screen_height: int = screen_geometry.height()

        width: int = int(screen_width * 0.55)
        height: int = int(screen_height * 0.65)

        self.move(int(screen_width / 2 - width / 2), 150)
        self.resize(width, height)

        self.setWindowTitle('Class Widgets - 更多功能')
        self.setWindowIcon(QIcon(f'{base_directory}/img/logo/favicon-exmenu.ico')) # type: ignore[no-untyped-call]

        self.addSubInterface(self.interface, fIcon.INFO, '更多设置') # type: ignore[attr-defined]

    def closeEvent(self, e: Any) -> None: # Added type hint for event 'e'
        self.deleteLater()
        super().closeEvent(e) # Call super class's closeEvent


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ExtraMenu()
    ex.show()
    sys.exit(app.exec())
