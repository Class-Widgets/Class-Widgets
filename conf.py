import json
import os
import sys
import configparser as config
from pathlib import Path
from shutil import copy

from datetime import datetime
from loguru import logger
from file import base_directory, read_conf, write_conf, save_data_to_json, path

import list

if os.name == 'nt':
    from win32com.client import Dispatch

conf = config.ConfigParser()
name = 'Class Widgets'

PLUGINS_DIR = Path(base_directory) / 'plugins'

# app 图标
if os.name == 'nt':
    app_icon = os.path.join(base_directory, 'img', 'favicon.ico')
elif os.name == 'darwin':
    app_icon = os.path.join(base_directory, 'img', 'favicon.icns')
else:
    app_icon = os.path.join(base_directory, 'img', 'favicon.png')


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


def load_theme_config(theme):
    try:
        with open(f'{base_directory}/ui/{theme}/theme.json', 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        logger.warning(f"主题配置文件 {theme} 不存在，返回默认配置")
        return f'{base_directory}/ui/default/theme.json'
    except Exception as e:
        logger.error(f"加载主题数据时出错: {e}")
        return None


def load_plugin_config():
    try:
        if os.path.exists(f'{base_directory}/config/plugin.json'):  # 如果配置文件存在
            with open(f'{base_directory}/config/plugin.json', 'r', encoding='utf-8') as file:
                data = json.load(file)
        else:
            with open(f'{base_directory}/config/plugin.json', 'w', encoding='utf-8') as file:
                data = {"enabled_plugins": []}
                json.dump(data, file, ensure_ascii=False, indent=4)
        return data
    except Exception as e:
        logger.error(f"加载启用插件数据时出错: {e}")
        return None


def save_plugin_config(data):
    data_dict = load_plugin_config()
    data_dict.update(data)
    try:
        with open(f'{base_directory}/config/plugin.json', 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"保存启用插件数据时出错: {e}")
        return False


def save_installed_plugin(data):
    data = {"plugins": data}
    try:
        with open(f'{base_directory}/plugins/plugins_from_pp.json', 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"保存已安装插件数据时出错: {e}")
        return False


def load_theme_width(theme):
    try:
        with open(f'{base_directory}/ui/{theme}/theme.json', 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data['widget_width']
    except Exception as e:
        logger.error(f"加载主题宽度时出错: {e}")
        return list.widget_width


def is_temp_week():
    if read_conf('Temp', 'set_week') is None or read_conf('Temp', 'set_week') == '':
        return False
    else:
        return read_conf('Temp', 'set_week')


def is_temp_schedule():
    if read_conf('Temp', 'temp_schedule') is None or read_conf('Temp', 'temp_schedule') == '':
        return False
    else:
        return read_conf('Temp', 'temp_schedule')


def add_shortcut_to_startmenu(file='', icon=''):
    if os.name != 'nt':
        return
    try:
        if file == "":
            file_path = os.path.realpath(__file__)
        else:
            file_path = os.path.abspath(file)  # 将相对路径转换为绝对路径

        if icon == "":
            icon_path = file_path  # 如果未指定图标路径，则使用程序路径
        else:
            icon_path = os.path.abspath(icon)  # 将相对路径转换为绝对路径

        # 获取开始菜单文件夹路径
        menu_folder = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs')

        # 快捷方式文件名（使用文件名或自定义名称）
        name = os.path.splitext(os.path.basename(file_path))[0]  # 使用文件名作为快捷方式名称
        shortcut_path = os.path.join(menu_folder, f'{name}.lnk')

        # 创建快捷方式
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = file_path
        shortcut.WorkingDirectory = os.path.dirname(file_path)
        shortcut.IconLocation = icon_path  # 设置图标路径
        shortcut.save()
    except Exception as e:
        logger.error(f"创建开始菜单快捷方式时出错: {e}")


def add_shortcut(file='', icon=''):
    if os.name != 'nt':
        return
    try:
        if file == "":
            file_path = os.path.realpath(__file__)
        else:
            file_path = os.path.abspath(file)

        if icon == "":
            icon_path = file_path
        else:
            icon_path = os.path.abspath(icon)

        # 获取桌面文件夹路径
        desktop_folder = os.path.join(os.environ['USERPROFILE'], 'Desktop')

        # 快捷方式文件名（使用文件名或自定义名称）
        name = os.path.splitext(os.path.basename(file_path))[0]  # 使用文件名作为快捷方式名称
        shortcut_path = os.path.join(desktop_folder, f'{name}.lnk')

        # 创建快捷方式
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = file_path
        shortcut.WorkingDirectory = os.path.dirname(file_path)
        shortcut.IconLocation = icon_path  # 设置图标路径
        shortcut.save()
    except Exception as e:
        logger.error(f"创建桌面快捷方式时出错: {e}")


def add_to_startup(file_path='', icon_path=''):  # 注册到开机启动
    if os.name != 'nt':
        return
    if file_path == "":
        file_path = os.path.realpath(__file__)
    else:
        file_path = os.path.abspath(file_path)  # 将相对路径转换为绝对路径

    if icon_path == "":
        icon_path = file_path  # 如果未指定图标路径，则使用程序路径
    else:
        icon_path = os.path.abspath(icon_path)  # 将相对路径转换为绝对路径

    # 获取启动文件夹路径
    startup_folder = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')

    # 快捷方式文件名（使用文件名或自定义名称）
    name = os.path.splitext(os.path.basename(file_path))[0]  # 使用文件名作为快捷方式名称
    shortcut_path = os.path.join(startup_folder, f'{name}.lnk')

    # 创建快捷方式
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = file_path
    shortcut.WorkingDirectory = os.path.dirname(file_path)
    shortcut.IconLocation = icon_path  # 设置图标路径
    shortcut.save()


def remove_from_startup():
    startup_folder = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    shortcut_path = os.path.join(startup_folder, f'{name}.lnk')
    if os.path.exists(shortcut_path):
        os.remove(shortcut_path)


def get_time_offset():  # 获取时差偏移
    time_offset = read_conf('General', 'time_offset')
    if time_offset is None or time_offset == '' or time_offset == '0':
        return 0
    else:
        return int(time_offset)


def get_custom_countdown():  # 获取自定义倒计时
    custom_countdown = read_conf('Date', 'countdown_date')
    if custom_countdown is None or custom_countdown == '':
        return '未设置'
    else:
        custom_countdown = datetime.strptime(custom_countdown, '%Y-%m-%d')
        if custom_countdown < datetime.now():
            return '0 天'
        else:
            cd_text = custom_countdown - datetime.now()
            return f'{cd_text.days + 1} 天'
            # return (
            #     f"{cd_text.days} 天 {cd_text.seconds // 3600} 小时 {cd_text.seconds // 60 % 60} 分"
            # )


def get_week_type():  # 获取单双周
    if read_conf('Date', 'start_date') != '':
        start_date = read_conf('Date', 'start_date')
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        today = datetime.now()
        week_num = (today - start_date).days // 7 + 1
        if week_num % 2 == 0:
            return 1  # 双周
        else:
            return 0  # 单周
    else:
        return 0  # 默认单周


def get_is_widget_in(widget='example.ui'):
    widgets_list = list.get_widget_config()
    if widget in widgets_list:
        return True
    else:
        return False


def save_widget_conf_to_json(new_data):
    # 初始化 data_dict 为一个空字典
    data_dict = {}
    if os.path.exists(f'{base_directory}/config/widget.json'):
        try:
            with open(f'{base_directory}/config/widget.json', 'r', encoding='utf-8') as file:
                data_dict = json.load(file)
        except Exception as e:
            print(f"读取现有数据时出错: {e}")
            return e
    data_dict.update(new_data)
    try:
        with open(f'{base_directory}/config/widget.json', 'w', encoding='utf-8') as file:
            json.dump(data_dict, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"保存数据时出错: {e}")
        return e


def load_plugins():  # 加载插件配置文件
    plugin_dict = {}
    for folder in Path(PLUGINS_DIR).iterdir():
        if folder.is_dir() and (folder / 'plugin.json').exists():
            try:
                with open(f'{base_directory}/plugins/{folder.name}/plugin.json', 'r', encoding='utf-8') as file:
                    data = json.load(file)
            except Exception as e:
                logger.error(f"加载插件配置文件数据时出错，将跳过: {e}")  # 跳过奇怪的文件夹
            plugin_dict[str(folder.name)] = {}
            plugin_dict[str(folder.name)]['name'] = data['name']  # 名称
            plugin_dict[str(folder.name)]['version'] = data['version']  # 插件版本号
            plugin_dict[str(folder.name)]['author'] = data['author']  # 作者
            plugin_dict[str(folder.name)]['description'] = data['description']  # 描述
            plugin_dict[str(folder.name)]['plugin_ver'] = data['plugin_ver']  # 插件架构版本
            plugin_dict[str(folder.name)]['settings'] = data['settings']  # 设置
    return plugin_dict


def check_config():
    conf = config.ConfigParser()
    with open(f'{base_directory}/config/default_config.json', 'r', encoding='utf-8') as file:  # 加载默认配置
        default_conf = json.load(file)

    if not os.path.exists('config.ini'):  # 如果配置文件不存在，则copy默认配置文件
        conf.read_dict(default_conf)
        with open(path, 'w', encoding='utf-8') as configfile:
            conf.write(configfile)
        if sys.platform == 'linux':
            conf.set('General', 'hide_method', '2')
            with open(path, 'w', encoding='utf-8') as configfile:
                conf.write(configfile)
        logger.info("配置文件不存在，已创建并写入默认配置。")
        copy(f'{base_directory}/config/default.json', f'{base_directory}/config/schedule/新课表 - 1.json')
    else:
        with open(path, 'r', encoding='utf-8') as configfile:
            conf.read_file(configfile)

        if conf['Other']['version'] != default_conf['Other']['version']:  # 如果配置文件版本不同，则更新配置文件
            logger.info(f"配置文件版本不同，将重新适配")
            try:
                for section, options in default_conf.items():
                    if section not in conf:
                        conf[section] = options
                    else:
                        for key, value in options.items():
                            if key not in conf[section]:
                                conf[section][key] = str(value)
                conf.set('Other', 'version', default_conf['Other']['version'])
                with open(path, 'w', encoding='utf-8') as configfile:
                    conf.write(configfile)
                logger.info(f"配置文件已更新")
            except Exception as e:
                logger.error(f"配置文件更新失败: {e}")

        if not os.path.exists(f"{base_directory}/config/schedule/{read_conf('General', 'schedule')}"):  # 如果config.ini课程表不存在，则创建

            schedule_config = []
            # 遍历目标目录下的所有文件
            for file_name in os.listdir(f'{base_directory}/config/schedule'):
                # 找json
                if file_name.endswith('.json') and file_name != 'backup.json':
                    # 将文件路径添加到列表
                    schedule_config.append(file_name)
            if not schedule_config:
                copy(f'{base_directory}/config/default.json', f'{base_directory}/config/schedule/{read_conf("General", "schedule")}')
                logger.info(f"课程表不存在，已创建默认课程表")
            else:
                write_conf('General', 'schedule', schedule_config[0])
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


check_config()


if __name__ == '__main__':
    print('AL_1S')
    print(get_week_type())
    print(load_plugins())
    # save_data_to_json(test_data_dict, 'schedule-1.json')
    # loaded_data = load_from_json('schedule-1.json')
    # print(loaded_data)
    # schedule = loaded_data.get('schedule')

    # print(schedule['0'])
    # add_shortcut_to_startmenu('Settings.exe', 'img/favicon.ico')
