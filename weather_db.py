import datetime
import sqlite3
import json
from loguru import logger
from typing import Dict, Any, Optional, List, Union, Tuple # Added for type hints
from pathlib import Path # Added for Path object

from conf import base_directory # base_directory is Path
from file import config_center # config_center is ConfigCenter

# Ensure base_directory is Path, if not, convert it
base_dir_path: Path = Path(base_directory) # type: ignore[attr-defined]

path: Path = base_dir_path / "config" / "data" / "xiaomi_weather.db"
api_config: Dict[str, Any] = {}
try:
    with open(base_dir_path / "config" / "data" / "weather_api.json", 'r', encoding='utf-8') as f:
        api_config = json.load(f)
except FileNotFoundError:
    logger.error("weather_api.json not found. Weather functionality will be impaired.")
except json.JSONDecodeError:
    logger.error("Error decoding weather_api.json. Weather functionality will be impaired.")


def update_path() -> None: # Added return type
    global path
    current_api: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    db_name: Optional[str] = None
    if current_api and 'weather_api_parameters' in api_config and \
       current_api in api_config['weather_api_parameters'] and \
       'database' in api_config['weather_api_parameters'][current_api]:
        db_name = api_config['weather_api_parameters'][current_api]['database']

    if db_name:
        path = base_dir_path / "config" / "data" / db_name
    else:
        logger.warning(f"Database name not found for API: {current_api}. Using default xiaomi_weather.db.")
        path = base_dir_path / "config" / "data" / "xiaomi_weather.db"


def search_by_name(search_term: str) -> List[str]: # Added types
    update_path()
    conn: Optional[sqlite3.Connection] = None
    result_list: List[str] = []
    try:
        conn = sqlite3.connect(str(path)) # sqlite3.connect expects str or PathLike
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute('SELECT * FROM citys WHERE name LIKE ?', ('%' + search_term + '%',))
        cities_results: List[Tuple[Any, ...]] = cursor.fetchall() # Each row is a tuple

        city_row: Tuple[Any, ...]
        for city_row in cities_results:
            if len(city_row) > 2 and isinstance(city_row[2], str): # Ensure index 2 exists and is string
                result_list.append(city_row[2])
    except sqlite3.Error as e:
        logger.error(f"SQLite error in search_by_name: {e}")
    finally:
        if conn:
            conn.close()
    return result_list


def search_code_by_name(search_term: Union[Tuple[str, str], str]) -> str: # Added types, search_term can be tuple or str
    if search_term == ('', '') or not search_term: # Handle empty tuple or empty string
        return "101010100" # Default Beijing
    update_path()
    conn: Optional[sqlite3.Connection] = None
    result: str = "101010100"  # Default city code (Beijing)
    
    processed_search_term_tuple: Tuple[str, str]
    processed_search_term_single: str

    if isinstance(search_term, tuple):
        processed_search_term_tuple = (search_term[0].replace('市','').replace('区',''), search_term[1].replace('市','').replace('区',''))
        search_query_exact = f"{processed_search_term_tuple[0]}.{processed_search_term_tuple[1]}"
        search_query_like = processed_search_term_tuple[0] # Use only city part for LIKE if district fails
    else: # Is string
        processed_search_term_single = search_term.replace('市','').replace('区','')
        search_query_exact = processed_search_term_single
        search_query_like = processed_search_term_single

    try:
        conn = sqlite3.connect(str(path))
        cursor: sqlite3.Cursor = conn.cursor()
        logger.info(f"Searching for city code for: {search_term}")

        cursor.execute('SELECT * FROM citys WHERE name = ?', (search_query_exact,))
        exact_results: List[Tuple[Any, ...]] = cursor.fetchall()

        cities_results_final: List[Tuple[Any, ...]] = exact_results
        if not exact_results:
            cursor.execute('SELECT * FROM citys WHERE name LIKE ?', ('%' + search_query_like + '%',))
            cities_results_final = cursor.fetchall()

        if cities_results_final:
            city_row: Tuple[Any, ...]
            for city_row in cities_results_final:
                # Ensure city_row[2] (name) and city_row[3] (code) exist and are strings
                if len(city_row) > 3 and isinstance(city_row[2], str) and isinstance(city_row[3], str):
                    db_city_name = city_row[2]
                    # More flexible matching for names
                    if db_city_name == search_query_exact or \
                       db_city_name == search_query_like or \
                       db_city_name.startswith(search_query_like):
                        result = city_row[3]
                        logger.debug(f"找到城市: {db_city_name}，代码: {result}")
                        break # Found best match
            else: # If loop finishes without break (no exact/preferred match)
                if len(cities_results_final[0]) > 3 and isinstance(cities_results_final[0][3], str):
                    result = cities_results_final[0][3] # Fallback to first result from LIKE query
                    logger.debug(f"模糊找到城市: {cities_results_final[0][2]}，代码: {result}")
        else:
            logger.warning(f'未找到城市: {search_term}，使用默认城市代码 {result}')

    except sqlite3.Error as e:
        logger.error(f"SQLite error in search_code_by_name: {e}")
    finally:
        if conn:
            conn.close()
    return result


