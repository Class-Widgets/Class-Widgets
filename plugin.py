import importlib
import os
from pathlib import Path

from loguru import logger

import conf
from file import base_directory


class PluginLoader:  # 插件加载器
    def __init__(self, p_mgr=None):
        self.plugins_settings = {}
        self.plugins_name = []
        self.plugins_dict = {}
        self.manager = p_mgr

    def set_manager(self, p_mgr):
        self.manager = p_mgr

    def load_plugins(self):
        for folder in Path(conf.PLUGINS_DIR).iterdir():
            if folder.is_dir() and (folder / 'plugin.json').exists():
                self.plugins_name.append(folder.name)  # 检测所有插件

                if folder.name not in conf.load_plugin_config()['enabled_plugins']:
                    continue
                relative_path = conf.PLUGINS_DIR.name
                module_name = f"{relative_path}.{folder.name}"
                module = importlib.import_module(module_name)

                if hasattr(module, 'Settings'):  # 设置页
                    plugin_class = getattr(module, "Settings")  # 获取 Plugin 类
                    # 实例化插件
                    self.plugins_settings[folder.name] = plugin_class(os.path.normpath(os.path.join(base_directory, conf.PLUGINS_DIR, folder.name)))

                if not self.manager:
                    continue
                if hasattr(module, 'Plugin'):  # 插件入口
                    plugin_class = getattr(module, "Plugin")  # 获取 Plugin 类
                    # 实例化插件
                    self.plugins_dict[folder.name] = plugin_class(
                        self.manager.get_app_contexts(folder.name), self.manager.method
                    )

                logger.success(f"加载插件成功：{module_name}")
        return self.plugins_name

    def run_plugins(self):
        for plugin in self.plugins_dict.values():
            plugin.execute()

    def update_plugins(self):
        for plugin in self.plugins_dict.values():
            if hasattr(plugin, 'update'):
                plugin.update(self.manager.get_app_contexts())


p_loader = PluginLoader()


if __name__ == '__main__':
    p_loader.load_plugins()
    p_loader.run_plugins()
