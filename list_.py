import json
import os
from copy import deepcopy
from shutil import copy

from loguru import logger
from file import base_directory, config_center, save_data_to_json # type: ignore[attr-defined]
from typing import List, Dict, Any, Union # Added for type hinting

# Define more specific types if possible, e.g. for subject colors if they are always tuples or specific string format
SubjectColors = Dict[str, str] # Assuming color is stored as string e.g. '(R, G, B)'
SubjectIcons = Dict[str, str]
SubjectAbbreviations = Dict[str, str]
WidgetNameDict = Dict[str, str]
WidgetWidthDict = Dict[str, int]


week: List[str] = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
week_type: List[str] = ['单周', '双周']
part_type: List[str] = ['节点', '休息段']
window_status: List[str] = ['无', '置于顶部', '置于底部']
color_mode: List[str] = ['浅色', '深色', '跟随系统']
hide_mode: List[str] = ['无', '上课时自动隐藏', '窗口最大化时隐藏', '灵活隐藏']
non_nt_hide_mode: List[str] = ['无', '上课时自动隐藏']
version_channel: List[str] = ['正式版 (Release)', '测试版 (Beta)']

theme_folder: List[str] = []
theme_names: List[str] = []

subject: SubjectColors = {
    '语文': '(255, 151, 135',  # 红
    '数学': '(105, 84, 255',  # 蓝
    '英语': '(236, 135, 255',  # 粉
    '生物': '(68, 200, 94',  # 绿
    '地理': '(80, 214, 200',  # 浅蓝
    '政治': '(255, 110, 110',  # 红
    '历史': '(180, 130, 85',  # 棕
    '物理': '(130, 85, 180',  # 紫
    '化学': '(84, 135, 190',  # 蓝
    '美术': '(0, 186, 255',  # 蓝
    '音乐': '(255, 101, 158',  # 红
    '体育': '(255, 151, 135',  # 红
    '信息技术': '(84, 135, 190',  # 蓝
    '电脑': '(84, 135, 190',  # 蓝
    '课程表未加载': '(255, 151, 135',  # 红

    '班会': '(255, 151, 135',  # 红
    '自习': '(115, 255, 150',  # 绿
    '课间': '(135, 255, 191',  # 绿
    '大课间': '(255, 151, 135',  # 红
    '放学': '(84, 255, 101',  # 绿
    '暂无课程': '(84, 255, 101',  # 绿
}

schedule_dir: str = os.path.join(base_directory, 'config', 'schedule') # base_directory is Path, so schedule_dir will be Path

class_activity: List[str] = ['课程', '课间']
time_periods: List[str] = ['上午', '下午', '晚修'] # Renamed 'time' to avoid conflict with time module
class_kind: List[str] = [
    '自定义', '语文', '数学', '英语', '政治', '历史', '生物', '地理',
    '物理', '化学', '体育', '班会', '自习', '早读', '大课间', '美术',
    '音乐', '心理', '信息技术'
]

default_widgets: List[str] = [
    'widget-time.ui', 'widget-countdown.ui',
    'widget-current-activity.ui', 'widget-next-activity.ui'
]

widget_width: WidgetWidthDict = {  # 默认宽度
    'widget-time.ui': 210, 'widget-countdown.ui': 200,
    'widget-current-activity.ui': 360, 'widget-next-activity.ui': 290,
    'widget-countdown-day.ui': 200, 'widget-weather.ui': 200
}

widget_conf: WidgetNameDict = { # Assuming keys are user-facing names and values are filenames
    '当前日期': 'widget-time.ui', '活动倒计时': 'widget-countdown.ui',
    '当前活动': 'widget-current-activity.ui', '更多活动': 'widget-next-activity.ui',
    '倒计日': 'widget-countdown-day.ui', '天气': 'widget-weather.ui'
}

widget_name: WidgetNameDict = { # Filename to user-facing name
    'widget-time.ui': '当前日期', 'widget-countdown.ui': '活动倒计时',
    'widget-current-activity.ui': '当前活动', 'widget-next-activity.ui': '更多活动',
    'widget-countdown-day.ui': '倒计日', 'widget-weather.ui': '天气'
}

native_widget_name: List[str] = [widget_name[i] for i in widget_name] # Assuming all keys in widget_name are valid

subject_icon: SubjectIcons # Declare type, will be initialized in try-except
subject_abbreviation: SubjectAbbreviations # Declare type