def search_by_num(search_term: str) -> str: # Added types
    update_path()
    conn: Optional[sqlite3.Connection] = None
    result: str = '北京'  # 默认城市名称
    try:
        conn = sqlite3.connect(str(path))
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute('SELECT * FROM citys WHERE city_num LIKE ?', ('%' + search_term + '%',))
        cities_results: List[Tuple[Any, ...]] = cursor.fetchall()
        if cities_results and len(cities_results[0]) > 2 and isinstance(cities_results[0][2], str):
            result = cities_results[0][2]
    except sqlite3.Error as e:
        logger.error(f"SQLite error in search_by_num: {e}")
    finally:
        if conn:
            conn.close()
    return result


def get_weather_by_code(code: str) -> str:  # 用代码获取天气描述. Added types
    current_api_name: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    if not current_api_name: return '未知'

    status_file_path = base_dir_path / "config" / "data" / f"{current_api_name}_status.json"
    try:
        with open(status_file_path, 'r', encoding="utf-8") as f:
            weather_status: Dict[str, Any] = json.load(f)

        weather_info_list: List[Dict[str, Any]] = weather_status.get('weatherinfo', [])
        weather_item: Dict[str, Any]
        for weather_item in weather_info_list:
            if str(weather_item.get('code')) == code:
                return str(weather_item.get('wea', '未知'))
    except FileNotFoundError:
        logger.error(f"Weather status file not found: {status_file_path}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding weather status file: {status_file_path}")
    except Exception as e:
        logger.error(f"Error in get_weather_by_code: {e}")
    return '未知'


def get_weather_icon_by_code(code: str) -> str:  # 用代码获取天气图标. Added types
    current_api_name: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    default_icon_path: str = str(base_dir_path / "img" / "weather" / "99.svg")
    if not current_api_name: return default_icon_path

    status_file_path = base_dir_path / "config" / "data" / f"{current_api_name}_status.json"
    weather_code_to_use: Optional[str] = None

    try:
        with open(status_file_path, 'r', encoding="utf-8") as f:
            weather_status: Dict[str, Any] = json.load(f)

        weather_info_list: List[Dict[str, Any]] = weather_status.get('weatherinfo', [])
        weather_item: Dict[str, Any]
        for weather_item in weather_info_list:
            if str(weather_item.get('code')) == code:
                original_code: Optional[Any] = weather_item.get('original_code')
                weather_code_to_use = str(original_code) if original_code is not None else str(weather_item.get('code'))
                break
    except Exception as e:
        logger.error(f"Error processing weather status file in get_weather_icon_by_code: {e}")
        return default_icon_path

    if not weather_code_to_use:
        logger.error(f'未找到天气代码 {code}')
        return default_icon_path

    current_time: dt.datetime = dt.datetime.now()
    # 根据天气和时间获取天气图标
    if weather_code_to_use in ('0', '1', '3', '13'):  # 晴、多云、阵雨、阵雪
        if current_time.hour < 6 or current_time.hour >= 18:  # 如果是夜间
            return str(base_dir_path / "img" / "weather" / f"{weather_code_to_use}d.svg")
    return str(base_dir_path / "img" / "weather" / f"{weather_code_to_use}.svg")


