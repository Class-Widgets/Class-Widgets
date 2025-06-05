import datetime as dt
import json
import os
import platform
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from shutil import rmtree
import asyncio

from PyQt5 import uic, QtCore
from PyQt5.QtCore import Qt, QTime, QUrl, QDate, pyqtSignal, QThread, QObject
from PyQt5.QtGui import QIcon, QDesktopServices, QColor
from PyQt5.QtWidgets import QApplication, QHeaderView, QTableWidgetItem, QLabel, QHBoxLayout, QSizePolicy, \
    QSpacerItem, QFileDialog, QVBoxLayout, QScroller, QWidget
from packaging.version import Version
from loguru import logger
from qfluentwidgets import (
    Theme, setTheme, FluentWindow, FluentIcon as fIcon, ToolButton, ListWidget, ComboBox, CaptionLabel,
    SpinBox, LineEdit, PrimaryPushButton, TableWidget, Flyout, InfoBarIcon, InfoBar, InfoBarPosition,
    FlyoutAnimationType, NavigationItemPosition, MessageBox, SubtitleLabel, PushButton, SwitchButton,
    CalendarPicker, BodyLabel, ColorDialog, isDarkTheme, TimeEdit, EditableComboBox, MessageBoxBase,
    SearchLineEdit, Slider, PlainTextEdit, ToolTipFilter, ToolTipPosition, RadioButton, HyperlinkLabel,
    PrimaryDropDownPushButton, Action, RoundMenu, CardWidget, ImageLabel, StrongBodyLabel,
    TransparentDropDownToolButton, Dialog, SmoothScrollArea, TransparentToolButton, HyperlinkButton, HyperlinkLabel
)

import conf
import list_ as list_
import tip_toast
import utils
from utils import update_tray_tooltip
import weather_db
import weather_db as wd
from conf import base_directory
from cses_mgr import CSES_Converter
from generate_speech import get_tts_voices, get_voice_id_by_name, get_voice_name_by_id, get_available_engines
import generate_speech
from file import config_center, schedule_center
from network_thread import VersionThread
from plugin import p_loader
from plugin_plaza import PluginPlaza
from typing import Tuple, Optional, Dict, Any, List, Union # Added for type hints

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling) # type: ignore
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps) # type: ignore

today: dt.date = dt.date.today()
plugin_plaza: Optional[PluginPlaza] = None

plugin_dict: Dict[str, Any] = {}  # 插件字典
enabled_plugins: Dict[str, List[str]] = {}  # 启用的插件列表, e.g. {'enabled_plugins': ['plugin1', 'plugin2']}

morning_st: Union[int, Tuple[int, int]] = 0 # Stores (hour, minute) or 0 if not set
afternoon_st: Union[int, Tuple[int, int]] = 0 # Stores (hour, minute) or 0 if not set

current_week: int = 0 # Represents the current week being edited or viewed in UI (0-6 usually)

# schedule_center.schedule_data is Dict[str, Any] based on file.py
loaded_data: Dict[str, Any] = schedule_center.schedule_data # type: ignore

# schedule_dict stores processed schedule data, likely Dict[str, List[str]] where key is week day string ('0'-'6')
schedule_dict: Dict[str, List[str]] = {}  # 对应时间线的课程表
schedule_even_dict: Dict[str, List[str]] = {}  # 对应时间线的课程表（双周）

# timeline_dict stores timeline data, Dict[str (week_day_str or 'default'), List[str (item_description_str)]]
timeline_dict: Dict[str, List[str]] = {}  # 时间线字典

countdown_dict: Dict[str, str] = {} # Stores date strings (e.g. "YYYY-M-D") as keys and event text as values


def open_plaza() -> None: # Added return type
    global plugin_plaza
    if plugin_plaza is None or not plugin_plaza.isVisible():
        plugin_plaza = PluginPlaza()
        plugin_plaza.show()
        plugin_plaza.closed.connect(cleanup_plaza) # type: ignore[attr-defined] # Assuming closed is a signal
        logger.info('打开“插件广场”')
    else:
        plugin_plaza.raise_()
        plugin_plaza.activateWindow()


def cleanup_plaza() -> None: # Added return type
    global plugin_plaza
    logger.info('关闭“插件广场”')
    if plugin_plaza is not None: # Ensure it exists before deleting
        # plugin_plaza.deleteLater() # Prefer deleteLater for QObjects if PluginPlaza is one
        del plugin_plaza # Original code uses del
    plugin_plaza = None


def get_timeline() -> Dict[str, Any]: # Added return type
    global loaded_data
    loaded_data = schedule_center.schedule_data # type: ignore
    # Assuming loaded_data['timeline'] exists and is a dictionary
    return loaded_data.get('timeline', {})


def open_dir(path: str) -> None: # Added return type
    if sys.platform.startswith('win32'):
        os.startfile(path) # type: ignore[attr-defined]
    elif sys.platform.startswith('linux'):
        subprocess.run(['xdg-open', path])
    else: # macOS or other
        msg_box = Dialog(
            '无法打开文件夹', f'Class Widgets 在您的系统下不支持自动打开文件夹，请手动打开以下地址：\n{path}'
        )
        msg_box.yesButton.setText('好')
        msg_box.cancelButton.hide()
        if msg_box.buttonLayout is not None:
            msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()


def switch_checked(section: str, key: str, checked: bool) -> None: # Added types
    config_value: str = '1' if checked else '0'
    config_center.write_conf(section, key, config_value) # type: ignore[no-untyped-call]
    if key == 'auto_startup':
        if checked:
            conf.add_to_startup() # type: ignore[no-untyped-call]
        else:
            conf.remove_from_startup() # type: ignore[no-untyped-call]


def get_theme_name() -> str: # Added return type
    theme_val: Optional[str] = config_center.read_conf('General', 'theme') # type: ignore[no-untyped-call]
    # base_directory is Path object
    if theme_val and os.path.exists(Path(base_directory) / "ui" / theme_val / "theme.json"): # type: ignore[attr-defined]
        return theme_val
    else:
        return 'default'


