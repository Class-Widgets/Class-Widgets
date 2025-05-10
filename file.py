import json
import os
import sys
from pathlib import Path
from shutil import copy

from loguru import logger
import configparser as config

base_directory = os.path.dirname(os.path.abspath(__file__))
'''
if base_directory.endswith('MacOS'):
    base_directory = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)), 'Resources')
'''
path = f'{base_directory}/config.ini'


class ConfigCenter:
    """
    Config中心
    """
    def __init__(self):
        self.config = config.ConfigParser()
        self.config.read(path, encoding='utf-8')
        with open(f'{base_directory}/config/default_config.json', encoding="utf-8") as default:
            self.default_data = json.load(default)

        self.check_config()
        self.schedule_name = self.read_conf('General', 'schedule')
        self.old_schedule_name = self.schedule_name

    def update_conf(self):
        try:
            self.config.read_file(open(path, 'r', encoding='utf-8'))

            self.schedule_name = self.read_conf('General', 'schedule')
            if self.schedule_name != self.old_schedule_name:
                logger.info(f'已切换课程表: {self.schedule_name}')
                schedule_center.update_schedule()
                self.old_schedule_name = self.schedule_name
        except Exception as e:
            logger.error(f'更新配置文件时出错: {e}')

    def read_conf(self, section='General', key=''):
        if section in self.config and key in self.config[section]:
            return self.config[section][key]
        elif section in self.config and key == '':
            return dict(self.config[section])
        elif section in self.default_data and key in self.default_data[section]:
            logger.info('配置文件出现问题，已尝试修复')
            self.write_conf(section, key, self.default_data[section][key])
            return self.default_data[section][key]
        elif section in self.default_data and key == '':
            logger.info('配置文件出现问题，已尝试修复')
            self.write_conf(section, '', self.default_data[section])
            return dict(self.default_data[section])
        else:
            return None

    def write_conf(self, section, key, value):
        if section not in self.config:
            self.config.add_section(section)

        self.config.set(section, key, str(value))

        with open(path, 'w', encoding='utf-8') as configfile:
            self.config.write(configfile)

    def check_config(self):
        if not os.path.exists(path):  # 如果配置文件不存在，则copy默认配置文件
            self.config.read_dict(self.default_data)
            with open(path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            if sys.platform != 'win32':
                self.config.set('General', 'hide_method', '2')
                with open(path, 'w', encoding='utf-8') as configfile:
                    self.config.write(configfile)
            logger.info("配置文件不存在，已创建并写入默认配置。")
            copy(f'{base_directory}/config/default.json', f'{base_directory}/config/schedule/新课表 - 1.json')
        else:
            with open(path, 'r', encoding='utf-8') as configfile:
                self.config.read_file(configfile)

            if self.config['Other']['version'] != self.default_data['Other']['version']:  # 如果配置文件版本不同，则更新配置文件
                logger.info(f"配置文件版本不同，将重新适配")
                try:
                    for section, options in self.default_data.items():
                        if section not in self.config:
                            self.config[section] = options
                        else:
                            for key, value in options.items():
                                if key not in self.config[section]:
                                    self.config[section][key] = str(value)
                    self.config.set('Other', 'version', self.default_data['Other']['version'])
                    with open(path, 'w', encoding='utf-8') as configfile:
                        self.config.write(configfile)
                    logger.info(f"配置文件已更新")
                except Exception as e:
                    logger.error(f"配置文件更新失败: {e}")

            if not os.path.exists(f"{base_directory}/config/schedule/{self.read_conf('General', 'schedule')}"):
                # 如果config.ini课程表不存在，则创建

                schedule_config = []
                # 遍历目标目录下的所有文件
                for file_name in os.listdir(f'{base_directory}/config/schedule'):
                    # 找json
                    if file_name.endswith('.json') and file_name != 'backup.json':
                        # 将文件路径添加到列表
                        schedule_config.append(file_name)
                if not schedule_config:
                    copy(f'{base_directory}/config/default.json',
                         f'{base_directory}/config/schedule/{self.read_conf("General", "schedule")}')
                    logger.info(f"课程表不存在，已创建默认课程表")
                else:
                    self.write_conf('General', 'schedule', schedule_config[0])
            print(os.path.join(os.getcwd(), 'config', 'schedule'))

        # 判断是否存在 Plugins 文件夹
        plugins_dir = Path(base_directory) / 'plugins'
        if not plugins_dir.exists():
            plugins_dir.mkdir()
            logger.info("Plugins 文件夹不存在，已创建。")

        # 判断 Plugins 文件夹内是否存在 plugins_from_pp.json 文件
        plugins_file = plugins_dir / 'plugins_from_pp.json'
        if not plugins_file.exists():
            with open(plugins_file, 'w', encoding='utf-8') as file:
                # 使用 indent=4 来缩进，并确保数组元素在多行显示
                json.dump({"plugins": []}, file, ensure_ascii=False, indent=4)
            logger.info("plugins_from_pp.json 文件不存在，已创建。")


class ScheduleCenter:
    """
    课程表中心
    """
    def __init__(self):
        self.schedule_data = None
        self.update_schedule()

    def update_schedule(self):
        """
        更新课程表
        """
        self.schedule_data:dict = load_from_json(config_center.schedule_name)
        if self.schedule_data.get('url', None) is None:
            self.schedule_data['url'] = 'local'
            self.save_data(self.schedule_data, config_center.schedule_name)

    def update_url(self, url):
        """
        更新课程表url
        """
        self.schedule_data['url'] = url
        self.save_data(self.schedule_data, config_center.schedule_name)

    def save_data(self, new_data, filename):
        # 更新，添加或覆盖新的数据
        self.schedule_data.update(new_data)

        # 将更新后的数据保存回文件
        try:
            with open(f'{base_directory}/config/schedule/{filename}', 'w', encoding='utf-8') as file:
                json.dump(self.schedule_data, file, ensure_ascii=False, indent=4)
            return f"数据已成功保存到 config/schedule/{filename}"
        except Exception as e:
            logger.error(f"保存数据时出错: {e}")
    


def load_from_json(filename):
    """
    从 JSON 文件中加载数据。
    :param filename: 要加载的文件
    :return: 返回从文件中加载的数据字典
    """
    try:
        with open(f'{base_directory}/config/schedule/{filename}', 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data
    except Exception as e:
        logger.error(f"加载数据时出错: {e}")
        return None


def save_data_to_json(new_data, filename):
    # 初始化 data_dict 为一个空字典
    data_dict = {}

    # 如果文件存在，先读取文件中的现有数据
    if os.path.exists(f'{base_directory}/config/schedule/{filename}'):
        try:
            with open(f'{base_directory}/config/schedule/{filename}', 'r', encoding='utf-8') as file:
                data_dict = json.load(file)
        except Exception as e:
            logger.error(f"读取现有数据时出错: {e}")

    # 更新 data_dict，添加或覆盖新的数据
    data_dict.update(new_data)

    # 将更新后的数据保存回文件
    try:
        with open(f'{base_directory}/config/schedule/{filename}', 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return f"数据已成功保存到 config/schedule/{filename}"
    except Exception as e:
        logger.error(f"保存数据时出错: {e}")


config_center = ConfigCenter()
schedule_center = ScheduleCenter()
