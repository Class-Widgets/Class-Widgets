import json
import os

from loguru import logger
import configparser as config

base_directory = os.path.dirname(os.path.abspath(__file__))

if base_directory.endswith('MacOS'):
    base_directory = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)), 'Resources')

path = f'{base_directory}/config.ini'


# CONFIG
# 读取config
def read_conf(section='General', key=''):
    data = config.ConfigParser()
    try:
        with open(path, 'r', encoding='utf-8') as configfile:
            data.read_file(configfile)
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.error(f'读取配置文件时出错: {e}')
        return None

    if section in data and key in data[section]:
        return data[section][key]
    elif section in data and key == '':
        return data[section]
    else:
        return None


# 写入config
def write_conf(section, key, value):
    data = config.ConfigParser()
    try:
        with open(path, 'r', encoding='utf-8') as configfile:
            data.read_file(configfile)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f'读取配置文件时出错: {e}')
        return None

    if section not in data:
        data.add_section(section)

    data.set(section, key, str(value))

    with open(path, 'w', encoding='utf-8') as configfile:
        data.write(configfile)


# JSON
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
