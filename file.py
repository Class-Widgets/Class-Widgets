import json
import os
import sys
from pathlib import Path
from shutil import copy

from loguru import logger
import configparser
from packaging.version import Version # type: ignore
# from packaging.version import Version # Marked as ignored if not directly used for type hinting
# but it is used for runtime checks. If stubs are missing, this is fine.
import configparser as config # Alias for configparser
from typing import Any, Callable, Dict, Optional, Union # Added for type hinting
import utils # Assuming utils is a module with a stop function

base_directory: Path = Path(os.path.dirname(os.path.abspath(__file__)))
'''
if str(base_directory).endswith('MacOS'):
    base_directory = (base_directory.parent / 'Resources').resolve()
'''
config_path: Path = base_directory / 'config.ini'


class ConfigCenter:
    """
    Config中心
    """
    def __init__(self, base_dir_param: Path, schedule_update_callback: Optional[Callable[[], None]] = None) -> None: # Added type hints
        self.base_directory: Path = base_dir_param # Renamed to avoid conflict with module-level var
        self.config_version: int = 1
        self.config_file_name: str = 'config.ini'
        self.user_config_path: Path = self.base_directory / self.config_file_name
        self.default_config_path: Path = self.base_directory / 'config' / 'default_config.json'
        self.config: configparser.ConfigParser = configparser.ConfigParser()
        self.default_data: Dict[str, Any] = {}
        self.schedule_update_callback: Optional[Callable[[], None]] = schedule_update_callback

        self._load_default_config()
        self._load_user_config()
        self._check_and_migrate_config()

        # self.read_conf can return various types, ensure schedule_name is str
        schedule_name_read: Any = self.read_conf('General', 'schedule')
        self.schedule_name: str = str(schedule_name_read) if schedule_name_read is not None else 'default_schedule.json' # Provide default or handle None
        self.old_schedule_name: str = self.schedule_name

    def _load_default_config(self) -> None: # Added return type hint
        """加载默认配置文件"""
        try:
            with open(self.default_config_path, 'r', encoding="utf-8") as default_file: # Added 'r' mode and renamed var
                self.default_data = json.load(default_file)
        except FileNotFoundError: # More specific exception
            logger.error(f"Default config file not found: {self.default_config_path}")
            self.default_data = {} # Ensure default_data is initialized
            # Consider re-raising or exiting if this is critical
        except json.JSONDecodeError as e: # More specific exception
            logger.error(f"Error decoding default config JSON: {e}")
            self.default_data = {}
        except Exception as e: # Catch-all for other errors
            logger.error(f"加载默认配置文件失败: {e}")
            self.default_data = {}
            # GUI error display logic - consider moving to a UI handling module
            from qfluentwidgets import Dialog # type: ignore
            from PyQt5.QtWidgets import QApplication # type: ignore
            # import sys # Already imported
            app = QApplication.instance() or QApplication(sys.argv) # type: ignore
            dlg = Dialog( # type: ignore
                'Class Widgets 启动失败w(ﾟДﾟ)w',
                f'加载默认配置文件失败,请检查文件完整性或尝试重新安装。\n错误信息: {e}'
            )
            dlg.yesButton.setText('好') # type: ignore
            dlg.cancelButton.hide() # type: ignore
            dlg.buttonLayout.insertStretch(0, 1) # type: ignore
            dlg.setFixedWidth(550) # type: ignore
            dlg.exec() # type: ignore
            utils.stop(0) # type: ignore[no-untyped-call] # Assuming utils.stop exists

    def _load_user_config(self) -> None: # Added return type hint
        """加载用户配置文件"""
        try:
            self.config.read(self.user_config_path, encoding='utf-8')
        except Exception as e: # Consider more specific exceptions like configparser.Error
            logger.error(f"加载配置文件失败: {e}")

    def _initialize_config(self) -> None: # Added return type hint
        """初始化配置文件（当配置文件不存在时）"""
        logger.info("配置文件不存在，已创建并写入默认配置。")
        self.config.read_dict(self.default_data) # type: ignore[no-untyped-call]
        self._write_config_to_file()
        if sys.platform != 'win32':
            self.config.set('General', 'hide_method', '2')
            self._write_config_to_file()

        # Ensure target directory exists before copying
        target_schedule_dir = self.base_directory / 'config' / 'schedule'
        target_schedule_dir.mkdir(parents=True, exist_ok=True)
        copy(self.base_directory / 'config' / 'default.json', target_schedule_dir / '新课表 - 1.json')

    def _migrate_config(self) -> None: # Added return type hint
        """迁移配置文件（当配置文件版本不一致时）"""
        logger.warning(f"配置文件版本不同,重新适配")
        try:
            for section, options in self.default_data.items():
                if section not in self.config: # type: ignore[operator] # ConfigParser sections are not directly in self.config
                    self.config.add_section(section)
                    for key, value in options.items(): # type: ignore[union-attr] # options can be str if default_data is not well-formed
                        self.config[section][key] = str(value)
                    logger.debug(f"添加新的配置节: {section}")
                else:
                    for key, value in options.items(): # type: ignore[union-attr]
                        if key not in self.config[section]:
                            self.config[section][key] = str(value)
                            logger.debug(f"添加新的配置项: {section}.{key}")

            version_from_default: Optional[str] = self.default_data.get('Version', {}).get('version') # type: ignore[union-attr]
            if version_from_default:
                self.config.set('Version', 'version', version_from_default)
            self._write_config_to_file()
            logger.success(f"配置文件已更新")
        except Exception as e: # Consider more specific exceptions
            logger.error(f"配置文件更新失败: {e}")

    def _check_schedule_config(self) -> None: # Added return type hint
        """检查课程表配置文件"""
        schedule_dir: Path = self.base_directory / 'config' / 'schedule'
        schedule_dir.mkdir(parents=True, exist_ok=True) # Ensure directory exists

        # read_conf can return various types, ensure schedule_name is str
        schedule_name_read: Any = self.read_conf('General', 'schedule', '新课表 - 1.json')
        schedule_name_str: str = str(schedule_name_read) if schedule_name_read is not None else '新课表 - 1.json'
        current_schedule_file: Path = schedule_dir / schedule_name_str

        if not current_schedule_file.exists():
            schedule_config_files: list[str] = [] # Corrected type
            for file_name_path in schedule_dir.iterdir(): # Renamed for clarity
                if file_name_path.suffix == '.json' and file_name_path.name != 'backup.json':
                    schedule_config_files.append(file_name_path.name)

            if not schedule_config_files:
                # Ensure default.json exists before copying
                default_schedule_src = self.base_directory / 'config' / 'default.json'
                if default_schedule_src.exists():
                    copy(default_schedule_src, current_schedule_file) # Use current_schedule_file directly
                    logger.info(f"课程表不存在,已创建默认课程表: {schedule_name_str}")
                else:
                    logger.error(f"Default schedule file not found at {default_schedule_src}, cannot create initial schedule.")
            else:
                self.write_conf('General', 'schedule', schedule_config_files[0])
        # print(Path.cwd() / 'config' / 'schedule') # For debugging, consider removing

    def _check_plugins_directory(self) -> None: # Added return type hint
        """检查插件目录和文件"""
        plugins_dir: Path = self.base_directory / 'plugins'
        if not plugins_dir.exists():
            plugins_dir.mkdir(parents=True, exist_ok=True) # Ensure parent dirs are also created
            logger.info("Plugins 文件夹不存在，已创建。")

        plugins_file: Path = plugins_dir / 'plugins_from_pp.json'
        if not plugins_file.exists():
            try:
                with open(plugins_file, 'w', encoding='utf-8') as file_handle: # Renamed var
                    json.dump({"plugins": []}, file_handle, ensure_ascii=False, indent=4)
                logger.info("plugins_from_pp.json 文件不存在，已创建。")
            except IOError as e: # More specific exception for file I/O
                 logger.error(f"创建 plugins_from_pp.json 文件失败: {e}")


    def _write_config_to_file(self) -> None: # Added return type hint
        """将当前配置写入文件"""
        try:
            with open(self.user_config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
        except IOError as e: # More specific exception for file I/O
            logger.error(f"写入配置文件失败 {self.user_config_path}: {e}")


    def _check_and_migrate_config(self) -> None: # Added return type hint
        """检查并迁移配置文件"""
        if not self.user_config_path.exists():
            self._initialize_config()
        else:
            self._load_user_config()
            # Ensure self.config is not None after _load_user_config if it can fail and leave it None
            if self.config is None: # Should not happen if _load_user_config initializes self.config
                 logger.error("Config parser not initialized after loading user config.")
                 self._initialize_config() # Attempt to re-initialize
                 if self.config is None: # Still None, critical error
                      logger.critical("Failed to initialize config parser. Aborting migration.")
                      return

            user_config_version_str: str
            if 'Version' in self.config and 'version' in self.config['Version']:
                user_config_version_str = self.config['Version']['version']
            else:
                user_config_version_str = '0.0.0' # Default if not found

            default_config_version_str: Optional[str] = self.default_data.get('Version', {}).get('version')
            if default_config_version_str is None: # Should not happen if default_data is well-formed
                logger.error("Default config version is missing. Cannot compare versions.")
                default_config_version_str = '0.0.0' # Fallback, though this indicates an issue

            user_config_version: Version
            default_config_version: Version
            try:
                user_config_version = Version(user_config_version_str)
            except ValueError: # More specific exception for Version parsing
                logger.warning(f"配置文件中的版本号 '{user_config_version_str}' 无效")
                user_config_version = Version('0.0.0')

            try:
                default_config_version = Version(default_config_version_str)
            except ValueError:
                logger.error(f"默认配置文件中的版本号 '{default_config_version_str}' 无效")
                return # Cannot proceed without a valid default version

            if user_config_version < default_config_version:
                logger.info(f"检测到配置文件版本不一致或缺失 (配置版本: {user_config_version}, 默认版本: {default_config_version})，正在执行配置迁移...")
                self._migrate_config()
                # _migrate_config already calls _write_config_to_file, so this might be redundant
                # self._write_config_to_file()
        self._check_schedule_config()
        self._check_plugins_directory()

    def update_conf(self) -> None: # Added return type hint
        """重新加载配置文件并更新相关状态"""
        try:
            self._load_user_config()
            # Ensure self.config is valid after loading
            if self.config is None:
                 logger.error("Config parser not available after trying to update config.")
                 return

            new_schedule_name_any: Any = self.read_conf('General', 'schedule')
            new_schedule_name: str = str(new_schedule_name_any) if new_schedule_name_any is not None else self.old_schedule_name

            if new_schedule_name != self.old_schedule_name:
                logger.info(f'已切换到课程表: {new_schedule_name}')
                self.old_schedule_name = new_schedule_name
                if self.schedule_update_callback: # Check if callback is set
                    self.schedule_update_callback()

        except Exception as e: # Consider more specific exceptions
            logger.error(f'更新配置文件时出错: {e}')

    def read_conf(self, section: str = 'General', key: str = '', fallback: Any = None) -> Any: # Added type hints
        """读取配置项，并根据默认配置中的类型信息进行转换"""
        # Check if section exists in either current config or default data
        if section not in self.config and section not in self.default_data: # type: ignore[operator]
            logger.warning(f"配置节未找到: Section='{section}'")
            if not key: # If no key is specified, and section is missing, behavior is to add empty section
                try:
                    self.config.add_section(section)
                    logger.info(f"已为 '{section}' 添加空节")
                    return {} # Return empty dict for a new section
                except (configparser.DuplicateSectionError, ValueError) as e: # Handle potential errors
                    logger.error(f"Error adding section {section}: {e}")
                    return fallback # Or perhaps {} or raise error
            return fallback

        # If no key is specified, return the whole section
        if not key:
            if section in self.config: # type: ignore[operator]
                return dict(self.config[section]) # Return as a dict
            elif section in self.default_data: # Fallback to default_data if section not in live config
                converted_section: Dict[str, Any] = {}
                # Ensure default_data[section] is a dict before iterating
                default_section_items = self.default_data.get(section)
                if isinstance(default_section_items, dict):
                    for k, item_info in default_section_items.items():
                        if isinstance(item_info, dict) and "type" in item_info and "default" in item_info:
                            converted_section[k] = self._convert_value(item_info["default"], item_info["type"])
                        else: # If item_info is not a dict with type/default, use it as is
                            converted_section[k] = item_info
                return converted_section
            else: # Should not be reached if first check is comprehensive
                 return {}


        # If a key is specified, try to get it from the live config first
        if section in self.config and key in self.config[section]: # type: ignore[operator]
            # Assuming value from config is string, may need conversion based on default_data type
            value_from_config: str = self.config[section][key]
            # Try to find type info from default_data to convert
            if section in self.default_data:
                item_info = self.default_data[section].get(key)
                if isinstance(item_info, dict) and "type" in item_info:
                    return self._convert_value(value_from_config, item_info["type"])
            return value_from_config # Return as string if no type info

        # If key not in live config, try to get it from default_data (with type conversion)
        if section in self.default_data:
            item_info = self.default_data[section].get(key)
            if item_info is not None:
                if isinstance(item_info, dict) and "type" in item_info and "default" in item_info:
                    return self._convert_value(item_info["default"], item_info["type"])
                else: # If item_info is a direct value in default_data
                    return item_info

        logger.warning(f"配置项未找到: Section='{section}', Key='{key}'")
        return fallback

    def _convert_value(self, value: Any, value_type: str) -> Any: # Added type hints
        """根据指定的类型转换值"""
        try:
            if value_type == "int":
                return int(value)
            elif value_type == "bool":
                return str(value).lower() == "true"
            elif value_type == "float":
                return float(value)
            elif value_type == "list":
                # Assuming value is a string like "item1,item2,item3"
                return [item.strip() for item in str(value).split(',')]
            elif value_type == "json":
                # Assuming value is a JSON string
                return json.loads(str(value))
            else: # Default to string if type is unknown or not specified as needing conversion
                return str(value)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"Error converting value '{value}' to type '{value_type}': {e}")
            # Fallback mechanism: return original value or raise error
            return value # Or raise a custom conversion error

    def write_conf(self, section: str, key: str, value: Any) -> None: # Added type hints
        """写入配置项"""
        if section not in self.config: # type: ignore[operator]
            try:
                self.config.add_section(section)
            except (configparser.DuplicateSectionError, ValueError) as e: # Handle potential errors
                logger.error(f"Error adding section {section}: {e}")
                return # Or raise
        self.config[section][key] = str(value) # ConfigParser stores everything as string
        self._write_config_to_file() # Write immediately after change


