import json
import os
import sys
from pathlib import Path
from shutil import copy
from typing import Dict, Any, Optional, Union, Callable, List

from loguru import logger
import configparser
from packaging.version import Version
import json

from PyQt5.QtCore import QCoreApplication


base_directory = Path(os.path.dirname(os.path.abspath(__file__)))
'''
if str(base_directory).endswith('MacOS'):
    base_directory = (base_directory.parent / 'Resources').resolve()
'''
config_path = base_directory / 'config.ini'




class ConfigCenter:
    """
    Config中心
    """
    def __init__(self, base_directory: Path, schedule_update_callback: Optional[Callable[[], None]] = None) -> None:
        self.base_directory = base_directory
        self.config_version = 1
        self.config_file_name = 'config.ini'
        self.user_config_path = self.base_directory / self.config_file_name
        self.default_config_path = self.base_directory / 'config' / 'default_config.json'
        self.config = configparser.ConfigParser()
        self.default_data: Dict[str, Any] = {}
        self.schedule_update_callback = schedule_update_callback

        self._load_default_config()
        self._load_user_config()
        self._check_and_migrate_config()

        self.schedule_name = self.read_conf('General', 'schedule')
        self.old_schedule_name = self.schedule_name

    def _load_default_config(self) -> None:
        """加载默认配置文件"""
        try:
            with open(self.default_config_path, encoding="utf-8") as default:
                self.default_data = json.load(default)
        except Exception as e:
            logger.error(f"加载默认配置文件失败: {e}")
            self.default_data = {}
            from qfluentwidgets import Dialog
            from PyQt5.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)
            dlg = Dialog(
                QCoreApplication.translate("file", 'Class Widgets 启动失败w(ﾟДﾟ)w'),
                QCoreApplication.translate("file", '加载默认配置文件失败,请检查文件完整性或尝试重新安装。\n错误信息: {e}')
            )
            dlg.yesButton.setText(QCoreApplication.translate("file", '好'))
            dlg.cancelButton.hide()
            dlg.buttonLayout.insertStretch(0, 1)
            dlg.setFixedWidth(550)
            dlg.exec()
            import utils
            utils.stop(0)

    def _load_user_config(self) -> None:
        """加载用户配置文件"""
        try:
            self.config.read(self.user_config_path, encoding='utf-8')
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")

    def _migrate_config(self) -> None:
        """迁移配置文件（当配置文件版本不一致时）"""
        logger.warning(f"配置文件版本不同,重新适配")
        try:
            self._perform_specific_migrations()
            for section, options in self.default_data.items():
                if section not in self.config:
                    self.config.add_section(section)
                    for key, value in options.items():
                        self.config[section][key] = str(value)
                    logger.debug(f"添加新的配置节: {section}")
                else:
                    for key, value in options.items():
                        if key not in self.config[section]:
                            self.config[section][key] = str(value)
                            logger.debug(f"添加新的配置项: {section}.{key}")

            version_from_default = self.default_data.get('Version', {}).get('version')
            if version_from_default:
                self.config.set('Version', 'version', version_from_default)
            self._write_config_to_file()
            logger.success(f"配置文件已更新")
        except Exception as e:
            logger.error(f"配置文件更新失败: {e}")

    def _perform_specific_migrations(self) -> None:
        """执行特定的配置迁移规则"""
        migration_rules = [
            {
                'old_section': 'General',
                'old_key': 'time_offset',
                'new_section': 'Time', 
                'new_key': 'time_offset',
                'remove_old': True
            },
            {
                'old_section': 'Other',
                'old_key': 'auto_check_update',
                'new_section': 'Version',
                'new_key': 'auto_check_update', 
                'remove_old': True
            }
        ]
        self.migrate_config(migration_rules=migration_rules)

    def _check_schedule_config(self) -> None:
        """检查课程表配置文件"""
        schedule_dir = base_directory / 'config' / 'schedule'
        schedule_name = self.read_conf('General', 'schedule', '新课表 - 1.json')
        current_schedule_file = schedule_dir / schedule_name

        if not current_schedule_file.exists():
            schedule_config = []
            for file_name in schedule_dir.iterdir():
                if file_name.suffix == '.json' and file_name.name != 'backup.json':
                    schedule_config.append(file_name.name)
            if not schedule_config:
                copy(base_directory / 'config' / 'default.json',
                     schedule_dir / schedule_name)
                logger.info(f"课程表不存在,已创建默认课程表")
            else:
                self.write_conf('General', 'schedule', schedule_config[0])
        print(Path.cwd() / 'config' / 'schedule')

    def _check_plugins_directory(self) -> None:
        """检查插件目录和文件"""
        plugins_dir = base_directory / 'plugins'
        if not plugins_dir.exists():
            plugins_dir.mkdir()
            logger.info("Plugins 文件夹不存在，已创建。")

        plugins_file = plugins_dir / 'plugins_from_pp.json'
        if not plugins_file.exists():
            with open(plugins_file, 'w', encoding='utf-8') as file:
                json.dump({"plugins": []}, file, ensure_ascii=False, indent=4)
            logger.info("plugins_from_pp.json 文件不存在，已创建。")

    def _write_config_to_file(self) -> None:
        """将当前配置写入文件"""
        with open(self.user_config_path, 'w', encoding='utf-8') as configfile:
            self.config.write(configfile)

    def migrate_config_item(self, old_section: str, old_key: str, new_section: str, new_key: str, 
                           transform_func: Optional[Callable[[Any], Any]] = None, 
                           remove_old: bool = True) -> bool:
        """配置项迁移函数
        
        Args:
            old_section: 原配置节名
            old_key: 原配置键名
            new_section: 新配置节名
            new_key: 新配置键名
            transform_func: 值转换函数，可选
            remove_old: 是否删除原配置项，默认True
            
        Returns:
            bool: 迁移是否成功
        """
        try:
            if old_section not in self.config or old_key not in self.config[old_section]:
                logger.debug(f"原配置项不存在: {old_section}.{old_key}")
                return False
            old_value = self.config[old_section][old_key]
            new_value = transform_func(old_value) if transform_func else old_value
            if new_section not in self.config:
                self.config.add_section(new_section)
                logger.debug(f"创建新配置节: {new_section}")
            self.config[new_section][new_key] = str(new_value)
            logger.debug(f"配置项迁移: {old_section}.{old_key} -> {new_section}.{new_key} (值: {old_value} -> {new_value})")
            if remove_old:
                del self.config[old_section][old_key]
                logger.debug(f"已删除原配置项: {old_section}.{old_key}")
                if not self.config[old_section]:
                    self.config.remove_section(old_section)
                    logger.debug(f"已删除空配置节: {old_section}")
            return True
        except Exception as e:
            logger.error(f"配置项迁移失败 {old_section}.{old_key} -> {new_section}.{new_key}: {e}")
            return False
    
    def migrate_config(self, old_section: str = None, old_key: str = None, new_section: str = None, 
                       new_key: str = None, transform_func: Optional[Callable[[Any], Any]] = None, 
                       remove_old: bool = True, migration_rules: Optional[List[Dict[str, Any]]] = None) -> Union[bool, Dict[str, bool]]:
        """配置迁移

        Args:
            # 单个配置项迁移参数
            old_section: 原配置节名
            old_key: 原配置键名
            new_section: 新配置节名
            new_key: 新配置键名
            transform_func: 值转换函数，可选
            remove_old: 是否删除原配置项，默认True
            # 批量迁移参数
            migration_rules: 迁移规则列表，每个规则为字典，包含:
                - old_section: 原配置节
                - old_key: 原配置键
                - new_section: 新配置节
                - new_key: 新配置键
                - transform_func: 转换函数 (可选)
                - remove_old: 是否删除原配置 (可选,默认True)
                
        Returns:
            Union[bool, Dict[str, bool]]: 单个迁移返回bool，批量迁移返回Dict[str, bool]
            
        Raises:
            ValueError: 当参数不正确时抛出异常
        """
        if migration_rules is not None:
            if not isinstance(migration_rules, list):
                raise ValueError("migration_rules 必须是列表类型")
            return self._batch_migrate_internal(migration_rules)
        if not all([old_section, old_key, new_section, new_key]):
            raise ValueError("需提供完整参数")
        result = self.migrate_config_item(old_section, old_key, new_section, new_key, 
                                         transform_func, remove_old)
        if result:
            self._write_config_to_file()
        return result
    
    def _batch_migrate_internal(self, migration_rules: List[Dict[str, Any]]) -> Dict[str, bool]:
        results = {}
        for i, rule in enumerate(migration_rules):
            rule_name = f"{rule['old_section']}.{rule['old_key']}->{rule['new_section']}.{rule['new_key']}"
            try:
                success = self.migrate_config_item(
                    old_section=rule['old_section'],
                    old_key=rule['old_key'],
                    new_section=rule['new_section'],
                    new_key=rule['new_key'],
                    transform_func=rule.get('transform_func'),
                    remove_old=rule.get('remove_old', True)
                )
                results[rule_name] = success
            except Exception as e:
                logger.error(f"批量迁移规则 {i} 执行失败: {e}")
                results[rule_name] = False
        if any(results.values()):
            self._write_config_to_file()
            logger.debug(f"批量配置迁移完成,成功: {sum(results.values())}/{len(results)}")
        return results

    def _check_and_migrate_config(self) -> None:
        self._check_schedule_config()
        self._check_plugins_directory()

    def update_conf(self) -> None:
        """重新加载配置文件并更新相关状态"""
        try:
            self._load_user_config()

            new_schedule_name = self.read_conf('General', 'schedule')
            if new_schedule_name != self.old_schedule_name:
                logger.info(f'已切换到课程表: {new_schedule_name}')

                self.old_schedule_name = new_schedule_name
        except Exception as e:
            logger.error(f'更新配置文件时出错: {e}')

    def read_conf(self, section: str = 'General', key: str = '', fallback: Any = None) -> Union[str, Any]:
        """读取配置项，并根据默认配置中的类型信息进行转换"""
        if section not in self.config and section not in self.default_data:
            logger.warning(f"配置节未找到: Section='{section}'")
            if not key:
                self.config.add_section(section)
                logger.info(f"已为 '{section}' 添加空节")
                return {}
            return fallback
        if not key:
            if section in self.config:
                return dict(self.config[section])
            else:
                converted_section = {}
                for k, item_info in self.default_data.get(section, {}).items():
                    if isinstance(item_info, dict) and "type" in item_info and "default" in item_info:
                        converted_section[k] = self._convert_value(item_info["default"], item_info["type"])
                    else:
                        converted_section[k] = item_info
                return converted_section
        if section in self.config:
            value = self.config[section].get(key)
            if value is not None:
                return value
        if section in self.default_data:
            item_info = self.default_data[section].get(key)
            if item_info is not None:
                if (translation := QCoreApplication.translate('config', f'{section}.{key}')) != f'{section}.{key}':
                    return translation
                if isinstance(item_info, dict) and "type" in item_info and "default" in item_info:
                    return self._convert_value(item_info["default"], item_info["type"])
                else:
                    return item_info
        logger.warning(f"配置项未找到: Section='{section}', Key='{key}'")
        return fallback

    def _convert_value(self, value: Any, value_type: str) -> Any:
        """根据指定的类型转换值"""
        if value is None:
            if value_type == "int":
                return 0
            elif value_type == "bool":
                return False
            elif value_type == "float":
                return 0.0
            elif value_type == "list":
                return []
            elif value_type == "json":
                return {}
            else:
                return ""
        try:
            if value_type == "int":
                return int(value)
            elif value_type == "bool":
                return str(value).lower() == "true"
            elif value_type == "float":
                return float(value)
            elif value_type == "list":
                return [item.strip() for item in str(value).split(',')]
            elif value_type == "json":
                return json.loads(str(value))
            else:
                return str(value)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            logger.warning(f"配置值转换失败: {value} -> {value_type}, 错误: {e}")
            if value_type == "int":
                return 0
            elif value_type == "bool":
                return False
            elif value_type == "float":
                return 0.0
            elif value_type == "list":
                return []
            elif value_type == "json":
                return {}
            else:
                return str(value) if value is not None else ""

    def write_conf(self, section: str, key: str, value: Any) -> None:
        """写入配置项"""
        if section not in self.config:
            self.config.add_section(section)
        self.config[section][key] = str(value)
        with open(self.user_config_path, 'w', encoding='utf-8') as configfile:
            self.config.write(configfile)


