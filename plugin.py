import importlib
import json
from pathlib import Path
import shutil
from typing import Dict, List, Optional, Any

from loguru import logger

import conf

class PluginLoader:  # 插件加载器
    def __init__(self, p_mgr: Optional[Any] = None) -> None:
        self.plugins_settings: Dict[str, Any] = {}
        self.plugins_name: List[str] = []
        self.plugins_dict: Dict[str, Any] = {}
        self.manager = p_mgr

    def set_manager(self, p_mgr: Any) -> None:
        self.manager = p_mgr

    def load_plugins(self) -> List[str]:
        plugin_config = conf.load_plugin_config()
        safe_plugin_enabled = plugin_config.get('safe_plugin', False)
        if 'temp_disabled_plugins' in plugin_config:
            temp_disabled = plugin_config['temp_disabled_plugins']
            if temp_disabled:
                for plugin_name in temp_disabled:
                    if plugin_name not in plugin_config.get('enabled_plugins', []):
                        plugin_config['enabled_plugins'].append(plugin_name)
                plugin_config['temp_disabled_plugins'] = []
                conf.save_plugin_config(plugin_config)
        
        for folder in Path(conf.PLUGINS_DIR).iterdir():
            if folder.is_dir() and (folder / 'plugin.json').exists():
                self.plugins_name.append(folder.name)  # 检测所有插件

                if folder.name not in conf.load_plugin_config()['enabled_plugins']:
                    continue
                relative_path = conf.PLUGINS_DIR.name
                module_name = f"{relative_path}.{folder.name}"
                try:
                    module = importlib.import_module(module_name)

                    if hasattr(module, 'Settings'):  # 设置页
                        plugin_class = getattr(module, "Settings")  # 获取 Plugin 类
                        # 实例化插件
                        self.plugins_settings[folder.name] = plugin_class(f'{conf.PLUGINS_DIR}/{folder.name}')

                    if self.manager and hasattr(module, 'Plugin'):  # 插件入口
                        plugin_class = getattr(module, "Plugin")  # 获取 Plugin 类
                        # 实例化插件
                        self.plugins_dict[folder.name] = plugin_class(
                            self.manager.get_app_contexts(folder.name), self.manager.method
                        )

                    logger.success(f"加载插件成功：{module_name}")
                except (ImportError, FileNotFoundError) as e:
                    logger.warning(f"加载插件 {folder.name} 失败: {e}. 将禁用此插件")
                    plugin_config = conf.load_plugin_config()
                    if folder.name in plugin_config['enabled_plugins']:
                        plugin_config['enabled_plugins'].remove(folder.name)
                        conf.save_plugin_config(plugin_config)
                    if folder.name in self.plugins_name:
                        self.plugins_name.remove(folder.name)
                    if safe_plugin_enabled:
                        self._disable_plugin_safely(folder.name)
                        logger.warning(f"已临时禁用插件 {folder.name}")
                    continue
                except Exception as e:
                    logger.error(f"加载插件 {folder.name} 时发生未知错误: {e}")
                    if safe_plugin_enabled:
                        self._disable_plugin_safely(folder.name)
                        logger.warning(f"已临时禁用插件 {folder.name}")
                    # 大部分情况一般不会影响运行
                    continue
        return self.plugins_name

    def _disable_plugin_safely(self, plugin_name: str) -> None:
        """安全禁用插件"""
        plugin_config = conf.load_plugin_config()
        if plugin_name in plugin_config.get('enabled_plugins', []):
            plugin_config['enabled_plugins'].remove(plugin_name)
            if 'temp_disabled_plugins' not in plugin_config:
                plugin_config['temp_disabled_plugins'] = []
            if plugin_name not in plugin_config['temp_disabled_plugins']:
                plugin_config['temp_disabled_plugins'].append(plugin_name)
            conf.save_plugin_config(plugin_config)
            logger.info(f"插件 {plugin_name} 已被临时禁用")

    def run_plugins(self) -> None:
        for plugin in self.plugins_dict.values():
            plugin.execute()

    def update_plugins(self) -> None:
        for plugin in self.plugins_dict.values():
            if hasattr(plugin, 'update'):
                if self.manager:
                    plugin.update(self.manager.get_app_contexts())

    def delete_plugin(self, plugin_name: str) -> bool:
        plugin_dir = Path(conf.PLUGINS_DIR) / plugin_name
        if not plugin_dir.is_dir():
            logger.warning(f"插件目录 {plugin_dir} 不存在，无法删除。")
            return False
        widgets_to_remove = []
        if widgets_to_remove:
            try:
                widget_config_path = Path(conf.base_directory) / 'config' / 'widget.json'
                if widget_config_path.exists():
                    with open(widget_config_path, 'r', encoding='utf-8') as f:
                        widget_config = json.load(f)

                    original_widgets = widget_config.get('widgets', [])
                    # 过滤掉要移除的组件
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

        plugin_config = conf.load_plugin_config()
        if plugin_name in plugin_config.get('enabled_plugins', []):
            plugin_config['enabled_plugins'].remove(plugin_name)
            conf.save_plugin_config(plugin_config)
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

p_loader = PluginLoader()


if __name__ == '__main__':
    p_loader.load_plugins()
    p_loader.run_plugins()
