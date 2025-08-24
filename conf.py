import configparser as config
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dateutil import parser
from loguru import logger
from PyQt5.QtCore import QCoreApplication

import list_
from basic_dirs import CONFIG_HOME, CW_HOME, PLUGIN_HOME, THEME_DIRS
from data_model import ThemeConfig, ThemeInfo
from file import config_center
from utils import TimeManagerFactory

if os.name == 'nt':
    from win32com.client import Dispatch

conf = config.ConfigParser()
name = 'Class Widgets'

# app 图标
app_icon = CW_HOME / 'img' / (
    'favicon.ico' if os.name == 'nt' else
    'favicon.icns' if os.name == 'darwin' else
    'favicon.png'
)

update_countdown_custom_last = 0
countdown_cnt = 0


def __load_json(path: Path) -> ThemeConfig:
    with open(path, 'r', encoding='utf-8') as file:
        return ThemeConfig.model_validate_json(file.read())


# 此函数在 i18n_manager.py 有重复定义，更新时需同步
def load_theme_config(theme: str) -> ThemeInfo:
    default_path = CW_HOME / 'ui' / 'default' / 'theme.json'
    try:
        config_path = next(
            (
                dir
                for theme_dir in THEME_DIRS
                if (dir := (theme_dir / theme / 'theme.json')).exists()
            ),
            default_path
        )
        return ThemeInfo(
            path=config_path.parent,
            config=__load_json(config_path)
        )
    except Exception as e:
        logger.error(f"加载主题数据时出错: {repr(e)}，返回默认主题")
        return ThemeInfo(
            path=default_path.parent,
            config=__load_json(default_path)
        )


def load_plugin_config() -> Dict[str, List[str]]:
    try:
        plugin_config_path = CONFIG_HOME / 'plugin.json'
        if plugin_config_path.exists():
            with open(plugin_config_path, encoding='utf-8') as file:
                data : Dict[str, List[str]] = json.load(file)
        else:
            with open(plugin_config_path, 'w', encoding='utf-8') as file:
                data = {"enabled_plugins": []}
                json.dump(data, file, ensure_ascii=False, indent=4)
        return data
    except Exception as e:
        logger.error(f"加载启用插件数据时出错: {e}")
        return {"enabled_plugins": []}


def save_plugin_config(data: Dict[str, Any]) -> bool:
    data_dict = load_plugin_config()
    data_dict.update(data)
    try:
        with open(CONFIG_HOME / 'plugin.json', 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"保存启用插件数据时出错: {e}")
        return False


def save_installed_plugin(raw_data: List[Any]) -> bool:
    data = {"plugins": raw_data}
    try:
        with open(PLUGIN_HOME / 'plugins_from_pp.json', 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"保存已安装插件数据时出错: {e}")
        return False


def is_temp_week() -> Union[bool, str]:
    if config_center.read_conf('Temp', 'set_week') is None or config_center.read_conf('Temp', 'set_week') == '':
        return False
    else:
        return config_center.read_conf('Temp', 'set_week')


def is_temp_schedule() -> bool:
    return not (config_center.read_conf('Temp', 'temp_schedule') in [None, ''])