class ScheduleCenter:
    """
    课程表中心
    """
    def __init__(self, config_center_instance: ConfigCenter) -> None:
        self.config_center = config_center_instance
        self.schedule_data: Dict[str, Any] = {}
        self.update_schedule()

    def update_schedule(self) -> None:
        """
        更新课程表
        """
        self.schedule_data = load_from_json(self.config_center.read_conf('General', 'schedule'))
        if 'timeline' not in self.schedule_data:
            self.schedule_data['timeline'] = {}
        if self.schedule_data.get('url', None) is None:
            self.schedule_data['url'] = 'local'
            self.save_data(self.schedule_data, config_center.schedule_name)

    def update_url(self, url: str) -> None:
        """
        更新课程表url
        """
        self.schedule_data['url'] = url
        self.save_data(self.schedule_data, config_center.schedule_name)

    def save_data(self, new_data: Dict[str, Any], filename: str) -> Optional[str]:
        if 'timeline' in new_data and isinstance(new_data['timeline'], dict):
            if 'timeline' in self.schedule_data and isinstance(self.schedule_data['timeline'], dict):
                self.schedule_data['timeline'].update(new_data['timeline'])
            else:
                self.schedule_data['timeline'] = new_data['timeline']
            temp_new_data = new_data.copy()
            del temp_new_data['timeline']
            self.schedule_data.update(temp_new_data)
        else:
            self.schedule_data.update(new_data)

        # 将更新后的数据保存回文件
        try:
            with open(base_directory / 'config' / 'schedule' / filename, 'w', encoding='utf-8') as file:
                json.dump(self.schedule_data, file, ensure_ascii=False, indent=4)
            return f"数据已成功保存到 config/schedule/{filename}"
        except Exception as e:
            logger.error(f"保存数据时出错: {e}")
            return None


