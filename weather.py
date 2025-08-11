import os
import re
import json
import time
import sqlite3
import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from PyQt5.QtCore import QCoreApplication

import requests
from loguru import logger
from PyQt5.QtCore import QThread, pyqtSignal, QEventLoop

from file import config_center, base_directory


class WeatherFetchThread(QThread):
    """(异步)天气数据获取"""
    weather_data_ready = pyqtSignal(dict)
    weather_error = pyqtSignal(str)

    def __init__(self, weather_manager):
        super().__init__()
        self.weather_manager = weather_manager
        self._is_running = False

    def run(self):
        try:
            self._is_running = True
            weather_data = self.weather_manager.fetch_weather_data()
            if self._is_running:
                if 'error' in weather_data.get('now', {}):
                    self.weather_error.emit(weather_data['now']['error'])
                else:
                    self.weather_data_ready.emit(weather_data)
        except Exception as e:
            if self._is_running:
                error_msg = f"异步获取天气数据失败: {e}"
                logger.error(error_msg)
                self.weather_error.emit(error_msg)
        finally:
            self._is_running = False

    def stop(self):
        """停止线程"""
        self._is_running = False
        if self.isRunning():
            self.quit()
            self.wait(3000)


class WeatherReminderThread(QThread):
    """异步天气提醒数据获取"""
    reminders_ready = pyqtSignal(list)
    alerts_ready = pyqtSignal(list)

    def __init__(self, weather_manager, weather_data):
        super().__init__()
        self.weather_manager = weather_manager
        self.weather_data = weather_data
        self._is_running = False

    def run(self):
        try:
            self._is_running = True
            if self._is_running:
                current_api = self.weather_manager.get_current_api()
                current_location = self.weather_manager._get_location_key()
                reminders = self.weather_manager.get_weather_reminders(current_api, current_location)
                if self._is_running:
                    self.reminders_ready.emit(reminders)
            if self._is_running:
                from weather import get_unified_weather_alerts
                unified_alert_data = get_unified_weather_alerts(self.weather_data)
                all_alerts = unified_alert_data.get('all_alerts', [])
                seen_titles = set()
                unique_alerts = []
                for alert in all_alerts:
                    title = alert.get("title", "")
                    if title not in seen_titles:
                        seen_titles.add(title)
                        unique_alerts.append(alert)

                if self._is_running:
                    self.alerts_ready.emit(unique_alerts)

        except Exception as e:
            if self._is_running:
                logger.error(f"异步获取天气提醒和预警失败: {e}")
                self.reminders_ready.emit([])
                self.alerts_ready.emit([])
        finally:
            self._is_running = False

    def stop(self):
        """停止线程"""
        self._is_running = False
        if self.isRunning():
            self.quit()
            self.wait(3000)

def cache_result(expire_seconds: int = 300):
    """缓存装饰器 """
    # 她还是忘了不了她的缓存
    def decorator(func):
        cache: Dict[str, Tuple[Any, float]] = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = str(args) + str(sorted(kwargs.items()))
            current_time = time.time()
            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if current_time - timestamp < expire_seconds:
                    # logger.debug(f"使用缓存结果: {func.__name__}")
                    return result
            result = func(*args, **kwargs)
            cache[cache_key] = (result, current_time)
            return result

        wrapper.clear_cache = lambda: cache.clear()
        return wrapper
    return decorator


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"{func.__name__} 第{attempt + 1}次尝试失败: {e},{delay}秒后重试")
                        time.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} 所有重试均失败: {e}")
            if last_exception is None:
                raise RuntimeError(f"{func.__name__} 在 {max_retries} 次重试后出现未知问题")
            raise last_exception
        return wrapper
    return decorator

class WeatherapiProvider(ABC):
    """天气api数据基类"""

    def __init__(self, api_name: str, config: Dict[str, Any]):
        self.api_name = api_name
        self.config = config
        self.base_url = config.get('url', '')
        self.parameters = config.get('parameters', {})

    @abstractmethod
    def fetch_current_weather(self, location_key: str, api_key: str) -> Dict[str, Any]:
        """获取当前天气数据"""
        pass

    @abstractmethod
    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取天气预警数据"""
        pass

    @abstractmethod
    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据"""
        pass

    @abstractmethod
    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码"""
        pass

    @abstractmethod
    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述"""
        pass

    @abstractmethod
    def parse_update_time(self, data: Dict[str, Any]) -> Optional[str]:
        """解析更新时间"""
        pass

    def supports_alerts(self) -> bool:
        """检查是否支持天气预警"""
        return 'alerts' in self.config and bool(self.config['alerts'])

    def get_database_name(self) -> str:
        """获取数据库文件名"""
        return self.config.get('database', 'xiaomi_weather.db')

    @abstractmethod
    def fetch_forecast_data(self, location_key: str, api_key: str, forecast_type: str, days: int = 5) -> Dict[str, Any]:
        """获取预报数据的统一方法"""
        pass

    @abstractmethod
    def parse_forecast_data(self, raw_data: Dict[str, Any], forecast_type: str) -> List[Dict[str, Any]]:
        """解析预报数据的统一方法"""
        pass


@dataclass
class WeatherExtractionContext:
    """天气数据提取"""
    current_params: Dict[str, Any]
    key: str
    weather_data: Dict[str, Any]
    current_api: str = ''
    parameter_path: str = ''


class WeatherDataCache:
    """天气数据缓存管理器"""

    def __init__(self, default_expire: int = 300):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self.default_expire = default_expire

    def get(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self.default_expire:
                return data
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, expire: Optional[int] = None) -> None:
        """设置缓存数据"""
        self._cache[key] = (value, time.time())

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()