try:  # 加载课程/主题配置文件
    # Ensure paths are constructed with Path objects for consistency
    subject_config_path = base_directory / 'config' / 'data' / 'subject.json'
    with open(subject_config_path, 'r', encoding='utf-8') as f:
        subject_info: Dict[str, Any] = json.load(f)

    subject_icon = subject_info.get('subject_icon', {}) # Use .get for safety
    subject_abbreviation = subject_info.get('subject_abbreviation', {})

    ui_dir_path = base_directory / 'ui'
    if ui_dir_path.is_dir(): # Check if ui directory exists
        theme_folder = [f.name for f in ui_dir_path.iterdir() if f.is_dir()]
    else:
        theme_folder = [] # Initialize as empty list if ui dir doesn't exist
        logger.warning(f"UI directory not found at {ui_dir_path}")

except FileNotFoundError:
    logger.error(f"Subject config file not found at {base_directory / 'config' / 'data' / 'subject.json'}. Using default subject settings.")
    # Fallback default values
    config_center.write_conf('General', 'theme', 'default') # type: ignore[no-untyped-call]
    subject_icon = {
        '语文': 'chinese', '数学': 'math', '英语': 'abc', '生物': 'biology', '地理': 'geography',
        '政治': 'chinese', '历史': 'history', '物理': 'physics', '化学': 'chemistry', '美术': 'art',
        '音乐': 'music', '体育': 'pe', '信息技术': 'it', '电脑': 'it', '课程表未加载': 'xmark',
        '班会': 'meeting', '自习': 'self_study', '课间': 'break', '大课间': 'pe',
        '放学': 'after_school', '暂无课程': 'break',
    }
    subject_abbreviation = {'历史': '史'}
    theme_folder = [] # Ensure theme_folder is initialized

except json.JSONDecodeError as e:
    logger.error(f"Error decoding subject_info.json: {e}. Using default subject settings.")
    config_center.write_conf('General', 'theme', 'default') # type: ignore[no-untyped-call]
    subject_icon = {} # Initialize to empty or default
    subject_abbreviation = {}
    theme_folder = []

except Exception as e: # Catch other potential errors
    logger.error(f'加载课程/主题配置文件发生错误，使用默认配置：{e}')
    config_center.write_conf('General', 'theme', 'default') # type: ignore[no-untyped-call]
    subject_icon = {} # Initialize to empty or default
    subject_abbreviation = {}
    theme_folder = []


not_exist_themes: List[str] = []
countdown_modes: List[str] = ['轮播', '多小组件']

for folder_name in theme_folder: # Renamed folder to folder_name for clarity
    try:
        json_file = json.load(open(f'{base_directory}/ui/{folder}/theme.json', 'r', encoding='utf-8'))
        theme_names.append(json_file['name'])
    except Exception as e:
        logger.error(f'加载主题文件 theme.json {folder} 发生错误，跳过：{e}')
        not_exist_themes.append(folder)

for folder in not_exist_themes:
    theme_folder.remove(folder)


def get_widget_list() -> List[str]: # Added return type hint
    rl: List[str] = []
    # widget_conf is Dict[str, str], so item is str
    for item in widget_conf.keys(): # Iterate over keys directly
        rl.append(item)
    return rl


def get_widget_names() -> List[str]: # Added return type hint
    rl: List[str] = []
    # widget_name is Dict[str, str], so value is str
    for value in widget_name.values(): # Iterate over values directly
        rl.append(value)
    return rl


def get_current_theme_num() -> Union[int, str]: # Return type can be int or str
    # Ensure theme_folder is a list of strings
    for i, folder_name_str in enumerate(theme_folder): # Use enumerate for index and value
        # Construct Path object for checking existence
        schedule_theme_path = base_directory / 'config' / 'schedule' / f"{folder_name_str}.json"
        if not schedule_theme_path.exists(): # Use Path.exists()
             # This seems to imply a logic error or specific handling for "default"
             # If a theme file is missing, it returns "default" immediately.
            return "default"

        # config_center.read_conf returns Any, ensure comparison is appropriate
        current_theme_in_conf: Any = config_center.read_conf('General', 'theme') # type: ignore[no-untyped-call]
        if folder_name_str == str(current_theme_in_conf): # Compare with str representation
            return i
    return "default" # Default if no match found or theme_folder is empty


def get_theme_ui_path(name: str) -> str: # Added parameter and return type hints
    # Ensure theme_names and theme_folder are List[str]
    for i, theme_name_str in enumerate(theme_names):
        if theme_name_str == name:
            if i < len(theme_folder): # Check index bounds
                return theme_folder[i]
            else:
                # This case implies theme_names and theme_folder are out of sync
                logger.error(f"Theme name '{name}' found but corresponding folder index is out of bounds.")
                return 'default' # Fallback or error handling
    return 'default' # Default if name not found


def get_subject_abbreviation(key: str) -> str: # Added parameter and return type hints
    # subject_abbreviation is Dict[str, str]
    return subject_abbreviation.get(key, key[:1]) # Use .get for safer access and default


