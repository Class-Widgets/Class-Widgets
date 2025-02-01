"""
CSES Format Support
what is CSES: https://github.com/CSES-org/CSES
"""

import json
from datetime import datetime, timedelta
from os import PathLike
from pathlib import Path
from typing import Literal

from cses import WEEKDAY_ITEMS, Class, CsesConfig, Schedule
from loguru import logger
from yaml import safe_load

import conf
from file import base_directory

# CSES_WEEKS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def _read_cses(file: PathLike) -> dict:
    with open(file, "r") as i:
        return safe_load(i)


def cses_to_cw(file: PathLike):
    raw_config = _read_cses(file)
    raw_version = str(raw_config.get("version"))
    if raw_version != conf.read_conf("Other", "cses_version"):
        raise ValueError(f"version不正确，应为 1，得到 {raw_version}")
    try:
        cfg = CsesConfig.load_from_dict(raw_config)
    except Exception as e:
        raise ValueError(f"序列化 CSES 配置文件错误：{e}")

    try:
        with open(
            f"{base_directory}/config/default.json", "r", encoding="utf-8"
        ) as f:  # 加载默认配置
            cw_format = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError("Default config not found")

    part_count = 0
    part_list = []

    for day in cfg.schedules:  # 课程
        # name = day['name']
        weeks = day.weeks
        classes = day.classes

        last_end_time = None

        for class_count, class_ in enumerate(classes):  # 时间线
            week = str(WEEKDAY_ITEMS.index(day.enable_day))  # 星期
            subject = class_.subject  # 课程名
            time_diff = None

            # 节点
            if class_count == 0:
                time = [class_.start_time.hour, class_.start_time.minute]
                if (
                    time in part_list and weeks != "odd" and weeks != "even"
                ):  # 实现双周时间线
                    continue  # 跳过重复的节点

                cw_format["part"][str(part_count)] = time
                cw_format["part_name"][str(part_count)] = f"Part {part_count}"
                part_count += 1
                part_list.append(time)

            # 时间线
            start_time = datetime.strptime(
                class_.start_time.isoformat("minutes"), "%H:%M"
            )
            end_time = datetime.strptime(class_.end_time.isoformat("minutes"), "%H:%M")

            # 计算时长
            duration = int((end_time - start_time).total_seconds() / 60)
            if last_end_time:
                time_diff = int(
                    (start_time - last_end_time).total_seconds() / 60
                )  # 时差

            if not time_diff:  # 如果连堂或第一节课
                cw_format["timeline"][week][f"a{part_count - 1}{class_count}"] = (
                    duration
                )
            else:
                cw_format["timeline"][week][f"f{part_count - 1}{class_count - 1}"] = (
                    time_diff
                )
                cw_format["timeline"][week][f"a{part_count - 1}{class_count}"] = (
                    duration
                )

            last_end_time = end_time

            # 课程
            if weeks == "even":
                cw_format["schedule_even"][week].append(subject)
            elif weeks == "odd":
                cw_format["schedule"][week].append(subject)
            elif weeks == "all":
                cw_format["schedule"][week].append(subject)
                cw_format["schedule_even"][week].append(subject)
            else:
                logger.warning("本软件暂时不支持更多的周数循环")
    print(cw_format)


def _read_cw(path: PathLike) -> dict:
    with open(path, "r", encoding="utf-8") as data:
        return json.load(data)


def cw_to_ces(input: PathLike, output: PathLike):
    def convert(schedules, type_: Literal["all", "even", "odd"] = "odd"):
        class_counter_dict = {}  # 记录一个节点当天的课程数
        for part in parts:  # 节点循环
            name = part_names[part]
            part_start_time = datetime.strptime(
                f"{parts[part][0]}:{parts[part][1]}", "%H:%M"
            )
            print(f"Part {part}: {name} - {part_start_time.strftime('%H:%M')}")
            class_counter_dict[part] = {}

            for day, subjects in schedules.items():
                time_counter = 0
                class_counter = 0
                if timelines[day]:  # 自定时间线存在
                    timeline = timelines[day]
                else:  # 自定时间线不存在
                    timeline = timelines["default"]

                timelines_part = {str(day): []}  # 一个节点的时间线列表
                for key, time in timeline.items():  # 时间线循环
                    if key.startswith(f"a{part}"):  # 科目
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

                        if subject == "未添加":  # 跳过未添加的科目
                            continue

                        class_dict["subject"] = subject
                        class_dict["start_time"] = start_time.strftime("%H:%M")
                        class_dict["end_time"] = end_time.strftime("%H:%M")

                        timelines_part[str(day)].append(class_dict)
                    if key[1] == part:  # 时间叠加counter
                        time_counter += int(time)

                class_counter_dict[part][day] = (
                    class_counter  # 记录一个节点当天的课程数
                )

                print(timelines_part)
                output_tmp.schedules.append(
                    Schedule(
                        name=f"{name}_{WEEKDAY_ITEMS[int(day)]}",
                        enable_day=WEEKDAY_ITEMS[int(day)],  # type: ignore
                        weeks=type_,
                        classes=list(
                            Class.from_dict(timelines_part[str(day)][i])
                            for i in range(len(timelines_part[str(day)]))
                        ),
                    )
                )

    data = _read_cw(input)
    parts = data["part"]
    part_names = data["part_name"]
    timelines = data["timeline"]
    schedules_odd = data["schedule"]
    schedule_even = data["schedule_even"]
    version = conf.read_conf("Other", "cses_version")
    if not isinstance(version, str):
        raise ValueError("cses_version must be str")
    output_tmp = CsesConfig(int(version), [], [])
    convert(schedules_odd)
    convert(schedule_even, "even")
    output_tmp.save_to_file(output)


if __name__ == "__main__":
    # EXAMPLE
    # importer = cses_to_cw(Path("./config/cses_schedule/test.yaml"))

    print("_____________________________", end="\n")  # 输出分割线

    exporter = cw_to_ces(
        input=Path("./config/schedule/新课表 - 1.json"),
        output=Path("./config/cses_schedule/test.yaml"),
    )
