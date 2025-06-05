import json
import os
import configparser as config
from pathlib import Path
from typing import Any, Dict, Optional, Union, List # Added for type hinting

from datetime import datetime
import time
from dateutil import parser
from loguru import logger
from file import base_directory, config_center # type: ignore
# We assume 'file' module might not have stubs, so ignore type errors for it.

import list_ # type: ignore
# We assume 'list_' module might not have stubs or is dynamically generated.

if os.name == 'nt':
    from win32com.client import Dispatch # type: ignore
    # Dispatch is windows specific, may not be available/typed on other systems

base_directory: Path = Path(base_directory) # type: ignore
conf: config.ConfigParser = config.ConfigParser()
name: str = 'Class Widgets'

PLUGINS_DIR: Path = Path(base_directory) / 'plugins'

# app 图标
app_icon: Path = base_directory / 'img' / (
    'favicon.ico' if os.name == 'nt' else
    'favicon.icns' if os.name == 'darwin' else
    'favicon.png'
)

update_countdown_custom_last: float = 0.0 # Assuming it's a timestamp
countdown_cnt: int = 0

def load_theme_config(theme: str) -> Union[Dict[str, Any], str, None]:
    try:
        with open(base_directory / 'ui' / theme / 'theme.json', 'r', encoding='utf-8') as file:
            data: Dict[str, Any] = json.load(file)
            return data
    except FileNotFoundError:
        logger.warning(f"主题配置文件 {theme} 不存在，返回默认配置")
        return str(base_directory / 'ui' / 'default' / 'theme.json')
    except Exception as e:
        logger.error(f"加载主题数据时出错: {e}")
        return None


def load_plugin_config() -> Optional[Dict[str, Any]]:
    try:
        plugin_config_path: Path = base_directory / 'config' / 'plugin.json'
        if plugin_config_path.exists():
            with open(plugin_config_path, 'r', encoding='utf-8') as file:
                data: Dict[str, Any] = json.load(file)
        else:
            # Create the config directory if it doesn't exist
            (base_directory / 'config').mkdir(parents=True, exist_ok=True)
            with open(plugin_config_path, 'w', encoding='utf-8') as file:
                data = {"enabled_plugins": []}
                json.dump(data, file, ensure_ascii=False, indent=4)
        return data
    except Exception as e:
        logger.error(f"加载启用插件数据时出错: {e}")
        return None


def save_plugin_config(data: Dict[str, Any]) -> bool:
    data_dict: Optional[Dict[str, Any]] = load_plugin_config()
    if data_dict is None:
        # This case should ideally not be reached if load_plugin_config ensures file creation.
        # However, as a safeguard, initialize data_dict.
        data_dict = {"enabled_plugins": []}
    data_dict.update(data)
    try:
        # Ensure config directory exists
        (base_directory / 'config').mkdir(parents=True, exist_ok=True)
        with open(base_directory / 'config' / 'plugin.json', 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"保存启用插件数据时出错: {e}")
        return False


def save_installed_plugin(data: List[str]) -> bool: # Assuming data is a list of plugin names or identifiers
    data_to_save: Dict[str, List[str]] = {"plugins": data}
    try:
        # Ensure plugins directory exists
        (base_directory / 'plugins').mkdir(parents=True, exist_ok=True)
        with open(base_directory / 'plugins' / 'plugins_from_pp.json', 'w', encoding='utf-8') as file:
            json.dump(data_to_save, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"保存已安装插件数据时出错: {e}")
        return False


def load_theme_width(theme: str) -> Any: # Assuming widget_width can be various types or is defined in list_
    try:
        with open(base_directory / 'ui' / theme / 'theme.json', 'r', encoding='utf-8') as file:
            data: Dict[str, Any] = json.load(file)
            return data['widget_width']
    except Exception as e:
        logger.error(f"加载主题宽度时出错: {e}")
        return list_.widget_width # type: ignore