class WeatherManager:
    """天气管理"""

    def __init__(self):
        self.api_config = self._load_api_config()
        self.cache = WeatherDataCache()
        self.providers = self._initialize_providers()
        self.current_weather_data = None
        self.current_alert_data = None

    def _load_api_config(self) -> Dict[str, Any]:
        """加载天气api"""
        try:
            api_config_path = os.path.join(base_directory, 'config', 'data', 'weather_api.json')
            with open(api_config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f'加载天气api配置失败: {e}')
            return {}

    def _initialize_providers(self) -> Dict[str, WeatherapiProvider]:
        """初始化天气api数据"""
        providers = {}
        for api_name in self.api_config.get('weather_api_list', []):
            try:
                provider = self._create_single_provider(api_name)
                if provider:
                    providers[api_name] = provider
            except Exception as e:
                logger.error(f'初始化天气提供者 {api_name} 失败: {e}')
        return providers

    def _create_single_provider(self, api_name: str) -> Optional[WeatherapiProvider]:
        """创建提供者"""
        api_params = self.api_config.get('weather_api_parameters', {}).get(api_name, {})
        weather_api_url = self.api_config.get('weather_api', {}).get(api_name, '')

        config = self._build_provider_config(api_params, weather_api_url)
        provider_class = self._get_provider_class(api_name)

        return provider_class(api_name, config)

    def _build_provider_config(self, api_params: Dict[str, Any], weather_api_url: str) -> Dict[str, Any]:
        """构建配置"""
        return {
            'url': weather_api_url,
            'parameters': api_params,
            'alerts': api_params.get('alerts', {}),
            'database': api_params.get('database', 'xiaomi_weather.db'),
            'return_desc': api_params.get('return_desc', False),
            'method': api_params.get('method', 'location_key'),
            'hourly_forecast': api_params.get('hourly_forecast', {}),
            'daily_forecast': api_params.get('daily_forecast', {})
        }

    def _get_provider_class(self, api_name: str) -> Type[WeatherapiProvider]:
        """获得提供类"""
        if api_name == 'xiaomi_weather':
            provider_class_name = 'XiaomiWeatherProvider'
        elif api_name == 'qweather':
            provider_class_name = 'QWeatherProvider'
        elif api_name == 'open_meteo':
            provider_class_name = 'OpenMeteoProvider'
        else:
            provider_class_name = f'{api_name.capitalize()}WeatherProvider'
        if provider_class_name in globals():
            return globals()[provider_class_name]  # type: ignore[no-any-return]
        # 通用(你认为永远是你认为的)
        return GenericWeatherProvider

    def get_current_api(self) -> str:
        """获取当前选择的天气api"""
        result = config_center.read_conf('Weather', 'api')
        return str(result) if result is not None else ''

    def get_current_provider(self) -> Optional[WeatherapiProvider]:
        """获取当前天气api提供者"""
        current_api = self.get_current_api()
        return self.providers.get(current_api)

    def get_api_list(self) -> List[str]:
        """获取可用的天气api列表"""
        result = self.api_config.get('weather_api_list', [])
        return result if isinstance(result, list) else []

    def get_api_list_zh(self) -> List[str]:
        """获取天气api中文名称列表"""
        result = self.api_config.get('weather_api_list_zhCN', [])
        return result if isinstance(result, list) else []

    def on_api_changed(self, new_api: str):
        """清理缓存"""
        self.cache.clear()
        self.current_weather_data = None
        self.current_alert_data = None
        if hasattr(self.fetch_weather_data, 'clear_cache'):
            self.fetch_weather_data.clear_cache()
        if hasattr(self.get_weather_reminders, 'clear_cache'):
            self.get_weather_reminders.clear_cache()

    def clear_processor_cache(self, processor):
        """清理数据处理器缓存"""
        if hasattr(processor, 'clear_cache'):
            processor.clear_cache()

    @retry_on_failure(max_retries=3, delay=1.0)
    @cache_result(expire_seconds=300)
    def fetch_weather_data(self) -> Dict[str, Any]:
        """获取天气数据"""
        provider = self.get_current_provider()
        if not provider:
            logger.error(f'未找到天气提供源: {self.get_current_api()}')
            return self._get_fallback_data()

        try:
            validation_result = self._validate_weather_params()
            if validation_result:
                return validation_result
            location_key = self._get_location_key()
            api_key = config_center.read_conf('Weather', 'api_key')
            weather_data = provider.fetch_current_weather(location_key, api_key)
            alert_data = self._fetch_alert_data_safely(provider, location_key, api_key)
            result = self._build_weather_result(weather_data, alert_data)
            self.current_weather_data = result
            return result
        except Exception as e:
            logger.error(f'获取天气数据失败: {e}')
            return self._get_fallback_data(error_code='NETWORK_ERROR')

    def _validate_weather_params(self) -> Optional[Dict[str, Any]]:
        """验证天气参数"""
        location_key = self._get_location_key()
        api_key = config_center.read_conf('Weather', 'api_key')
        current_api = config_center.read_conf('Weather', 'api')
        if not location_key:
            logger.error('位置信息未配置或无效')
            return self._get_fallback_data(error_code='LOCATION')
        if self._is_api_key_required(current_api) and not api_key:
            logger.error(f'{current_api} api密钥缺失')
            return self._get_fallback_data(error_code='API_KEY')

        return None

    def _fetch_alert_data_safely(self, provider: WeatherapiProvider, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """安全获取预警数据"""
        if not provider.supports_alerts():
            return None
        try:
            return provider.fetch_weather_alerts(location_key, api_key)
        except Exception as e:
            logger.warning(f'获取天气预警失败: {e}')
            return None

    def _build_weather_result(self, weather_data: Dict[str, Any], alert_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """构建结果"""
        return {
            'now': weather_data,
            'alert': alert_data or {}
        }

    def _get_location_key(self) -> str:
        """获取位置值"""
        location_key = config_center.read_conf('Weather', 'city')
        if location_key == '0' or not location_key:
            location_key = self._get_auto_location()
        return location_key

    def _get_auto_location(self) -> str:
        """自动获取位置"""
        try:
            method = self.get_current_provider().config['method']
            if method == 'coordinates':
                return self._get_coordinates_location()
            from network_thread import getCity
            city_thread = getCity()
            loop = QEventLoop()
            city_thread.finished.connect(loop.quit)
            city_thread.start()
            loop.exec_()  # 阻塞到完成
            location_key = config_center.read_conf('Weather', 'city')
            if location_key == '0' or not location_key:
                return '101010100'  # 默认北京
            return location_key
        except Exception as e:
            logger.error(f'自动获取位置失败: {e}')
            return '101010100'

    def _get_coordinates_location(self) -> str:
        """获取坐标位置"""
        try:
            from network_thread import getCoordinates
            coordinates_thread = getCoordinates()
            loop = QEventLoop()
            coordinates_thread.finished.connect(loop.quit)
            coordinates_thread.start()
            loop.exec_()  # 阻塞到完成
            coordinates_data = config_center.read_conf('Weather', 'city')
            if coordinates_data and ',' in coordinates_data:
                return coordinates_data
            return '116.0,40.0'  # 默认北京
        except Exception as e:
            logger.error(f'获取坐标位置失败: {e}')
            return '116.0,40.0'

    def _is_api_key_required(self, api_name: str) -> bool:
        """最神经病的一集"""
        return api_name in ['qweather', 'amap_weather', 'qq_weather']

    def _get_fallback_data(self, error_code: str = 'UNKNOWN_ERROR') -> Dict[str, Any]:
        """回退数据"""
        error_messages = {
            'LOCATION': {'value': '错误', 'unit': '位置信息缺失'},
            'API_KEY': {'value': '错误', 'unit': 'API密钥缺失'},
            'NETWORK_ERROR': {'value': '错误', 'unit': '网络错误'},
            'UNKNOWN_ERROR': {'value': '错误', 'unit': '未知错误'}
        }
        error_info = error_messages.get(error_code, error_messages['UNKNOWN_ERROR'])
        return {
            'error': {
                'info': error_info,
                'code': error_code
            },
            'now': {},
            'alert': {}
        }

    def get_unified_weather_data(self, data_type: str) -> Optional[str]:
        """获取数据(统一)"""
        if not self.current_weather_data:
            return None

        provider = self.get_current_provider()
        if not provider:
            return None
        if 'error' in self.current_weather_data.get('now', {}):
            logger.warning(f'当前数据存在错误,跳过解析: {self.current_weather_data["now"]["error"]}')
            return None
        try:
            if data_type == 'temperature':
                return provider.parse_temperature(self.current_weather_data)
            elif data_type == 'icon':
                return provider.parse_weather_icon(self.current_weather_data)
            elif data_type == 'description':
                return provider.parse_weather_description(self.current_weather_data)
            elif data_type == 'feels_like':
                if hasattr(provider, 'parse_feels_like'):
                    return provider.parse_feels_like(self.current_weather_data)
                return None
            elif data_type == 'wind_direction':
                if hasattr(provider, 'parse_wind_direction'):
                    return provider.parse_wind_direction(self.current_weather_data)
                return None
            elif data_type == 'aqi':
                if hasattr(provider, 'parse_aqi'):
                    return provider.parse_aqi(self.current_weather_data)
                return None
            elif data_type in ('co', 'no2', 'o3', 'pm10', 'pm25', 'so2'):
                if hasattr(provider, 'parse_aqi_data'):
                    aqi_data = provider.parse_aqi_data(self.current_weather_data)
                    return aqi_data.get(data_type)
                return None
            else:
                logger.warning(f'未知的数据类型: {data_type}')
                return None
        except Exception as e:
            logger.error(f'解析天气数据失败 ({data_type}): {e}')
            return None

    def fetch_forecast(self, forecast_type: str, days: int = 5) -> List[Dict[str, Any]]:
        """统一获取天气预报数据

        Args:
            forecast_type: 预报类型 ('hourly' 或 'daily')
            days: 仅对 daily 类型有效, 预报天数
        """
        provider = self.get_current_provider()
        if not provider:
            logger.error(f'未找到天气提供源: {self.get_current_api()}')
            return []

        try:
            location_key = self._get_location_key()
            api_key = config_center.read_conf('Weather', 'api_key')

            # 获取原始数据
            raw_data = provider.fetch_forecast_data(location_key, api_key, forecast_type, days)

            # 解析数据
            parsed_data = provider.parse_forecast_data(raw_data, forecast_type)

            return parsed_data
        except Exception as e:
            logger.error(f'获取 {forecast_type} 预报失败: {e}')
            return []

    def fetch_hourly_forecast(self) -> List[Dict[str, Any]]:
        """获取逐小时天气预报"""
        return self.fetch_forecast('hourly')

    def fetch_daily_forecast(self, days: int = 5) -> List[Dict[str, Any]]:
        """获取多天天气预报"""
        return self.fetch_forecast('daily', days)

    def get_precipitation_info(self) -> Dict[str, Any]:
        """获取降水信息"""
        provider = self.get_current_provider()
        if not provider:
            logger.error(f'未找到天气提供源: {self.get_current_api()}')
            return {
                'precipitation': False,
                'precipitation_time': [],
                'tomorrow_precipitation': False,
                'precipitation_day': 0,
                'first_hour_precip': False,
                'same_precipitation': True,
                'temp_change': 0
            }

        try:
            # 使用统一接口获取预报数据
            hourly_data = self.fetch_hourly_forecast()
            daily_data = self.fetch_daily_forecast(5)

            # 当前降水状态
            precipitation_now = False
            if self.current_weather_data and 'now' in self.current_weather_data:
                current_icon = provider.parse_weather_icon(self.current_weather_data['now'])
                if current_icon:
                    precipitation_now = provider._is_precipitation(str(current_icon))
                    # logger.debug(f"当前天气图标代码: {current_icon}, 是否降水: {precipitation_now}")

            # 降水信息初始化
            precipitation_time = []
            tomorrow_precipitation = False
            precipitation_day = 0
            first_hour_precip = False
            same_precipitation = True
            temp_change = 0

            # 处理逐小时预报数据
            if hourly_data:
                if not isinstance(hourly_data, list):
                    logger.warning(f"逐小时预报数据不是列表类型: {type(hourly_data)}")
                    hourly_data = []
                if len(hourly_data) > 0:
                    first_hour = hourly_data[0]
                    # 获取第一个小时的降水状态
                    if 'precipitation' in first_hour:
                        precip_value = first_hour['precipitation']
                        first_hour_precip = bool(precip_value) and float(precip_value) > 0
                        # logger.debug(f"第一小时降水量: {precip_value}, 是否降水: {first_hour_precip}")
                    elif 'weather_code' in first_hour:
                        first_hour_precip = provider._is_precipitation(str(first_hour['weather_code']))
                        # logger.debug(f"第一小时天气代码: {first_hour['weather_code']}, 是否降水: {first_hour_precip}")

                    same_precipitation = (precipitation_now == first_hour_precip)
                    # logger.debug(f"当前降水状态: {precipitation_now}, 第一小时降水状态: {first_hour_precip}, 是否相同: {same_precipitation}")
                    # 降水时间分组
                    current_precip = None
                    count = 0
                    for hour in hourly_data:
                        is_precip = False
                        if 'precipitation' in hour:
                            precip_value = hour['precipitation']
                            is_precip = bool(precip_value) and float(precip_value) > 0
                        elif 'weather_code' in hour:
                            is_precip = provider._is_precipitation(str(hour['weather_code']))
                        if current_precip is None:
                            current_precip = is_precip
                            count = 1
                        elif current_precip == is_precip:
                            count += 1
                        else:
                            precipitation_time.append(count)
                            current_precip = is_precip
                            count = 1
                    if count > 0:
                        precipitation_time.append(count)

            # 处理多天预报数据
            if daily_data:
                if not isinstance(daily_data, list):
                    logger.warning(f"多天预报数据不是列表类型: {type(daily_data)}")
                    daily_data = []

                if len(daily_data) > 1:
                    tomorrow = daily_data[1]
                    # 获取明日降水状态
                    if 'precipitation_day' in tomorrow:
                        tomorrow_precipitation = tomorrow['precipitation_day']
                    elif 'weather_day' in tomorrow:
                        tomorrow_precipitation = provider._is_precipitation(str(tomorrow['weather_day']))
                    # 降水持续天数
                    for day in daily_data:
                        if 'precipitation_day' in day:
                            if day['precipitation_day']:
                                precipitation_day += 1
                            else:
                                break
                        elif 'weather_day' in day:
                            if provider._is_precipitation(str(day['weather_day'])):
                                precipitation_day += 1
                            else:
                                break

                    # 计算最高气温变化
                    #                                  ! 小米天气api 的 temp_low 才是最高气温 以后可能需要单独处理 !
                    today = daily_data[0]
                    tomorrow = daily_data[1]
                    try:  #                            ↑ ↑ ↑
                        today_high = float(today.get('temp_low', today.get('tempMax', today.get('daytemp', 0))))
                        tomorrow_high = float(tomorrow.get('temp_low', tomorrow.get('tempMax', tomorrow.get('daytemp', 0))))
                        temp_change = tomorrow_high - today_high
                    except (ValueError, TypeError, KeyError) as e:
                        logger.error(f"计算温度变化失败: {e}")
                        temp_change = 0

            return {
                'precipitation': precipitation_now,  # 当前是否降水
                'precipitation_time': precipitation_time,  # 降水状态逐小时预报分组列表
                'tomorrow_precipitation': tomorrow_precipitation,  # 明日是否降水
                'precipitation_day': precipitation_day,  # 降水持续天数
                'first_hour_precip': first_hour_precip,  # 预报中第一小时是否降水
                'same_precipitation': same_precipitation,  # 当前降水和第一小时降水状态是否相同
                'temp_change': temp_change  # 今明最高温变化值
            }
        except Exception as e:
            logger.error(f'获取降水信息失败: {e}')
            return {
                'precipitation': False,
                'precipitation_time': [],
                'tomorrow_precipitation': False,
                'precipitation_day': 0,
                'first_hour_precip': False,
                'same_precipitation': True,
                'temp_change': 0
            }

    @cache_result(expire_seconds=600)  # 缓存10分钟
    def get_weather_reminders(self, api_name: str = None, location_key: str = None) -> List[Dict[str, Any]]:
        """获取天气提醒信息

        Args:
            api_name: API名称
            location_key: 城市位置键
        """
        if api_name is None:
            api_name = self.get_current_api()
        if location_key is None:
            location_key = self._get_location_key()

        provider = self.get_current_provider()
        if not provider:
            return []

        try:
            import threading
            timeout_occurred = threading.Event()
            def timeout_handler():
                timeout_occurred.set()
            # 15秒超时
            timer = threading.Timer(15.0, timeout_handler)
            timer.start()

            try:
                precip_info = self.get_precipitation_info()
                reminders = []
                hourly_forecast = self.fetch_hourly_forecast()
                if hourly_forecast and len(hourly_forecast) > 0:
                    same_precipitation = precip_info['same_precipitation']
                    if same_precipitation:  # 当前降水和第一个小时的降水状态相同
                        if precip_info['precipitation']:  # 当前正在降水, 降水持续
                            if precip_info['precipitation_time'] and precip_info['precipitation_time'][0] <= 2:
                                duration = precip_info['precipitation_time'][0]
                                reminders.append({
                                    'type': 'precipitation_hours',
                                    'title': QCoreApplication.translate(
                                        "WeatherReminder",
                                        "降水将持续 {} 小时"
                                    ).format(duration),
                                    'icon': 'rain'
                                })
                            else:
                                reminders.append({
                                    'type': 'precipitation_continue',
                                    'title': QCoreApplication.translate(
                                        "WeatherReminder",
                                        "降水将持续很久"
                                    ),
                                    'icon': 'rain'
                                })
                        else:  # 当前没有降水, 很久后才有降水
                            if precip_info['precipitation_time'] and precip_info['precipitation_time'][0] <= 3:
                                hours = precip_info['precipitation_time'][0]
                                reminders.append({
                                    'type': 'precipitation_soon',
                                    'title': QCoreApplication.translate(
                                        "WeatherReminder",
                                        "{} 小时后有降水"
                                    ).format(hours),
                                    'icon': 'rain'
                                })
                            # 明日降水提醒
                            elif precip_info['tomorrow_precipitation']:
                                days = precip_info['precipitation_day']  # 先留着吧
                                reminders.append({
                                    'type': 'tomorrow_precipitation',
                                    'title': QCoreApplication.translate(
                                        "WeatherReminder",
                                        "明日有降水"
                                    ),
                                    'icon': 'rain'
                                })
                else:
                    if precip_info['precipitation']:
                        reminders.append({
                            'type': 'precipitation_stop_soon',
                            'title': QCoreApplication.translate(
                                "WeatherReminder",
                                "雨快要停了"
                            ),
                            'icon': 'no_rain'
                        })
                    else:
                        reminders.append({
                            'type': 'precipitation_start_soon',
                            'title': QCoreApplication.translate(
                                "WeatherReminder",
                                "快要下雨了"
                            ),
                            'icon': 'rain'
                        })

                # 气温提醒
                if precip_info['temp_change'] >= 8:
                    reminders.append({
                        'type': 'temperature_rise',
                        'title': QCoreApplication.translate(
                            "WeatherReminder",
                            "明日气温陡升"
                        ),
                        'icon': 'high_temp'
                    })
                elif precip_info['temp_change'] <= -8:
                    reminders.append({
                        'type': 'temperature_drop',
                        'title': QCoreApplication.translate(
                            "WeatherReminder",
                            "明日气温骤降"
                        ),
                        'icon': 'low_temp'
                    })

                return reminders
            finally:
                timer.cancel()  # 取消超时定时器
        except Exception as e:
            logger.error(f'获取天气提醒失败: {e}')
            return []


class GenericWeatherProvider(WeatherapiProvider):
    """通用天气api获得"""

    @retry_on_failure(max_retries=2, delay=0.5)
    def fetch_current_weather(self, location_key: str, api_key: str) -> Dict[str, Any]:
        """获取当前天气数据"""
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            url = self.base_url.format(location_key=location_key, days=1, key=api_key)
            #logger.debug(f'{self.api_name} 请求URL: {url}')
            response = requests.get(url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f'{self.api_name} 获取天气数据失败: {e}')
            raise

    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取天气预警数据"""
        if not self.supports_alerts():
            return None

        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            alert_url = self.config['alerts'].get('url', '')
            if not alert_url:
                return None

            url = alert_url.format(location_key=location_key, key=api_key)
            # logger.debug(f'{self.api_name} 预警请求URL: {url.replace(api_key, "***" if api_key else "(空)")}')
            response = requests.get(url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f'{self.api_name} 获取预警数据失败: {e}')
            return None

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据"""
        temp_path = self.parameters.get('temp', '')
        if not temp_path:
            logger.error(f"温度路径为空: {self.api_name}")
            return None
        # logger.debug(f"解析温度 - api: {self.api_name}, 路径: {temp_path}")
        value = self._extract_value_by_path(data, temp_path)
        # logger.debug(f"提取的温度值: {value}")
        return f"{value}°" if value is not None else None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码"""
        icon_path = self.parameters.get('icon', '')
        if not icon_path:
            logger.error(f"图标路径为空: {self.api_name}")
            return None
        value = self._extract_value_by_path(data, icon_path)
        # logger.debug(f"提取的图标值: {value}")
        # 神经天气服务商
        if self.config.get('return_desc', False) and value:
            pass

        return str(value) if value is not None else None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析描述"""
        desc_path = self.parameters.get('description', '')
        if desc_path:
            result = self._extract_value_by_path(data, desc_path)
            return str(result) if result is not None else None

        icon_code = self.parse_weather_icon(data)
        if icon_code:
            # 通过WeatherDataProcessor获得
            return None

        return None

    def _extract_value_by_path(self, data: Dict[str, Any], path: str) -> Optional[Union[str, int, float, Dict[str, Any], List[Any]]]:
        """提取数据值"""
        if not self._is_valid_extraction_input(data, path):
            return None

        try:
            value: Any = data
            for key in path.split('.'):
                value = self._extract_single_key(value, key)
                if value is None:
                    return None
            return value
        except Exception as e:
            logger.error(f'解析数据路径 {path} 失败: {e}')
            return None

    def _is_valid_extraction_input(self, data: Any, path: str) -> bool:
        """验证输入有效性"""
        return bool(path and data)

    def _extract_single_key(self, value: Any, key: str) -> Optional[Union[str, int, float, Dict[str, Any], List[Any]]]:
        """提取单键值"""
        if key == '0' and isinstance(value, list):
            return value[0] if len(value) > 0 else None
        elif isinstance(value, dict):
            return value.get(key)
        else:
            return None

    def fetch_forecast_data(self, location_key: str, api_key: str, forecast_type: str, days: int = 5) -> Dict[str, Any]:
        """获取预报数据的统一方法"""
        config_key = f"{forecast_type}_forecast"
        forecast_config = self.config.get(config_key, {})

        if not forecast_config:
            logger.warning(f"{self.api_name} 未配置 {forecast_type} 预报")
            return {}

        try:
            from network_thread import proxies
            url_template = forecast_config.get('url', '')
            if not url_template:
                return {}
            url = url_template.format(
                location_key=location_key,
                key=api_key,
                days=days
            )
            if self.config.get('method') == 'coordinates':
                if ',' in location_key:
                    lon, lat = location_key.split(',')
                    url = url.format(lon=lon, lat=lat)

            # logger.debug(f"获取 {forecast_type} 预报数据: {url}")
            response = requests.get(url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取 {forecast_type} 预报失败: {e}")
            return {}

    def parse_forecast_data(self, raw_data: Dict[str, Any], forecast_type: str) -> List[Dict[str, Any]]:
        """解析预报数据的统一方法"""
        config_key = f"{forecast_type}_forecast"
        forecast_config = self.config.get(config_key, {})

        if not forecast_config:
            return []

        data_path = forecast_config.get('data_path', '')
        if not data_path:
            return []

        # 提取原始预报数据
        forecast_data = self._extract_value_by_path(raw_data, data_path)
        if not forecast_data:
            return []

        # 确保数据是列表类型
        if not isinstance(forecast_data, list):
            forecast_data = [forecast_data]

        # 创建基本预报条目
        forecast_items = []
        for i, item in enumerate(forecast_data):
            if not isinstance(item, dict):
                continue

            forecast_item = {}
            # 映射字段
            for field, path_template in forecast_config.get('fields', {}).items():
                # 处理路径中的索引占位符
                path = path_template.replace('{index}', str(i))
                value = self._extract_value_by_path(item, path)
                if value is not None:
                    forecast_item[field] = value

            if forecast_item:
                forecast_items.append(forecast_item)

        return forecast_items

    def fetch_hourly_forecast(self, location_key: str, api_key: str) -> List[Dict[str, Any]]:
        """获取逐小时天气预报数据(兼容接口)"""
        try:
            raw_data = self.fetch_forecast_data(location_key, api_key, "hourly")
            return self.parse_forecast_data(raw_data, "hourly")
        except Exception as e:
            logger.error(f"获取逐小时预报失败: {e}")
            return []

    def fetch_daily_forecast(self, location_key: str, api_key: str, days: int = 5) -> List[Dict[str, Any]]:
        """获取多天天气预报数据(兼容接口)"""
        try:
            raw_data = self.fetch_forecast_data(location_key, api_key, "daily", days)
            return self.parse_forecast_data(raw_data, "daily")
        except Exception as e:
            logger.error(f"获取多天预报失败: {e}")
            return []

    def parse_update_time(self, data: Dict[str, Any]) -> Optional[str]:
        """解析更新时间(通用实现)"""
        try:
            # 尝试从配置的路径获取更新时间
            update_time_path = self.parameters.get('updateTime', '')
            if update_time_path:
                value = self._extract_value_by_path(data, update_time_path)
                if value:
                    return str(value)
            common_fields = ['updateTime', 'update_time', 'lastUpdate', 'last_update', 'time']
            for field in common_fields:
                value = data.get(field)
                if value:
                    return str(value)

            return None
        except Exception as e:
            logger.error(f"解析更新时间失败({self.api_name}): {e}")
            return None


class XiaomiWeatherProvider(GenericWeatherProvider):
    """小米天气api获得"""

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气温度"""
        try:
            # 结构: now.current.temperature.value
            current = data.get("current", {})
            temperature = current.get('temperature', {})
            temp_unit = temperature.get('unit', '℃')
            temp_value = temperature.get('value')

            if temp_value is not None and str(temp_value).strip():
                return f"{temp_value}{temp_unit}"
            else:
                logger.error(f"小米天气api温度数据为空: {temp_value}")
                return None
        except Exception as e:
            logger.error(f"解析小米天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析图标代码"""
        try:
            # 结构: now.current.weather
            current = data.get("current", {})
            code = current.get('weather')
            if code is None or str(code).strip() == '':
                logger.error(f"天气码为空: {code}")
                return None
            return str(code)
        except Exception as e:
            logger.error(f"解析天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气api描述"""
        try:
            weather_code = self.parse_weather_icon(data)
            if weather_code:
                return weather_code  # WeatherDataProcessor处理
            return None
        except Exception as e:
            logger.error(f"解析小米天气描述失败: {e}")
            return None

    def parse_wind_speed(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气风速"""
        try:
            # 结构: now.current.wind.speed
            current = data.get("current", {})
            wind = current.get('wind', {})
            speed = wind.get('speed', {})
            speed_value = speed.get('value')
            speed_unit = speed.get('unit', 'km/h')
            if speed_value is not None and str(speed_value).strip():
                return f"{speed_value} {speed_unit}"
            return None
        except Exception as e:
            logger.error(f"解析风速失败(小米天气): {e}")
            return None

    def parse_humidity(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气湿度"""
        try:
            # 结构: now.current.humidity
            current = data.get("current", {})
            humidity = current.get('humidity', {})
            humidity_value = humidity.get('value')
            if humidity_value is not None and str(humidity_value).strip():
                return f"{humidity_value} %"
            return None
        except Exception as e:
            logger.error(f"解析湿度失败(小米天气): {e}")
            return None

    def parse_visibility(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气能见度"""
        try:
            # 结构: now.current.visibility
            current = data.get("current", {})
            visibility = current.get('visibility')
            if isinstance(visibility, dict):
                visibility_value = visibility.get('value')
                visibility_unit = visibility.get('unit', 'km')
                if visibility_value is not None and str(visibility_value).strip():
                    return f"{visibility_value} {visibility_unit}"
                else:
                    return f"-- {visibility_unit}"
            elif isinstance(visibility, (int, float)):
                return f"{visibility} km"
            elif isinstance(visibility, str) and visibility.strip():
                return f"{visibility} km"

            logger.warning(f"小米天气能见度数据为空或格式不正确: '{visibility}' (类型: {type(visibility)})")
            return "-- km"
        except Exception as e:
            logger.error(f"解析能见度失败(小米天气): {e}")
            return None

    def parse_pressure(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气气压"""
        try:
            # 结构: now.current.pressure
            current = data.get("current", {})
            pressure = current.get('pressure', {})
            pressure_value = pressure.get('value')
            pressure_unit = pressure.get('unit', 'hPa')
            if pressure_value is not None and str(pressure_value).strip():
                return f"{pressure_value} {pressure_unit}"
            return None
        except Exception as e:
            logger.error(f"解析气压失败(小米天气): {e}")
            return None

    def parse_feels_like(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气体感温度"""
        try:
            # 结构: now.current.feelsLike
            current = data.get("current", {})
            feels_like = current.get('feelsLike', {})
            feels_like_value = feels_like.get('value')
            feels_like_unit = feels_like.get('unit', '℃')
            if feels_like_value is not None and str(feels_like_value).strip():
                return f"{feels_like_value}{feels_like_unit}"
            return None
        except Exception as e:
            logger.error(f"解析体感温度失败(小米天气): {e}")
            return None

    def parse_wind_direction(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气风向"""
        try:
            # 结构: now.current.wind.direction
            current = data.get("current", {})
            wind = current.get('wind', {})
            direction = wind.get('direction', {})
            direction_value = direction.get('value')
            direction_unit = direction.get('unit', '°')
            if direction_value is not None and str(direction_value).strip():
                # 将角度转换为方向描述
                direction_desc = self._convert_wind_direction(float(direction_value))
                return f"{direction_desc}"
            return None
        except Exception as e:
            logger.error(f"解析风向失败(小米天气): {e}")
            return None

    def _convert_wind_direction(self, degree: float) -> str:
        """将风向角度转换为方向描述"""
        directions = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
        ]
        index = int((degree + 11.25) / 22.5) % 16
        return directions[index]

    def parse_aqi_data(self, data: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """解析小米天气空气质量数据"""
        try:
            # 结构: aqi字段内
            aqi_data = data.get('aqi', {})
            result = {
                'aqi': aqi_data.get('aqi'),
                'co': aqi_data.get('co'),
                'no2': aqi_data.get('no2'),
                'o3': aqi_data.get('o3'),
                'pm10': aqi_data.get('pm10'),
                'pm25': aqi_data.get('pm25'),
                'so2': aqi_data.get('so2'),
                'suggest': aqi_data.get('suggest'),
                'src': aqi_data.get('src')
            }
            return result
        except Exception as e:
            logger.error(f"解析空气质量数据失败(小米天气): {e}")
            return {}

    def parse_aqi(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气AQI指数"""
        try:
            aqi_data = data.get('aqi', {})
            aqi_value = aqi_data.get('aqi')
            if aqi_value is not None and str(aqi_value).strip():
                return str(aqi_value)
            return None
        except Exception as e:
            logger.error(f"解析AQI失败(小米天气): {e}")
            return None

    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取小米天气预警"""
        try:
            weather_data = self.fetch_current_weather(location_key, api_key)
            if weather_data:
                alerts = self.parse_weather_alerts(weather_data)
                if alerts:
                    result = {'warning': alerts}
                    return result
            return None
        except Exception as e:
            return None

    def parse_weather_alerts(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析小米天气预警"""
        try:
            alerts_data = data.get('alerts', [])
            if not alerts_data:
                return []

            return self._process_xiaomi_alerts(alerts_data)
        except Exception as e:
            return []

    def _process_xiaomi_alerts(self, alerts_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理小米天气预警"""
        alerts = []
        for alert_item in alerts_data:
            if isinstance(alert_item, dict):
                alert = self._build_xiaomi_alert(alert_item)
                alerts.append(alert)
        return alerts

    def _build_xiaomi_alert(self, alert_item: Dict[str, Any]) -> Dict[str, Any]:
        """构建小米天气预警"""
        return {
            'id': alert_item.get('alertId', ''),
            'title': alert_item.get('title', ''),
            'level': alert_item.get('level', ''),
            'detail': alert_item.get('detail', ''),
            'start_time': alert_item.get('pubTime', ''),
            'end_time': alert_item.get('end_time', ''),
            'type': alert_item.get('type', ''),
            'description': alert_item.get('detail', '')
        }

    def parse_update_time(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气更新时间"""
        try:
            # 小米天气API的更新时间可能在不同位置
            update_time = data.get('updateTime')
            if update_time:
                return str(update_time)
            # 尝试从current字段获取
            current = data.get('current', {})
            update_time = current.get('updateTime')
            if update_time:
                return str(update_time)
            # 尝试从其他可能的字段获取
            update_time = data.get('lastUpdate') or data.get('time')
            if update_time:
                return str(update_time)
            return None
        except Exception as e:
            logger.error(f"解析小米天气更新时间失败: {e}")
            return None

    def fetch_hourly_forecast(self, location_key: str, api_key: str) -> List[Dict[str, Any]]:
        """获取小米天气的逐小时预报数据"""
        try:
            raw_data = super().fetch_hourly_forecast(location_key, api_key)
            return self.parse_hourly_forecast(raw_data)
        except Exception as e:
            logger.error(f"获取小米天气逐小时预报失败: {e}")
            return []

    def fetch_daily_forecast(self, location_key: str, api_key: str, days: int = 5) -> List[Dict[str, Any]]:
        """获取小米天气的多天预报数据"""
        try:
            raw_data = super().fetch_daily_forecast(location_key, api_key, days)
            return self.parse_daily_forecast(raw_data)
        except Exception as e:
            logger.error(f"获取小米天气多天预报失败: {e}")
            return []

    def _is_precipitation(self, weather_code: str) -> bool:
        """判断天气是否为降水类型"""
        weather_desc = weather_processor.get_weather_by_code(weather_code)
        # 检查天气描述中是否包含降水关键词
        return any(keyword in weather_desc for keyword in ["雨", "雪", "雹"])

    def parse_hourly_forecast(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析逐小时天气预报数据, 添加降水判断"""
        result = []
        precipitation_time = []  # 存储降水时间分组
        current_precip = None    # 当前降水状态
        count = 0                # 当前分组计数

        try:
            temps = data.get("temperature", {}).get("value", [])
            weather_codes = data.get("weather", {}).get("value", [])

            # 构建每小时数据
            for i in range(min(len(temps), len(weather_codes))):
                weather_code = str(weather_codes[i])
                is_precip = self._is_precipitation(weather_code)

                hour_data = {
                    "temperature": temps[i],
                    "weather_code": weather_code,
                    "precipitation": is_precip,  # 添加降水标记
                    "hour": i  # 相对于当前时间的小时偏移
                }
                result.append(hour_data)

                # 降水状态分组统计
                if current_precip is None:
                    current_precip = is_precip
                    count = 1
                elif current_precip == is_precip:
                    count += 1
                else:
                    precipitation_time.append(count)
                    current_precip = is_precip
                    count = 1

            # 添加最后一组
            if count > 0:
                precipitation_time.append(count)

            # 添加降水分组统计结果
            result.append({"precipitation_time": precipitation_time})

        except Exception as e:
            logger.error(f"解析小米逐小时预报失败: {e}")

        return result

    def parse_daily_forecast(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析多天天气预报数据, 添加降水日统计"""
        result = []
        precipitation_days = []  # 存储降水日标记
        tomorrow_precipitation = False  # 明日白天是否降水
        precipitation_day = 0  # 连续降水日天数

        try:
            temp_ranges = data.get("temperature", {}).get("value", [])
            weather_values = data.get("weather", {}).get("value", [])

            for i in range(min(len(temp_ranges), len(weather_values))):
                weather_day = str(weather_values[i]["from"]) if "from" in weather_values[i] else ""
                weather_night = str(weather_values[i]["to"]) if "to" in weather_values[i] else ""

                # 判断是否为降水日
                day_precip = self._is_precipitation(weather_day) if weather_day else False
                night_precip = self._is_precipitation(weather_night) if weather_night else False
                is_precip_day = day_precip or night_precip

                day_data = {
                    "day": i,  # 日期偏移
                    "temp_high": temp_ranges[i]["to"] if "to" in temp_ranges[i] else "",
                    "temp_low": temp_ranges[i]["from"] if "from" in temp_ranges[i] else "",
                    "weather_day": weather_day,
                    "weather_night": weather_night,
                    "precipitation_day": is_precip_day,  # 标记是否为降水日
                    "day_precipitation": day_precip  # 标记白天是否有降水
                }
                result.append(day_data)
                precipitation_days.append(is_precip_day)

                # 检查明日是否是白天降水日
                if i == 1:
                    tomorrow_precipitation = day_precip

            # 计算连续降水日天数
            if tomorrow_precipitation:
                # 从明日开始计算连续降水日
                for i in range(1, len(precipitation_days)):
                    if precipitation_days[i]:
                        precipitation_day += 1
                    else:
                        break

                # 添加统计结果
                result.append({
                    "tomorrow_precipitation": tomorrow_precipitation,
                    "precipitation_day": precipitation_day
                })

        except Exception as e:
            logger.error(f"解析小米多天预报失败: {e}")

        return result

    def fetch_forecast_data(self, location_key: str, api_key: str, forecast_type: str, days: int = 5) -> Dict[str, Any]:
        """小米天气特殊处理"""
        try:
            # 获取完整天气数据
            full_data = self.fetch_current_weather(location_key, api_key)
            if not full_data:
                return {}

            if forecast_type == 'hourly':
                hourly_forecast = full_data.get("forecastHourly", {})
                return hourly_forecast
            elif forecast_type == 'daily':
                daily_forecast = full_data.get("forecastDaily", {})
                # 根据请求的天数截取数据
                if days > 0:
                    for key in ["temperature", "weather", "wind", "precipitationProbability"]:
                        if key in daily_forecast and "value" in daily_forecast[key]:
                            daily_forecast[key]["value"] = daily_forecast[key]["value"][:days]
                return daily_forecast
            else:
                return {}
        except Exception as e:
            logger.error(f"获取小米天气{forecast_type}预报失败: {e}")
            return {}

    def parse_forecast_data(self, raw_data: Dict[str, Any], forecast_type: str) -> List[Dict[str, Any]]:
        """小米天气特殊解析"""
        if forecast_type == 'hourly':
            return self.parse_hourly_forecast(raw_data)
        elif forecast_type == 'daily':
            return self.parse_daily_forecast(raw_data)
        return []


class QWeatherProvider(GenericWeatherProvider):
    """和风天气api提供者"""

    @retry_on_failure(max_retries=2, delay=0.5)
    def fetch_current_weather(self, location_key: str, api_key: str) -> Dict[str, Any]:
        """获取当前天气数据(支持经纬度和城市ID)"""
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            if ',' in location_key:
                lon, lat = location_key.split(',')
                lat = f"{float(lat):.2f}"
                lon = f"{float(lon):.2f}"
                # Note：和风天气API要求经度在前, 纬度在后 (小数点后两位)
                url = self.base_url.format(location_key=f"{lon},{lat}", key=api_key)
            else:
                url = self.base_url.format(location_key=location_key, key=api_key)
            # logger.debug(f'{self.api_name} 请求URL: {url.replace(api_key, "***" if api_key else "(空)")}')
            response = requests.get(url, proxies=proxies, timeout=10)
            response.raise_for_status()
            result = response.json()
            # logger.debug(f'{self.api_name} API响应: {result}')
            return result
        except Exception as e:
            logger.error(f'{self.api_name} 获取天气数据失败: {e}')
            raise

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据(和风天气)"""
        try:
            # 和风天气api结构: now.temp
            now = data.get('now', {})
            temp = now.get('temp')

            if temp is not None:
                return f"{temp}°"
            return None
        except Exception as e:
            logger.error(f"解析和风天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码(和风天气)"""
        try:
            # 和风天气api结构: now.icon
            now = data.get('now', {})
            icon_code = now.get('icon')

            if icon_code is not None:
                return str(icon_code)
            return None
        except Exception as e:
            logger.error(f"解析和风天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述(和风天气)"""
        try:
            # 和风天气api结构: now.text
            now = data.get('now', {})
            text = now.get('text')

            if text:
                return text
            icon_code = self.parse_weather_icon(data)
            return icon_code if icon_code else None
        except Exception as e:
            logger.error(f"解析和风天气描述失败: {e}")
            return None

    def parse_update_time(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气数据更新时间(和风天气)"""
        try:
            # 和风天气api结构: updateTime
            update_time = data.get('updateTime')
            if update_time:
                return str(update_time)

            # 如果顶层没有, 尝试从now中获取
            now = data.get('now', {})
            update_time = now.get('updateTime')
            if update_time:
                return str(update_time)

            return None
        except Exception as e:
            logger.error(f"解析和风天气更新时间失败: {e}")
            return None

    def parse_humidity(self, data: Dict[str, Any]) -> Optional[str]:
        """解析湿度数据(和风天气)"""
        try:
            # 和风天气api结构: now.humidity
            now = data.get('now', {})
            humidity = now.get('humidity')

            if humidity is not None:
                return f"{humidity}%"
            return None
        except Exception as e:
            logger.error(f"解析和风天气湿度失败: {e}")
            return None

    def parse_pressure(self, data: Dict[str, Any]) -> Optional[str]:
        """解析气压数据(和风天气)"""
        try:
            # 和风天气api结构: now.pressure
            now = data.get('now', {})
            pressure = now.get('pressure')

            if pressure is not None:
                return f"{pressure} hPa"
            return None
        except Exception as e:
            logger.error(f"解析和风天气气压失败: {e}")
            return None

    def parse_visibility(self, data: Dict[str, Any]) -> Optional[str]:
        """解析能见度数据(和风天气)"""
        try:
            # 和风天气api结构: now.vis
            now = data.get('now', {})
            visibility = now.get('vis')

            if visibility is not None:
                return f"{visibility} km"
            return None
        except Exception as e:
            logger.error(f"解析和风天气能见度失败: {e}")
            return None

    def parse_feels_like(self, data: Dict[str, Any]) -> Optional[str]:
        """解析体感温度数据(和风天气)"""
        try:
            # 和风天气api结构: now.feelsLike
            now = data.get('now', {})
            feels_like = now.get('feelsLike')

            if feels_like is not None:
                return f"{feels_like}°"
            return None
        except Exception as e:
            logger.error(f"解析和风天气体感温度失败: {e}")
            return None

    def parse_wind_direction(self, data: Dict[str, Any]) -> Optional[str]:
        """解析风向数据(和风天气)"""
        try:
            # 和风天气api结构: now.windDir 和 now.wind360
            now = data.get('now', {})
            wind_dir = now.get('windDir')
            wind_360 = now.get('wind360')
            if wind_360 is not None:
                try:
                    degree = float(wind_360)
                    direction_desc = self._convert_wind_direction(degree)
                    return f"{direction_desc}"
                except (ValueError, TypeError):
                    pass
            if wind_dir:
                return wind_dir

            return None
        except Exception as e:
            logger.error(f"解析和风天气风向失败: {e}")
            return None

    def _convert_wind_direction(self, degree: float) -> str:
        """将风向角度转换为方向描述(和风天气)"""
        directions = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
        ]
        index = int((degree + 11.25) / 22.5) % 16
        return directions[index]

    def parse_wind_speed(self, data: Dict[str, Any]) -> Optional[str]:
        """解析风速数据(和风天气)"""
        try:
            now = data.get('now', {})
            wind_speed = now.get('windSpeed')
            wind_scale = now.get('windScale')
            if wind_speed is not None:
                return f"{wind_speed} km/h"
            if wind_scale is not None:
                return f"{wind_scale}级"

            return None
        except Exception as e:
            logger.error(f"解析和风天气风速失败: {e}")
            return None

    def fetch_air_quality_data(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取和风天气空气质量数据"""
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            if ',' in location_key:
                lon, lat = location_key.split(',')
                lat = f"{float(lat):.2f}"
                lon = f"{float(lon):.2f}"
                # Note：和风天气API要求经度在前, 纬度在后 (小数点后两位)
                air_url = f"https://devapi.qweather.com/v7/air/now?location={lon},{lat}&key={api_key}"
            else:
                air_url = f"https://devapi.qweather.com/v7/air/now?location={location_key}&key={api_key}"

            response = requests.get(air_url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f'和风天气获取空气质量数据失败: {e}')
            return None

    def parse_aqi(self, data: Dict[str, Any]) -> Optional[str]:
        """解析AQI数据(和风天气)"""
        try:
            # 和风天气空气质量api结构: now.aqi
            now = data.get('now', {})
            aqi = now.get('aqi')

            if aqi is not None:
                return str(aqi)
            return None
        except Exception as e:
            logger.error(f"解析和风天气AQI失败: {e}")
            return None

    def parse_aqi_data(self, data: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """解析空气质量(和风天气)"""
        result = {
            'co': None,
            'no2': None,
            'o3': None,
            'pm10': None,
            'pm25': None,
            'so2': None
        }
        try:
            # 和风天气空气质量api结构: now.co, now.no2, now.o3, now.pm10, now.pm2p5, now.so2
            now = data.get('now', {})
            # 一氧化碳 (CO)
            co = now.get('co')
            if co is not None:
                result['co'] = f"{co} mg/m³"
            # 二氧化氮 (NO2)
            no2 = now.get('no2')
            if no2 is not None:
                result['no2'] = f"{no2} μg/m³"
            # 臭氧 (O3)
            o3 = now.get('o3')
            if o3 is not None:
                result['o3'] = f"{o3} μg/m³"
            # PM10
            pm10 = now.get('pm10')
            if pm10 is not None:
                result['pm10'] = f"{pm10} μg/m³"
            # PM2.5 (note:和风天气为pm2p5)
            pm25 = now.get('pm2p5')
            if pm25 is not None:
                result['pm25'] = f"{pm25} μg/m³"
            # 二氧化硫 (SO2)
            so2 = now.get('so2')
            if so2 is not None:
                result['so2'] = f"{so2} μg/m³"
            return result
        except Exception as e:
            logger.error(f"解析和风天气空气质量数据失败: {e}")
            return result

    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取和风天气预警数据"""
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            if ',' in location_key:
                lon, lat = location_key.split(',')
                lat = f"{float(lat):.2f}"
                lon = f"{float(lon):.2f}"
                # Note：和风天气API要求经度在前, 纬度在后 (小数点后两位)
                alert_url = f"https://devapi.qweather.com/v7/warning/now?location={lon},{lat}&key={api_key}"
            else:
                alert_url = f"https://devapi.qweather.com/v7/warning/now?location={location_key}&key={api_key}"
            # logger.debug(f'和风天气预警请求URL: {alert_url.replace(api_key, "***" if api_key else "(空)")}')

            response = requests.get(alert_url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f'和风天气获取预警数据失败: {e}')
            return None

    def parse_weather_alerts(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析和风天气预警"""
        try:
            if not self._validate_qweather_response(data):
                return []

            warning_list = data.get('warning', [])
            if not warning_list:
                return []

            return self._process_qweather_warnings(warning_list)
        except Exception as e:
            logger.error(f"解析和风天气预警数据失败: {e}")
            return []

    def _validate_qweather_response(self, data: Dict[str, Any]) -> bool:
        """验证和风天气响应"""
        if data.get('code') != '200':
            logger.warning(f"和风天气预警API返回错误: {data.get('code')}, 完整响应: {data}")
            return False
        return True

    def _process_qweather_warnings(self, warning_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理和风天气预警"""
        alerts = []
        for warning in warning_list:
            try:
                alert = self._build_qweather_alert(warning)
                alerts.append(alert)
                # logger.debug(f"解析预警: {alert['title']} - {alert['level']}")
            except Exception as e:
                logger.error(f"解析单个预警失败: {e}")
                continue

        # logger.info(f"和风天气成功解析 {len(alerts)} 条预警信息")
        return alerts

    def _build_qweather_alert(self, warning: Dict[str, Any]) -> Dict[str, Any]:
        """构建和风天气预警"""
        return {
            'id': warning.get('id', ''),
            'title': warning.get('title', ''),
            'sender': warning.get('sender', ''),
            'pub_time': warning.get('pubTime', ''),
            'start_time': warning.get('startTime', ''),
            'end_time': warning.get('endTime', ''),
            'status': warning.get('status', ''),
            'level': warning.get('level', ''),
            'severity': warning.get('severity', ''),
            'severity_color': warning.get('severityColor', ''),
            'type': warning.get('type', ''),
            'type_name': warning.get('typeName', ''),
            'text': warning.get('text', ''),
            'urgency': warning.get('urgency', ''),
            'certainty': warning.get('certainty', ''),
            'related': warning.get('related', '')
        }

    def supports_alerts(self) -> bool:
        """和风天气支持预警功能"""
        return True

    def _is_precipitation(self, weather_code: str) -> bool:
        """判断天气是否为降水类型(和风天气)"""
        if weather_code.isdigit():
            code = int(weather_code)
            # 和风天气降水代码：
            # 300-399: 雨
            # 400-499: 雪
            # 500-515: 雾霾等
            precipitation_codes = {
                # 雨类
                300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 313, 314, 315, 316, 317, 318, 399,
                # 雪类
                400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 456, 457, 499,
                # 雨夹雪
                350, 351, 352, 353, 354, 355, 356, 357, 358,
                # 冰雹
                500, 501, 502, 503, 504, 507, 508,
                # 常见的简化代码
                13  # 雨
            }
            return code in precipitation_codes
        return False

    def parse_forecast_data(self, raw_data: Dict[str, Any], forecast_type: str) -> List[Dict[str, Any]]:
        """解析和风天气预报数据"""
        try:
            if forecast_type == 'hourly':
                return self._parse_hourly_forecast(raw_data)
            elif forecast_type == 'daily':
                return self._parse_daily_forecast(raw_data)
            else:
                return []
        except Exception as e:
            logger.error(f"解析和风天气{forecast_type}预报数据失败: {e}")
            return []

    def _parse_hourly_forecast(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析和风天气逐小时预报数据"""
        result = []
        try:
            if data.get('code') != '200':
                # logger.warning(f"和风天气逐小时预报API返回错误: {data.get('code')}")
                return []
            hourly_data = data.get('hourly', [])
            if not hourly_data:
                # logger.warning("和风天气逐小时预报数据为空")
                return []
            for i, hour_item in enumerate(hourly_data):
                if not isinstance(hour_item, dict):
                    continue
                hour_forecast = {
                    'hour': i,  # 相对于当前时间的小时偏移
                    'fxTime': hour_item.get('fxTime', ''),
                    'temperature': hour_item.get('temp', ''),
                    'weather_code': hour_item.get('icon', ''),
                    'weather_text': hour_item.get('text', ''),
                    'wind_direction': hour_item.get('windDir', ''),
                    'wind_speed': hour_item.get('windSpeed', ''),
                    'wind_scale': hour_item.get('windScale', ''),
                    'humidity': hour_item.get('humidity', ''),
                    'precipitation_probability': hour_item.get('pop', ''),
                    'precipitation': hour_item.get('precip', ''),
                    'pressure': hour_item.get('pressure', ''),
                    'cloud': hour_item.get('cloud', ''),
                    'dew': hour_item.get('dew', ''),
                    'is_precipitation': self._is_precipitation(str(hour_item.get('icon', '')))
                }
                result.append(hour_forecast)

            # logger.info(f"和风天气成功解析 {len(result)} 小时预报数据")
            return result

        except Exception as e:
            logger.error(f"解析和风天气逐小时预报失败: {e}")
            return []

    def _parse_daily_forecast(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析和风天气每日预报数据"""
        result = []
        try:
            if data.get('code') != '200':
                # logger.warning(f"和风天气每日预报API返回错误: {data.get('code')}")
                return []
            daily_data = data.get('daily', [])
            if not daily_data:
                # logger.warning("和风天气每日预报数据为空")
                return []
            for i, day_item in enumerate(daily_data):
                if not isinstance(day_item, dict):
                    continue
                day_forecast = {
                    'day': i,  # 相对于今天的天数偏移
                    'fxDate': day_item.get('fxDate', ''),
                    'sunrise': day_item.get('sunrise', ''),
                    'sunset': day_item.get('sunset', ''),
                    'moonrise': day_item.get('moonrise', ''),
                    'moonset': day_item.get('moonset', ''),
                    'moon_phase': day_item.get('moonPhase', ''),
                    'moon_phase_icon': day_item.get('moonPhaseIcon', ''),
                    'temp_max': day_item.get('tempMax', ''),
                    'temp_min': day_item.get('tempMin', ''),
                    'weather_day_icon': day_item.get('iconDay', ''),
                    'weather_day_text': day_item.get('textDay', ''),
                    'weather_night_icon': day_item.get('iconNight', ''),
                    'weather_night_text': day_item.get('textNight', ''),
                    'wind_direction_day': day_item.get('windDirDay', ''),
                    'wind_speed_day': day_item.get('windSpeedDay', ''),
                    'wind_scale_day': day_item.get('windScaleDay', ''),
                    'wind_direction_night': day_item.get('windDirNight', ''),
                    'wind_speed_night': day_item.get('windSpeedNight', ''),
                    'wind_scale_night': day_item.get('windScaleNight', ''),
                    'humidity': day_item.get('humidity', ''),
                    'precipitation': day_item.get('precip', ''),
                    'pressure': day_item.get('pressure', ''),
                    'visibility': day_item.get('vis', ''),
                    'cloud': day_item.get('cloud', ''),
                    'uv_index': day_item.get('uvIndex', ''),
                    'is_precipitation_day': self._is_precipitation(str(day_item.get('iconDay', ''))),
                    'is_precipitation_night': self._is_precipitation(str(day_item.get('iconNight', '')))
                }
                result.append(day_forecast)

            # logger.info(f"和风天气成功解析 {len(result)} 天预报数据")
            return result
        except Exception as e:
            logger.error(f"解析和风天气每日预报失败: {e}")
            return []


class AmapWeatherProvider(GenericWeatherProvider):
    """高德天气api提供者"""

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据(高德天气)"""
        try:
            # 高德天气api结构: lives[0].temperature
            lives = data.get('lives', [])
            if lives and len(lives) > 0:
                temp = lives[0].get('temperature')
                if temp is not None:
                    return f"{temp}°"
            return None
        except Exception as e:
            logger.error(f"解析高德天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码(高德天气)"""
        try:
            # 高德天气api结构: lives[0].weather
            lives = data.get('lives', [])
            if lives and len(lives) > 0:
                weather = lives[0].get('weather')
                if weather is not None:
                    return str(weather)
            return None
        except Exception as e:
            logger.error(f"解析高德天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述(高德天气)"""
        try:
            # 高德天气api结构: lives[0].weather
            lives = data.get('lives', [])
            if lives and len(lives) > 0:
                weather = lives[0].get('weather')
                if weather:
                    return weather

            return None
        except Exception as e:
            logger.error(f"解析高德天气描述失败: {e}")
            return None

    def parse_update_time(self, data: Dict[str, Any]) -> Optional[str]:
        """解析高德天气更新时间"""
        try:
            # 高德天气API的更新时间可能在不同位置
            update_time = data.get('updateTime')
            if update_time:
                return str(update_time)

            # 尝试从lives字段获取
            lives = data.get('lives', [])
            if lives and len(lives) > 0:
                update_time = lives[0].get('reporttime') or lives[0].get('updateTime')
                if update_time:
                    return str(update_time)

            # 尝试从其他可能的字段获取
            update_time = data.get('reporttime') or data.get('lastUpdate')
            if update_time:
                return str(update_time)

            return None
        except Exception as e:
            logger.error(f"解析高德天气更新时间失败: {e}")
            return None


class QQWeatherProvider(GenericWeatherProvider):
    """腾讯天气api提供者"""

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据(腾讯天气)"""
        try:
            # 腾讯天气api结构: result.realtime[0].infos.temp
            realtime = data.get('result', {}).get('realtime', [])
            if realtime and len(realtime) > 0:
                temp = realtime[0].get('infos', {}).get('temp')
                if temp is not None:
                    return f"{temp}°"
            return None
        except Exception as e:
            logger.error(f"解析腾讯天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码(腾讯天气)"""
        try:
            # 腾讯天气api结构: result.realtime[0].infos.weather_code
            realtime = data.get('result', {}).get('realtime', [])
            if realtime and len(realtime) > 0:
                weather_code = realtime[0].get('infos', {}).get('weather_code')
                if weather_code is not None:
                    return str(weather_code)
            return None
        except Exception as e:
            logger.error(f"解析腾讯天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述(腾讯天气)"""
        try:
            # 腾讯天气api结构: result.realtime[0].infos.weather
            realtime = data.get('result', {}).get('realtime', [])
            if realtime and len(realtime) > 0:
                weather = realtime[0].get('infos', {}).get('weather')
                if weather:
                    return weather

            return None
        except Exception as e:
            logger.error(f"解析腾讯天气描述失败: {e}")
            return None

    def parse_update_time(self, data: Dict[str, Any]) -> Optional[str]:
        """解析腾讯天气更新时间"""
        try:
            # 腾讯天气API的更新时间可能在不同位置
            update_time = data.get('updateTime')
            if update_time:
                return str(update_time)

            # 尝试从result字段获取
            result = data.get('result', {})
            update_time = result.get('updateTime') or result.get('update_time')
            if update_time:
                return str(update_time)

            # 尝试从realtime字段获取
            realtime = result.get('realtime', [])
            if realtime and len(realtime) > 0:
                update_time = realtime[0].get('updateTime') or realtime[0].get('update_time')
                if update_time:
                    return str(update_time)

            return None
        except Exception as e:
            logger.error(f"解析腾讯天气更新时间失败: {e}")
            return None


class OpenMeteoProvider(GenericWeatherProvider):
    @retry_on_failure(max_retries=2, delay=0.5)
    def fetch_current_weather(self, location_key, api_key):
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            lon, lat = location_key.split(',')
        except:
            raise ValueError(f'{self.api_name}: location_key 不为逗号分隔的经纬度模式')

        try:
            from network_thread import proxies
            weather_url = self.base_url.format(lon=lon, lat=lat)
            headers = {
                'User-Agent': 'ClassWidgets'
            }
            weather_response = requests.get(weather_url, proxies=proxies, timeout=10, headers=headers)
            weather_response.raise_for_status()
            weather_data = weather_response.json()
            try:
                air_quality_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=carbon_monoxide,nitrogen_dioxide,ozone,pm10,pm2_5,sulphur_dioxide&timezone=auto"
                air_response = requests.get(air_quality_url, proxies=proxies, timeout=10, headers=headers)
                air_response.raise_for_status()
                air_data = air_response.json()
                weather_data['air_quality'] = air_data
            except Exception as e:
                logger.warning(f'获取空气质量数据失败: {e}')
                weather_data['air_quality'] = None

            return weather_data
        except Exception as e:
            logger.error(f'{self.api_name} 获取天气数据失败: {e}')
            raise

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据(Open-Meteo)"""
        try:
            current = data.get('current', {})
            temp = current.get('temperature_2m')
            current_units = data.get('current_units', {})
            unit = current_units.get('temperature_2m', '°C')
            if temp is not None:
                return f"{temp}{unit}"
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码(Open-Meteo)"""
        try:
            current = data.get('current', {})
            weather_code = current.get('weather_code')
            if weather_code is not None:
                return str(weather_code)
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述(Open-Meteo)"""
        try:
            return self.parse_weather_icon(data)
        except Exception as e:
            logger.error(f"解析 Open-Meteo 描述失败: {e}")
            return None

    def parse_update_time(self, data: Dict[str, Any]) -> Optional[str]:
        """解析Open-Meteo更新时间"""
        try:
            # Open-Meteo API的更新时间通常在current字段中
            current = data.get('current', {})
            update_time = current.get('time')
            if update_time:
                return str(update_time)

            # 尝试从顶层获取
            update_time = data.get('time') or data.get('updateTime')
            if update_time:
                return str(update_time)

            return None
        except Exception as e:
            logger.error(f"解析Open-Meteo更新时间失败: {e}")
            return None

    def _is_precipitation(self, weather_code: str) -> bool:
        """判断天气是否为降水类型(Open-Meteo)"""
        # Open-Meteo降水代码: 51-67, 71-77, 80-86, 95-99
        if weather_code.isdigit():
            code = int(weather_code)
            return (51 <= code <= 67) or (71 <= code <= 77) or (80 <= code <= 86) or (95 <= code <= 99)
        return False

    def parse_feels_like(self, data: Dict[str, Any]) -> Optional[str]:
        """解析体感温度(Open-Meteo)"""
        try:
            current = data.get('current', {})
            feels_like = current.get('apparent_temperature')
            current_units = data.get('current_units', {})
            unit = current_units.get('apparent_temperature', '°C')
            if feels_like is not None:
                return f"{feels_like}{unit}"
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 体感温度失败: {e}")
            return None

    def parse_humidity(self, data: Dict[str, Any]) -> Optional[str]:
        """解析湿度(Open-Meteo)"""
        try:
            current = data.get('current', {})
            humidity = current.get('relative_humidity_2m')
            if humidity is not None:
                return f"{humidity}%"
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 湿度失败: {e}")
            return None

    def parse_wind_speed(self, data: Dict[str, Any]) -> Optional[str]:
        """解析风速(Open-Meteo)"""
        try:
            current = data.get('current', {})
            wind_speed = current.get('wind_speed_10m')
            current_units = data.get('current_units', {})
            unit = current_units.get('wind_speed_10m', 'km/h')
            if wind_speed is not None:
                return f"{wind_speed} {unit}"
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 风速失败: {e}")
            return None

    def parse_wind_direction(self, data: Dict[str, Any]) -> Optional[str]:
        """解析风向(Open-Meteo)"""
        try:
            current = data.get('current', {})
            wind_direction = current.get('wind_direction_10m')
            if wind_direction is not None:
                # 将角度转换为方向描述, 使用与小米天气相同的格式
                direction_desc = self._convert_wind_direction(float(wind_direction))
                return f"{direction_desc}"
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 风向失败: {e}")
            return None

    def _convert_wind_direction(self, degree: float) -> str:
        """将风向角度转换为方向描述(Open-Meteo)"""
        directions = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
        ]
        index = int((degree + 11.25) / 22.5) % 16
        return directions[index]

    def parse_pressure(self, data: Dict[str, Any]) -> Optional[str]:
        """解析气压(Open-Meteo)"""
        try:
            current = data.get('current', {})
            pressure = current.get('surface_pressure')
            current_units = data.get('current_units', {})
            unit = current_units.get('surface_pressure', 'hPa')
            if pressure is not None:
                return f"{pressure} {unit}"
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 气压失败: {e}")
            return None

    def parse_visibility(self, data: Dict[str, Any]) -> Optional[str]:
        """解析能见度(Open-Meteo)"""
        try:
            current = data.get('current', {})
            visibility = current.get('visibility')

            if visibility is not None:
                if isinstance(visibility, (int, float)):
                    visibility_km = visibility / 1000
                    return f"{visibility_km:.1f} km"
                elif isinstance(visibility, dict):
                    visibility_value = visibility.get('value')
                    if isinstance(visibility_value, (int, float)):
                        visibility_km = visibility_value / 1000
                        return f"{visibility_km:.1f} km"
                elif isinstance(visibility, str):
                    try:
                        visibility_num = float(visibility)
                        visibility_km = visibility_num / 1000
                        return f"{visibility_km:.1f} km"
                    except ValueError:
                        logger.warning(f"Open-Meteo能见度字符串无法转换为数值: '{visibility}'")
                        return None

                logger.warning(f"Open-Meteo能见度数据格式不正确: '{visibility}' (类型: {type(visibility)})")
            return None
        except Exception as e:
            logger.error(f"解析 Open-Meteo 能见度失败: {e}")
            return None

    def parse_aqi_data(self, data: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """解析空气质量数据(Open-Meteo)"""
        aqi_data = {
            'co': None,
            'no2': None,
            'o3': None,
            'pm10': None,
            'pm25': None,
            'so2': None
        }
        try:
            air_quality = data.get('air_quality')
            if not air_quality:
                return aqi_data
            current = air_quality.get('current', {})
            current_units = air_quality.get('current_units', {})
            # 一氧化碳 (CO)
            if 'carbon_monoxide' in current:
                co_value = current['carbon_monoxide']
                co_unit = current_units.get('carbon_monoxide', 'μg/m³')
                if co_value is not None:
                    aqi_data['co'] = f"{co_value} {co_unit}"
            # 二氧化氮 (NO2)
            if 'nitrogen_dioxide' in current:
                no2_value = current['nitrogen_dioxide']
                no2_unit = current_units.get('nitrogen_dioxide', 'μg/m³')
                if no2_value is not None:
                    aqi_data['no2'] = f"{no2_value} {no2_unit}"
            # 臭氧 (O3)
            if 'ozone' in current:
                o3_value = current['ozone']
                o3_unit = current_units.get('ozone', 'μg/m³')
                if o3_value is not None:
                    aqi_data['o3'] = f"{o3_value} {o3_unit}"
            # PM10
            if 'pm10' in current:
                pm10_value = current['pm10']
                pm10_unit = current_units.get('pm10', 'μg/m³')
                if pm10_value is not None:
                    aqi_data['pm10'] = f"{pm10_value} {pm10_unit}"
            # PM2.5
            if 'pm2_5' in current:
                pm25_value = current['pm2_5']
                pm25_unit = current_units.get('pm2_5', 'μg/m³')
                if pm25_value is not None:
                    aqi_data['pm25'] = f"{pm25_value} {pm25_unit}"
            # 二氧化硫 (SO2)
            if 'sulphur_dioxide' in current:
                so2_value = current['sulphur_dioxide']
                so2_unit = current_units.get('sulphur_dioxide', 'μg/m³')
                if so2_value is not None:
                    aqi_data['so2'] = f"{so2_value} {so2_unit}"
        except Exception as e:
            logger.error(f"解析 Open-Meteo 空气质量数据失败: {e}")

        return aqi_data

    def fetch_forecast_data(self, location_key: str, api_key: str, forecast_type: str, days: int = 7) -> Dict[str, Any]:
        """获取预报数据(Open-Meteo)"""
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            lon, lat = location_key.split(',')
        except:
            raise ValueError(f'{self.api_name}: location_key 不为逗号分隔的经纬度模式')

        try:
            from network_thread import proxies
            # Open-Meteo的预报数据已经在主API中包含了
            url = self.base_url.format(lon=lon, lat=lat)
            headers = {
                'User-Agent': f"ClassWidgets/{config_center.read_conf('Version', 'version')} (contact: IsHPDuwu@outlook.com)"
            }
            response = requests.get(url, proxies=proxies, timeout=10, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f'{self.api_name} 获取预报数据失败: {e}')
            raise

    def parse_forecast_data(self, raw_data: Dict[str, Any], forecast_type: str) -> List[Dict[str, Any]]:
        """解析预报数据(Open-Meteo)"""
        try:
            if forecast_type == 'hourly':
                return self._parse_hourly_forecast(raw_data)
            elif forecast_type == 'daily':
                return self._parse_daily_forecast(raw_data)
            else:
                logger.error(f'不支持的预报类型: {forecast_type}')
                return []
        except Exception as e:
            logger.error(f'解析 Open-Meteo {forecast_type} 预报数据失败: {e}')
            return []

    def _parse_hourly_forecast(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析逐小时预报数据(Open-Meteo)"""
        try:
            hourly = data.get('hourly', {})
            if not hourly:
                return []

            times = hourly.get('time', [])
            temperatures = hourly.get('temperature_2m', [])
            weather_codes = hourly.get('weather_code', [])
            apparent_temps = hourly.get('apparent_temperature', [])
            humidity = hourly.get('relative_humidity_2m', [])
            wind_speeds = hourly.get('wind_speed_10m', [])
            wind_directions = hourly.get('wind_direction_10m', [])
            pressures = hourly.get('surface_pressure', [])
            visibility = hourly.get('visibility', [])

            hourly_units = data.get('hourly_units', {})

            forecast_list = []
            for i in range(min(len(times), 24)):  # 限制为24小时
                hour_data = {
                    'time': times[i] if i < len(times) else None,
                    'temperature': f"{temperatures[i]}{hourly_units.get('temperature_2m', '°C')}" if i < len(temperatures) and temperatures[i] is not None else None,
                    'weather_code': str(weather_codes[i]) if i < len(weather_codes) and weather_codes[i] is not None else None,
                    'apparent_temperature': f"{apparent_temps[i]}{hourly_units.get('apparent_temperature', '°C')}" if i < len(apparent_temps) and apparent_temps[i] is not None else None,
                    'humidity': f"{humidity[i]}%" if i < len(humidity) and humidity[i] is not None else None,
                    'wind_speed': f"{wind_speeds[i]} {hourly_units.get('wind_speed_10m', 'km/h')}" if i < len(wind_speeds) and wind_speeds[i] is not None else None,
                    'wind_direction': f"{wind_directions[i]}°" if i < len(wind_directions) and wind_directions[i] is not None else None,
                    'pressure': f"{pressures[i]} {hourly_units.get('surface_pressure', 'hPa')}" if i < len(pressures) and pressures[i] is not None else None,
                    'visibility': f"{visibility[i]/1000:.1f} km" if i < len(visibility) and visibility[i] is not None else None,
                    'precipitation': "0.0"  # Open-Meteo在基础API中不直接提供降水量
                }
                forecast_list.append(hour_data)
            # logger.info(f'Open-Meteo成功解析 {len(forecast_list)} 小时预报数据')
            return forecast_list
        except Exception as e:
            logger.error(f'解析 Open-Meteo 逐小时预报失败: {e}')
            return []

    def _parse_daily_forecast(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析每日预报数据(Open-Meteo)"""
        try:
            daily = data.get('daily', {})
            if not daily:
                return []

            times = daily.get('time', [])
            temp_max = daily.get('temperature_2m_max', [])
            temp_min = daily.get('temperature_2m_min', [])
            weather_codes = daily.get('weather_code', [])
            daily_units = data.get('daily_units', {})
            forecast_list = []
            for i in range(min(len(times), 7)):  # 限制为7天
                day_data = {
                    'date': times[i] if i < len(times) else None,
                    'temp_max': f"{temp_max[i]}{daily_units.get('temperature_2m_max', '°C')}" if i < len(temp_max) and temp_max[i] is not None else None,
                    'temp_min': f"{temp_min[i]}{daily_units.get('temperature_2m_min', '°C')}" if i < len(temp_min) and temp_min[i] is not None else None,
                    'weather_code': str(weather_codes[i]) if i < len(weather_codes) and weather_codes[i] is not None else None,
                }
                forecast_list.append(day_data)
            # logger.info(f'Open-Meteo成功解析 {len(forecast_list)} 天预报数据')
            return forecast_list
        except Exception as e:
            logger.error(f'解析 Open-Meteo 每日预报失败: {e}')
            return []


class WeatherDatabase:
    """天气数据库管理类"""

    def __init__(self, weather_manager: WeatherManager):
        self.weather_manager = weather_manager
        self._update_db_path()

    def _update_db_path(self) -> str:
        """更新数据库路径"""
        current_api = self.weather_manager.get_current_api()
        api_params = self.weather_manager.api_config.get('weather_api_parameters', {})
        db_name = api_params.get(current_api, {}).get('database', 'xiaomi_weather.db')
        self.db_path = os.path.join(base_directory, 'config', 'data', db_name)
        return self.db_path

    def search_city_by_name(self, search_term: str) -> List[str]:
        """根据城市名称搜索城市"""
        self._update_db_path()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM citys WHERE name LIKE ?', ('%' + search_term + '%',))
            cities_results = cursor.fetchall()
            conn.close()

            return [city[2] for city in cities_results]
        except Exception as e:
            logger.error(f'搜索城市失败: {e}')
            return []

    def search_code_by_name(self, city_name: str, district_name: str = '') -> str:
        """根据城市名称获取城市代码"""
        normalized_city, normalized_district = self._normalize_city_params(city_name, district_name)
        if not normalized_city:
            return '101010100'

        self._update_db_path()
        try:
            return self._search_city_in_database(normalized_city, normalized_district)
        except Exception as e:
            logger.error(f'搜索城市代码失败: {e}')
            return '101010100'

    def _normalize_city_params(self, city_name: str, district_name: str = '') -> Tuple[str, str]:
        """标准化参数"""
        if isinstance(city_name, (tuple, list)):
            city_name = str(city_name[0]) if city_name else ''
        if isinstance(district_name, (tuple, list)):
            district_name = str(district_name[0]) if district_name else ''
        if not city_name:
            return '', ''
        clean_city = city_name.replace('市', '')
        clean_district = district_name.replace('区', '') if district_name else ''

        return clean_city, clean_district

    def _search_city_in_database(self, clean_city: str, clean_district: str) -> str:
        """在数据库中搜索城市"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 先精确匹配
            exact_result = self._try_exact_match(cursor, clean_city, clean_district)
            if exact_result:
                return exact_result
            # 再模糊匹配
            fuzzy_result = self._try_fuzzy_match(cursor, clean_city)
            if fuzzy_result:
                return fuzzy_result
            logger.warning(f'未找到城市: {clean_city}, 使用默认城市代码')
            return '101010100'
        finally:
            conn.close()

    def _try_exact_match(self, cursor, clean_city: str, clean_district: str) -> Optional[str]:
        """尝试精确匹配"""
        search_name = f"{clean_city}.{clean_district}" if clean_district else clean_city
        cursor.execute('SELECT * FROM citys WHERE name = ?', (search_name,))
        exact_results = cursor.fetchall()

        if exact_results:
            logger.debug(f'找到城市: {exact_results[0][2]}, 代码: {exact_results[0][3]}')
            return str(exact_results[0][3])
        return None

    def _try_fuzzy_match(self, cursor, clean_city: str) -> Optional[str]:
        """尝试模糊匹配"""
        cursor.execute('SELECT * FROM citys WHERE name LIKE ?', ('%' + clean_city + '%',))
        fuzzy_results = cursor.fetchall()

        if fuzzy_results:
            logger.debug(f'模糊找到城市: {fuzzy_results[0][2]}, 代码: {fuzzy_results[0][3]}')
            return str(fuzzy_results[0][3])
        return None

    def search_city_by_code(self, city_code: str) -> str:
        if len(city_code.split(',')) != 1:
            return 'coordinates'
        """根据城市代码获取城市名称"""
        self._update_db_path()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM citys WHERE city_num LIKE ?', ('%' + city_code + '%',))
            cities_results = cursor.fetchall()
            conn.close()

            if cities_results:
                return cities_results[0][2]
            return '北京'  # 默认城市

        except Exception as e:
            logger.error(f'根据代码搜索城市失败: {e}')
            return '北京'


class WeatherDataProcessor:
    """统一天气数据处理"""

    def __init__(self, weather_manager: WeatherManager):
        self.weather_manager = weather_manager
        self._status_cache = {}

    def clear_cache(self):
        """清理所有缓存"""
        self._status_cache.clear()

    def clear_api_cache(self, api_name: str):
        """清理指定api的缓存"""
        if api_name in self._status_cache:
            del self._status_cache[api_name]

    def _convert_temperature_unit(self, temp_str: str) -> str:
        """根据配置转换温度单位"""
        if not temp_str:
            return temp_str
        try:
            target_unit = config_center.read_conf('Weather', 'temperature_unit', 'celsius')
            match = re.match(r'([+-]?\d+(?:\.\d+)?)\s*([°℃℉CF]?)', temp_str.strip())
            if not match:
                return temp_str
            temp_value = float(match.group(1))
            current_unit = match.group(2).lower() if match.group(2) else ''
            is_celsius = current_unit in ['', '℃', '°c', 'c'] or '℃' in temp_str
            is_fahrenheit = current_unit in ['℉', '°f', 'f'] or '℉' in temp_str
            if not is_celsius and not is_fahrenheit:
                is_celsius = True
            if target_unit == 'fahrenheit':
                if is_celsius:
                    # 摄氏度->华氏度: F = C * 9/5 + 32
                    converted_temp = temp_value * 9/5 + 32
                    return f"{converted_temp:.1f}℉"
                else:
                    return f"{temp_value:.1f}℉"
            else:  # celsius
                if is_fahrenheit:
                    # 华氏度->摄氏度: C = (F - 32) * 5/9
                    converted_temp = (temp_value - 32) * 5/9
                    return f"{converted_temp:.1f}℃"
                else:
                    return f"{temp_value:.1f}℃"
        except Exception as e:
            logger.error(f"温度单位转换失败: {e}")
            return temp_str

    def _load_weather_status(self, api_name: Optional[str] = None) -> Dict[str, Any]:
        """加载天气状态配置"""
        if not api_name:
            api_name = self.weather_manager.get_current_api()
        if api_name in self._status_cache:
            return self._status_cache[api_name]

        try:
            with open(os.path.join(base_directory, 'config', 'data', f'{api_name}_status.json'), 'r', encoding='utf-8') as f:
                status_data = json.load(f)
                self._status_cache[api_name] = status_data
                return status_data
        except Exception as e:
            logger.error(f'加载天气状态配置失败: {e}')
            return {'weatherinfo': []}

    def get_weather_by_code(self, code: str, api_name: Optional[str] = None) -> str:
        """根据天气代码获取天气描述"""
        weather_status = self._load_weather_status(api_name)
        for weather in weather_status.get('weatherinfo', []):
            if str(weather.get('code')) == str(code):
                # logger.debug(f'天气代码 {code} 对应的天气描述为: {weather.get("wea", "未知")}')
                return weather.get('wea', '未知')
        return '未知'

    def get_weather_icon_by_code(self, code: str, api_name: Optional[str] = None) -> str:
        """根据天气代码获取图标路径"""
        weather_status = self._load_weather_status(api_name)
        weather_code = self._find_weather_code(weather_status, code, api_name)

        if not weather_code:
            return self._get_default_weather_icon()

        return self._build_weather_icon_path(weather_code)

    def _find_weather_code(self, weather_status: Dict[str, Any], code: str, api_name: Optional[str]) -> Optional[str]:
        """查找代码"""
        if code is None or str(code).strip() == '' or str(code) == 'None':
            logger.error(f'天气代码为空或无效({api_name}): {code}')
            return None

        if not weather_status or 'weatherinfo' not in weather_status:
            logger.error(f'天气状态数据无效({api_name}): {weather_status}')
            return None

        for weather in weather_status.get('weatherinfo', []):
            weather_code = weather.get('code')
            if weather_code is not None and str(weather_code) == str(code):
                original_code = weather.get('original_code')
                if original_code is not None:
                    return str(original_code)
                else:
                    return str(weather.get('code'))

        logger.error(f'未找到天气代码({api_name}) {code}')
        return None

    def _get_default_weather_icon(self) -> str:
        """获取默认图标"""
        return os.path.join(base_directory, 'img', 'weather', '99.svg')

    def _build_weather_icon_path(self, weather_code: str) -> str:
        """构建图标路径"""
        if self._is_night_weather_type(weather_code) and self._is_night_time():
            return os.path.join(base_directory, 'img', 'weather', f'{weather_code}d.svg')

        icon_path = os.path.join(base_directory, 'img', 'weather', f'{weather_code}.svg')
        if not os.path.exists(icon_path):
            logger.warning(f'天气图标文件不存在: {icon_path}')
            return self._get_default_weather_icon()

        return icon_path

    def _is_night_weather_type(self, weather_code: str) -> bool:
        """夜间天气类型判断"""
        return weather_code in ('0', '1', '3', '13')  # 晴、多云、阵雨、阵雪

    def _is_night_time(self) -> bool:
        """夜间时间判断"""
        current_time = datetime.datetime.now()
        return current_time.hour < 6 or current_time.hour >= 18

    def get_weather_stylesheet(self, code: str, api_name: Optional[str] = None) -> str:
        """获取天气背景样式"""
        current_time = datetime.datetime.now()
        weather_status = self._load_weather_status(api_name)
        weather_code = '99'

        for weather in weather_status.get('weatherinfo', []):
            if str(weather.get('code')) == str(code):
                original_code = weather.get('original_code')
                weather_code = str(original_code) if original_code is not None else str(weather.get('code'))
                break

        if weather_code in ('0', '1', '3', '99', '900'):  # 晴、多云、阵雨、未知
            if 6 <= current_time.hour < 18:  # 日间
                return os.path.join('img', 'weather', 'bkg', 'day.png')
            else:  # 夜间
                return os.path.join('img', 'weather', 'bkg', 'night.png')

        return os.path.join('img', 'weather', 'bkg', 'rain.png')

    def get_weather_code_by_description(self, description: str, api_name: Optional[str] = None) -> str:
        """根据天气描述获取天气代码"""
        weather_status = self._load_weather_status(api_name)
        for weather in weather_status.get('weatherinfo', []):
            if str(weather.get('wea')) == description:
                return str(weather.get('code'))
        return '99'

    def get_alert_image_path(self, alert_type: str) -> str:
        """获取天气预警图标路径"""
        provider = self.weather_manager.get_current_provider()
        if not provider or not provider.supports_alerts():
            return os.path.join(base_directory, 'img', 'weather', 'alerts', 'blue.png')

        alerts_config = provider.config.get('alerts', {})
        alerts_types = alerts_config.get('types', {})

        color_mapping = {
            'blue': '蓝色',
            'yellow': '黄色',
            'orange': '橙色',
            'red': '红色'
        }
        icon_name = alerts_types.get(alert_type)
        if not icon_name and alert_type in color_mapping:
            icon_name = alerts_types.get(color_mapping[alert_type])
        if not icon_name:
            icon_name = 'blue.png'
        return os.path.join(base_directory, 'img', 'weather', 'alerts', icon_name)

    def is_alert_supported(self) -> bool:
        """检查当前api是否支持天气预警"""
        provider = self.weather_manager.get_current_provider()
        return provider.supports_alerts() if provider else False

    def extract_weather_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """从天气数据中提取指定字段的值(兼容旧接口)"""
        if not weather_data:
            logger.error('weather_data is None!')
            return None

        provider = self.weather_manager.get_current_provider()
        if not provider:
            return self._legacy_extract_weather_data(key, weather_data)

        try:
            if key == 'temp':
                temp_result = provider.parse_temperature(weather_data)
                # 应用温度单位转换
                if temp_result:
                    return self._convert_temperature_unit(temp_result)
                return temp_result
            elif key == 'icon':
                icon_code = provider.parse_weather_icon(weather_data)
                if provider.config.get('return_desc', False) and icon_code:
                    return self.get_weather_code_by_description(icon_code, self.weather_manager.get_current_api())
                return icon_code
            elif key in ('alert', 'alert_title', 'alert_desc'):
                return self._extract_alert_data(key, weather_data)
            elif key == 'wind_speed':
                if hasattr(provider, 'parse_wind_speed'):
                    return provider.parse_wind_speed(weather_data)
                return self._legacy_extract_weather_data(key, weather_data)
            elif key == 'humidity':
                if hasattr(provider, 'parse_humidity'):
                    return provider.parse_humidity(weather_data)
                return self._legacy_extract_weather_data(key, weather_data)
            elif key == 'visibility':
                if hasattr(provider, 'parse_visibility'):
                    return provider.parse_visibility(weather_data)
                return self._legacy_extract_weather_data(key, weather_data)
            elif key == 'pressure':
                if hasattr(provider, 'parse_pressure'):
                    return provider.parse_pressure(weather_data)
                return self._legacy_extract_weather_data(key, weather_data)
            elif key == 'feels_like':
                if hasattr(provider, 'parse_feels_like'):
                    feels_like_result = provider.parse_feels_like(weather_data)
                    # 应用温度单位转换
                    if feels_like_result:
                        return self._convert_temperature_unit(feels_like_result)
                    return feels_like_result
                return self._legacy_extract_weather_data(key, weather_data)
            elif key == 'wind_direction':
                if hasattr(provider, 'parse_wind_direction'):
                    return provider.parse_wind_direction(weather_data)
                return self._legacy_extract_weather_data(key, weather_data)
            elif key == 'aqi':
                if hasattr(provider, 'parse_aqi'):
                    return provider.parse_aqi(weather_data)
                return self._legacy_extract_weather_data(key, weather_data)
            elif key in ('co', 'no2', 'o3', 'pm10', 'pm25', 'so2'):
                if hasattr(provider, 'parse_aqi_data'):
                    aqi_data = provider.parse_aqi_data(weather_data)
                    return aqi_data.get(key)
                return self._legacy_extract_weather_data(key, weather_data)
            elif key == 'updateTime':
                # 提取天气数据的更新时间
                if hasattr(provider, 'parse_update_time'):
                    return provider.parse_update_time(weather_data)
                return self._legacy_extract_weather_data(key, weather_data)
            else:
                # 回退到旧方法
                return self._legacy_extract_weather_data(key, weather_data)
        except Exception as e:
            logger.error(f'提取天气数据失败 ({key}): {e}')
            return self._legacy_extract_weather_data(key, weather_data)

    def _extract_alert_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """提取预警数据"""
        provider = self.weather_manager.get_current_provider()
        if not provider or not provider.supports_alerts():
            return None

        if isinstance(provider, QWeatherProvider):
            return self._extract_qweather_alert_data(key, weather_data)
        elif isinstance(provider, XiaomiWeatherProvider):
            return self._extract_xiaomi_alert_data(key, weather_data)

        alerts_config = provider.config.get('alerts', {})
        if key == 'alert':
            path = alerts_config.get('type', '')
        elif key == 'alert_title':
            path = alerts_config.get('title', '')
        elif key == 'alert_desc':
            path = alerts_config.get('description', '')
        else:
            return None
        if not path:
            return None
        if hasattr(provider, '_extract_value_by_path'):
            return provider._extract_value_by_path(weather_data, path)

        return None

    def _extract_qweather_alert_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """提取和风天气预警数据"""
        try:
            alert_data = weather_data.get('alert', {})
            if not alert_data or alert_data.get('code') != '200':
                return None
            warning_list = alert_data.get('warning', [])
            if not warning_list:
                return None
            first_warning = warning_list[0]
            if key == 'alert':
                return first_warning.get('severityColor', '')
            elif key == 'alert_title':
                return first_warning.get('title', '')
            elif key == 'alert_desc':
                return first_warning.get('text', '')
            else:
                return None

        except Exception as e:
            logger.error(f"提取和风天气预警数据失败: {e}")
            return None

    def _extract_xiaomi_alert_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """提取小米天气预警数据"""
        try:
            # 预警数据alert.warning
            alert_data = weather_data.get('alert', {})
            if not alert_data or 'warning' not in alert_data:
                return None
            alerts_data = alert_data.get('warning', [])
            if not alerts_data or not isinstance(alerts_data, list):
                return None
            first_alert = alerts_data[0]
            if not isinstance(first_alert, dict):
                return None
            result = None
            if key == 'alert':
                result = first_alert.get('level', '')
            elif key == 'alert_title':
                result = first_alert.get('title', '')
            elif key == 'alert_desc':
                result = first_alert.get('detail', '')
            else:
                return None
            return result

        except Exception as e:
            return None

    def get_weather_alerts(self, weather_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取所有预警信息"""
        provider = self.weather_manager.get_current_provider()
        if not provider or not provider.supports_alerts():
            return []

        alert_data = weather_data.get('alert', {})
        if isinstance(provider, QWeatherProvider):
            return self._get_qweather_alerts(provider, alert_data)
        elif isinstance(provider, XiaomiWeatherProvider):
            return self._get_xiaomi_alerts(alert_data)
        else:
            return self._get_generic_alerts(alert_data)

    def _get_qweather_alerts(self, provider, alert_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取和风天气预警"""
        if hasattr(provider, 'parse_weather_alerts'):
            return provider.parse_weather_alerts(alert_data)
        return []

    def _get_xiaomi_alerts(self, alert_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取小米天气预警"""
        if alert_data and 'warning' in alert_data and isinstance(alert_data.get('warning'), list):
            return alert_data.get('warning', [])
        return []

    def _get_generic_alerts(self, alert_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取通用天气预警"""
        if not alert_data:
            return []

        if 'warning' in alert_data and isinstance(alert_data.get('warning'), list):
            warnings = alert_data.get('warning', [])
            return [warning for warning in warnings if isinstance(warning, dict)]

        if 'alerts' in alert_data:
            return alert_data.get('alerts', [])

        return []

    def get_unified_alert_data(self, weather_data: Dict[str, Any]) -> Dict[str, Any]:
        """获取统一格式的预警数据

        Args:
            weather_data (Dict[str, Any]): 原始天气数据

        Returns:
        {
            'has_alert': bool,  # 是否有预警
            'alert_count': int,  # 预警数量
            'primary_alert': {  # 主要预警(最高级别)
                'type': str,  # 预警类型(如'暴雨')
                'level': str,  # 预警级别(蓝/黄/橙/红)
                'color': str,  # 预警颜色代码
                'title': str,  # 预警标题
                'description': str,  # 预警描述
                'severity': int,  # 严重程度(1-4, 4最严重)
                'display_text': str  # 用于显示的简短文本
            },
            'all_alerts': List[Dict]  # 所有预警详情
        }
        """
        provider = self.weather_manager.get_current_provider()
        if not self._validate_alert_support(provider):
            return self._create_empty_alert_data()
        all_alerts = self.get_weather_alerts(weather_data)
        if not all_alerts:
            return self._create_empty_alert_data()
        unified_alerts = self._process_all_alerts(all_alerts, provider)
        if not unified_alerts:
            return self._create_empty_alert_data()
        return self._build_unified_alert_result(unified_alerts)

    def _validate_alert_support(self, provider) -> bool:
        """预警支持验证"""
        return provider and provider.supports_alerts()

    def _create_empty_alert_data(self) -> Dict[str, Any]:
        """创建空模板"""
        return {
            'has_alert': False,
            'alert_count': 0,
            'primary_alert': None,
            'all_alerts': []
        }

    def _process_all_alerts(self, all_alerts: List[Dict[str, Any]], provider) -> List[Dict[str, Any]]:
        """处理预警数据"""
        unified_alerts = []
        exclude_keywords = self._get_alert_exclude_keywords()

        for alert in all_alerts:
            unified_alert = self._normalize_alert_data(alert, provider)
            if unified_alert and not self._should_exclude_alert(unified_alert, exclude_keywords):
                unified_alerts.append(unified_alert)
        return unified_alerts

    def _get_alert_exclude_keywords(self) -> List[str]:
        try:
            exclude_str = config_center.read_conf('Weather', 'alert_exclude', '')
            if not exclude_str or not exclude_str.strip():
                return []
            keywords = [keyword.strip() for keyword in re.split(r'\s+', exclude_str.strip()) if keyword.strip()]
            unique_keywords = []
            seen = set()
            for keyword in keywords:
                if keyword not in seen:
                    unique_keywords.append(keyword)
                    seen.add(keyword)
            return unique_keywords
        except Exception as e:
            logger.error(f"获得排除关键词失败: {e}")
            return []

    def _should_exclude_alert(self, alert: Dict[str, Any], exclude_keywords: List[str]) -> bool:
        if not exclude_keywords:
            return False
        title = alert.get('title', '').lower()
        for keyword in exclude_keywords:
            if keyword.lower() in title:
                logger.debug(f"预警被排除:'{keyword}' 标题: '{alert.get('title', '未知预警')}'")
                return True

        return False

    def _build_unified_alert_result(self, unified_alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建预警模板"""
        unified_alerts.sort(key=lambda x: x.get('severity', 0), reverse=True)
        primary_alert = unified_alerts[0]
        return {
            'has_alert': True,
            'alert_count': len(unified_alerts),
            'primary_alert': primary_alert,
            'all_alerts': unified_alerts
        }

    def _normalize_alert_data(self, alert: Dict[str, Any], provider) -> Optional[Dict[str, Any]]:
        """预警数据标准化"""
        try:
            if 'severityColor' in alert or 'startTime' in alert:
                return self._normalize_qweather_alert(alert)
            elif isinstance(provider, QWeatherProvider):
                return self._normalize_qweather_alert(alert)
            elif isinstance(provider, XiaomiWeatherProvider):
                return self._normalize_xiaomi_alert(alert)
            else:
                return self._normalize_generic_alert(alert)
        except Exception as e:
            logger.error(f"标准化预警数据失败: {e}")
            return None

    def _normalize_qweather_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """标准化和风天气预警"""
        title = alert.get('title', '')
        severity_text = alert.get('severity', '')  # API返回的严重等级文本
        severity_color = alert.get('severityColor', '')  # API返回的严重等级颜色
        alert_type, alert_level = self._extract_alert_info_from_title(title)
        # 严重等级：Cancel, None, Unknown, Standard, Minor, Moderate, Major, Severe, Extreme
        severity_text_map = {
            'Cancel': 0, 'None': 0, 'Unknown': 1, 'Standard': 1,
            'Minor': 1, 'Moderate': 2, 'Major': 3, 'Severe': 3, 'Extreme': 4
        }
        severity_color_map = {
            'White': 0, 'Blue': 1, 'Green': 1, 'Yellow': 2,
            'Orange': 3, 'Red': 4, 'Black': 4,
            'white': 0, 'blue': 1, 'green': 1, 'yellow': 2,
            'orange': 3, 'red': 4, 'black': 4
        }
        if severity_text and severity_text in severity_text_map:
            severity = severity_text_map[severity_text]
        elif severity_color and severity_color in severity_color_map:
            severity = severity_color_map[severity_color]
        else:
            severity = 1  # 默认为Minor
        if alert_type and alert_level:
            display_text = f"{alert_type}{alert_level}色预警"
        elif alert_type:
            display_text = f"{alert_type}预警"
        else:
            display_text = "天气预警"
        return {
            'type': alert_type or '未知',
            'level': alert_level or severity_color,
            'color': severity_color,
            'title': title,
            'description': alert.get('text', ''),
            'severity': severity,
            'display_text': display_text,
            'start_time': alert.get('startTime', ''),
            'end_time': alert.get('endTime', ''),
            'source': 'qweather'
        }

    def _normalize_xiaomi_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """标准化小米天气预警"""
        title = alert.get('title', '')
        alert_type, alert_level = self._extract_xiaomi_alert_info(alert, title)
        severity = self._calculate_xiaomi_severity(alert_level)
        display_text = self._build_xiaomi_display_text(alert_type, alert_level)

        return {
            'type': alert_type,
            'level': alert_level,
            'color': alert_level,  # 小米天气用level作为颜色
            'title': title,
            'description': alert.get('detail', ''),
            'severity': severity,
            'display_text': display_text,
            'start_time': alert.get('start_time', ''),
            'end_time': alert.get('end_time', ''),
            'source': 'xiaomi'
        }

    def _extract_xiaomi_alert_info(self, alert: Dict[str, Any], title: str) -> Tuple[str, str]:
        """提取小米天气预警类型,级别"""
        alert_type = alert.get('type', '')
        alert_level = alert.get('level', '')

        if not alert_type or not alert_level:
            extracted_type, extracted_level = self._extract_alert_info_from_title(title)
            alert_type = alert_type or extracted_type or '未知'
            alert_level = alert_level or extracted_level or '未知'

        return alert_type, alert_level

    def _calculate_xiaomi_severity(self, alert_level: str) -> int:
        """映射严重度"""
        level_map = {
            '蓝色': 1, '黄色': 2, '橙色': 3, '红色': 4,
            '蓝': 1, '黄': 2, '橙': 3, '红': 4
        }
        return level_map.get(alert_level, 1)

    def _build_xiaomi_display_text(self, alert_type: str, alert_level: str) -> str:
        """构建小米天气预警文本"""
        if alert_type and alert_level:
            return f"{alert_type}{alert_level}预警"
        elif alert_type:
            return f"{alert_type}预警"
        else:
            return "天气预警"

    def _normalize_generic_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """标准化通用预警数据(其他天气API)"""
        title = alert.get('title', alert.get('name', ''))
        alert_type, alert_level = self._extract_alert_info_from_title(title)
        severity = 1
        if 'level' in alert:
            level_map = {'1': 1, '2': 2, '3': 3, '4': 4}
            severity = level_map.get(str(alert['level']), 1)
        elif alert_level:
            level_map = {'蓝': 1, '黄': 2, '橙': 3, '红': 4}
            severity = level_map.get(alert_level, 1)
        display_text = f"{alert_type}预警" if alert_type else "天气预警"
        return {
            'type': alert_type or '未知',
            'level': alert_level or '未知',
            'color': alert.get('color', ''),
            'title': title,
            'description': alert.get('description', alert.get('desc', '')),
            'severity': severity,
            'display_text': display_text,
            'start_time': alert.get('start_time', ''),
            'end_time': alert.get('end_time', ''),
            'source': 'generic'
        }

    def _extract_alert_info_from_title(self, title: str) -> Tuple[Optional[str], Optional[str]]:
        """从预警标题中提取预警类型和级别"""
        pattern = r'发布(\w+)(蓝|黄|橙|红)色预警'
        match = re.search(pattern, title)

        if match:
            alert_type = match.group(1)  # 预警类型
            alert_level = match.group(2)  # 预警级别
            return alert_type, alert_level
        # fallback
        type_patterns = [
            r'(暴雨|大雨|雷电|大风|高温|寒潮|冰雹|雾|霾|道路结冰|森林火险|干旱|台风|龙卷风)预警',
            r'(\w+)(蓝|黄|橙|红)色预警',
            r'(\w+)预警'
        ]

        for pattern in type_patterns:
            match = re.search(pattern, title)
            if match:
                if len(match.groups()) >= 2:
                    return match.group(1), match.group(2)
                else:
                    return match.group(1), None

        return None, None

    def _legacy_extract_weather_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """数据提取(向后兼容)"""
        current_api = self.weather_manager.get_current_api()
        api_params = self.weather_manager.api_config.get('weather_api_parameters', {})
        current_params = api_params.get(current_api, {})

        parameter_path = self._get_parameter_path(key, current_params)
        if not parameter_path:
            logger.error(f'未找到参数路径: {key}')
            return None

        value = self._extract_value_by_api(current_api, current_params, key, parameter_path, weather_data)
        return self._format_extracted_value(key, value, current_params)

    def _get_parameter_path(self, key: str, current_params: Dict[str, Any]) -> str:
        """获取参数路径"""
        if key == 'alert':
            alerts_config = current_params.get('alerts', {})
            return alerts_config.get('type', '')
        elif key == 'alert_title':
            alerts_config = current_params.get('alerts', {})
            return alerts_config.get('title', '')
        else:
            return current_params.get(key, '')

    def _extract_value_by_api(self, current_api: str, current_params: Dict[str, Any],
                             key: str, parameter_path: str, weather_data: Dict[str, Any]) -> Any:
        """根据API类型提取值"""
        context = WeatherExtractionContext(
            current_params=current_params,
            key=key,
            weather_data=weather_data,
            current_api=current_api,
            parameter_path=parameter_path
        )

        if current_api == 'amap_weather':
            return self._extract_amap_value(context)
        elif current_api == 'qq_weather':
            return self._extract_qq_value(context)
        else:
            return self._extract_generic_value(context)

    def _extract_amap_value(self, context: WeatherExtractionContext) -> str:
        """提取高德天气值"""
        return context.weather_data.get('lives', [{}])[0].get(
            context.current_params.get(context.key, ''), ''
        )

    def _extract_qq_value(self, context: WeatherExtractionContext) -> str:
        """提取QQ天气值"""
        realtime_data = context.weather_data.get('result', {}).get('realtime', [{}])
        if realtime_data:
            return str(realtime_data[0].get('infos', {}).get(
                context.current_params.get(context.key, ''), ''
            ))
        return ''

    def _extract_generic_value(self, context: WeatherExtractionContext) -> Any:
        """提取通用天气值"""
        value = context.weather_data
        parameters = context.parameter_path.split('.')

        for param in parameters:
            value = self._process_single_parameter(value, param, context.current_api, context.key)
            if value is None or value == '错误':
                return value
        return value

    def _process_single_parameter(self, value: Any, param: str, current_api: str, key: str) -> Any:
        """处理单个参数"""
        if not value:
            logger.warning(f'天气信息值{key}为空')
            return None

        if param == '0':
            if isinstance(value, list) and len(value) > 0:
                return value[0]
            else:
                logger.error(f'无法获取数组第一个元素: {param}')
                return None
        elif isinstance(value, dict) and param in value:
            return value[param]
        else:
            logger.error(f'获取天气参数失败, {param}不存在于{current_api}中')
            return '错误'

    def _format_extracted_value(self, key: str, value: Any, current_params: Dict[str, Any]) -> Optional[str]:
        """格式化提取值"""
        if value is None:
            return None

        if key == 'temp' and value:
            return str(value) + '°'
        elif key == 'icon' and current_params.get('return_desc', False):
            return self.get_weather_code_by_description(str(value))

        return str(value)


class WeatherReportThread(QThread):
    """天气数据获取"""
    weather_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.weather_manager = WeatherManager()
        self._is_running = False

    def run(self):
        """线程运行方法"""
        try:
            self._is_running = True
            weather_data = self.weather_manager.fetch_weather_data()
            if self._is_running:
                if weather_data:
                    self.weather_signal.emit(weather_data)
                else:
                    logger.error('获取天气数据返回None')
                    self.weather_signal.emit({'error': {'info': {'value': '错误', 'unit': ''}}})
        except Exception as e:
            if self._is_running:
                logger.error(f'触发天气信息失败: {e}')
                self.weather_signal.emit({'error': {'info': {'value': '错误', 'unit': ''}}})
        finally:
            self._is_running = False

    def stop(self):
        """停止线程"""
        self._is_running = False
        if self.isRunning():
            self.quit()
            self.wait(3000)


weather_manager = WeatherManager()
weather_database = WeatherDatabase(weather_manager)
weather_processor = WeatherDataProcessor(weather_manager)


def on_weather_api_changed(new_api: str):
    global weather_manager, weather_processor
    weather_manager.on_api_changed(new_api)
    weather_processor.clear_cache()

# 兼容性用
def search_by_name(search_term: str) -> List[str]:
    """根据名称搜索城市"""
    return weather_database.search_city_by_name(search_term)


def search_code_by_name(city_name: str, district_name: str = '') -> str:
    """根据名称搜索城市代码"""
    return weather_database.search_code_by_name(city_name, district_name)


def search_by_num(city_code: str) -> str:
    """根据代码搜索城市"""
    return weather_database.search_city_by_code(city_code)


def get_weather_by_code(code: str) -> str:
    """根据代码获取天气描述"""
    return weather_processor.get_weather_by_code(code)


def get_weather_icon_by_code(code: str) -> str:
    """根据代码获取天气图标"""
    return weather_processor.get_weather_icon_by_code(code)

def get_weather_stylesheet(code: str) -> str:
    """获取天气样式表"""
    return weather_processor.get_weather_stylesheet(code)


def get_weather_data(key: str = 'temp', weather_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """获取天气数据"""
    return weather_processor.extract_weather_data(key, weather_data)


def get_unified_weather_alerts(weather_data: Dict[str, Any]) -> Dict[str, Any]:
    """获取统一格式的天气预警数据

    Args:
        weather_data: 天气数据字典

    Returns:
        统一格式的预警数据字典, 包含:
        - has_alert: 是否有预警
        - alert_count: 预警数量
        - primary_alert: 主要预警信息
        - all_alerts: 所有预警列表
    """
    return weather_processor.get_unified_alert_data(weather_data)


def get_alert_image(alert_type: str) -> str:
    """获取预警图标"""
    return weather_processor.get_alert_image_path(alert_type)


def get_alert_icon_by_severity(severity: Union[str, int]) -> str:
    """根据预警等级获取对应图标路径"""
    try:
        severity_color_map = {
            '1': 'blue',
            '2': 'yellow',
            '3': 'orange',
            '4': 'red',
            'minor': 'blue',
            'moderate': 'yellow',
            'severe': 'orange',
            'extreme': 'red'
        }
        severity_str = str(severity).lower() if severity else '2'
        color = severity_color_map.get(severity_str, 'yellow')
        icon_path = os.path.join(base_directory, 'img', 'weather', 'alerts', f'{color}.png')
        return icon_path if os.path.exists(icon_path) else os.path.join(base_directory, 'img', 'weather', 'alerts', 'blue.png')
    except Exception as e:
        logger.error(f"获取预警图标失败: {e}")
        return os.path.join(base_directory, 'img', 'weather', 'alerts', 'blue.png')


def simplify_alert_text(text: str) -> str:
    """简化预警文本"""
    if not text:
        return '预警'
    try:
        match = re.search(r'(发布|升级为)(\w+)(蓝色|黄色|橙色|红色)预警', text)
        if match:
            return match.group(2)  # 简化至仅剩预警类别, 如"暴雨" "雷暴大风"
        return text.replace('预警', '').strip() or '未知预警'
    except Exception as e:
        logger.error(f"简化预警文本失败: {e}")
        return '未知预警'


def get_severity_text(severity: Union[str, int]) -> str:
    """根据预警等级获取对应的文本描述"""
    try:
        severity_text_map = {
            '1': '蓝色',
            '2': '黄色',
            '3': '橙色',
            '4': '红色',
            'minor': '蓝色',
            'moderate': '黄色',
            'severe': '橙色',
            'extreme': '红色',
            'blue': '蓝色',
            'yellow': '黄色',
            'orange': '橙色',
            'red': '红色',
            '蓝': '蓝色',
            '黄': '黄色',
            '橙': '橙色',
            '红': '红色'
        }
        severity_str = str(severity).lower() if severity else '2'
        return severity_text_map.get(severity_str, '黄色')
    except Exception as e:
        logger.error(f"获取预警等级文本失败: {e}")
        return '黄色'


def is_supported_alert() -> bool:
    """检查是否支持预警"""
    return weather_processor.is_alert_supported()


def get_weather_url() -> str:
    """获取天气URL"""
    provider = weather_manager.get_current_provider()
    return provider.base_url if provider else ''


def get_weather_alert_url() -> Optional[str]:
    """获取天气预警URL"""
    provider = weather_manager.get_current_provider()
    if not provider or not provider.supports_alerts():
        return 'NotSupported'
    alerts_config = provider.config.get('alerts', {})
    return alerts_config.get('url')

def get_hourly_forecast() -> Dict[str, Any]:
    """获取逐小时天气预报

    Returns:
        Dict[str, Any]: 包含预报数据和状态信息的字典
            - success: bool, 是否成功获取数据
            - supported: bool, 当前提供者是否支持逐小时预报
            - data: List[Dict[str, Any]], 预报数据列表
            - error: str, 错误信息(如果有)
    """
    try:
        provider = weather_manager.get_current_provider()
        if not provider:
            return {
                'success': False,
                'supported': False,
                'data': [],
                'error': '未找到天气提供者'
            }
        forecast_config = provider.config.get('forecast', {})
        hourly_supported = forecast_config.get('hourly', False)
        if not hourly_supported:
            logger.warning(f'{provider.api_name} 不支持逐小时预报')
            return {
                'success': False,
                'supported': False,
                'data': [],
                'error': f'{provider.api_name} 不支持逐小时预报'
            }

        forecast_data = weather_manager.fetch_hourly_forecast()
        return {
            'success': True,
            'supported': True,
            'data': forecast_data if forecast_data else [],
            'error': None
        }

    except Exception as e:
        logger.error(f'获取逐小时预报失败: {e}')
        return {
            'success': False,
            'supported': False,
            'data': [],
            'error': str(e)
        }

def get_daily_forecast(days: int = 5) -> Dict[str, Any]:
    """获取多天天气预报

    Args:
        days: 预报天数, 默认5天

    Returns:
        Dict[str, Any]: 包含预报数据和状态信息的字典
            - success: bool, 是否成功获取数据
            - supported: bool, 当前提供者是否支持多天预报
            - data: List[Dict[str, Any]], 预报数据列表
            - days: int, 实际获取的天数
            - error: str, 错误信息(如果有)
    """
    try:
        provider = weather_manager.get_current_provider()
        if not provider:
            return {
                'success': False,
                'supported': False,
                'data': [],
                'days': 0,
                'error': '未找到天气提供者'
            }
        # 检查是否支持多天预报
        forecast_config = provider.config.get('forecast', {})
        daily_supported = forecast_config.get('daily', False)
        if not daily_supported:
            logger.warning(f'{provider.api_name} 不支持多天预报')
            return {
                'success': False,
                'supported': False,
                'data': [],
                'days': 0,
                'error': f'{provider.api_name} 不支持多天预报'
            }

        if days <= 0:
            days = 5
        elif days > 15:  # 限制最大天数
            days = 15
            logger.warning('预报天数超过限制, 已调整为15天')

        forecast_data = weather_manager.fetch_daily_forecast(days)
        return {
            'success': True,
            'supported': True,
            'data': forecast_data if forecast_data else [],
            'days': len(forecast_data) if forecast_data else 0,
            'error': None
        }

    except Exception as e:
        logger.error(f'获取多天预报失败: {e}')
        return {
            'success': False,
            'supported': False,
            'data': [],
            'days': 0,
            'error': str(e)
        }

def get_precipitation_info() -> Dict[str, Any]:
    """获取降水信息

    Returns:
        Dict[str, Any]: 包含降水信息和状态的字典
            - success: bool, 是否成功获取数据
            - supported: bool, 当前提供者是否支持降水分析
            - data: Dict[str, Any], 降水信息数据
            - error: str, 错误信息(如果有)
    """
    try:
        provider = weather_manager.get_current_provider()
        if not provider:
            return {
                'success': False,
                'supported': False,
                'data': {
                    'precipitation': False,
                    'precipitation_time': [],
                    'tomorrow_precipitation': False,
                    'precipitation_day': 0,
                    'first_hour_precip': False,
                    'same_precipitation': True,
                    'temp_change': 0
                },
                'error': '未找到天气提供者'
            }

        # 检查是否支持降水分析 (需要逐小时和多天预报)
        forecast_config = provider.config.get('forecast', {})
        hourly_supported = forecast_config.get('hourly', False)
        daily_supported = forecast_config.get('daily', False)
        if not (hourly_supported and daily_supported):
            logger.warning(f'{provider.api_name} 不完全支持降水分析 (需要逐小时和多天预报)')
            return {
                'success': False,
                'supported': False,
                'data': {
                    'precipitation': False,
                    'precipitation_time': [],
                    'tomorrow_precipitation': False,
                    'precipitation_day': 0,
                    'first_hour_precip': False,
                    'same_precipitation': True,
                    'temp_change': 0
                },
                'error': f'{provider.api_name} 不完全支持降水分析'
            }

        precipitation_data = weather_manager.get_precipitation_info()
        return {
            'success': True,
            'supported': True,
            'data': precipitation_data,
            'error': None
        }

    except Exception as e:
        logger.error(f'获取降水信息失败: {e}')
        return {
            'success': False,
            'supported': False,
            'data': {
                'precipitation': False,
                'precipitation_time': [],
                'tomorrow_precipitation': False,
                'precipitation_day': 0,
                'first_hour_precip': False,
                'same_precipitation': True,
                'temp_change': 0
            },
            'error': str(e)
        }


if __name__ == '__main__':
    try:
        print("=== 天气系统测试 ===")

        print("\n城市搜索")
        cities = search_by_name('北京')
        print(f"搜索'北京'的结果: {cities[:5]}")
        code = search_code_by_name('北京', '')
        print(f"北京的城市代码: {code}")
        city_name = search_by_num(code)
        print(f"代码{code}对应的城市: {city_name}")
        print("\n数据获取")
        current_api = weather_manager.get_current_api()
        print(f"当前使用的天气API: {current_api}")
        weather_data = weather_manager.fetch_weather_data()
        if weather_data:
            print(f"获取到的天气数据结构: {type(weather_data)}")
            print(f"天气数据顶级键: {list(weather_data.keys()) if isinstance(weather_data, dict) else 'Not a dict'}")
            if isinstance(weather_data, dict):
                for key, value in weather_data.items():
                    if isinstance(value, dict):
                        print(f"{key}: {type(value)} - 键: {list(value.keys())}")
                    else:
                        print(f"{key}: {type(value)} = {value}")
            print("\n数据解析")
            provider = weather_manager.get_current_provider()
            if provider:
                print(f"当前Provider: {type(provider).__name__}")
                test_data = weather_data
                if 'now' in weather_data:
                    test_data = weather_data['now']
                    print("使用'now'字段进行测试")
                elif 'current' in weather_data:
                    test_data = weather_data['current']
                    print("使用'current'字段进行测试")
                else:
                    print("使用完整数据进行测试")
                try:
                    temp = provider.parse_temperature(weather_data)
                    print(f"Provider解析的温度: {temp}")
                except Exception as e:
                    print(f"Provider温度解析失败: {e}")
                try:
                    icon = provider.parse_weather_icon(weather_data)
                    print(f"Provider解析的天气图标: {icon}")
                except Exception as e:
                    print(f"Provider图标解析失败: {e}")
                temp_processor = weather_processor.extract_weather_data('temp', weather_data)
                icon_processor = weather_processor.extract_weather_data('icon', weather_data)
                print(f"Processor解析的温度: {temp_processor}")
                print(f"Processor解析的天气图标: {icon_processor}")

        else:
            print("未获取到天气数据")

        print("\n天气描述")
        weather_desc = get_weather_by_code('0')
        print(f"天气代码0对应的描述: {weather_desc}")
        icon_path = get_weather_icon_by_code('0')
        print(f"天气代码0对应的图标: {icon_path}")
        # 测试逐小时预报
        hourly_result = get_hourly_forecast()
        print(f"逐小时预报支持状态: {hourly_result['supported']}, 成功: {hourly_result['success']}")
        if hourly_result['success'] and hourly_result['data']:
            print("逐小时天气预报 (近12小时):")
            precipitation_time = None

            for hour in hourly_result['data']:
                if "precipitation_time" in hour:
                    precipitation_time = hour["precipitation_time"]
                    continue

                weather_desc = get_weather_by_code(str(hour["weather_code"]))
                precip_status = "有降水" if hour["precipitation"] else "无降水"
                print(f"{hour['hour']}小时后: {hour['temperature']}°C, {weather_desc} ({precip_status})")

            if precipitation_time:
                print(f"降水时间分组: {precipitation_time}")
        else:
            print(f"无逐小时预报数据: {hourly_result.get('error', '未知错误')}")

        # 测试5天预报
        daily_result = get_daily_forecast(5)
        print(f"\n多天预报支持状态: {daily_result['supported']}, 成功: {daily_result['success']}, 实际天数: {daily_result['days']}")
        if daily_result['success'] and daily_result['data']:
            print("\n5 天天气预报:")
            tomorrow_precip = False
            precip_days = 0

            for day in daily_result['data']:
                if "tomorrow_precipitation" in day:
                    tomorrow_precip = day["tomorrow_precipitation"]
                    precip_days = day["precipitation_day"]
                    continue

                day_weather = get_weather_by_code(str(day["weather_day"]))
                night_weather = get_weather_by_code(str(day["weather_night"]))
                precip_status = "降水日" if day["precipitation_day"] else "非降水日"
                day_precip_status = "白天有降水" if day["day_precipitation"] else "白天无降水"

                print(f"第 {day['day']+1} 天: {day['temp_high']} - {day['temp_low']}°C")
                print(f"  白天: {day_weather}, 夜间: {night_weather}")
                print(f"  状态: {precip_status}, {day_precip_status}")

        else:
            print(f"无 5 天预报数据: {daily_result.get('error', '未知错误')}")

        precipitation_result = get_precipitation_info()
        print(f"\n降水分析支持状态: {precipitation_result['supported']}, 成功: {precipitation_result['success']}")
        if precipitation_result['success']:
            print("降水信息:")
            print(precipitation_result['data'])
        else:
            print(f"无法获取降水信息: {precipitation_result.get('error', '未知错误')}")

        current_api = weather_manager.get_current_api()
        current_location = weather_manager._get_location_key()
        print(weather_manager.get_weather_reminders(current_api, current_location))

    except Exception as e:
        print(f"测试出错: {e}")
        import traceback
        traceback.print_exc()
