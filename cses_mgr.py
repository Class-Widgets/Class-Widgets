"""
CSES Format Support
what is CSES: https://github.com/CSES-org/CSES
"""
import json
import cses
from datetime import datetime, timedelta
from loguru import logger

import list as list_
import conf
from file import base_directory

CSES_WEEKS_TEXTS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
CSES_WEEKS = [1, 2, 3, 4, 5, 6, 7]


class CSES_Converter:
    """
    CSES 文件管理器
    集成导入/导出CSES文件的功能
    """

    def __init__(self, path='./'):
        self.generator = None
        self.parser = None
        self.path = path

    def load_parser(self):
        if not cses.CSESParser.is_cses_file(self.path):
            return "Error: Not a CSES file"  # 判定格式

        self.parser = cses.CSESParser(self.path)
        return self.parser

    def load_generator(self):
        self.generator = cses.CSESGenerator(version=int(conf.read_conf('Other', 'cses_version')))

    def convert_to_cw(self):
        """
        将CSES文件转换为Class Widgets格式
        """
        try:
            with open(f'{base_directory}/config/default.json', 'r', encoding='utf-8') as file:  # 加载默认配置
                cw_format = json.load(file)
        except FileNotFoundError:
            logger.error(f'File {base_directory}/config/default.json not found')
            return False

        if not self.parser:
            raise Exception("Parser not loaded, please load_parser() first.")
        # 课程表
        cses_schedules = self.parser.get_schedules()
        print(cses_schedules)

        part_count = 0
        part_list = []

        for day in cses_schedules:  # 课程
            # name = day['name']
            enable_day = day['enable_day']
            weeks = day['weeks']
            classes = day['classes']

            last_end_time = None
            class_count = 0

            for class_ in classes:  # 时间线
                week = str(CSES_WEEKS.index(enable_day))  # 星期
                subject = class_['subject']  # 课程名
                time_diff = None

                # 节点
                if class_ == classes[0]:
                    time = [int(str(class_['start_time']).split(':')[0]), int(str(class_['start_time']).split(':')[1])]
                    if time in part_list and weeks != 'odd' and weeks != 'even':  # 实现双周时间线
                        continue  # 跳过重复的节点

                    cw_format['part'][str(part_count)] = time
                    cw_format['part_name'][str(part_count)] = f'Part {part_count}'
                    part_count += 1
                    part_list.append(time)

                # 时间线
                start_time = datetime.strptime(str(class_['start_time'])[:5], '%H:%M')
                end_time = datetime.strptime(str(class_['end_time'])[:5], '%H:%M')
                class_count += 1

                # 计算时长
                duration = int((end_time - start_time).total_seconds() / 60)
                if last_end_time:
                    time_diff = int((start_time - last_end_time).total_seconds() / 60)  # 时差

                if not time_diff:  # 如果连堂或第一节课
                    cw_format['timeline'][week][f'a{part_count - 1}{class_count}'] = duration
                else:
                    cw_format['timeline'][week][f'f{part_count - 1}{class_count - 1}'] = time_diff
                    cw_format['timeline'][week][f'a{part_count - 1}{class_count}'] = duration

                last_end_time = end_time

                # 课程
                if weeks == 'even':
                    cw_format['schedule_even'][week].append(subject)
                elif weeks == 'odd':
                    cw_format['schedule'][week].append(subject)
                elif weeks == 'all':
                    cw_format['schedule'][week].append(subject)
                    cw_format['schedule_even'][week].append(subject)
                else:
                    logger.warning('本软件暂时不支持更多的周数循环')

        print(cw_format)
        return cw_format

    def convert_to_cses(self, cw_data=None, cw_path='./'):
        """
        将Class Widgets格式转换为CSES文件，需提供保存路径和Class Widgets数据/路径
        Args:
            cw_data: Class Widgets格式数据 (Optional)
            cw_path: Class Widgets文件路径(Optional)
        """
        def convert(schedules, type_='odd'):
            class_counter_dict = {}  # 记录一个节点当天的课程数
            for part in parts:  # 节点循环
                name = part_names[part]
                part_start_time = datetime.strptime(f'{parts[part][0]}:{parts[part][1]}', '%H:%M')
                print(f'Part {part}: {name} - {part_start_time.strftime("%H:%M")}')
                class_counter_dict[part] = {}

                for day, subjects in schedules.items():
                    time_counter = 0
                    class_counter = 0
                    if timelines[day]:  # 自定时间线存在
                        timeline = timelines[day]
                    else:  # 自定时间线不存在
                        timeline = timelines['default']

                    timelines_part = {str(day): []}  # 一个节点的时间线列表
                    for key, time in timeline.items():  # 时间线循环
                        if key.startswith(f'a{part}'):  # 科目
                            class_dict = {}

                            other_parts_classes = 0
                            for p, t in class_counter_dict.items():  # 超级嵌套
                                if p == part:  # 排除当前节点
                                    continue
                                all_time = 0
                                for c, d in t.items():  # 超级嵌套
                                    if c != str(day):  # 排除其他天
                                        continue
                                    all_time += d
                                other_parts_classes += all_time

                            start_time = part_start_time + timedelta(minutes=time_counter)
                            end_time = start_time + timedelta(minutes=int(time))
                            subject = subjects[int(key[2:]) - 1 + other_parts_classes]
                            class_counter += 1

                            if subject == '未添加':  # 跳过未添加的科目
                                time_counter += int(time)  # 时间叠加
                                continue

                            class_dict['subject'] = subject
                            class_dict['start_time'] = start_time.strftime('%H:%M')
                            class_dict['end_time'] = end_time.strftime('%H:%M')

                            timelines_part[str(day)].append(class_dict)
                        if key[1] == part:  # 时间叠加counter
                            time_counter += int(time)

                    class_counter_dict[part][day] = class_counter  # 记录一个节点当天的课程数

                    print(timelines_part)
                    if not timelines_part[str(day)]:  # 跳过空时间线
                        continue

                    self.generator.add_schedule(
                        name=f'{name}_{CSES_WEEKS_TEXTS[int(day)]}',
                        enable_day=CSES_WEEKS[int(day)],
                        weeks=type_,
                        classes=[timelines_part[str(day)][i] for i in range(len(timelines_part[str(day)]))]
                    )

        def check_subjects(schedule):  # 检查课表是否有未正式设定的科目
            unset_subjects = []
            for _, classes in schedule.items():
                for class_ in classes:
                    if class_ == '未添加':
                        continue
                    if class_ not in cw_subjects['subject_list']:
                        unset_subjects.append(class_)
            return unset_subjects

        """
        转换/CONVERT
        """
        # 科目
        try:
            with open(f'{base_directory}/config/data/subject.json', 'r', encoding='utf-8') as data:
                cw_subjects = json.load(data)
        except FileNotFoundError:
            logger.error(f'File {base_directory}/config/data/subject.json not found')
            return False

        for subject_ in cw_subjects['subject_list']:
            self.generator.add_subject(
                name=subject_, simplified_name=list_.get_subject_abbreviation(subject_),
                teacher=None, room=None
            )

        # 课表
        if not self.generator:
            raise Exception("Generator not loaded, please load_generator() first.")

        if cw_path != './' and cw_data is None:  # 加载Class Widgets数据
            try:
                with open(cw_path, 'r', encoding='utf-8') as data:
                    cw_data = json.load(data)
            except FileNotFoundError:
                logger.error(f'File {cw_path} not found')
                return False
        else:
            raise Exception("Please provide a path or a cw_data")

        parts = cw_data['part']
        part_names = cw_data['part_name']
        timelines = cw_data['timeline']
        schedules_odd = cw_data['schedule']
        schedule_even = cw_data['schedule_even']

        convert(schedules_odd)
        convert(schedule_even, 'even')
        us_set_odd = set(check_subjects(schedules_odd))
        us_set_even = set(check_subjects(schedule_even))
        us_union = us_set_odd.union(us_set_even)

        for subject_ in list(us_union):
            self.generator.add_subject(
                name=subject_, simplified_name=list_.get_subject_abbreviation(subject_),
                teacher=None, room=None
            )

        try:
            self.generator.save_to_file(self.path)
            return True
        except Exception as e:
            logger.error(f'Error: {e}')
            return False


if __name__ == '__main__':
    # EXAMPLE
    importer = CSES_Converter(path='./config/cses_schedule/test.yaml')
    importer.load_parser()
    importer.convert_to_cw()

    print('_____________________________', end='\n')  # 输出分割线

    exporter = CSES_Converter(path='./config/cses_schedule/test2.yaml')
    exporter.load_generator()
    exporter.convert_to_cses(cw_path='./config/schedule/default (3).json')