def load_from_json(filename: str) -> Dict[str, Any]:
    """
    从 JSON 文件中加载数据。
    :param filename: 要加载的文件
    :return: 返回从文件中加载的数据字典
    """
    try:
        with open(base_directory / 'config' / 'schedule' / filename, 'r', encoding='utf-8') as file:
            data: Dict[str, Any] = json.load(file)
        return data
    except FileNotFoundError:
        logger.error(f"文件未找到: {filename}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"JSON 解码错误: {filename}")
        return {}
    except Exception as e:
        logger.error(f"加载 JSON 文件时出错: {e}")
        return {}


def save_data_to_json(data: Dict[str, Any], filename: str) -> None:
    """
    将数据保存到 JSON 文件中。
    :param data: 要保存的数据字典
    :param filename: 要保存到的文件
    """
    try:
        with open(base_directory / 'config' / 'schedule' / filename, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"保存数据到 JSON 文件时出错: {e}")


config_center = ConfigCenter(base_directory)
schedule_center = ScheduleCenter(config_center)
config_center.schedule_update_callback = schedule_center.update_schedule

if __name__ == '__main__':
    QCoreApplication.translate('config', 'General.schedule')
    QCoreApplication.translate('config', 'TTS.language')
    QCoreApplication.translate('config', 'TTS.attend_class')
    QCoreApplication.translate('config', 'TTS.finish_class')
    QCoreApplication.translate('config', 'TTS.prepare_class')
    QCoreApplication.translate('config', 'TTS.after_school')
    QCoreApplication.translate('config', 'Weather.api')
    QCoreApplication.translate('config', 'Plugin.mirror')