def is_temp_week() -> Union[bool, Any]: # Return type depends on config_center.read_conf
    conf_value: Any = config_center.read_conf('Temp', 'set_week')
    if conf_value is None or conf_value == '':
        return False
    else:
        return conf_value


def is_temp_schedule() -> Union[bool, Any]: # Return type depends on config_center.read_conf
    conf_value: Any = config_center.read_conf('Temp', 'temp_schedule')
    if (
        conf_value is None
        or conf_value == ''
    ):
        return False
    else:
        return conf_value


def add_shortcut_to_startmenu(file: str = '', icon: str = '') -> None:
    if os.name != 'nt':
        return
    try:
        file_path_obj: Path = Path(file) if file else Path(__file__).resolve()
        icon_path_obj: Path = Path(icon) if icon else file_path_obj

        # 获取开始菜单文件夹路径
        appdata: Optional[str] = os.getenv('APPDATA')
        if not appdata:
            logger.error("APPDATA environment variable not found.")
            return
        menu_folder: Path = Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'

        # 快捷方式文件名（使用文件名或自定义名称）
        # Using global 'name' for shortcut is likely a bug, should use file_path_obj.stem
        shortcut_name: str = file_path_obj.stem
        shortcut_path_obj: Path = menu_folder / f'{shortcut_name}.lnk'

        # 创建快捷方式
        shell: Any = Dispatch('WScript.Shell') # type: ignore
        shortcut: Any = shell.CreateShortCut(str(shortcut_path_obj))
        shortcut.Targetpath = str(file_path_obj)
        shortcut.WorkingDirectory = str(file_path_obj.parent)
        shortcut.IconLocation = str(icon_path_obj)  # 设置图标路径
        shortcut.save()
    except Exception as e:
        logger.error(f"创建开始菜单快捷方式时出错: {e}")


def add_shortcut(file: str = '', icon: str = '') -> None:
    if os.name != 'nt':
        return
    try:
        file_path_obj: Path = Path(file) if file else Path(__file__).resolve()
        icon_path_obj: Path = Path(icon) if icon else file_path_obj

        # 获取桌面文件夹路径
        userprofile: Optional[str] = os.environ.get('USERPROFILE')
        if not userprofile:
            logger.error("USERPROFILE environment variable not found.")
            return
        desktop_folder: Path = Path(userprofile) / 'Desktop'

        # 快捷方式文件名（使用文件名或自定义名称）
        # Using global 'name' for shortcut is likely a bug, should use file_path_obj.stem
        shortcut_name: str = file_path_obj.stem
        shortcut_path_obj: Path = desktop_folder / f'{shortcut_name}.lnk'

        # 创建快捷方式
        shell: Any = Dispatch('WScript.Shell') # type: ignore
        shortcut: Any = shell.CreateShortCut(str(shortcut_path_obj))
        shortcut.Targetpath = str(file_path_obj)
        shortcut.WorkingDirectory = str(file_path_obj.parent)
        shortcut.IconLocation = str(icon_path_obj)  # 设置图标路径
        shortcut.save()
    except Exception as e:
        logger.error(f"创建桌面快捷方式时出错: {e}")


def add_to_startup(file_path_str: str = f'{base_directory}/ClassWidgets.exe', icon_path_str: str = '') -> None:  # 注册到开机启动
    if os.name != 'nt':
        return

    file_p: Path = Path(file_path_str) if file_path_str else Path(__file__).resolve()
    icon_p: Path = Path(icon_path_str) if icon_path_str else file_p

    # 获取启动文件夹路径
    appdata: Optional[str] = os.getenv('APPDATA')
    if not appdata:
        logger.error("APPDATA environment variable not found.")
        return
    startup_folder: Path = Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'

    # 快捷方式文件名（使用文件名或自定义名称）
    # Using global 'name' for shortcut is likely a bug, should use file_p.stem
    shortcut_name: str = file_p.stem
    shortcut_path_obj: Path = startup_folder / f'{shortcut_name}.lnk'

    # 创建快捷方式
    shell: Any = Dispatch('WScript.Shell') # type: ignore
    shortcut: Any = shell.CreateShortCut(str(shortcut_path_obj))
    shortcut.Targetpath = str(file_p)
    shortcut.WorkingDirectory = str(file_p.parent)
    shortcut.IconLocation = str(icon_p)  # 设置图标路径
    shortcut.save()