# 学科图标
def get_subject_icon(key: str) -> str: # Added parameter and return type hints
    # subject_icon is Dict[str, str]
    icon_name: Optional[str] = subject_icon.get(key)
    if icon_name:
        return str(base_directory / 'img' / 'subject' / f'{icon_name}.svg') # Construct Path then convert to str
    else:
        return str(base_directory / 'img' / 'subject' / 'self_study.svg')


# 学科主题色
def subject_color(key: str) -> str: # Added parameter and return type hints
    # subject is Dict[str, str]
    return subject.get(key, '(75, 170, 255') # Use .get for safer access and default


def get_schedule_config() -> List[str]: # Type hint already good
    schedule_config_list: List[str] = [] # Renamed for clarity
    # schedule_dir is str, but os.listdir expects PathLike or str.
    # It's better if schedule_dir is Path. Assuming base_directory is Path.
    schedule_dir_path = base_directory / 'config' / 'schedule'
    if not schedule_dir_path.is_dir(): # Check if directory exists
        logger.error(f"Schedule directory not found: {schedule_dir_path}")
        schedule_config_list.append('添加新课表')
        return schedule_config_list

    for file_name_str in os.listdir(schedule_dir_path): # file_name_str is str
        if file_name_str.endswith('.json') and file_name_str != 'backup.json':
            schedule_config_list.append(file_name_str)
    schedule_config_list.append('添加新课表')
    return schedule_config_list


def return_default_schedule_number() -> int: # Added return type hint
    total: int = 0
    schedule_dir_path = base_directory / 'config' / 'schedule'
    if not schedule_dir_path.is_dir():
        logger.warning(f"Schedule directory for default numbers not found: {schedule_dir_path}")
        return 0

    for file_name_str in os.listdir(schedule_dir_path):
        if file_name_str.startswith('新课表 - '): # Check prefix
            total += 1
    return total


def create_new_profile(filename: str) -> None: # Added parameter and return type hints
    # Ensure paths are Path objects
    source_path = base_directory / 'config' / 'default.json'
    destination_path = base_directory / 'config' / 'schedule' / filename
    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True) # Ensure destination directory exists
        copy(str(source_path), str(destination_path)) # shutil.copy might need strings
    except FileNotFoundError:
        logger.error(f"Source file for new profile not found: {source_path}")
    except Exception as e:
        logger.error(f"Error creating new profile '{filename}': {e}")


def import_schedule(filepath: str, filename: str) -> Union[bool, Exception]:  # 导入课表. Return type can be bool or Exception
    try:
        with open(filepath, 'r', encoding='utf-8') as file_handle:
            check_data: Dict[str,Any] = json.load(file_handle)
    except FileNotFoundError:
        logger.error(f"File not found during import: {filepath}")
        return False
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {filepath}: {e}")
        return False
    except Exception as e: # Catch other read errors
        logger.error(f"加载数据时出错 {filepath}: {e}")
        return False

    checked_data: Union[bool, Dict[str, Any]] = convert_schedule(check_data)
    if checked_data is False or not isinstance(checked_data, dict) : # convert_schedule can return False
        logger.error(f"Schedule conversion failed for {filepath}")
        return False # Or the error from convert_schedule if it's an exception

    # 保存文件
    try:
        # print(check_data) # Original data, maybe log checked_data instead for debugging
        destination_path = base_directory / 'config' / 'schedule' / filename
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        # copy source to destination first, then overwrite with converted data
        copy(filepath, str(destination_path))
        save_data_to_json(checked_data, filename) # type: ignore[no-untyped-call] # save_data_to_json is defined later
        config_center.write_conf('General', 'schedule', filename) # type: ignore[no-untyped-call]
        return True
    except Exception as e: # Catch errors during copy or save
        logger.error(f"保存数据时出错 {filename}: {e}")
        return e # Return the exception


