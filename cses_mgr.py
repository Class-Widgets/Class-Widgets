"""
CSES Format Support
what is CSES: https://github.com/CSES-org/CSES
"""
import json
import typing
import cses
from datetime import datetime, timedelta
from loguru import logger

import list_ as list_
import conf
from file import base_directory, config_center

CSES_WEEKS_TEXTS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
CSES_WEEKS: typing.List[int] = [1, 2, 3, 4, 5, 6, 7]


def _get_time(time_input: typing.Union[str, int]) -> datetime: # Renamed 'time' to 'time_input' to avoid conflict
    if isinstance(time_input, str):
        return datetime.strptime(time_input, '%H:%M:%S') # Removed redundant str() cast
    elif isinstance(time_input, int):
        # Ensure integer division for clarity, though Python 3 does this by default for /
        hours = time_input // 3600
        minutes = (time_input // 60) % 60
        seconds = time_input % 60
        return datetime.strptime(f'{hours}:{minutes}:{seconds}','%H:%M:%S')
    else:
        # Corrected the error message to use the new variable name
        raise ValueError(f'需要 int 或 HH:MM:SS 类型，得到 {type(time_input)}，值为 {time_input}')


class CSES_Converter:
    """
    CSES 文件管理器
    集成导入/导出CSES文件的功能
    """

    def __init__(self, path: str = './'):
        self.generator: typing.Optional[cses.CSESGenerator] = None # Added type hint
        self.parser: typing.Optional[cses.CSESParser] = None # Added type hint
        self.path: str = path # Added type hint

    def load_parser(self) -> typing.Union[str, cses.CSESParser]: # Added return type hint
        if not cses.CSESParser.is_cses_file(self.path):
            return "Error: Not a CSES file"  # 判定格式

        self.parser = cses.CSESParser(self.path) # type: ignore[no-untyped-call]
        return self.parser

    def load_generator(self) -> None: # Added return type hint
        # Assuming config_center.read_conf returns a string convertible to int
        cses_version_str: typing.Optional[str] = config_center.read_conf('Version', 'cses_version')
        if cses_version_str is None:
            # Handle missing configuration: log error and possibly use a default or raise exception
            logger.error("CSES version not configured. Using default or failing.")
            # Example: use a default version, or raise an error to stop execution
            # For now, let's assume it might proceed with a default if cses.CSESGenerator handles it,
            # or it might fail if the version is strictly required by the constructor.
            # If CSESGenerator requires an int, this will cause an error later if not handled.
            # self.generator = cses.CSESGenerator() # Or some default
            raise ValueError("CSES version is not configured.")
        try:
            version = int(cses_version_str)
            self.generator = cses.CSESGenerator(version=version) # type: ignore[no-untyped-call]
        except ValueError:
            logger.error(f"Invalid CSES version configured: {cses_version_str}. Must be an integer.")
            raise

    def convert_to_cw(self) -> typing.Union[bool, typing.Dict[str, typing.Any]]: # Added return type hint
        """
        将CSES文件转换为Class Widgets格式
        """
        try:
            # Define type for cw_format before assignment
            cw_format: typing.Dict[str, typing.Any]
            with open(f'{base_directory}/config/default.json', 'r', encoding='utf-8') as file:  # 加载默认配置
                cw_format = json.load(file)
        except FileNotFoundError:
            logger.error(f'File {base_directory}/config/default.json not found')
            return False # Return bool as per type hint
        except json.JSONDecodeError: # More specific exception
            logger.error(f'Error decoding JSON from {base_directory}/config/default.json')
            return False

        if not self.parser:
            # Consider raising a more specific error or ensuring parser is loaded in __init__ or a setup method
            raise Exception("Parser not loaded, please load_parser() first.")

        # Assuming get_schedules() returns a list of dictionaries.
        # The exact structure of these dictionaries would ideally be defined in a TypedDict or dataclass.
        cses_schedules: typing.List[typing.Dict[str, typing.Any]] = self.parser.get_schedules() # type: ignore[no-untyped-call]
        # print(cses_schedules) # For debugging, consider removing or using logger

        part_count: int = 0
        part_list: typing.List[typing.List[int]] = [] # List of [hour, minute]

        for day_schedule in cses_schedules:  # Renamed 'day' to 'day_schedule' to avoid confusion with datetime.day
            # name_val: str = day_schedule['name'] # Assuming 'name' is a string; 'name_val' to avoid conflict if 'name' is used elsewhere
            enable_day_val: int = day_schedule['enable_day'] # Assuming 'enable_day' is an int (index for CSES_WEEKS or similar)
            weeks_val: str = day_schedule['weeks'] # Assuming 'weeks' is a string ('odd', 'even', 'all')
            classes_val: typing.List[typing.Dict[str, typing.Any]] = day_schedule['classes'] # List of class dicts

            last_end_time: typing.Optional[datetime] = None
            class_count: int = 0

            for class_info in classes_val:  # Renamed 'class_' to 'class_info'
                # Ensure enable_day_val is a valid index for CSES_WEEKS
                # Add error handling or validation if necessary
                week_str: str = str(CSES_WEEKS.index(enable_day_val))
                subject_str: str = class_info['subject'] # Assuming 'subject' is a string
                time_diff_minutes: typing.Optional[int] = None # Renamed and specified type

                # 节点
                if class_info == classes_val[0]: # Check if it's the first class of the day_schedule
                    raw_start_time_dt: datetime = _get_time(class_info['start_time'])
                    time_repr: typing.List[int] = [raw_start_time_dt.hour, raw_start_time_dt.minute]
                    if time_repr not in part_list:  # 跳过重复的(已创建的)节点
                        cw_format['part'][str(part_count)] = time_repr
                        cw_format['part_name'][str(part_count)] = f'Part {part_count}'
                        part_count += 1
                        part_list.append(time_repr)

                # 时间线
                start_time_dt: datetime = _get_time(class_info['start_time'])
                end_time_dt: datetime = _get_time(class_info['end_time'])
                class_count += 1

                # 计算时长
                duration_minutes: int = int((end_time_dt - start_time_dt).total_seconds() / 60)
                if last_end_time:
                    time_diff_minutes = int((start_time_dt - last_end_time).total_seconds() / 60)  # 时差

                # Ensure part_count is valid before using part_count - 1 as index
                # This logic assumes part_count has been incremented at least once if classes are present.
                current_part_idx = part_count -1
                if current_part_idx <0:
                    logger.error("part_count logic error, index would be negative.")
                    # Potentially skip this entry or handle error
                    continue


                if time_diff_minutes is None:  # 如果连堂或第一节课
                    cw_format['timeline'][week_str][f'a{current_part_idx}{class_count}'] = duration_minutes
                else:
                    # Ensure class_count-1 is valid; it should be if time_diff_minutes is not None
                    cw_format['timeline'][week_str][f'f{current_part_idx}{class_count - 1}'] = time_diff_minutes
                    cw_format['timeline'][week_str][f'a{current_part_idx}{class_count}'] = duration_minutes

                last_end_time = end_time_dt

                # 课程
                # Ensure week_str is a valid key for schedule dictionaries
                if weeks_val == 'even':
                    cw_format['schedule_even'][week_str].append(subject_str)
                elif weeks_val == 'odd':
                    cw_format['schedule'][week_str].append(subject_str)
                elif weeks_val == 'all':
                    cw_format['schedule'][week_str].append(subject_str)
                    cw_format['schedule_even'][week_str].append(subject_str)
                else:
                    logger.warning(f'本软件暂时不支持 "{weeks_val}" 类型的周数循环') # Clarified warning

        # print(cw_format) # For debugging
        return cw_format # Return Dict as per type hint

    def convert_to_cses(self, cw_data: typing.Optional[typing.Dict[str, typing.Any]] = None, cw_path: str = './') -> bool: # Added type hints
        """
        将Class Widgets格式转换为CSES文件，需提供保存路径和Class Widgets数据/路径
        Args:
            cw_data: Class Widgets格式数据 (Optional)
            cw_path: Class Widgets文件路径(Optional)
        """
        # Define types for variables that will be extracted from cw_data
        # These are assumptions based on common structures.
        # For more accuracy, the actual structure of cw_data needs to be known.
        parts_type = typing.Dict[str, typing.List[int]] # e.g., {"0": [8,0], "1": [9,0]}
        part_names_type = typing.Dict[str, str] # e.g., {"0": "Part 0", "1": "Part 1"}
        timelines_type = typing.Dict[str, typing.Dict[str, int]] # e.g. {"0": {"a00": 45, "f00":10}} (day: timeline_item: duration)
        schedules_data_type = typing.Dict[str, typing.List[str]] # e.g. {"0": ["Math", "Science"]} (day: list of subjects)

        # Nested function type hints
        def convert(schedules: schedules_data_type, type_str: str ='odd') -> None:
            class_counter_dict: typing.Dict[str, typing.Dict[str, int]] = {}  # part_idx: {day_idx: count}

            # Iterate through parts (assuming parts is available in the outer scope)
            for part_idx_str, part_time_list in parts.items():
                part_name: str = part_names[part_idx_str]
                part_start_time_dt: datetime = datetime.strptime(f'{part_time_list[0]}:{part_time_list[1]}', '%H:%M')
                # print(f'Part {part_idx_str}: {part_name} - {part_start_time_dt.strftime("%H:%M")}') # Debugging
                class_counter_dict[part_idx_str] = {}

                for day_idx_str, subjects_list in schedules.items():
                    time_counter_minutes: int = 0
                    class_counter_for_day: int = 0

                    # Determine timeline: specific day's or default
                    current_timeline: typing.Dict[str, int] = timelines.get(day_idx_str) or timelines['default']

                    # Store class details for the current part and day
                    day_classes_details: typing.List[typing.Dict[str,str]] = []

                    for timeline_key, duration_minutes in current_timeline.items():
                        if timeline_key.startswith(f'a{part_idx_str}'):  # 'a' for activity/class

                            # Calculate how many classes from other parts on this day precede this one
                            other_parts_total_classes: int = 0
                            for prev_part_idx, daily_counts in class_counter_dict.items():
                                if prev_part_idx == part_idx_str: # Skip current part
                                    continue
                                other_parts_total_classes += daily_counts.get(day_idx_str, 0)

                            # Determine subject for this class
                            # The index for subjects_list depends on timeline_key structure and other_parts_total_classes
                            # Assuming key[2:] (or similar) correctly identifies class sequence within its part
                            # This part of logic (int(key[2:]) - 1 + other_parts_total_classes) is complex and error-prone
                            # Ensure key[1] is indeed part_idx_str for this block
                            subject_index_str = timeline_key[len(f'a{part_idx_str}'):] # Get the class sequence number string
                            try:
                                subject_sequence_in_part = int(subject_index_str) -1 # if keys are like a01, a02...
                            except ValueError:
                                logger.error(f"Could not parse subject sequence from timeline key: {timeline_key}")
                                continue


                            actual_subject_index = subject_sequence_in_part + other_parts_total_classes
                            if actual_subject_index >= len(subjects_list):
                                logger.error(f"Subject index out of bounds for day {day_idx_str}, part {part_idx_str}")
                                continue # Or handle error appropriately

                            subject_name: str = subjects_list[actual_subject_index]
                            class_counter_for_day += 1

                            if subject_name == '未添加':
                                time_counter_minutes += duration_minutes
                                continue

                            class_start_time_dt: datetime = part_start_time_dt + timedelta(minutes=time_counter_minutes)
                            class_end_time_dt: datetime = class_start_time_dt + timedelta(minutes=duration_minutes)

                            day_classes_details.append({
                                'subject': subject_name,
                                'start_time': class_start_time_dt.strftime('%H:%M:00'),
                                'end_time': class_end_time_dt.strftime('%H:%M:00')
                            })

                        # This condition seems to be checking if the timeline_key's *second character* matches the part_idx_str
                        # This could be problematic if part_idx_str can be more than one digit (e.g. "10", "11")
                        # Assuming part_idx_str is always a single digit for this logic to hold as written.
                        # If part_idx_str can be "10", then key[1] would be "0", not "10".
                        # This needs clarification or correction based on actual timeline_key format.
                        # For now, I'll assume it's intended for single-digit part indexes.
                        if len(timeline_key) > 1 and timeline_key[1] == part_idx_str: # Check timeline_key format
                            time_counter_minutes += duration_minutes

                    class_counter_dict[part_idx_str][day_idx_str] = class_counter_for_day

                    if not day_classes_details:
                        continue

                    # Ensure generator is not None before calling methods
                    if self.generator:
                        self.generator.add_schedule( # type: ignore[no-untyped-call]
                            name=f'{part_name}_{CSES_WEEKS_TEXTS[int(day_idx_str)]}',
                            enable_day=CSES_WEEKS[int(day_idx_str)],
                            weeks=type_str,
                            classes=day_classes_details
                        )

        # Type hint for cw_subjects, assuming a specific structure
        cw_subjects_type = typing.Dict[str, typing.List[str]] # e.g. {"subject_list": ["Math", "Art"]}
        cw_subjects: cw_subjects_type


        def check_subjects(schedule: schedules_data_type) -> typing.List[str]:
            unset_subjects: typing.List[str] = []
            # Ensure cw_subjects is loaded and has 'subject_list'
            if 'subject_list' not in cw_subjects:
                logger.error("cw_subjects not loaded or 'subject_list' key missing.")
                return [] # Or raise an error

            for _, classes_list in schedule.items():
                for class_name in classes_list:
                    if class_name == '未添加':
                        continue
                    if class_name not in cw_subjects['subject_list']:
                        unset_subjects.append(class_name)
            return unset_subjects

        """
        转换/CONVERT
        """
        # 科目
        # Try to load subjects, handle potential errors
        subject_config_path = Path(f'{base_directory}/config/data/subject.json')
        try:
            with open(subject_config_path, 'r', encoding='utf-8') as data_file:
                cw_subjects = json.load(data_file)
        except FileNotFoundError:
            logger.error(f'File {subject_config_path} not found')
            return False
        except json.JSONDecodeError:
            logger.error(f'Error decoding JSON from {subject_config_path}')
            return False

        if not self.generator:
             raise Exception("Generator not loaded, please load_generator() first.")

        # Add subjects from the loaded list
        for subject_name_str in cw_subjects.get('subject_list', []): # Use .get for safety
            self.generator.add_subject( # type: ignore[no-untyped-call]
                name=subject_name_str,
                simplified_name=list_.get_subject_abbreviation(subject_name_str), # type: ignore[no-untyped-call]
                teacher=None,
                room=None
            )

        # 课表
        # Load cw_data if path is provided and cw_data is None
        # Ensure cw_data is correctly typed after loading or assignment
        loaded_cw_data: typing.Optional[typing.Dict[str, typing.Any]] = cw_data
        if cw_path != './' and loaded_cw_data is None:
            try:
                with open(cw_path, 'r', encoding='utf-8') as data_file:
                    loaded_cw_data = json.load(data_file)
            except FileNotFoundError:
                logger.error(f'File {cw_path} not found')
                return False
            except json.JSONDecodeError:
                logger.error(f'Error decoding JSON from {cw_path}')
                return False

        if loaded_cw_data is None : # If still None after trying to load
             # Original code raises an exception if both are None or path is default.
             # This ensures loaded_cw_data is not None if we proceed.
            raise Exception("Please provide a valid path or cw_data dictionary.")

        # Extract data from loaded_cw_data with expected types
        # Using .get for safer access, assuming default.json structure might vary or keys might be missing
        parts: parts_type = loaded_cw_data.get('part', {})
        part_names: part_names_type = loaded_cw_data.get('part_name', {})
        timelines: timelines_type = loaded_cw_data.get('timeline', {})
        schedules_odd: schedules_data_type = loaded_cw_data.get('schedule', {})
        schedule_even: schedules_data_type = loaded_cw_data.get('schedule_even', {})

        convert(schedules_odd, 'odd') # type: ignore[arg-type] # Call with defined schedules_odd
        convert(schedule_even, 'even') # type: ignore[arg-type] # Call with defined schedule_even

        # Check for subjects not in the official list and add them
        us_set_odd: typing.Set[str] = set(check_subjects(schedules_odd))
        us_set_even: typing.Set[str] = set(check_subjects(schedule_even))
        us_union: typing.Set[str] = us_set_odd.union(us_set_even)

        for subject_name_str in list(us_union):
             if self.generator: # Ensure generator exists
                self.generator.add_subject( # type: ignore[no-untyped-call]
                    name=subject_name_str,
                    simplified_name=list_.get_subject_abbreviation(subject_name_str), # type: ignore[no-untyped-call]
                    teacher=None,
                    room=None
                )

        # Save the generated CSES file
        try:
            if self.generator: # Ensure generator exists
                self.generator.save_to_file(self.path) # type: ignore[no-untyped-call]
            return True
        except Exception as e: # Broad exception, consider more specific ones
            logger.error(f'Error saving CSES file: {e}')
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