def add_shortcut_to_startmenu(file: str = '', icon: str = '') -> None:
    if os.name != 'nt':
        return
    try:
        file_path = Path(file) if file else Path(__file__).resolve()
        icon_path = Path(icon) if icon else file_path

        # 获取开始菜单文件夹路径
        menu_folder = Path(os.getenv('APPDATA')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'

        # 快捷方式文件名（使用文件名或自定义名称）
        name = file_path.stem  # 使用文件名作为快捷方式名称
        shortcut_path = menu_folder / f'{name}.lnk'

        # 创建快捷方式
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = str(file_path)
        shortcut.WorkingDirectory = str(file_path.parent)
        shortcut.IconLocation = str(icon_path)  # 设置图标路径
        shortcut.save()
    except Exception as e:
        logger.error(f"创建开始菜单快捷方式时出错: {e}")


def add_shortcut(file: str = '', icon: str = '') -> None:
    if os.name != 'nt':
        return
    try:
        file_path = Path(file) if file else Path(__file__).resolve()
        icon_path = Path(icon) if icon else file_path

        # 获取桌面文件夹路径
        desktop_folder = Path(os.environ['USERPROFILE']) / 'Desktop'

        # 快捷方式文件名（使用文件名或自定义名称）
        name = file_path.stem  # 使用文件名作为快捷方式名称
        shortcut_path = desktop_folder / f'{name}.lnk'

        # 创建快捷方式
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = str(file_path)
        shortcut.WorkingDirectory = str(file_path.parent)
        shortcut.IconLocation = str(icon_path)  # 设置图标路径
        shortcut.save()
    except Exception as e:
        logger.error(f"创建桌面快捷方式时出错: {e}")


def add_to_startup(file_path: str = str(CW_HOME / "ClassWidgets.exe"), icon_path: str = '') -> None:  # 注册到开机启动
    if os.name != 'nt':
        return
    file_path = Path(file_path) if file_path else Path(__file__).resolve()
    icon_path = Path(icon_path) if icon_path else file_path

    # 获取启动文件夹路径
    startup_folder = Path(os.getenv('APPDATA')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'

    # 快捷方式文件名（使用文件名或自定义名称）
    name = file_path.stem  # 使用文件名作为快捷方式名称
    shortcut_path = startup_folder / f'{name}.lnk'

    # 创建快捷方式
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(file_path)
    shortcut.WorkingDirectory = str(file_path.parent)
    shortcut.IconLocation = str(icon_path)  # 设置图标路径
    shortcut.save()


def remove_from_startup() -> None:
    startup_folder = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    shortcut_path = os.path.join(startup_folder, f'{name}.lnk')
    if os.path.exists(shortcut_path):
        os.remove(shortcut_path)

def update_countdown(cnt: int) -> None:
    global update_countdown_custom_last
    global countdown_cnt
    if (length:=len(config_center.read_conf('Date', 'cd_text_custom').split(','))) == 0:
        countdown_cnt = -1
    elif config_center.read_conf('Date', 'countdown_custom_mode') == '1':
        countdown_cnt = cnt
    elif (nowtime:=time.time()) - update_countdown_custom_last > int(config_center.read_conf('Date', 'countdown_upd_cd')):
        update_countdown_custom_last = nowtime
        countdown_cnt += 1
        if countdown_cnt >= length:
            countdown_cnt = 0 if length != 0 else -1

def get_cd_text_custom() -> str:
    global countdown_cnt
    if countdown_cnt == -1:
        return QCoreApplication.translate("conf", '未设置')
    if countdown_cnt >= len(li:=config_center.read_conf('Date', 'cd_text_custom').split(',')):
        return QCoreApplication.translate("conf", '未设置')
    return li[countdown_cnt] if countdown_cnt >= 0 else ''


def get_custom_countdown() -> str:
    global countdown_cnt
    if countdown_cnt == -1:
        return QCoreApplication.translate("conf", '未设置')
    li = config_center.read_conf('Date', 'countdown_date').split(',')
    if countdown_cnt == -1 or countdown_cnt >= len(li):
        return QCoreApplication.translate("conf", '未设置')  # 获取自定义倒计时
    else:
        custom_countdown = li[countdown_cnt]
        if custom_countdown == '':
            return QCoreApplication.translate("conf", '未设置')
        try:
            custom_countdown = parser.parse(custom_countdown)
        except Exception as e:
            logger.error(f"解析日期时出错: {custom_countdown}, 错误: {e}")
            return '解析失败'
        current_time = TimeManagerFactory.get_instance().get_current_time()
        if custom_countdown < current_time:
            return '0 天'
        else:
            cd_text = custom_countdown - current_time
            return f'{cd_text.days + 1} 天'
            # return (
            #     f"{cd_text.days} 天 {cd_text.seconds // 3600} 小时 {cd_text.seconds // 60 % 60} 分"
            # )


def get_week_type() -> int:
    """
    获取单双周类型
    :return: 0 - 单周, 1 - 双周
    """
    if (temp_schedule := config_center.read_conf('Temp', 'set_schedule')) not in ('', None):  # 获取单双周
        return int(temp_schedule)
    start_date_str = config_center.read_conf('Date', 'start_date')
    if start_date_str not in ('', None):
        try:
            start_date = parser.parse(start_date_str)
        except (ValueError, TypeError):
            logger.error(f"解析日期时出错: {start_date_str}")
            return 0  # 解析失败默认单周
        today = TimeManagerFactory.get_instance().get_current_time()
        week_num = (today - start_date).days // 7 + 1
        if week_num % 2 == 0:
            return 1  # 双周
        else:
            return 0  # 单周
    else:
        return 0  # 默认单周


def get_is_widget_in(widget: str = 'example.ui') -> bool:
    widgets_list = list_.get_widget_config()
    return widget in widgets_list


def save_widget_conf_to_json(new_data: Dict[str, Any]) -> bool:
    # 初始化 data_dict 为一个空字典
    data_dict = {}
    widget_json_path = CONFIG_HOME / 'widget.json'
    if widget_json_path.exists():
        try:
            with open(widget_json_path, encoding='utf-8') as file:
                data_dict = json.load(file)
        except Exception as e:
            print(f"读取现有数据时出错: {e}")
            return False
    data_dict.update(new_data)
    try:
        with open(widget_json_path, 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"保存数据时出错: {e}")
        return False


def load_plugins() -> Dict[str, Dict[str, str]]:  # 加载插件配置文件
    plugin_dict = {}
    for folder in PLUGIN_HOME.iterdir():
        if folder.is_dir() and (folder / 'plugin.json').exists():
            try:
                with open(PLUGIN_HOME / folder.name / "plugin.json", encoding='utf-8') as file:
                    data = json.load(file)
            except Exception as e:
                logger.error(f"加载插件配置文件数据时出错，将跳过: {e}")  # 跳过奇怪的文件夹
            plugin_dict[str(folder.name)] = {}
            plugin_dict[str(folder.name)]['name'] = data['name']  # 名称
            plugin_dict[str(folder.name)]['version'] = data['version']  # 插件版本号
            plugin_dict[str(folder.name)]['author'] = data['author']  # 作者
            plugin_dict[str(folder.name)]['description'] = data['description']  # 描述
            plugin_dict[str(folder.name)]['plugin_ver'] = data['plugin_ver']  # 插件架构版本
            plugin_dict[str(folder.name)]['settings'] = data['settings']  # 设置
            plugin_dict[str(folder.name)]['url'] = data.get('url', '')  # 插件URL
    return plugin_dict


if __name__ == '__main__':
    print('AL_1S')
    print(get_week_type())
    print(load_plugins())
    # save_data_to_json(test_data_dict, 'schedule-1.json')
    # loaded_data = load_from_json('schedule-1.json')
    # print(loaded_data)
    # schedule = loaded_data.get('schedule')

    # print(schedule['0'])
    # add_shortcut_to_startmenu('Settings.exe', 'img/favicon.ico')