def get_weather_stylesheet(code: str) -> str:  # 天气背景样式. Added types
    current_api_name: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    default_bkg: str = 'img/weather/bkg/day.png' # Default background
    if not current_api_name: return default_bkg

    status_file_path = base_dir_path / "config" / "data" / f"{current_api_name}_status.json"
    weather_code_to_use: str = '99' # Default to "unknown" weather code

    try:
        with open(status_file_path, 'r', encoding="utf-8") as f:
            weather_status: Dict[str, Any] = json.load(f)
        weather_info_list: List[Dict[str, Any]] = weather_status.get('weatherinfo', [])
        weather_item: Dict[str, Any]
        for weather_item in weather_info_list:
            if str(weather_item.get('code')) == code:
                original_code: Optional[Any] = weather_item.get('original_code')
                weather_code_to_use = str(original_code) if original_code is not None else str(weather_item.get('code', '99'))
                break
    except Exception as e:
        logger.error(f"Error processing weather status file in get_weather_stylesheet: {e}")
        # Fall through to use default weather_code_to_use '99'

    current_time: dt.datetime = dt.datetime.now()
    if weather_code_to_use in ('0', '1', '3', '99', '900'):  # 晴、多云、阵雨、未知
        if 6 <= current_time.hour < 18:  # 如果是日间
            return 'img/weather/bkg/day.png'
        else:  # 如果是夜间
            return 'img/weather/bkg/night.png'
    return 'img/weather/bkg/rain.png'


def get_weather_url() -> Optional[str]: # Added return type
    current_api: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    if current_api and current_api in api_config.get('weather_api_list', []):
        return api_config.get('weather_api', {}).get(current_api)
    else: # Fallback to default if current_api is not valid or not in list
        return api_config.get('weather_api', {}).get('xiaomi_weather')


def get_weather_alert_url() -> Optional[str]: # Added return type
    current_api: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    default_api_name = 'xiaomi_weather' # Default API if current is not found

    api_to_check = current_api if current_api and current_api in api_config.get('weather_api_list', []) else default_api_name

    api_params = api_config.get('weather_api_parameters', {}).get(api_to_check, {})
    alerts_config = api_params.get('alerts')

    if not alerts_config: # Could be None or False
        return 'NotSupported'
    return alerts_config.get('url')


def get_weather_code_by_description(value: str) -> str: # Added types
    current_api_name: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    if not current_api_name: return '99'

    status_file_path = base_dir_path / "config" / "data" / f"{current_api_name}_status.json"
    try:
        with open(status_file_path, 'r', encoding="utf-8") as f:
            weather_status: Dict[str, Any] = json.load(f)

        weather_info_list: List[Dict[str, Any]] = weather_status.get('weatherinfo', [])
        weather_item: Dict[str, Any]
        for weather_item in weather_info_list:
            if str(weather_item.get('wea')) == value:
                return str(weather_item.get('code', '99'))
    except Exception as e:
        logger.error(f"Error in get_weather_code_by_description: {e}")
    return '99'


def get_alert_image(alert_type: str) -> str: # Added types
    current_api: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    default_api_name = 'xiaomi_weather'
    api_to_check = current_api if current_api and current_api in api_config.get('weather_api_list', []) else default_api_name

    alerts_list: Dict[str, str] = api_config.get('weather_api_parameters', {}).get(api_to_check, {}).get('alerts', {}).get('types', {})

    image_name: Optional[str] = alerts_list.get(alert_type)
    if image_name:
        return str(base_dir_path / "img" / "weather" / "alerts" / image_name)
    return str(base_dir_path / "img" / "weather" / "alerts" / "default.png") # Fallback image


