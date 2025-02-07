import importlib
from pathlib import Path

from loguru import logger

import conf


class PluginLoader:  # 插件加载器
    def __init__(self, p_mgr=None):
        self.plugins_settings = {}
        self.plugins = []
        self.plugins_dict = {}
        self.manager = p_mgr

    def set_manager(self, p_mgr):
        self.manager = p_mgr

    def load_plugins(self):
        for folder in Path(conf.PLUGINS_DIR).iterdir():
            if folder.is_dir() and (folder / 'plugin.json').exists():
                if folder.name not in conf.load_plugin_config()['enabled_plugins']:
                    continue
                relative_path = conf.PLUGINS_DIR.name
                module_name = f"{relative_path}.{folder.name}"
                module = importlib.import_module(module_name)

                if hasattr(module, 'Settings'):
                    plugin_class = getattr(module, "Settings")  # 获取 Plugin 类
                    # 实例化插件
                    self.plugins_settings[folder.name] = plugin_class(f'{conf.PLUGINS_DIR}/{folder.name}')

                if not self.manager:
                    continue
                if hasattr(module, 'Plugin'):
                    plugin_class = getattr(module, "Plugin")  # 获取 Plugin 类
                    # 实例化插件
                    self.plugins.append(plugin_class(self.manager.get_app_contexts(folder.name), self.manager.method))

                logger.success(f"加载插件成功：{module_name}")
        return self.plugins

    def run_plugins(self):
        for plugin in self.plugins:
            plugin.execute()

    def update_plugins(self):
        for plugin in self.plugins:
            if hasattr(plugin, 'update'):
                plugin.update(self.manager.get_app_contexts())


p_loader = PluginLoader()


if __name__ == '__main__':
    p_loader.load_plugins()
    p_loader.run_plugins()
