import json

from loguru import logger
import configparser as config

from basic_dirs import CONFIG_HOME, CW_HOME


path = CW_HOME / 'config.ini'


class ConfigCenter:
    """
    Config中心
    """
    def __init__(self):
        self.config = config.ConfigParser()
        self.config.read(path, encoding='utf-8')
        self.schedule_name = self.read_conf('General', 'schedule')
        self.old_schedule_name = self.schedule_name

        with open(CW_HOME / 'config/default_config.json', encoding="utf-8") as default:
            self.default_data = json.load(default)

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
        self.schedule_data = load_from_json(config_center.schedule_name)

    def save_data(self, new_data, filename):
        # 更新，添加或覆盖新的数据
        self.schedule_data.update(new_data)

        # 将更新后的数据保存回文件
        try:
            with open(CONFIG_HOME / 'config/schedule' / str(filename), 'w', encoding='utf-8') as file:
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
        with open(CONFIG_HOME / 'config/schedule' / str(filename), 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data
    except Exception as e:
        logger.error(f"加载数据时出错: {e}")
        return None


def save_data_to_json(new_data, filename):
    # 初始化 data_dict 为一个空字典
    data_dict = {}

    # 如果文件存在，先读取文件中的现有数据
    file_path = CONFIG_HOME / 'schedule' / str(filename)
    if file_path.exists():
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data_dict = json.load(file)
        except Exception as e:
            logger.error(f"读取现有数据时出错: {e}")

    # 更新 data_dict，添加或覆盖新的数据
    data_dict.update(new_data)

    # 将更新后的数据保存回文件
    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return f"数据已成功保存到 config/schedule/{filename}"
    except Exception as e:
        logger.error(f"保存数据时出错: {e}")


config_center = ConfigCenter()
schedule_center = ScheduleCenter()