class ScheduleCenter:
    """
    课程表中心
    """
    def __init__(self, config_center_instance: ConfigCenter) -> None: # Added return type hint
        self.config_center: ConfigCenter = config_center_instance
        self.schedule_data: Optional[Dict[str, Any]] = None # schedule_data can be None initially
        self.update_schedule()

    def update_schedule(self) -> None: # Added return type hint
        """
        更新课程表
        """
        # Ensure read_conf returns a str for filename, or handle None/other types
        schedule_filename_any: Any = self.config_center.read_conf('General', 'schedule')
        schedule_filename: str = str(schedule_filename_any) if schedule_filename_any is not None else "default.json" # Fallback filename

        loaded_data = load_from_json(schedule_filename)
        if not isinstance(loaded_data, dict): # Ensure loaded_data is a dict
            logger.error(f"Failed to load schedule data or data is not a dictionary for {schedule_filename}")
            self.schedule_data = {} # Initialize to empty dict to prevent errors
        else:
            self.schedule_data = loaded_data

        if 'timeline' not in self.schedule_data: # Check after schedule_data is confirmed to be a dict
            self.schedule_data['timeline'] = {}

    def save_data(self, new_data: Dict[str, Any], filename: str) -> Optional[str]: # Added type hints
        if self.schedule_data is None: # Ensure schedule_data is initialized
            logger.error("Schedule data not loaded, cannot save.")
            return None # Indicate failure or handle as appropriate

        # Process timeline data specifically if present
        if 'timeline' in new_data and isinstance(new_data['timeline'], dict):
            if 'timeline' in self.schedule_data and isinstance(self.schedule_data['timeline'], dict):
                self.schedule_data['timeline'].update(new_data['timeline'])
            else: # If existing schedule_data['timeline'] is not a dict or doesn't exist
                self.schedule_data['timeline'] = new_data['timeline']

            # Update other data, excluding 'timeline' which was already handled
            temp_new_data = {k: v for k, v in new_data.items() if k != 'timeline'}
            self.schedule_data.update(temp_new_data)
        else: # If 'timeline' not in new_data or not a dict, update all new_data
            self.schedule_data.update(new_data)

        # 将更新后的数据保存回文件
        try:
            target_path: Path = self.config_center.base_directory / 'config' / 'schedule' / filename
            target_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
            with open(target_path, 'w', encoding='utf-8') as file_handle:
                json.dump(self.schedule_data, file_handle, ensure_ascii=False, indent=4)
            return f"数据已成功保存到 config/schedule/{filename}"
        except IOError as e: # More specific exception for file I/O
            logger.error(f"保存数据时出错: {e}")
            return None # Indicate failure
        except Exception as e: # Catch other potential errors
            logger.error(f"保存数据时发生未知错误: {e}")
            return None


