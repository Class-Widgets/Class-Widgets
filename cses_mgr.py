"""
CSES Format Support
what is CSES: https://github.com/CSES-org/CSES
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

from loguru import logger
import cses
import yaml

import list as list_
import conf
from file import base_directory

# CSES_WEEKS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


class CSES_Converter:
    """
    CSES 文件管理器
    集成导入/导出CSES文件的功能
    """

    def __init__(self, path="./"):
        self.parser = None
        self.path = path

    def load_parser(self):
        try:
            self.parser = cses.CsesConfig.read_from_file(Path(self.path))
        except Exception:
            return "Error: Not a CSES file"  # 判定格式
        return self.parser

    def convert_to_cw(self):
        """
        将CSES文件转换为Class Widgets格式
        """
        raw_config = self.load_parser()
        with open(self.path, "r") as i:
            raw_config = yaml.safe_load(i)
        raw_version = str(raw_config.get("version"))
        if raw_version != conf.read_conf("Other", "cses_version"):
            logger.error(f"version 不正确，应为 1，得到 {raw_version}")
            return False

        try:
            cfg = cses.CsesConfig.load_from_dict(raw_config)
        except Exception as e:
            logger.error(f"序列化 CSES 配置文件错误：{e}")
            return False

        try:
            with open(
                f"{base_directory}/config/default.json", "r", encoding="utf-8"
            ) as f:  # 加载默认配置
                cw_format = json.load(f)
        except FileNotFoundError:
            logger.error(f"File {base_directory}/config/default.json not found")
            return False

        part_count = 0
        part_list = []

        for day in cfg.schedules:  # 课程
            # name = day['name']
            enable_day = day.enable_day
            weeks = day.weeks
            classes = day.classes

            last_end_time = None
            class_count = 0

            for class_ in classes:  # 时间线
                week = str(cses.WEEKDAY_ITEMS.index(enable_day))  # 星期
                subject = class_.subject  # 课程名
                time_diff = None

                # 节点
                if class_ == classes[0]:
                    time = [class_.start_time.hour, class_.start_time.minute]
                    if time in part_list and weeks != 'odd' and weeks != 'even':  # 实现双周时间线
                        continue  # 跳过重复的节点

                    cw_format['part'][str(part_count)] = time
                    cw_format['part_name'][str(part_count)] = f'Part {part_count}'
                    part_count += 1
                    part_list.append(time)

                # 时间线
                start_time = datetime.strptime(class_.start_time.isoformat("minutes"), '%H:%M')
                end_time = datetime.strptime(class_.end_time.isoformat("minutes"), '%H:%M')
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

    def load_generator(self):
        self.generator = cses.CsesConfig(
            verison=int(conf.read_conf("Other", "cses_version")), # type: ignore
            subjects=[],
            schedules=[],
        )

    def convert_to_cses(self, cw_data=None, cw_path="./"):
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
                            print(subjects,int(key[2:]) - 1 + other_parts_classes)
                            subject = subjects[int(key[2:]) - 1 + other_parts_classes]
                            class_counter += 1

                            if subject == '未添加':  # 跳过未添加的科目
                                continue

                            class_dict['subject'] = subject
                            class_dict['start_time'] = start_time.strftime('%H:%M')
                            class_dict['end_time'] = end_time.strftime('%H:%M')

                            timelines_part[str(day)].append(class_dict)
                        if key[1] == part:  # 时间叠加counter
                            time_counter += int(time)
                    print(timelines_part)
                    temp_schedule = {
                        "name": f"{name}_{cses.WEEKDAY_ITEMS[int(day)]}",
                        "enable_day": cses.WEEKDAY_ITEMS[int(day)],
                        "weeks": type_,
                        "classes": [
                            timelines_part[str(day)][i]
                            for i in range(len(timelines_part[str(day)]))
                        ],
                    }
                    self.generator.schedules.append(
                        cses.Schedule.from_dict(temp_schedule)
                    )

        """
        转换/CONVERT
        """
        # 科目
        try:
            with open(
                f"{base_directory}/config/data/subject.json", "r", encoding="utf-8"
            ) as data:
                cw_subjects = json.load(data)
        except FileNotFoundError:
            logger.error(f"File {base_directory}/config/data/subject.json not found")
            return False

        for subject in cw_subjects["subject_list"]:
            temp_subject = {
                "name": subject,
                "simplified_name": list_.get_subject_abbreviation(subject),
                "teacher": None,
                "room": None,
            }
            self.generator.subjects.append(cses.Subject.from_dict(temp_subject))

        # 课表
        if not self.generator:
            raise Exception("Generator not loaded, please load_generator() first.")

        if cw_path != "./" and cw_data is None:  # 加载Class Widgets数据
            try:
                with open(cw_path, "r", encoding="utf-8") as data:
                    cw_data = json.load(data)
            except FileNotFoundError:
                logger.error(f"File {cw_path} not found")
                return False
        else:
            raise Exception("Please provide a path or a cw_data")

        parts = cw_data["part"]
        part_names = cw_data["part_name"]
        timelines = cw_data["timeline"]
        schedules_odd = cw_data["schedule"]
        schedule_even = cw_data["schedule_even"]

        convert(schedules_odd)
        convert(schedule_even, "even")
        try:
            self.generator.save_to_file(Path(self.path))
            return True
        except Exception as e:
            logger.error(f"Error: {e}")
            return False


if __name__ == "__main__":
    # EXAMPLE
    importer = CSES_Converter(path="./config/cses_schedule/test.yaml")
    importer.load_parser()
    importer.convert_to_cw()

    print("_____________________________", end="\n")  # 输出分割线

    exporter = CSES_Converter(path="./config/cses_schedule/test2.yaml")
    exporter.load_generator()
    exporter.convert_to_cses(cw_path="./config/schedule/default (3).json")