def is_supported_alert() -> bool: # Added return type
    current_api: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    default_api_name = 'xiaomi_weather'
    api_to_check = current_api if current_api and current_api in api_config.get('weather_api_list', []) else default_api_name

    alerts_config = api_config.get('weather_api_parameters', {}).get(api_to_check, {}).get('alerts')
    return bool(alerts_config) # True if alerts config exists and is not False/None/empty dict


def get_weather_data(key: str = 'temp', weather_data: Optional[Dict[str, Any]] = None) -> Optional[str]:  # 获取天气数据. Added types
    if weather_data is None:
        logger.error('weather_data is None!')
        return None

    current_api: Optional[str] = config_center.read_conf('Weather', 'api') # type: ignore[no-untyped-call]
    if not current_api:
        logger.error("Current weather API not configured.")
        return None

    api_parameters: Dict[str, Any] = api_config.get('weather_api_parameters', {}).get(current_api, {})
    if not api_parameters:
        logger.error(f"Parameters for API '{current_api}' not found.")
        return None

    parameter_path_str: Optional[str] = None
    if key == 'alert':
        parameter_path_str = api_parameters.get('alerts', {}).get('type')
    elif key == 'alert_title':
        if 'alerts' not in api_parameters or 'title' not in api_parameters['alerts']:
            return None
        parameter_path_str = api_parameters.get('alerts', {}).get('title')
    else:
        parameter_path_str = api_parameters.get(key)

    if not parameter_path_str:
        logger.error(f"Parameter path for key '{key}' not found in API config for '{current_api}'.")
        return '错误' # Original behavior

    parameter_parts: List[str] = parameter_path_str.split('.')

    value: Any = weather_data

    # API specific handling (original logic)
    if current_api == 'amap_weather':
        value = weather_data.get('lives', [{}])[0].get(api_parameters.get(key, '')) # type: ignore
    elif current_api == 'qq_weather':
        value = str(weather_data.get('result', {}).get('realtime', [{}])[0].get('infos', {}).get(api_parameters.get(key, '')))
    else: # General path traversal
        part: str
        for part in parameter_parts:
            if not value: # Value became None or empty dict/list
                logger.warning(f'天气信息值 for key {key} (part {part})为空 or path invalid.')
                return None
            if isinstance(value, list): # If part of path is list index
                try:
                    value = value[int(part)]
                except (IndexError, ValueError):
                    logger.error(f"Invalid list index '{part}' in path for key '{key}'.")
                    return '错误'
            elif isinstance(value, dict): # If part of path is dict key
                if part in value:
                    value = value[part]
                else:
                    logger.error(f"获取天气参数失败，'{part}'不存在于当前数据层级 for key '{key}' in API '{current_api}'.")
                    return '错误'
            else: # Unexpected type in path
                logger.error(f"Unexpected data type encountered while parsing weather data for key '{key}'.")
                return '错误'

    if value is None: return None # If value became None during traversal

    str_value = str(value) # Ensure value is string for final processing
    if key == 'temp':
        str_value += '°'
    elif key == 'icon':
        if api_parameters.get('return_desc'):
            str_value = get_weather_code_by_description(str_value)
    return str_value


if __name__ == '__main__':
    # 测试代码
    try:
        num_results: str = search_by_num('101310101')
        print(num_results)
        cities_results_list: List[str] = search_by_name('上海')
        print(cities_results_list)
        cities_code_result: str = search_code_by_name(('上海',''))
        print(cities_code_result)
        weather_desc: str = get_weather_by_code("3")
        print(weather_desc)
    except Exception as e:
        print(e)

[end of weather_db.py]