def remove_from_startup() -> None:
    appdata: Optional[str] = os.getenv('APPDATA')
    if not appdata:
        logger.error("APPDATA environment variable not found.")
        return
    startup_folder_str: str = os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    # Uses global 'name', which might be intentional here if it refers to the application's name for its shortcut.
    shortcut_path_str: str = os.path.join(startup_folder_str, f'{name}.lnk')
    if os.path.exists(shortcut_path_str):
        os.remove(shortcut_path_str)


def get_time_offset() -> int:  # 获取时差偏移
    time_offset_str: Any = config_center.read_conf('General', 'time_offset')
    if time_offset_str is None or time_offset_str == '' or time_offset_str == '0':
        return 0
    else:
        return int(time_offset_str)

def update_countdown(cnt: int) -> None:
    global update_countdown_custom_last
    global countdown_cnt
    # Assuming config_center.read_conf returns string or None
    cd_text_custom_str: Optional[str] = config_center.read_conf('Date', 'cd_text_custom')
    if not cd_text_custom_str: # Handles None or empty string
        length: int = 0
    else:
        length = len(cd_text_custom_str.split(','))

    if length == 0:
        countdown_cnt = -1
    elif config_center.read_conf('Date', 'countdown_custom_mode') == '1':
        countdown_cnt = cnt
    else:
        # Assuming config_center.read_conf returns a string that can be cast to int
        countdown_upd_cd_str: Optional[str] = config_center.read_conf('Date', 'countdown_upd_cd')
        if countdown_upd_cd_str is None: # Handle case where value might be missing
             # Default to a large number or handle error appropriately
            logger.error("Countdown update CD not configured.")
            return

        try:
            countdown_upd_cd = int(countdown_upd_cd_str)
        except ValueError:
            logger.error(f"Invalid countdown_upd_cd value: {countdown_upd_cd_str}")
            return

        nowtime: float = time.time()
        if nowtime - update_countdown_custom_last > countdown_upd_cd:
            update_countdown_custom_last = nowtime
            countdown_cnt += 1
            if countdown_cnt >= length:
                countdown_cnt = 0 if length != 0 else -1

def get_cd_text_custom() -> str:
    global countdown_cnt
    if countdown_cnt == -1:
        return '未设置'

    cd_text_custom_str: Optional[str] = config_center.read_conf('Date', 'cd_text_custom')
    if not cd_text_custom_str:
        return '未设置' # Or handle as an error/empty list case

    li: List[str] = cd_text_custom_str.split(',')
    if countdown_cnt >= len(li):
        # This case implies countdown_cnt might not have been reset correctly
        # or length calculation in update_countdown was different.
        # For safety, returning '未设置'
        return '未设置'
    return li[countdown_cnt] if countdown_cnt >= 0 else ''


def get_custom_countdown() -> str:
    global countdown_cnt
    if countdown_cnt == -1:
        return '未设置'

    countdown_date_str: Optional[str] = config_center.read_conf('Date', 'countdown_date')
    if not countdown_date_str:
        return '未设置' # Or handle as an error

    li: List[str] = countdown_date_str.split(',')
    if countdown_cnt >= len(li): # Similar safety check as in get_cd_text_custom
        return '未设置'

    custom_countdown_item_str: str = li[countdown_cnt]
    if custom_countdown_item_str == '':
        return '未设置'
    try:
        # Ensure parser.parse returns datetime, not Any
        custom_countdown_dt: datetime = parser.parse(custom_countdown_item_str)
    except Exception as e: # Catching generic Exception is broad; consider more specific ones if possible
        logger.error(f"解析日期时出错: {custom_countdown_item_str}, 错误: {e}")
        return '解析失败'

    now_dt: datetime = datetime.now()
    if custom_countdown_dt < now_dt:
        return '0 天'
    else:
        cd_text: Any = custom_countdown_dt - now_dt # This is a timedelta
        return f'{cd_text.days + 1} 天'
            # return (
            #     f"{cd_text.days} 天 {cd_text.seconds // 3600} 小时 {cd_text.seconds // 60 % 60} 分"
            # )