def convert_schedule(check_data: Optional[Dict[str, Any]]) -> Union[bool, Dict[str, Any]]:  # 转换课表. Added type hints
    if check_data is None:
        logger.warning('此文件为空')
        return False # Explicitly return False for None input

    # 校验课程表 - ensure check_data is a dict before using .get
    if not isinstance(check_data, dict) or (not check_data.get('timeline') and not check_data.get('schedule')):
        logger.warning('此文件不是课程表文件或格式不正确')
        return False # Return False for invalid format

    # Make a deep copy to avoid modifying the original dict if it's passed from elsewhere
    converted_data = deepcopy(check_data)

    # 转换为标准格式
    if 'schedule_even' not in converted_data: # Use 'in' for checking key presence
        logger.warning('此课程表格式不支持单双周, 添加空双周课表.')
        converted_data['schedule_even'] = {str(i): [] for i in range(7)} # Assuming 0-6 for Mon-Sun

    part_data = converted_data.get('part')
    # Check if part_data is a dict and if '0' entry exists and has length 2
    if isinstance(part_data, dict) and isinstance(part_data.get('0'), list) and len(part_data['0']) == 2:
        logger.warning('此课程表格式不支持休息段, 为所有节点添加默认类型 "节点".')
        for i_str in part_data: # Iterate through keys of part_data dict
            if isinstance(part_data[i_str], list) and len(part_data[i_str]) == 2:
                 part_data[i_str].append('节点') # Add type if missing

    #兼容旧版本: part 和 part_name 可能不存在
    if 'part' not in converted_data or 'part_name' not in converted_data:
        logger.warning('此课程表格式不支持节点 (旧版格式), 尝试转换...')
        try:
            # Ensure 'timeline' and its sub-keys exist before accessing
            timeline_data = converted_data.get('timeline', {})
            start_time_m_part = timeline_data.get('start_time_m', {}).get('part')
            start_time_a_part = timeline_data.get('start_time_a', {}).get('part')

            if start_time_m_part is None or start_time_a_part is None:
                logger.error("旧版课程表缺少 'start_time_m' 或 'start_time_a' 节点信息，无法转换。")
                return False

            converted_data['part'] = {"0": start_time_m_part, "1": start_time_a_part}
            converted_data['part_name'] = {"0": "上午", "1": "下午"}

            # Remove old keys if they exist
            if 'start_time_m' in timeline_data: del timeline_data['start_time_m']
            if 'start_time_a' in timeline_data: del timeline_data['start_time_a']

            old_timeline_content = deepcopy(timeline_data) # Operate on the timeline content
            converted_data['timeline'] = {'default': {}} # Reset timeline structure
            for i in range(7): # Mon-Sun
                converted_data['timeline'][str(i)] = {} # Ensure keys are strings

            for item_key, item_value in old_timeline_content.items():
                if not isinstance(item_key, str) or len(item_key) < 3: continue # Skip invalid keys

                part_char = item_key[1] # 'm' or 'a'
                part_num_str = "0" if part_char == 'm' else "1" #上午->0, 下午->1
                new_key_name = item_key[0] + part_num_str + item_key[2:] # Construct new key e.g. f00, a01
                converted_data['timeline']['default'][new_key_name] = item_value

        except KeyError as ke: # Catch specific KeyError if assumptions about old format are wrong
            logger.error(f"转换旧版课程表时缺少必要键: {ke}")
            return False
        except Exception as e: # Catch any other errors during conversion
            logger.error(f"转换旧版课程表数据时出错: {e}")
            return False

    return converted_data


def export_schedule(filepath: str, filename: str) -> Union[bool, Exception]:  # 导出课表. Added type hints
    try:
        source_path = base_directory / 'config' / 'schedule' / filename
        # Ensure destination directory for filepath exists if filepath includes directories
        Path(filepath).parent.mkdir(parents=True, exist_ok=True) # type: ignore[attr-defined]
        copy(str(source_path), filepath) # shutil.copy might need strings
        return True
    except FileNotFoundError:
        logger.error(f"Source file for export not found: {source_path}")
        return False # Return bool for file not found
    except Exception as e:
        logger.error(f"导出文件时出错 '{filename}' to '{filepath}': {e}")
        return e # Return the exception object


def get_widget_config() -> List[str]: # Added return type hint
    widget_config_path = base_directory / 'config' / 'widget.json'
    try:
        if widget_config_path.exists():
            with open(widget_config_path, 'r', encoding='utf-8') as file_handle:
                data: Dict[str, List[str]] = json.load(file_handle) # Expect specific structure
        else: # File doesn't exist, create with default
            default_widget_data = {'widgets': default_widgets[:]} # Use a copy of default_widgets
            with open(widget_config_path, 'w', encoding='utf-8') as file_handle:
                json.dump(default_widget_data, file_handle, indent=4)
            data = default_widget_data # Use the defaults we just wrote
        # Ensure 'widgets' key exists and is a list of strings
        widget_list = data.get('widgets', [])
        if not isinstance(widget_list, list) or not all(isinstance(item, str) for item in widget_list):
            logger.warning("Widget config 'widgets' key is not a list of strings. Returning default.")
            return default_widgets[:] # Return a copy
        return widget_list
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding widget.json: {e}. Returning default widgets.")
        return default_widgets[:]
    except Exception as e: # Catch other errors
        logger.error(f'ReadWidgetConfigFAILD: {e}. Returning default widgets.')
        return default_widgets[:]


if __name__ == '__main__':
    print(theme_folder)
    print(theme_names)
    print('AL-1S')
    print(get_widget_list())
