import json
import os
from copy import deepcopy
from shutil import copy

from loguru import logger
from file import base_directory, config_center, save_data_to_json

week = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
week_type = ['单周', '双周']
part_type = ['节点', '休息段']
window_status = ['无', '置于顶部', '置于底部']
color_mode = ['浅色', '深色', '跟随系统']
hide_mode = ['无', '上课时自动隐藏', '窗口最大化时隐藏', '灵活隐藏']
non_nt_hide_mode = ['无', '上课时自动隐藏']
version_channel = ['正式版 (Release)', '测试版 (Beta)']

theme_folder = []
theme_names = []

subject = {
    '语文': '(255, 151, 135',  # 红
    '数学': '(105, 84, 255',  # 蓝
    '英语': '(236, 135, 255',  # 粉
    '生物': '(68, 200, 94',  # 绿
    '地理': '(80, 214, 200',  # 浅蓝
    '政治': '(255, 110, 110',  # 红
    '历史': '(180, 130, 85',  # 棕
    '物理': '(130, 85, 180',  # 紫
    '化学': '(84, 135, 190',  # 蓝
    '美术': '(0, 186, 255',  # 蓝
    '音乐': '(255, 101, 158',  # 红
    '体育': '(255, 151, 135',  # 红
    '信息技术': '(84, 135, 190',  # 蓝
    '电脑': '(84, 135, 190',  # 蓝
    '课程表未加载': '(255, 151, 135',  # 红

    '班会': '(255, 151, 135',  # 红
    '自习': '(115, 255, 150',  # 绿
    '课间': '(135, 255, 191',  # 绿
    '大课间': '(255, 151, 135',  # 红
    '放学': '(84, 255, 101',  # 绿
    '暂无课程': '(84, 255, 101',  # 绿
}

schedule_dir = os.path.join(base_directory, 'config', 'schedule')

class_activity = ['课程', '课间']
time = ['上午', '下午', '晚修']
class_kind = [
    '自定义',
    '语文',
    '数学',
    '英语',
    '政治',
    '历史',
    '生物',
    '地理',
    '物理',
    '化学',
    '体育',
    '班会',
    '自习',
    '早读',
    '大课间',
    '美术',
    '音乐',
    '心理',
    '信息技术'
]

default_widgets = [
    'widget-time.ui',
    'widget-countdown.ui',
    'widget-current-activity.ui',
    'widget-next-activity.ui'
]

widget_width = {  # 默认宽度
    'widget-time.ui': 210,
    'widget-countdown.ui': 200,
    'widget-current-activity.ui': 360,
    'widget-next-activity.ui': 290,
    'widget-countdown-day.ui': 200,
    'widget-weather.ui': 200
}

widget_conf = {
    '当前日期': 'widget-time.ui',
    '活动倒计时': 'widget-countdown.ui',
    '当前活动': 'widget-current-activity.ui',
    '更多活动': 'widget-next-activity.ui',
    '倒计日': 'widget-countdown-day.ui',
    '天气': 'widget-weather.ui'
}

widget_name = {
    'widget-time.ui': '当前日期',
    'widget-countdown.ui': '活动倒计时',
    'widget-current-activity.ui': '当前活动',
    'widget-next-activity.ui': '更多活动',
    'widget-countdown-day.ui': '倒计日',
    'widget-weather.ui': '天气'
}

native_widget_name = [widget_name[i] for i in widget_name]

try:  # 加载课程/主题配置文件
    subject_info = json.load(open(f'{base_directory}/config/data/subject.json', 'r', encoding='utf-8'))
    subject_icon = subject_info['subject_icon']
    subject_abbreviation = subject_info['subject_abbreviation']
    theme_folder = [f for f in os.listdir(f'{base_directory}/ui/')
                    if os.path.isdir(os.path.join(f'{base_directory}/ui/', f))]
except Exception as e:
    logger.error(f'加载课程/主题配置文件发生错误，使用默认配置：{e}')
    config_center.write_conf('General', 'theme', 'default')
    subject_icon = {
        '语文': 'chinese',
        '数学': 'math',
        '英语': 'abc',
        '生物': 'biology',
        '地理': 'geography',
        '政治': 'chinese',
        '历史': 'history',
        '物理': 'physics',
        '化学': 'chemistry',
        '美术': 'art',
        '音乐': 'music',
        '体育': 'pe',
        '信息技术': 'it',
        '电脑': 'it',
        '课程表未加载': 'xmark',

        '班会': 'meeting',
        '自习': 'self_study',
        '课间': 'break',
        '大课间': 'pe',
        '放学': 'after_school',
        '暂无课程': 'break',
    }
    # 简称
    subject_abbreviation = {
        '历史': '史'
    }

not_exist_themes = []

countdown_modes = ['轮播', '多小组件']

for folder in theme_folder:
    try:
        json_file = json.load(open(f'{base_directory}/ui/{folder}/theme.json', 'r', encoding='utf-8'))
        theme_names.append(json_file['name'])
    except Exception as e:
        logger.error(f'加载主题文件 theme.json {folder} 发生错误，跳过：{e}')
        not_exist_themes.append(folder)

for folder in not_exist_themes:
    theme_folder.remove(folder)