def load_schedule_dict(schedule: Dict[str, List[str]], part: Dict[str, List[Union[int, str]]], part_name: Dict[str, str]) -> Dict[str, List[str]]: # Added types
    """
    加载课表字典
    """
    schedule_dict_: Dict[str, List[str]] = {}
    week_str: str
    item_list: List[str]
    for week_str, item_list in schedule.items(): # schedule is Dict[str, List[str]]
        all_class_for_week: List[str] = []
        # part is Dict[str, List[Union[int, str]]], len(part) gives number of parts
        count_per_part: List[int] = [0] * len(part) # Tracks lessons per part for indexing 'item_list'

        # Determine which timeline to use for this week_str
        current_timeline_for_week: Dict[str, Any] # Assuming timeline values are time in minutes (int or str)
        loaded_timeline_all: Dict[str, Any] = get_timeline() # Returns Dict[str, Any]
        if week_str in loaded_timeline_all and loaded_timeline_all[week_str]:
            current_timeline_for_week = loaded_timeline_all[week_str]
        else:
            current_timeline_for_week = loaded_timeline_all.get('default', {})

        timeline_item_name: str
        # timeline_item_time: Any # Value from timeline, usually int/str minutes
        for timeline_item_name, _ in current_timeline_for_week.items():
            if timeline_item_name.startswith('a'): # 'a' signifies a lesson/activity
                try:
                    part_index_str: str = timeline_item_name[1] # e.g., 'a01' -> '0'
                    # lesson_in_part_index_str: str = timeline_item_name[2:] # e.g., 'a01' -> '1' # Unused

                    part_index: int = int(part_index_str)
                    # lesson_in_part_num: int = int(lesson_in_part_index_str) # 1-based index from timeline name # Unused

                    num_a_items_processed = sum(1 for name in all_class_for_week if name != '未添加-' + part_name.get(str(part_index), ''))


                    prefix_lesson_name: str = item_list[num_a_items_processed]
                    period_display_name: str = part_name.get(str(part_index), f"P{part_index}")
                    all_class_for_week.append(f'{prefix_lesson_name}-{period_display_name}')

                except (IndexError, ValueError, KeyError) as e:
                    logger.warning(f"Error processing timeline item {timeline_item_name} for week {week_str}: {e}. Using placeholder.")
                    part_index_str_fallback: str = timeline_item_name[1] if len(timeline_item_name) > 1 else '?'
                    period_fallback_name: str = part_name.get(part_index_str_fallback, f"P{part_index_str_fallback}")
                    all_class_for_week.append(f'未添加-{period_fallback_name}')
        schedule_dict_[week_str] = all_class_for_week
    return schedule_dict_


def convert_to_dict(data_dict_: Dict[str, List[str]]) -> Dict[str, List[str]]: # Added types
    data_dict: Dict[str, List[str]] = {}
    week_str_cv: str
    item_list_cv: List[str]
    for week_str_cv, item_list_cv in data_dict_.items():
        replace_list: List[str] = []
        activity_description_str: str
        for activity_description_str in item_list_cv:
            item_info_parts: List[str] = activity_description_str.split('-')
            replace_list.append(item_info_parts[0])
        data_dict[str(week_str_cv)] = replace_list
    return data_dict


def se_load_item() -> None: # Added return type
    global schedule_dict, schedule_even_dict, loaded_data

    loaded_data = schedule_center.schedule_data # type: ignore[no-untyped-call]

    part_name_data: Dict[str, str] = loaded_data.get('part_name', {})
    part_data: Dict[str, List[Union[int, str]]] = loaded_data.get('part', {})
    schedule_data: Dict[str, List[str]] = loaded_data.get('schedule', {})
    schedule_even_data: Dict[str, List[str]] = loaded_data.get('schedule_even', {})

    schedule_dict = load_schedule_dict(schedule_data, part_data, part_name_data)
    schedule_even_dict = load_schedule_dict(schedule_even_data, part_data, part_name_data)


def cd_load_item() -> None: # Added return type
    global countdown_dict

    text_str: Optional[str] = config_center.read_conf('Date', 'cd_text_custom') # type: ignore[no-untyped-call]
    date_str: Optional[str] = config_center.read_conf('Date', 'countdown_date') # type: ignore[no-untyped-call]

    texts: List[str] = text_str.split(',') if text_str else []
    dates: List[str] = date_str.split(',') if date_str else []

    if len(texts) != len(dates):
        err_msg = f"len(cd_text_custom) (={len(texts)}) != len(countdown_date) (={len(dates)})"
        countdown_dict = {"Err": err_msg}
        logger.error(f"{err_msg} \n 请检查 config.ini [Date] 项！！")
        return

    countdown_dict = dict(zip(dates, texts))


class selectCity(MessageBoxBase):  # 选择城市
    def __init__(self, parent: Optional[QWidget] = None) -> None: # Added types
        super().__init__(parent)
        title_label: SubtitleLabel = SubtitleLabel()
        subtitle_label: BodyLabel = BodyLabel()
        self.search_edit: SearchLineEdit = SearchLineEdit()

        title_label.setText('搜索城市')
        subtitle_label.setText('请输入当地城市名进行搜索')
        self.yesButton.setText('选择此城市')
        self.cancelButton.setText('取消')

        self.search_edit.setPlaceholderText('输入城市名')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.search_city)

        self.city_list: ListWidget = ListWidget()
        self.city_list.addItems(wd.search_by_name('')) # type: ignore[no-untyped-call]
        self.get_selected_city()

        self.viewLayout.addWidget(title_label)
        self.viewLayout.addWidget(subtitle_label)
        self.viewLayout.addWidget(self.search_edit)
        self.viewLayout.addWidget(self.city_list)
        self.widget.setMinimumWidth(500)
        self.widget.setMinimumHeight(600)

    def search_city(self) -> None: # Added return type
        self.city_list.clear()
        self.city_list.addItems(wd.search_by_name(self.search_edit.text())) # type: ignore[no-untyped-call]
        self.city_list.clearSelection()

    def get_selected_city(self) -> None: # Added return type
        city_code_conf: Optional[str] = config_center.read_conf('Weather', 'city') # type: ignore[no-untyped-call]
        city_name_from_db: str = wd.search_by_num(str(city_code_conf)) # type: ignore[no-untyped-call]

        selected_city_items: List[QListWidgetItem] = self.city_list.findItems(
            city_name_from_db, QtCore.Qt.MatchFlag.MatchExactly # type: ignore[attr-defined]
        )
        if selected_city_items:
            item: QListWidgetItem = selected_city_items[0]
            self.city_list.setCurrentItem(item)
            self.city_list.scrollToItem(item)


class licenseDialog(MessageBoxBase):  # 显示软件许可协议
    def __init__(self, parent: Optional[QWidget] = None) -> None: # Added types
        super().__init__(parent)
        title_label: SubtitleLabel = SubtitleLabel()
        subtitle_label: BodyLabel = BodyLabel()
        self.license_text: PlainTextEdit = PlainTextEdit()

        title_label.setText('软件许可协议')
        subtitle_label.setText('此项目 (Class Widgets) 基于 GPL-3.0 许可证授权发布，详情请参阅：')
        self.yesButton.setText('好')
        self.cancelButton.hide()
        if self.buttonLayout is not None:
            self.buttonLayout.insertStretch(0, 1)
        self.license_text.setPlainText(open('LICENSE', 'r', encoding='utf-8').read())
        self.license_text.setReadOnly(True)

        self.viewLayout.addWidget(title_label)
        self.viewLayout.addWidget(subtitle_label)
        self.viewLayout.addWidget(self.license_text)
        self.widget.setMinimumWidth(600)
        self.widget.setMinimumHeight(500)