def get_week_type() -> int:
    temp_schedule_str: Optional[str] = config_center.read_conf('Temp', 'set_schedule')
    if temp_schedule_str not in ('', None):  # 获取单双周
        try:
            return int(temp_schedule_str)
        except ValueError:
            logger.error(f"Invalid temp_schedule value: {temp_schedule_str}")
            return 0 # Default or error value

    start_date_config_str: Optional[str] = config_center.read_conf('Date', 'start_date')
    if start_date_config_str not in ('', None):
        try:
            start_date_dt: datetime = parser.parse(start_date_config_str)
        except (ValueError, TypeError): # More specific error handling
            logger.error(f"解析日期时出错: {start_date_config_str}")
            return 0  # 解析失败默认单周

        today_dt: datetime = datetime.now()
        # Ensure days is int
        week_num: int = (today_dt - start_date_dt).days // 7 + 1
        if week_num % 2 == 0:
            return 1  # 双周
        else:
            return 0  # 单周
    else:
        return 0  # 默认单周


def get_is_widget_in(widget: str ='example.ui') -> bool:
    widgets_list: List[str] = list_.get_widget_config() # type: ignore
    if widget in widgets_list:
        return True
    else:
        return False


def save_widget_conf_to_json(new_data: Dict[str, Any]) -> Union[bool, Exception]:
    # 初始化 data_dict 为一个空字典
    data_dict: Dict[str, Any] = {}
    widget_config_path: Path = base_directory / 'config' / 'widget.json' # Use Path object
    if widget_config_path.exists():
        try:
            with open(widget_config_path, 'r', encoding='utf-8') as file:
                data_dict = json.load(file)
        except Exception as e: # More specific exception like json.JSONDecodeError could be used
            print(f"读取现有数据时出错: {e}") # Consider logging instead of printing
            return e
    data_dict.update(new_data)
    try:
        # Ensure config directory exists
        widget_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(widget_config_path, 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e: # More specific exception like IOError could be used
        print(f"保存数据时出错: {e}") # Consider logging instead of printing
        return e


def load_plugins() -> Dict[str, Dict[str, Any]]:  # 加载插件配置文件
    plugin_dict: Dict[str, Dict[str, Any]] = {}
    for folder in Path(PLUGINS_DIR).iterdir():
        if folder.is_dir():
            plugin_json_path: Path = folder / 'plugin.json' # More direct path construction
            if plugin_json_path.exists():
                try:
                    with open(plugin_json_path, 'r', encoding='utf-8') as file:
                        data: Dict[str, Any] = json.load(file)
                except Exception as e: # More specific exception like json.JSONDecodeError
                    logger.error(f"加载插件配置文件数据时出错 {plugin_json_path}, 将跳过: {e}")
                    continue # Skip this plugin if its config is invalid

                # Initialize plugin entry safely
                plugin_name_str = str(folder.name)
                plugin_dict[plugin_name_str] = {
                    'name': data.get('name', 'Unknown Plugin'), # Provide defaults
                    'version': data.get('version', 'N/A'),
                    'author': data.get('author', 'Unknown Author'),
                    'description': data.get('description', ''),
                    'plugin_ver': data.get('plugin_ver', 'N/A'),
                    'settings': data.get('settings', {}) # Assuming settings is a dict
                }
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