def get_widget_list():
    rl = []
    for item, value in widget_conf.items():
        rl.append(item)
    return rl


def get_widget_names():
    rl = []
    for item, value in widget_name.items():
        rl.append(value)
    return rl


def get_current_theme_num():
    for i in range(len(theme_folder)):
        if not os.path.exists(f'{base_directory}/config/schedule/{theme_folder[i]}.json'):
            return "default"
        if theme_folder[i] == config_center.read_conf('General', 'theme'):
            return i


def get_theme_ui_path(name):
    for i in range(len(theme_folder)):
        if theme_names[i] == name:
            return theme_folder[i]
    return 'default'


def get_subject_abbreviation(key):
    if key in subject_abbreviation:
        return subject_abbreviation[key]
    else:
        return key[:1]


# 学科图标
def get_subject_icon(key):
    if key in subject_icon:
        return f'{base_directory}/img/subject/{subject_icon[key]}.svg'
    else:
        return f'{base_directory}/img/subject/self_study.svg'


# 学科主题色
def subject_color(key):
    if key in subject:
        return f'{subject[key]}'
    else:
        return '(75, 170, 255'


def get_schedule_config():
    schedule_config = []
    # 遍历目标目录下的所有文件
    for file_name in os.listdir(schedule_dir):
        # 找json
        if file_name.endswith('.json') and file_name != 'backup.json':
            # 将文件路径添加到列表
            schedule_config.append(file_name)
    schedule_config.append('添加新课表')
    return schedule_config


def return_default_schedule_number():
    total = 0
    for file_name in os.listdir(schedule_dir):
        # 找json
        if file_name.startswith('新课表 - '):
            total += 1
    return total


def create_new_profile(filename):
    copy(f'{base_directory}/config/default.json', f'{base_directory}/config/schedule/{filename}')


def import_schedule(filepath, filename):  # 导入课表
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            check_data = json.load(file)
    except Exception as e:
        logger.error(f"加载数据时出错: {e}")
        return False

    checked_data = convert_schedule(check_data)
    # 保存文件
    try:
        print(check_data)
        copy(filepath, f'{base_directory}/config/schedule/{filename}')
        save_data_to_json(checked_data, filename)
        config_center.write_conf('General', 'schedule', filename)
        return True
    except Exception as e:
        logger.error(f"保存数据时出错: {e}")
        return e


def convert_schedule(check_data):  # 转换课表
    # 校验课程表
    if check_data is None:
        logger.warning('此文件为空')
        return False
    elif not check_data.get('timeline') and not check_data.get('schedule'):
        logger.warning('此文件不是课程表文件')
        return False
    # 转换为标准格式
    if not check_data.get('schedule_even'):
        logger.warning('此课程表格式不支持单双周')
        check_data['schedule_even'] = {str(i): [] for i in range(0, 6)}

    if len(check_data.get('part').get('0')) == 2:
        logger.warning('此课程表格式不支持休息段')
        for i in range(len(check_data.get('part'))):
            check_data['part'][str(i)].append('节点')

    if not check_data.get('part') or not check_data.get('part_name'):  # 兼容旧版本
        logger.warning('此课程表格式不支持节点')
        try:
            check_data['part'] = {  # 转换旧版本时间线为新版
                "0": check_data['timeline']['start_time_m']['part'], "1": check_data['timeline']['start_time_a']['part']
            }
            check_data['part_name'] = {"0": "上午", "1": "下午"}
            del check_data['timeline']['start_time_m']
            del check_data['timeline']['start_time_a']
            old_timeline = deepcopy(check_data['timeline'])
            # 转换为标准格式
            check_data['timeline']['default'] = {}
            for i in range(0, 6):
                check_data['timeline'][i] = {}

            for item_name, _ in old_timeline.items():
                if item_name[1] == 'a':
                    ma_to_num = 1
                else:
                    ma_to_num = 0
                new_name = item_name[0]+str(ma_to_num)+item_name[2]
                check_data['timeline']['default'][new_name] = check_data['timeline'][item_name]
                del check_data['timeline'][item_name]
        except Exception as e:
            logger.error(f"转换数据时出错: {e}")
            return False
          
    return check_data


def export_schedule(filepath, filename):  # 导出课表
    try:
        copy(f'{base_directory}/config/schedule/{filename}', filepath)
        return True
    except Exception as e:
        logger.error(f"导出文件时出错: {e}")
        return e


def get_widget_config():
    try:
        if os.path.exists(f'{base_directory}/config/widget.json'):
            with open(f'{base_directory}/config/widget.json', 'r', encoding='utf-8') as file:
                data = json.load(file)
        else:
            with open(f'{base_directory}/config/widget.json', 'w', encoding='utf-8') as file:
                data = {'widgets': [
                    'widget-weather.ui', 'widget-countdown.ui', 'widget-current-activity.ui', 'widget-next-activity.ui'
                ]}
                json.dump(data, file, indent=4)
        return data['widgets']
    except Exception as e:
        logger.error(f'ReadWidgetConfigFAILD: {e}')
        return default_widgets


if __name__ == '__main__':
    print(theme_folder)
    print(theme_names)
    print('AL-1S')
    print(get_widget_list())