class PluginSettingsDialog(MessageBoxBase):  # 插件设置对话框
    def __init__(self, plugin_dir: Optional[str] = None, parent: Optional[QWidget] = None) -> None: # Added types
        super().__init__(parent)
        self.plugin_widget: Optional[QWidget] = None
        self.plugin_dir: Optional[str] = plugin_dir
        self.parent: Optional[QWidget] = parent
        self.init_ui()

    def init_ui(self) -> None: # Added return type
        if self.plugin_dir and self.plugin_dir in p_loader.plugins_settings: # type: ignore[attr-defined]
            self.plugin_widget = p_loader.plugins_settings[self.plugin_dir] # type: ignore[attr-defined]
            self.viewLayout.addWidget(self.plugin_widget)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)

        self.cancelButton.hide()
        if self.buttonLayout is not None:
            self.buttonLayout.insertStretch(0, 1)

        self.widget.setMinimumWidth(875)
        self.widget.setMinimumHeight(625)


class PluginCard(CardWidget):  # 插件卡片
    def __init__(
            self,
            icon: Union[str, QIcon],
            title: str = 'Unknown',
            content: str = 'Unknown',
            version: str = '1.0.0',
            plugin_dir: str = '',
            author: Optional[str] = None,
            parent: Optional[QWidget] = None,
            enable_settings: Optional[bool] = None
    ) -> None: # Added types
        super().__init__(parent)
        icon_radius: int = 5
        self.plugin_dir: str = plugin_dir
        self.title: str = title
        self.parent_widget: Optional[QWidget] = parent

        self.iconWidget: ImageLabel = ImageLabel(icon)
        self.titleLabel: StrongBodyLabel = StrongBodyLabel(title, self)
        self.versionLabel: BodyLabel = BodyLabel(version, self)
        self.authorLabel: BodyLabel = BodyLabel(author if author else "未知作者", self)
        self.contentLabel: CaptionLabel = CaptionLabel(content, self)
        self.enableButton: SwitchButton = SwitchButton()
        self.moreButton: TransparentDropDownToolButton = TransparentDropDownToolButton()
        self.moreMenu: RoundMenu = RoundMenu(parent=self.moreButton)
        self.settingsBtn: TransparentToolButton = TransparentToolButton()
        self.settingsBtn.hide()

        self.hBoxLayout: QHBoxLayout = QHBoxLayout(self)
        self.hBoxLayout_Title: QHBoxLayout = QHBoxLayout()
        self.vBoxLayout: QVBoxLayout = QVBoxLayout()

        plugin_full_path = os.path.join(str(base_directory), str(conf.PLUGINS_DIR), self.plugin_dir) # type: ignore[attr-defined]

        self.moreMenu.addActions([
            Action(
                fIcon.FOLDER, f'打开“{title}”插件文件夹', # type: ignore[attr-defined]
                triggered=lambda: open_dir(plugin_full_path)
            ),
            Action(
                fIcon.DELETE, f'卸载“{title}”插件', # type: ignore[attr-defined]
                triggered=self.remove_plugin
            )
        ])
        if plugin_dir and plugin_dir in enabled_plugins.get('enabled_plugins', []):
            self.enableButton.setChecked(True)
            if enable_settings:
                self.moreMenu.addSeparator()
                self.moreMenu.addAction(Action(fIcon.SETTING, f'“{title}”插件设置', triggered=self.show_settings)) # type: ignore[attr-defined]
                self.settingsBtn.show()

        self.setFixedHeight(73)
        self.iconWidget.setFixedSize(48, 48)
        self.moreButton.setFixedSize(34, 34)
        self.iconWidget.setBorderRadius(icon_radius, icon_radius, icon_radius, icon_radius)
        self.contentLabel.setTextColor(QColor("#606060"), QColor("#d2d2d2"))
        self.contentLabel.setMaximumWidth(500)
        self.contentLabel.setWordWrap(True)
        self.versionLabel.setTextColor(QColor("#999999"), QColor("#999999"))
        self.authorLabel.setTextColor(QColor("#606060"), QColor("#d2d2d2"))
        self.enableButton.checkedChanged.connect(self.set_enable)
        self.enableButton.setOffText('禁用')
        self.enableButton.setOnText('启用')
        self.moreButton.setMenu(self.moreMenu)
        self.settingsBtn.setIcon(fIcon.SETTING) # type: ignore[attr-defined]
        self.settingsBtn.clicked.connect(self.show_settings)

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addLayout(self.hBoxLayout_Title)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignmentFlag.AlignVCenter) # type: ignore[attr-defined]
        self.vBoxLayout.setAlignment(Qt.AlignmentFlag.AlignVCenter) # type: ignore[attr-defined]
        self.hBoxLayout.addLayout(self.vBoxLayout, 1)

        self.hBoxLayout_Title.setSpacing(12)
        self.hBoxLayout_Title.setAlignment(Qt.AlignmentFlag.AlignLeft) # type: ignore[attr-defined]
        self.hBoxLayout_Title.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter) # type: ignore[attr-defined]
        self.hBoxLayout_Title.addWidget(self.authorLabel, 0, Qt.AlignmentFlag.AlignVCenter) # type: ignore[attr-defined]
        self.hBoxLayout_Title.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignVCenter) # type: ignore[attr-defined]

        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.settingsBtn, 0, Qt.AlignmentFlag.AlignRight) # type: ignore[attr-defined]
        self.hBoxLayout.addWidget(self.enableButton, 0, Qt.AlignmentFlag.AlignRight) # type: ignore[attr-defined]
        self.hBoxLayout.addWidget(self.moreButton, 0, Qt.AlignmentFlag.AlignRight) # type: ignore[attr-defined]

    def set_enable(self) -> None: # Added return type
        global enabled_plugins
        if 'enabled_plugins' not in enabled_plugins:
            enabled_plugins['enabled_plugins'] = []

        if self.enableButton.isChecked():
            if self.plugin_dir not in enabled_plugins['enabled_plugins']:
                enabled_plugins['enabled_plugins'].append(self.plugin_dir)
        else:
            if self.plugin_dir in enabled_plugins['enabled_plugins']:
                enabled_plugins['enabled_plugins'].remove(self.plugin_dir)
        conf.save_plugin_config(enabled_plugins) # type: ignore[no-untyped-call]

    def show_settings(self) -> None: # Added return type
        w = PluginSettingsDialog(self.plugin_dir, self.parent_widget)
        w.exec()

    def remove_plugin(self) -> None: # Added return type
        alert = MessageBox(f"您确定要删除插件“{self.title}”吗？", "删除此插件后，将无法恢复。", self.parent_widget)
        alert.yesButton.setText('永久删除')
        alert.yesButton.setStyleSheet("""
                PushButton{
                    border-radius: 5px;
                    padding: 5px 12px 6px 12px;
                    outline: none;
                }
                PrimaryPushButton{
                    color: white;
                    background-color: #FF6167;
                    border: 1px solid #FF8585;
                    border-bottom: 1px solid #943333;
                }
                PrimaryPushButton:hover{
                    background-color: #FF7E83;
                    border: 1px solid #FF8084;
                    border-bottom: 1px solid #B13939;
                }
                PrimaryPushButton:pressed{
                    color: rgba(255, 255, 255, 0.63);
                    background-color: #DB5359;
                    border: 1px solid #DB5359;
                }
            """)
        alert.cancelButton.setText('我再想想……')
        if alert.exec():
            success: bool = p_loader.delete_plugin(self.plugin_dir) # type: ignore[attr-defined]
            if success:
                try:
                    plugins_json_path = Path(base_directory) / "plugins" / "plugins_from_pp.json" # type: ignore[attr-defined]
                    installed_data: Dict[str, Any] = {}
                    if plugins_json_path.exists():
                        with open(plugins_json_path, 'r', encoding='utf-8') as f:
                            installed_data = json.load(f)

                    installed_plugins: List[str] = installed_data.get('plugins', [])
                    if self.plugin_dir in installed_plugins:
                        installed_plugins.remove(self.plugin_dir)
                        conf.save_installed_plugin(installed_plugins) # type: ignore[no-untyped-call]
                except Exception as e:
                    logger.error(f"更新已安装插件列表失败: {e}")

                InfoBar.success( # type: ignore[no-untyped-call]
                    title='卸载成功',
                    content=f'插件 “{self.title}” 已卸载。请重启 Class Widgets 以完全移除。',
                    orient=Qt.Horizontal, # type: ignore[attr-defined]
                    isClosable=True,
                    position=InfoBarPosition.BOTTOM_RIGHT, # type: ignore[attr-defined]
                    duration=5000,
                    parent=self.window()
                )
                self.deleteLater()
            else:
                InfoBar.error( # type: ignore[no-untyped-call]
                    title='卸载失败',
                    content=f'卸载插件 “{self.title}” 时出错，请查看日志获取详细信息。',
                    orient=Qt.Horizontal, # type: ignore[attr-defined]
                    isClosable=True,
                    position=InfoBarPosition.BOTTOM_RIGHT, # type: ignore[attr-defined]
                    duration=5000,
                    parent=self.window()
                )


