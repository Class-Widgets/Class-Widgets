import json
import os

from loguru import logger
import configparser as config

from basic_dirs import CONFIG_HOME, CW_HOME


path = CW_HOME / 'config.ini'


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
    with open(CW_HOME / 'config/default_config.json', encoding="utf-8") as default:
        default_data = json.load(default)

    if section in data and key in data[section]:
        return data[section][key]
    elif section in data and key == '':
        return data[section]
    elif section in default_data and key in default_data[section]:
        write_conf(section, key, default_data[section][key])
        logger.info('配置文件出现问题，已尝试修复')
        return default_data[section][key]
    elif section in default_data and key == '':
        write_conf(section, '', default_data[section])
        logger.info('配置文件出现问题，已尝试修复')
        return default_data[section]
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
