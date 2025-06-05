import importlib
import json
from pathlib import Path
import shutil
from typing import Dict, List, Any, Optional, Type # Added for type hints

from loguru import logger
from PyQt5.QtWidgets import QWidget # For type hinting settings UI

import conf

# Forward declaration for PluginManager if it's imported from elsewhere
# For now, assume it's a type that will be available or use 'Any'
# from main import PluginManager # Example if PluginManager is in main.py
PluginManagerType = Any # Placeholder until actual PluginManager type is known

class PluginBase: # Base class for plugins to define expected methods
    def __init__(self, app_context: Dict[str, Any], method_bindings: Any):
        pass
    def execute(self) -> None:
        pass
    def update(self, app_context: Dict[str, Any]) -> None:
        pass

class PluginSettingsBase(QWidget): # Base class for plugin settings UI
     def __init__(self, plugin_path: str):
        super().__init__()
        pass


class PluginLoader:  # 插件加载器
    def __init__(self, p_mgr: Optional[PluginManagerType] = None) -> None: # Added types
        self.plugins_settings: Dict[str, PluginSettingsBase] = {} # Stores instances of plugin settings UI classes
        self.plugins_name: List[str] = [] # List of detected plugin folder names
        self.plugins_dict: Dict[str, PluginBase] = {} # Stores instances of main plugin classes
        self.manager: Optional[PluginManagerType] = p_mgr

    def set_manager(self, p_mgr: PluginManagerType) -> None: # Added types
        self.manager = p_mgr

    def load_plugins(self) -> List[str]: # Added return type
        # conf.PLUGINS_DIR is str, Path object expected
        plugins_dir_path = Path(str(conf.PLUGINS_DIR)) # type: ignore[attr-defined]

        folder: Path
        for folder in plugins_dir_path.iterdir():
            if folder.is_dir() and (folder / 'plugin.json').exists():
                self.plugins_name.append(folder.name)  # 检测所有插件

                plugin_config_data: Dict[str, Any] = conf.load_plugin_config() # type: ignore[no-untyped-call]
                enabled_plugin_list: List[str] = plugin_config_data.get('enabled_plugins', [])

                if folder.name not in enabled_plugin_list:
                    continue

                # conf.PLUGINS_DIR is str
                relative_path: str = Path(str(conf.PLUGINS_DIR)).name # type: ignore[attr-defined]
                module_name: str = f"{relative_path}.{folder.name}"

                try:
                    module: Any = importlib.import_module(module_name)

                    if hasattr(module, 'Settings'):  # 设置页
                        settings_class: Type[PluginSettingsBase] = getattr(module, "Settings")  # 获取 Settings 类
                        # 实例化插件设置UI
                        # conf.PLUGINS_DIR is str
                        plugin_path_str = str(Path(str(conf.PLUGINS_DIR)) / folder.name) # type: ignore[attr-defined]
                        self.plugins_settings[folder.name] = settings_class(plugin_path_str)


                    if self.manager and hasattr(module, 'Plugin'):  # 插件入口
                        plugin_class: Type[PluginBase] = getattr(module, "Plugin")  # 获取 Plugin 类
                        # 实例化插件
                        # Assuming self.manager.get_app_contexts and self.manager.method are correctly defined
                        app_contexts = self.manager.get_app_contexts(folder.name) # type: ignore
                        method_bindings = self.manager.method # type: ignore
                        self.plugins_dict[folder.name] = plugin_class(app_contexts, method_bindings)

                    logger.success(f"加载插件成功：{module_name}")
                except (ImportError, FileNotFoundError) as e:
                    logger.warning(f"加载插件 {folder.name} 失败: {e}. 可能缺少文件或依赖项。将禁用此插件。")
                    # plugin_config already loaded
                    if folder.name in enabled_plugin_list:
                        enabled_plugin_list.remove(folder.name)
                        plugin_config_data['enabled_plugins'] = enabled_plugin_list
                        conf.save_plugin_config(plugin_config_data) # type: ignore[no-untyped-call]
                    if folder.name in self.plugins_name: # Also remove from detected list
                        self.plugins_name.remove(folder.name)
                    continue
                except Exception as e:
                    logger.error(f"加载插件 {folder.name} 时发生未知错误: {e}")
                    # 大部分情况一般不会影响运行
                    continue
        return self.plugins_name

    def run_plugins(self) -> None: # Added return type
        plugin_instance: PluginBase
        for plugin_instance in self.plugins_dict.values():
            try:
                plugin_instance.execute()
            except Exception as e:
                logger.error(f"执行插件 {type(plugin_instance).__name__} 时出错: {e}")


    def update_plugins(self) -> None: # Added return type
        plugin_instance: PluginBase
        for plugin_instance in self.plugins_dict.values():
            if hasattr(plugin_instance, 'update'):
                try:
                    if self.manager:
                        plugin_instance.update(self.manager.get_app_contexts()) # type: ignore
                    else:
                        logger.warning(f"PluginLoader manager not set, cannot update plugin {type(plugin_instance).__name__}")
                except Exception as e:
                     logger.error(f"更新插件 {type(plugin_instance).__name__} 时出错: {e}")


    def delete_plugin(self, plugin_name: str) -> bool: # Added types
        # conf.PLUGINS_DIR is str
        plugin_dir: Path = Path(str(conf.PLUGINS_DIR)) / plugin_name # type: ignore[attr-defined]
        if not plugin_dir.is_dir():
            logger.warning(f"插件目录 {plugin_dir} 不存在，无法删除。")
            return False

        # widgets_to_remove logic seems incomplete/commented out in original,
        # assuming it's not critical path for now or handled elsewhere if needed.
        widgets_to_remove: List[str] = []
        if widgets_to_remove: # This block will currently not run
            try:
                # conf.base_directory is Path
                widget_config_path: Path = Path(conf.base_directory) / 'config' / 'widget.json' # type: ignore[attr-defined]
                if widget_config_path.exists():
                    with open(widget_config_path, 'r', encoding='utf-8') as f:
                        widget_config: Dict[str, Any] = json.load(f)

                    original_widgets: List[str] = widget_config.get('widgets', [])
                    widget_config['widgets'] = [w for w in original_widgets if w not in widgets_to_remove]

                    with open(widget_config_path, 'w', encoding='utf-8') as f:
                        json.dump(widget_config, f, ensure_ascii=False, indent=4)
                    logger.info(f"已从 config/widget.json 中移除插件 {plugin_name} 的关联组件: {widgets_to_remove}")
                else:
                    logger.warning(f"主配置文件 config/widget.json 不存在，无法移除插件组件。")
            except Exception as e:
                logger.error(f"更新 config/widget.json 失败: {e}")

        if plugin_name in self.plugins_dict:
            del self.plugins_dict[plugin_name]
            logger.info(f"已移除正在运行的插件实例: {plugin_name}")
        if plugin_name in self.plugins_settings:
            del self.plugins_settings[plugin_name]
            logger.info(f"已移除插件设置实例: {plugin_name}")

        plugin_config_on_delete: Dict[str, Any] = conf.load_plugin_config() # type: ignore[no-untyped-call]
        enabled_plugins_on_delete: List[str] = plugin_config_on_delete.get('enabled_plugins', [])
        if plugin_name in enabled_plugins_on_delete:
            enabled_plugins_on_delete.remove(plugin_name)
            plugin_config_on_delete['enabled_plugins'] = enabled_plugins_on_delete
            conf.save_plugin_config(plugin_config_on_delete) # type: ignore[no-untyped-call]
            logger.info(f"已从启用插件列表中移除: {plugin_name}")

        if plugin_name in self.plugins_name:
            self.plugins_name.remove(plugin_name)

        try:
            shutil.rmtree(plugin_dir)
            logger.success(f"插件 {plugin_name} 已成功删除。")
            return True
        except Exception as e:
            logger.error(f"删除插件目录 {plugin_dir} 失败: {e}")
            return False

p_loader: PluginLoader = PluginLoader()


if __name__ == '__main__':
    # Example usage, assuming some p_mgr is available for testing
    # from main import PluginManager # Hypothetical import
    # manager_instance = PluginManager()
    # p_loader.set_manager(manager_instance)
    p_loader.load_plugins()
    p_loader.run_plugins()