class TextFieldMessageBox(MessageBoxBase):
    """ Custom message box """

    def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = '标题',
            text: str = '请输入内容',
            default_text: str = '',
            enable_check: Union[bool, List[str]] = False
    ) -> None: # Added types
        super().__init__(parent)
        self.fail_color: Tuple[QColor, QColor] = (QColor('#c42b1c'), QColor('#ff99a4'))
        self.success_color: Tuple[QColor, QColor] = (QColor('#0f7b0f'), QColor('#6ccb5f'))
        self.check_list: Union[bool, List[str]] = enable_check

        self.titleLabel: SubtitleLabel = SubtitleLabel()
        self.titleLabel.setText(title)
        self.subtitleLabel: BodyLabel = BodyLabel()
        self.subtitleLabel.setText(text)
        self.textField: LineEdit = LineEdit()
        self.tipsLabel: CaptionLabel = CaptionLabel()
        self.tipsLabel.setText('')
        self.yesButton.setText('确定')

        self.fieldLayout: QVBoxLayout = QVBoxLayout()
        self.textField.setPlaceholderText(default_text)
        self.textField.setClearButtonEnabled(True)
        if enable_check:
            self.textField.textChanged.connect(self.check_text)
            self.yesButton.setEnabled(False)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.subtitleLabel)
        self.viewLayout.addLayout(self.fieldLayout)
        self.fieldLayout.addWidget(self.textField)
        self.fieldLayout.addWidget(self.tipsLabel)

        self.widget.setMinimumWidth(350)

    def check_text(self) -> None: # Added return type
        self.tipsLabel.setTextColor(self.fail_color[0], self.fail_color[1])
        self.yesButton.setEnabled(False)
        current_text: str = self.textField.text()
        if not current_text:
            self.tipsLabel.setText('不能为空值啊 ( •̀ ω •́ )✧')
            return

        if isinstance(self.check_list, list):
            if f'{current_text}.json' in self.check_list:
                self.tipsLabel.setText('不可以和之前的课程名重复哦 o(TヘTo)')
                return

        self.yesButton.setEnabled(True)
        self.tipsLabel.setTextColor(self.success_color[0], self.success_color[1])
        self.tipsLabel.setText('很好！就这样！ヾ(≧▽≦*)o')