def load_from_json(filename: str) -> Dict[str, Any]: # Added type hints
    """
    从 JSON 文件中加载数据。
    :param filename: 要加载的文件 (should be just the name, not path)
    :return: 返回从文件中加载的数据字典, or empty dict on error.
    """
    # Construct full path using base_directory from ConfigCenter or module level
    # Assuming module-level base_directory is intended here.
    file_path: Path = base_directory / 'config' / 'schedule' / filename
    try:
        with open(file_path, 'r', encoding='utf-8') as file_handle: # Renamed var
            data: Dict[str, Any] = json.load(file_handle)
        return data
    except FileNotFoundError:
        logger.error(f"文件未找到: {file_path}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"JSON 解码错误: {file_path}")
        return {}
    except Exception as e: # Catch other potential errors during loading
        logger.error(f"加载 JSON 文件时出错 {file_path}: {e}")
        return {}


def save_data_to_json(data: Dict[str, Any], filename: str) -> None: # Added type hints
    """
    将数据保存到 JSON 文件中。
    :param data: 要保存的数据字典
    :param filename: 要保存到的文件 (should be just the name, not path)
    """
    # Construct full path
    file_path: Path = base_directory / 'config' / 'schedule' / filename
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True) # Ensure target directory exists
        with open(file_path, 'w', encoding='utf-8') as file_handle: # Renamed var
            json.dump(data, file_handle, ensure_ascii=False, indent=4)
    except IOError as e: # More specific for file I/O issues
        logger.error(f"保存数据到 JSON 文件 {file_path} 时出错: {e}")
    except Exception as e: # Catch other potential errors
        logger.error(f"保存数据到 JSON 文件 {file_path} 时发生未知错误: {e}")


config_center: ConfigCenter = ConfigCenter(base_directory)
schedule_center: ScheduleCenter = ScheduleCenter(config_center)
# Ensure the callback is correctly assigned if it's meant to be dynamic or used.
# If schedule_center needs to be fully initialized before callback assignment, this is fine.
config_center.schedule_update_callback = schedule_center.update_schedule