class TTSVoiceLoaderThread(QThread):
    voicesLoaded = pyqtSignal(list) # pyqtSignal(List[Dict[str, str]])
    errorOccurred = pyqtSignal(str)
    previewFinished = pyqtSignal(bool) # This signal seems unused in this thread, maybe for other purposes

    def __init__(self, engine_filter: Optional[str] = None, parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self.engine_filter: Optional[str] = engine_filter

    def run(self) -> None: # Added return type
        try:
            if self.isInterruptionRequested():
                return

            if self.engine_filter == "pyttsx3" and platform.system() != "Windows":
                logger.warning("当前系统不是Windows,跳过pyttsx3语音加载")
                self.voicesLoaded.emit([]) # Emit empty list
                return

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            available_voices: List[Dict[str, str]]
            error_message: Optional[str]
            available_voices, error_message = loop.run_until_complete(
                get_tts_voices(engine_filter=self.engine_filter) # type: ignore[no-untyped-call]
            )
            loop.close()

            if self.isInterruptionRequested():
                return

            if error_message:
                self.errorOccurred.emit(error_message)
            else:
                self.voicesLoaded.emit(available_voices)
        except Exception as e:
            logger.error(f"加载TTS语音列表时出错: {e}")
            self.errorOccurred.emit(str(e))


class TTSPreviewThread(QThread):
    previewFinished = pyqtSignal(bool)
    previewError = pyqtSignal(str)

    def __init__(self, text: str, engine: str, voice: Optional[str], parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self.text: str = text
        self.engine: str = engine
        self.voice: Optional[str] = voice

    def run(self) -> None: # Added return type
        try:
            if self.engine == "pyttsx3" and platform.system() != "Windows":
                logger.warning("当前系统不是Windows，跳过pyttsx3 TTS预览。")
                self.previewFinished.emit(False)
                return
            if self.isInterruptionRequested():
                logger.info("TTS预览线程收到中断请求，正在退出...")
                return

            from generate_speech import generate_speech_sync, TTSEngine # TTSEngine is a class
            from play_audio import play_audio # play_audio is a function

            logger.info(f"使用引擎 {self.engine} 生成预览语音")
            audio_file: str = generate_speech_sync( # type: ignore[no-untyped-call]
                text=self.text,
                engine=self.engine,
                voice=self.voice,
                auto_fallback=True,
                timeout=10.0
            )

            if self.isInterruptionRequested():
                logger.info("TTS预览线程收到中断请求，正在退出...")
                if os.path.exists(audio_file):
                    TTSEngine.delete_audio_file(audio_file)
                return

            if not os.path.exists(audio_file):
                raise FileNotFoundError(f"生成的音频文件不存在: {audio_file}")

            file_size: int = os.path.getsize(audio_file)
            if file_size < 10:
                logger.warning(f"生成的音频文件可能无效，大小仅为 {file_size} 字节: {audio_file}")
                if os.path.exists(audio_file):
                    TTSEngine.delete_audio_file(audio_file)
                raise ValueError(f"生成的音频文件可能无效，大小仅为 {file_size} 字节")

            play_audio(audio_file, tts_delete_after=True) # type: ignore[no-untyped-call]
            self.previewFinished.emit(True)
        except Exception as e:
            logger.error(f"TTS预览生成失败: {str(e)}")
            self.previewError.emit(str(e))


class SettingsMenu(FluentWindow):
    closed = pyqtSignal()

    def __init__(self) -> None: # Added return type
        super().__init__()
        self.tts_voice_loader_thread: Optional[TTSVoiceLoaderThread] = None
        self.button_clear_log: Optional[PushButton] = None
        self.version_thread: Optional[VersionThread] = None
        self.engine_selector: Optional[ComboBox] = None
        self.current_loaded_engine: Optional[str] = config_center.read_conf('TTS', 'engine') # type: ignore[no-untyped-call]
        self.TTSSettingsDialog: Optional[SettingsMenu.TTSSettings] = None
        self.available_voices: Optional[List[Dict[str,str]]] = None
        self.voice_selector: Optional[ComboBox] = None
        self.switch_enable_TTS: Optional[SwitchButton] = None
        self.engine_note_label: Optional[HyperlinkLabel] = None

        self.spInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/preview.ui') # type: ignore[attr-defined]
        self.spInterface.setObjectName("spInterface")
        self.teInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/timeline_edit.ui') # type: ignore[attr-defined]
        self.teInterface.setObjectName("teInterface")
        self.seInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/schedule_edit.ui') # type: ignore[attr-defined]
        self.seInterface.setObjectName("seInterface")
        self.cdInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/countdown_custom_edit.ui') # type: ignore[attr-defined]
        self.cdInterface.setObjectName("cdInterface")
        self.adInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/advance.ui') # type: ignore[attr-defined]
        self.adInterface.setObjectName("adInterface")
        self.ifInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/about.ui') # type: ignore[attr-defined]
        self.ifInterface.setObjectName("ifInterface")
        self.ctInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/custom.ui') # type: ignore[attr-defined]
        self.ctInterface.setObjectName("ctInterface")
        self.cfInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/configs.ui') # type: ignore[attr-defined]
        self.cfInterface.setObjectName("cfInterface")
        self.sdInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/sound.ui') # type: ignore[attr-defined]
        self.sdInterface.setObjectName("sdInterface")
        self.hdInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/help.ui') # type: ignore[attr-defined]
        self.hdInterface.setObjectName("hdInterface")
        self.plInterface: QWidget = uic.loadUi(f'{base_directory}/view/menu/plugin_mgr.ui') # type: ignore[attr-defined]
        self.plInterface.setObjectName("plInterface")

        self.version_number_label: Optional[QLabel] = self.ifInterface.findChild(QLabel, 'version_number_label')
        self.build_commit_label: Optional[QLabel] = self.ifInterface.findChild(QLabel, 'build_commit_label')
        self.build_uuid_label: Optional[QLabel] = self.ifInterface.findChild(QLabel, 'build_uuid_label')
        self.build_date_label: Optional[QLabel] = self.ifInterface.findChild(QLabel, 'build_date_label')
        self.conf_combo: Optional[ComboBox] = None
        self.version_channel: Optional[ComboBox] = None
        self.auto_check_update: Optional[SwitchButton] = None
        self.version: Optional[BodyLabel] = None


        self.init_nav()
        self.init_window()

    def init_font(self) -> None:  # 设置字体. Added return type
        self.setStyleSheet("""QLabel {
                    font-family: 'Microsoft YaHei';
                }""")

    def load_all_item(self) -> None: # Added return type
        self.setup_timeline_edit()
        self.setup_schedule_edit()
        self.setup_schedule_preview()
        self.setup_advance_interface()
        self.setup_about_interface()
        self.setup_customization_interface()
        self.setup_configs_interface()
        self.setup_sound_interface()
        self.setup_help_interface()
        self.setup_plugin_mgr_interface()
        self.setup_countdown_edit()

    # 初始化界面
    def setup_plugin_mgr_interface(self) -> None: # Added return type
        pm_scroll: Optional[SmoothScrollArea] = self.findChild(SmoothScrollArea, 'pm_scroll')
        if pm_scroll and pm_scroll.viewport():
            QScroller.grabGesture(pm_scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture) # type: ignore[attr-defined]

        global plugin_dict, enabled_plugins
        enabled_plugins = conf.load_plugin_config() # type: ignore[no-untyped-call]
        plugin_dict = conf.load_plugins() # type: ignore[no-untyped-call]

        open_pp: Optional[PushButton] = self.findChild(PushButton, 'open_plugin_plaza')
        if open_pp: open_pp.clicked.connect(open_plaza)

        open_pp2: Optional[PushButton] = self.findChild(PushButton, 'open_plugin_plaza_2')
        if open_pp2: open_pp2.clicked.connect(open_plaza)

        auto_delay_spinbox: Optional[SpinBox] = self.findChild(SpinBox, 'auto_delay')
        if auto_delay_spinbox:
            auto_delay_val: Optional[str] = config_center.read_conf('Plugin', 'auto_delay') # type: ignore[no-untyped-call]
            auto_delay_spinbox.setValue(int(auto_delay_val) if auto_delay_val and auto_delay_val.isdigit() else 0)
            auto_delay_spinbox.valueChanged.connect(
                lambda val: config_center.write_conf('Plugin', 'auto_delay', str(val))) # type: ignore[no-untyped-call]

        plugin_card_layout: Optional[QVBoxLayout] = self.findChild(QVBoxLayout, 'plugin_card_layout')
        open_plugin_folder_btn: Optional[PushButton] = self.findChild(PushButton, 'open_plugin_folder')
        if open_plugin_folder_btn:
            plugins_dir_path = os.path.join(str(base_directory), str(conf.PLUGINS_DIR)) # type: ignore[attr-defined]
            open_plugin_folder_btn.clicked.connect(lambda: open_dir(plugins_dir_path))

        if p_loader and not p_loader.plugins_settings: # type: ignore[attr-defined]
            p_loader.load_plugins() # type: ignore[attr-defined]

        if plugin_card_layout:
            while plugin_card_layout.count():
                child = plugin_card_layout.takeAt(0)
                if child and child.widget():
                    child.widget().deleteLater()

            plugin_name_key: str
            plugin_info: Dict[str, Any]
            for plugin_name_key, plugin_info in plugin_dict.items():
                icon_path_str: str
                icon_file_path = Path(base_directory) / conf.PLUGINS_DIR / plugin_name_key / 'icon.png' # type: ignore[attr-defined]
                if icon_file_path.exists():
                    icon_path_str = str(icon_file_path)
                else:
                    icon_path_str = str(Path(base_directory) / 'img' / 'settings' / 'plugin-icon.png') # type: ignore[attr-defined]

                card = PluginCard(
                    icon=icon_path_str,
                    title=plugin_info.get('name', 'Unknown'),
                    version=plugin_info.get('version', '1.0.0'),
                    author=plugin_info.get('author'),
                    plugin_dir=plugin_name_key,
                    content=plugin_info.get('description', 'N/A'),
                    enable_settings=plugin_info.get('settings', False),
                    parent=self
                )
                plugin_card_layout.addWidget(card)

        tips_plugin_empty_label: Optional[QLabel] = self.findChild(QLabel, 'tips_plugin_empty')
        if tips_plugin_empty_label:
            tips_plugin_empty_label.setVisible(not bool(plugin_dict))


    def setup_help_interface(self) -> None: # Added return type
        open_by_browser: Optional[PushButton] = self.findChild(PushButton, 'open_by_browser')
        if open_by_browser:
            open_by_browser.setIcon(fIcon.LINK) # type: ignore[attr-defined]
            open_by_browser.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
                'https://classwidgets.rinlit.cn/docs-user/'
            )))

    def setup_sound_interface(self) -> None: # Added return type
        sd_scroll: Optional[SmoothScrollArea] = self.findChild(SmoothScrollArea, 'sd_scroll')
        if sd_scroll and sd_scroll.viewport():
            QScroller.grabGesture(sd_scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture) # type: ignore[attr-defined]

        switch_enable_toast: Optional[SwitchButton] = self.findChild(SwitchButton, 'switch_enable_attend')
        if switch_enable_toast:
            attend_toast_conf: Optional[str] = config_center.read_conf('Toast', 'attend_class') # type: ignore[no-untyped-call]
            switch_enable_toast.setChecked(bool(int(attend_toast_conf)) if attend_toast_conf and attend_toast_conf.isdigit() else False)
            switch_enable_toast.checkedChanged.connect(lambda checked: switch_checked('Toast', 'attend_class', checked))

        switch_enable_finish: Optional[SwitchButton] = self.findChild(SwitchButton, 'switch_enable_finish')
        if switch_enable_finish:
            finish_toast_conf: Optional[str] = config_center.read_conf('Toast', 'finish_class') # type: ignore[no-untyped-call]
            switch_enable_finish.setChecked(bool(int(finish_toast_conf)) if finish_toast_conf and finish_toast_conf.isdigit() else False)
            switch_enable_finish.checkedChanged.connect(lambda checked: switch_checked('Toast', 'finish_class', checked))

        switch_enable_schoolout: Optional[SwitchButton] = self.findChild(SwitchButton, 'switch_enable_schoolout')
        if switch_enable_schoolout:
            after_school_conf: Optional[str] = config_center.read_conf('Toast', 'after_school') # type: ignore[no-untyped-call]
            switch_enable_schoolout.setChecked(bool(int(after_school_conf)) if after_school_conf and after_school_conf.isdigit() else False)
            switch_enable_schoolout.checkedChanged.connect(lambda checked: switch_checked('Toast', 'after_school', checked))

        switch_enable_prepare: Optional[SwitchButton] = self.findChild(SwitchButton, 'switch_enable_prepare')
        if switch_enable_prepare:
            prepare_toast_conf: Optional[str] = config_center.read_conf('Toast', 'prepare_class') # type: ignore[no-untyped-call]
            switch_enable_prepare.setChecked(bool(int(prepare_toast_conf)) if prepare_toast_conf and prepare_toast_conf.isdigit() else False)
            switch_enable_prepare.checkedChanged.connect(lambda checked: switch_checked('Toast', 'prepare_class', checked))

        switch_enable_pin_toast: Optional[SwitchButton] = self.findChild(SwitchButton, 'switch_enable_pin_toast')
        if switch_enable_pin_toast:
            pin_toast_conf: Optional[str] = config_center.read_conf('Toast', 'pin_on_top') # type: ignore[no-untyped-call]
            switch_enable_pin_toast.setChecked(bool(int(pin_toast_conf)) if pin_toast_conf and pin_toast_conf.isdigit() else False)
            switch_enable_pin_toast.checkedChanged.connect(lambda checked: switch_checked('Toast', 'pin_on_top', checked))

        slider_volume: Optional[Slider] = self.findChild(Slider, 'slider_volume')
        if slider_volume:
            volume_conf: Optional[str] = config_center.read_conf('Audio', 'volume') # type: ignore[no-untyped-call]
            slider_volume.setValue(int(volume_conf) if volume_conf and volume_conf.isdigit() else 100)
            slider_volume.valueChanged.connect(self.save_volume)

        preview_toast_button: Optional[PrimaryDropDownPushButton] = self.findChild(PrimaryDropDownPushButton, 'preview')
        if preview_toast_button:
            pre_toast_menu = RoundMenu(parent=preview_toast_button)
            pre_toast_menu.addActions([
                Action(fIcon.EDUCATION, '上课提醒', # type: ignore[attr-defined]
                       triggered=lambda: tip_toast.push_notification(1, lesson_name='信息技术')), # type: ignore[no-untyped-call]
                Action(fIcon.CAFE, '下课提醒', # type: ignore[attr-defined]
                       triggered=lambda: tip_toast.push_notification(0, lesson_name='信息技术')), # type: ignore[no-untyped-call]
                Action(fIcon.BOOK_SHELF, '预备提醒', # type: ignore[attr-defined]
                       triggered=lambda: tip_toast.push_notification(3, lesson_name='信息技术')), # type: ignore[no-untyped-call]
                Action(fIcon.CODE, '其他提醒', # type: ignore[attr-defined]
                       triggered=lambda: tip_toast.push_notification(4, title='通知', subtitle='测试通知示例', # type: ignore[no-untyped-call]
                                                                     content='这是一条测试通知ヾ(≧▽≦*)o'))
            ])
            preview_toast_button.setMenu(pre_toast_menu)

        switch_wave_effect: Optional[SwitchButton] = self.findChild(SwitchButton, 'switch_enable_wave')
        if switch_wave_effect:
            wave_conf: Optional[str] = config_center.read_conf('Toast', 'wave') # type: ignore[no-untyped-call]
            switch_wave_effect.setChecked(bool(int(wave_conf)) if wave_conf and wave_conf.isdigit() else False)
            switch_wave_effect.checkedChanged.connect(lambda checked: switch_checked('Toast', 'wave', checked))

        spin_prepare_time: Optional[SpinBox] = self.findChild(SpinBox, 'spin_prepare_class')
        if spin_prepare_time:
            prepare_min_conf: Optional[str] = config_center.read_conf('Toast', 'prepare_minutes') # type: ignore[no-untyped-call]
            spin_prepare_time.setValue(int(prepare_min_conf) if prepare_min_conf and prepare_min_conf.isdigit() else 0)
            spin_prepare_time.valueChanged.connect(self.save_prepare_time)

        tts_settings_btn: Optional[PushButton] = self.findChild(PushButton, 'TTS_PushButton')
        if tts_settings_btn:
            tts_settings_btn.clicked.connect(self.open_tts_settings)

    def available_voices_cnt(self, voices: List[Dict[str, str]]) -> None: # Added types
        self.available_voices = voices
        if hasattr(self, 'voice_selector') and self.voice_selector and \
           hasattr(self, 'update_tts_voices') and \
           self.TTSSettingsDialog and not self.TTSSettingsDialog.isHidden():
            self.update_tts_voices(self.available_voices) # type: ignore[no-untyped-call]

        if self.switch_enable_TTS: self.switch_enable_TTS.setEnabled(bool(voices))
        if self.voice_selector: self.voice_selector.setEnabled(bool(voices))

    class TTSSettings(MessageBoxBase): # TTS设置页
        tts_preview_thread_instance: Optional[TTSPreviewThread] = None # Class attribute to hold the thread

        def __init__(self, parent: Optional['SettingsMenu'] = None) -> None: # Added types. parent is SettingsMenu
            super().__init__(parent)
            self.parent_menu: Optional['SettingsMenu'] = parent
            self.temp_widget: QWidget = QWidget()
            ui_path: str = str(Path(base_directory) / 'view' / 'menu' / 'tts_settings.ui') # type: ignore[attr-defined]
            uic.loadUi(ui_path, self.temp_widget)
            self.viewLayout.addWidget(self.temp_widget)

            self.viewLayout.setContentsMargins(0, 0, 0, 0)
            self.cancelButton.hide()
            if parent:
                self.widget.setMinimumWidth(parent.width()//3*2)
                self.widget.setMinimumHeight(parent.height())

            switch_enable_TTS_child: Optional[SwitchButton] = self.widget.findChild(SwitchButton, 'switch_enable_tts')
            slider_speed_tts: Optional[Slider] = self.widget.findChild(Slider, 'slider_tts_speed')

            tts_enabled_conf: Optional[str] = config_center.read_conf('TTS', 'enable') # type: ignore[no-untyped-call]
            tts_enabled: bool = bool(int(tts_enabled_conf)) if tts_enabled_conf and tts_enabled_conf.isdigit() else False

            if switch_enable_TTS_child:
                switch_enable_TTS_child.setChecked(tts_enabled)
                if parent: switch_enable_TTS_child.checkedChanged.connect(parent.toggle_tts_settings)

            if slider_speed_tts:
                speed_conf: Optional[str] = config_center.read_conf('TTS', 'speed') # type: ignore[no-untyped-call]
                slider_speed_tts.setValue(int(speed_conf) if speed_conf and speed_conf.isdigit() else 100)
                if parent: slider_speed_tts.valueChanged.connect(parent.save_tts_speed)

            voice_selector_child: Optional[ComboBox] = self.widget.findChild(ComboBox, 'voice_selector')
            if voice_selector_child:
                voice_selector_child.clear()
                voice_selector_child.addItem("加载中...", userData=None)
                voice_selector_child.setEnabled(False)
            if switch_enable_TTS_child: switch_enable_TTS_child.setEnabled(False)

            if parent:
                parent.engine_selector = self.widget.findChild(ComboBox, 'engine_selector')
                if not parent.engine_selector:
                    parent.engine_selector = ComboBox(self.widget)
                parent.populate_tts_engines()
                if parent.engine_selector:
                    parent.engine_selector.currentTextChanged.connect(parent.on_engine_selected)

                parent.engine_note_label = self.widget.findChild(HyperlinkLabel, 'engine_note')
                if parent.engine_note_label:
                    parent.engine_note_label.clicked.connect(parent.show_engine_note)

                parent.voice_selector = voice_selector_child
                parent.switch_enable_TTS = switch_enable_TTS_child

            self.tts_vocab_button: Optional[PushButton] = self.widget.findChild(PushButton, 'tts_vocab_button')

            def show_vocab_note() -> None:
                mb_parent = self.parent_menu if self.parent_menu and isinstance(self.parent_menu, QWidget) else self
                w = MessageBox('小语法?',
                               '可以使用以下占位符来动态插入信息：\n'\
                               '- `{lesson_name}`: 开始&结束&下节的课程名(例如：信息技术)\n'\
                               '- `{minutes}`: 分钟数 (例如：5) *其他\n'\
                               '- `{title}`: 通知标题 (例如：重要通知) *其他\n'\
                               '- `{content}`: 通知内容 (例如：这是一条测试通知) *其他\n',
                               mb_parent)
                w.cancelButton.hide()
                w.exec()
            if self.tts_vocab_button: self.tts_vocab_button.clicked.connect(show_vocab_note)

            if parent and parent.available_voices is not None and \
               parent.engine_selector and parent.current_loaded_engine == parent.engine_selector.currentData():
                parent.update_tts_voices(parent.available_voices) # type: ignore[no-untyped-call]
            elif voice_selector_child:
                voice_selector_child.clear()
                voice_selector_child.addItem("加载中...", userData=None)
                voice_selector_child.setEnabled(False)

            text_attend_class_le: Optional[LineEdit] = self.widget.findChild(LineEdit, 'text_attend_class')
            if text_attend_class_le:
                text_attend_class_le.setText(config_center.read_conf('TTS', 'attend_class')) # type: ignore[no-untyped-call]
                text_attend_class_le.textChanged.connect(lambda text: config_center.write_conf('TTS', 'attend_class', text)) # type: ignore[no-untyped-call]

            text_prepare_class_le: Optional[LineEdit] = self.widget.findChild(LineEdit, 'text_prepare_class')
            if text_prepare_class_le:
                text_prepare_class_le.setText(config_center.read_conf('TTS', 'prepare_class')) # type: ignore[no-untyped-call]
                text_prepare_class_le.textChanged.connect(lambda text: config_center.write_conf('TTS', 'prepare_class', text)) # type: ignore[no-untyped-call]

            text_finish_class_le: Optional[LineEdit] = self.widget.findChild(LineEdit, 'text_finish_class')
            if text_finish_class_le:
                text_finish_class_le.setText(config_center.read_conf('TTS', 'finish_class')) # type: ignore[no-untyped-call]
                text_finish_class_le.textChanged.connect(lambda text: config_center.write_conf('TTS', 'finish_class', text)) # type: ignore[no-untyped-call]

            text_after_school_le: Optional[LineEdit] = self.widget.findChild(LineEdit, 'text_after_school')
            if text_after_school_le:
                text_after_school_le.setText(config_center.read_conf('TTS', 'after_school')) # type: ignore[no-untyped-call]
                text_after_school_le.textChanged.connect(lambda text: config_center.write_conf('TTS', 'after_school', text)) # type: ignore[no-untyped-call]

            text_notification_le: Optional[LineEdit] = self.widget.findChild(LineEdit, 'text_notification')
            if text_notification_le:
                text_notification_le.setText(config_center.read_conf('TTS', 'otherwise')) # type: ignore[no-untyped-call]
                text_notification_le.textChanged.connect(lambda text: config_center.write_conf('TTS', 'otherwise', text)) # type: ignore[no-untyped-call]

            preview_tts_button: Optional[PrimaryDropDownPushButton] = self.widget.findChild(PrimaryDropDownPushButton, 'preview')
            if preview_tts_button:
                preview_tts_menu = RoundMenu(parent=preview_tts_button)
                preview_tts_menu.addActions([
                    Action(fIcon.EDUCATION, '上课提醒', triggered=lambda: self.play_tts_preview('attend_class')), # type: ignore[attr-defined]
                    Action(fIcon.CAFE, '下课提醒', triggered=lambda: self.play_tts_preview('finish_class')), # type: ignore[attr-defined]
                    Action(fIcon.BOOK_SHELF, '预备提醒', triggered=lambda: self.play_tts_preview('prepare_class')), # type: ignore[attr-defined]
                    Action(fIcon.EMBED, '放学提醒', triggered=lambda: self.play_tts_preview('after_school')), # type: ignore[attr-defined]
                    Action(fIcon.CODE, '其他提醒', triggered=lambda: self.play_tts_preview('otherwise')) # type: ignore[attr-defined]
                ])
                preview_tts_button.setMenu(preview_tts_menu)

        def play_tts_preview(self, text_type: str) -> None:
            text_template: Optional[str] = config_center.read_conf('TTS', text_type) # type: ignore[no-untyped-call]
            if text_template is None:
                logger.warning(f"TTS template for '{text_type}' not found.")
                return

            from collections import defaultdict
            format_values = defaultdict(str, {
                'lesson_name': '信息技术',
                'minutes': '5',
                'title': '通知',
                'content': '这是一条测试通知ヾ(≧▽≦*)o'
            })
            text_to_speak: str = text_template.format_map(format_values)

            logger.debug(f"生成TTS文本: {text_to_speak}")

            try:
                current_engine: Optional[str] = None
                current_voice: Optional[str] = None
                if self.parent_menu and self.parent_menu.engine_selector:
                    current_engine = self.parent_menu.engine_selector.currentData()
                if self.parent_menu and self.parent_menu.voice_selector and self.parent_menu.voice_selector.currentData():
                    current_voice = self.parent_menu.voice_selector.currentData()

                if current_engine is None:
                    logger.error("TTS引擎未选择，无法预览。")
                    self.handle_tts_preview_error("TTS引擎未选择。")
                    return

                if self.parent_menu:
                    # Stop previous thread if running
                    if hasattr(self.parent_menu, 'tts_preview_thread_instance') and \
                       self.parent_menu.tts_preview_thread_instance and \
                       self.parent_menu.tts_preview_thread_instance.isRunning():
                        self.parent_menu.tts_preview_thread_instance.requestInterruption()
                        self.parent_menu.tts_preview_thread_instance.quit()
                        if not self.parent_menu.tts_preview_thread_instance.wait(1000):
                            logger.warning("旧TTS预览线程未能在超时时间内退出")

                    # Create and start new thread
                    self.parent_menu.tts_preview_thread_instance = TTSPreviewThread(
                        text=text_to_speak,
                        engine=current_engine,
                        voice=current_voice,
                        parent=self
                    )
                    self.parent_menu.tts_preview_thread_instance.previewError.connect(self.handle_tts_preview_error)
                    self.parent_menu.tts_preview_thread_instance.start()

            except Exception as e:
                logger.error(f"启动TTS预览线程失败: {str(e)}")
                MessageBox("TTS预览失败", f"启动TTS预览时出错: {str(e)}", self).exec() # type: ignore[no-untyped-call]

        def handle_tts_preview_error(self, error_message: str) -> None:
            logger.error(f"TTS生成预览失败: {error_message}")
            MessageBox("TTS生成失败", f"生成或播放语音时出错: {error_message}", self).exec() # type: ignore[no-untyped-call]


    def open_tts_settings(self) -> None:
        if not hasattr(self, 'TTSSettingsDialog') or not self.TTSSettingsDialog:
            self.TTSSettingsDialog = self.TTSSettings(self)

        current_selected_engine_in_selector: Optional[str] = None
        if self.engine_selector:
            current_selected_engine_in_selector = self.engine_selector.currentData()

        tts_enabled_conf: Optional[str] = config_center.read_conf('TTS', 'enable') # type: ignore[no-untyped-call]
        tts_enabled: bool = bool(int(tts_enabled_conf)) if tts_enabled_conf and tts_enabled_conf.isdigit() else False

        if self.voice_selector and self.switch_enable_TTS:
            if tts_enabled:
                self.voice_selector.clear()
                self.voice_selector.addItem("加载中...", userData=None)
                self.voice_selector.setEnabled(False)
                self.switch_enable_TTS.setEnabled(False)
            else:
                self.voice_selector.clear()
                self.voice_selector.addItem("未启用", userData=None)
                self.voice_selector.setEnabled(False)
                self.switch_enable_TTS.setEnabled(True)

        self.toggle_tts_settings(tts_enabled) # type: ignore[no-untyped-call]
        if self.TTSSettingsDialog:
            self.TTSSettingsDialog.show()
            self.TTSSettingsDialog.exec()

        logger.debug(f"加载引擎: {self.current_loaded_engine},{current_selected_engine_in_selector}(选择器)")
        if tts_enabled and current_selected_engine_in_selector is not None:
            self.load_tts_voices_for_engine(current_selected_engine_in_selector)
        elif self.voice_selector and self.switch_enable_TTS:
            self.voice_selector.clear()
            self.voice_selector.addItem("未启用", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(True)

    def on_engine_selected(self, engine_text: str) -> None: # Added types
        selected_engine_key: Optional[str] = None
        if self.engine_selector:
            selected_engine_key = self.engine_selector.currentData()

        if selected_engine_key and selected_engine_key != self.current_loaded_engine:
            logger.debug(f"TTS引擎被更改,尝试更新列表: {selected_engine_key}")
            config_center.write_conf('TTS', 'engine', selected_engine_key) # type: ignore[no-untyped-call]
            self.current_loaded_engine = selected_engine_key
            self.load_tts_voices_for_engine(selected_engine_key)
        elif not selected_engine_key:
            logger.warning("选择的TTS引擎键为空")

    def load_tts_voices_for_engine(self, engine_key: str) -> None: # Added types
        if not self.voice_selector or not self.switch_enable_TTS:
            logger.error("TTS UI elements (voice_selector or switch_enable_TTS) not initialized on SettingsMenu.")
            return

        if config_center.read_conf('TTS', 'enable') == '0': # type: ignore[no-untyped-call]
            self.voice_selector.clear()
            self.voice_selector.addItem("未启用", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(True)
            return

        self.voice_selector.clear()
        self.voice_selector.addItem("加载中...", userData=None)
        self.voice_selector.setEnabled(False)
        self.switch_enable_TTS.setEnabled(False)

        if self.tts_voice_loader_thread and self.tts_voice_loader_thread.isRunning():
            self.tts_voice_loader_thread.requestInterruption()
            self.tts_voice_loader_thread.quit()
            if not self.tts_voice_loader_thread.wait(2000):
                logger.warning("旧TTS加载线程未能在超时时间内退出，将在后台继续运行")
        self.tts_voice_loader_thread = None

        self.current_loaded_engine = engine_key
        self.available_voices = None
        self.tts_voice_loader_thread = TTSVoiceLoaderThread(engine_filter=engine_key, parent=self)
        self.tts_voice_loader_thread.voicesLoaded.connect(
            lambda voices: self.available_voices_cnt(voices) or (self.switch_enable_TTS.setEnabled(True) if self.switch_enable_TTS else None) # type: ignore[union-attr]
        )
        self.tts_voice_loader_thread.errorOccurred.connect(
            lambda error: self.handle_tts_load_error(error) or (self.switch_enable_TTS.setEnabled(True) if self.switch_enable_TTS else None) # type: ignore[union-attr]
        )
        self.tts_voice_loader_thread.start()

    def populate_tts_engines(self):
