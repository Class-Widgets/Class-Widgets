import json
import os
import shutil
import zipfile  # 解压插件zip
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from loguru import logger
from packaging.version import Version
from PyQt5.QtCore import QThread, pyqtSignal

import conf
import list_
import utils
from basic_dirs import CACHE_HOME, CW_HOME
from file import config_center
from i18n_manager import get_language_code

headers = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}  # 设置请求头
"""
proxies = {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}  # 加速访问
"""
proxies = {"http": None, "https": None}

MIRROR_PATH = CW_HOME / "data" / "mirror.json"
PLAZA_REPO_URL = "https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/"
PLAZA_REPO_DIR = "https://api.github.com/repos/Class-Widgets/plugin-plaza/contents/"
threads = []

# 读取镜像配置
mirror_list = []
try:
    with open(MIRROR_PATH, encoding='utf-8') as file:
        mirror_dict = json.load(file).get('gh_mirror')
except Exception as e:
    logger.error(f"读取镜像配置失败: {e}")

for name in mirror_dict:
    mirror_list.append(name)

if (
    config_center.read_conf('Plugin', 'mirror') not in mirror_list
):  # 如果当前配置不在镜像列表中，则设置为默认镜像
    logger.warning(f"当前配置不在镜像列表中，设置为默认镜像: {mirror_list[0]}")
    config_center.write_conf('Plugin', 'mirror', mirror_list[0])


class getRepoFileList(QThread):  # 获取仓库文件目录
    repo_signal = pyqtSignal(dict)

    def __init__(
        self,
        url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Banner/banner.json',
    ) -> None:
        super().__init__()
        self.download_url = url

    def run(self) -> None:
        try:
            plugin_info_data = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发banner信息失败: {e}")

    def get_plugin_info(self) -> Dict[str, Any]:
        try:
            mirror_url = mirror_dict[config_center.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)  # 禁用代理
            if response.status_code == 200:
                return response.json()
            logger.error(f"获取banner信息失败：{response.status_code}")
            return {"error": response.status_code}
        except Exception as e:
            logger.error(f"获取banner信息失败：{e}")
            return {"error": e}


class getPluginInfo(QThread):  # 获取插件信息(json)
    repo_signal = pyqtSignal(dict)

    def __init__(
        self,
        url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Plugins/plugin_list.json',
    ) -> None:
        super().__init__()
        self.download_url = url

    def run(self) -> None:
        try:
            plugin_info_data = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发插件信息失败: {e}")

    def get_plugin_info(self) -> Dict[str, Any]:
        try:
            mirror_url = mirror_dict[config_center.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)  # 禁用代理
            if response.status_code == 200:
                return response.json()
            logger.error(f"获取插件信息失败：{response.status_code}")
            return {}
        except Exception as e:
            logger.error(f"获取插件信息失败：{e}")
            return {}


class getTags(QThread):  # 获取插件标签(json)
    repo_signal = pyqtSignal(dict)

    def __init__(
        self,
        url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Plugins/plaza_detail.json',
    ) -> None:
        super().__init__()
        self.download_url = url

    def run(self) -> None:
        try:
            plugin_info_data = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发Tag信息失败: {e}")

    def get_plugin_info(self) -> Dict[str, Any]:
        try:
            mirror_url = mirror_dict[config_center.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)  # 禁用代理
            if response.status_code == 200:
                return response.json()
            logger.error(f"获取Tag信息失败：{response.status_code}")
            return {}
        except Exception as e:
            logger.error(f"获取Tag信息失败：{e}")
            return {}


class getImg(QThread):  # 获取图片
    repo_signal = pyqtSignal(bytes)

    def __init__(
        self,
        url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Banner/banner_1.png',
    ) -> None:
        super().__init__()
        self.download_url = url

    def run(self) -> None:
        try:
            banner_data = self.get_banner()
            if banner_data is not None:
                self.repo_signal.emit(banner_data)
            else:
                with open(
                    CW_HOME / "img" / "plaza" / "banner_pre.png", 'rb'
                ) as default_img:  # 读取默认图片
                    self.repo_signal.emit(default_img.read())
        except Exception as e:
            logger.error(f"触发图片失败: {e}")

    def get_banner(self) -> Optional[bytes]:
        try:
            mirror_url = mirror_dict[config_center.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)
            if response.status_code == 200:
                return response.content
            logger.error(f"获取图片失败：{response.status_code}")
            return None
        except Exception as e:
            logger.error(f"获取图片失败：{e}")
            return None


class getReadme(QThread):  # 获取README
    html_signal = pyqtSignal(str)

    def __init__(
        self,
        url: str = 'https://raw.githubusercontent.com/Class-Widgets/Class-Widgets/main/README.md',
    ) -> None:
        super().__init__()
        self.download_url = url

    def run(self) -> None:
        try:
            readme_data = self.get_readme()
            self.html_signal.emit(readme_data)
        except Exception as e:
            logger.error(f"触发README失败: {e}")

    def get_readme(self) -> str:
        try:
            mirror_url = mirror_dict[config_center.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            # print(url)
            response = requests.get(url, proxies=proxies)
            if response.status_code == 200:
                return response.text
            logger.error(f"获取README失败：{response.status_code}")
            return ''
        except Exception as e:
            logger.error(f"获取README失败：{e}")
            return ''


class getCity(QThread):
    coordinates_signal = pyqtSignal(float, float)  # 经纬度信号
    city_signal = pyqtSignal(str)  # 城市信息信号
    city_info_signal = pyqtSignal(str, str)  # 城市信息信号 (城市名, 城市key)
    error_signal = pyqtSignal(str)  # 错误信号
    finished_signal = pyqtSignal()  # 完成信号

    def __init__(
        self, mode: str = 'auto', write_config: bool = True, auto_type: str = 'coordinates'
    ) -> None:
        """
        城市获取线程

        Args:
            mode: 模式选择
                - 'auto': 自动获取城市信息(根据auto_type决定使用经纬度或cityid)
                - 'coordinates_only': 仅获取经纬度并发送信号
                - 'city_from_coordinates': 根据给定经纬度获取城市信息
            write_config: 是否将获取的信息写入配置
            auto_type: auto模式的类型
                - 'coordinates': 使用经纬度自动获取城市信息
                - 'cityid': 使用城市ID自动获取城市信息
        """
        super().__init__()
        self.mode = mode
        self.write_config = write_config
        self.auto_type = auto_type
        self.target_lat = None
        self.target_lon = None
        self.city_id = None
        self._load_api_config()

    def _load_api_config(self):
        """加载 API 配置"""
        try:
            config_path = Path(__file__).parent / 'data' / 'weather_api.json'
            with open(config_path, encoding='utf-8') as f:
                self.api_config = json.load(f)
        except Exception as e:
            logger.critical(f"加载 API 配置失败: {e}")

    def set_coordinates(self, latitude: float, longitude: float):
        """设置目标经纬度(city_from_coordinates)"""
        self.target_lat = latitude
        self.target_lon = longitude

    def set_city_id(self, city_id: str):
        """设置目标城市ID"""
        self.city_id = city_id

    def run(self) -> None:
        try:
            if self.mode == 'coordinates_only':
                coordinates = self.get_coordinates()
                if coordinates:
                    self.coordinates_signal.emit(coordinates[0], coordinates[1])

            elif self.mode == 'city_from_coordinates':
                if self.target_lat is not None and self.target_lon is not None:
                    city_data = self.get_city_by_coordinates(self.target_lat, self.target_lon)
                    if city_data:
                        city_key = city_data['key']
                        if city_data['key'].startswith('weathercn:'):
                            if config_center.read_conf('Weather', 'api') != 'xiaomi_weather':
                                city_key = city_data['key'].replace('weathercn:', '')
                        self.city_signal.emit(city_key)
                        self.city_info_signal.emit(city_data['name'], city_key)
                else:
                    raise ValueError("未设置目标经纬度")
            elif self.mode == 'auto':
                if self.auto_type == 'coordinates':
                    coordinates = self.get_coordinates()
                    if coordinates:
                        city_data = self.get_city_by_coordinates(coordinates[0], coordinates[1])
                        if city_data:
                            city_key = city_data['locationKey']  # 初始化 city_key
                            if city_data['locationKey'].startswith('weathercn:'):
                                if config_center.read_conf('Weather', 'api') != 'xiaomi_weather':
                                    city_key = city_data['locationKey'].replace('weathercn:', '')
                            self.city_signal.emit(city_key)
                            self.city_info_signal.emit(city_data['name'], city_key)
                            if self.write_config:
                                config_center.write_conf('Weather', 'city', city_key)
                                # logger.success(f"成功设置城市信息: {city_key}")
                elif self.city_id:
                    self.city_signal.emit(self.city_id)
                    if self.write_config:
                        config_center.write_conf('Weather', 'city', self.city_id)
                        # logger.success(f"成功设置城市信息: {self.city_id}")
                else:
                    raise ValueError("未设置城市ID")

            self.finished_signal.emit()

        except Exception as e:
            logger.error(f"获取城市失败: {e}")
            self.error_signal.emit(str(e))

    def get_coordinates(self) -> Tuple[float, float]:
        """获取当前位置的经纬度"""
        try:
            api_config = self.api_config['location_api']['ip_geolocation']
            url = api_config['url']
            timeout = api_config.get('timeout', 10)
            params = api_config.get('params', {})
            response_format = api_config['response_format']

            req = requests.get(url, params=params, proxies=proxies, timeout=timeout)
            if req.status_code == 200:
                data = req.json()
                success_field = response_format['success_field']
                success_value = response_format['success_value']

                if data.get(success_field) == success_value:
                    lat_field = response_format['latitude_field']
                    lon_field = response_format['longitude_field']
                    lat, lon = data[lat_field], data[lon_field]
                    # logger.success(f"获取坐标成功: 纬度 {lat}, 经度 {lon}")
                    return (lat, lon)

                error_field = response_format.get('error_field', 'message')
                error_msg = data.get(error_field, '未知错误')
                logger.error(f"获取坐标失败：{error_msg}")
                raise ValueError(f"获取坐标失败：{error_msg}")

            logger.error(f"获取坐标失败: HTTP {req.status_code}")
            raise ValueError(f"获取坐标失败: HTTP {req.status_code}")

        except Exception as e:
            logger.error(f"获取坐标异常: {e}")
            raise ValueError(f"获取坐标异常: {e}")

    def get_city_by_coordinates(self, latitude: float, longitude: float) -> dict:
        """根据经纬度获取城市信息"""
        try:
            api_config = self.api_config['city_api']['xiaomi_location']
            url = api_config['url']
            timeout = api_config.get('timeout', 10)
            params = api_config['params'].copy()
            response_format = api_config['response_format']
            params['latitude'] = latitude
            params['longitude'] = longitude
            current_locale = get_language_code()
            params['locale'] = current_locale

            req = requests.get(url, params=params, proxies=proxies, timeout=timeout)
            if req.status_code == 200:
                data = req.json()
                if data and len(data) > 0:
                    data_path = response_format.get('data_path', '0')
                    city_info = data[0] if data_path == '0' else data
                    city_key = city_info.get(response_format['location_key_field'], '')
                    city_name = city_info.get(response_format['city_name_field'], '')
                    affiliation = city_info.get(response_format['affiliation_field'], '')
                    # logger.success(f"获取城市成功: {city_name} ({affiliation}), key: {city_key}")
                    return {
                        'affiliation': affiliation,
                        'key': city_key,
                        'name': city_name,
                        'locationKey': city_key,
                    }

                logger.error("空数据")
                raise ValueError("空数据")

            logger.error(f"请求失败: HTTP {req.status_code}")
            raise ValueError(f"请求失败: HTTP {req.status_code}")

        except Exception as e:
            logger.error(f"获取城市失败: {e}")
            raise ValueError(f"获取城市失败: {e}")


class VersionThread(QThread):  # 获取最新版本号
    version_signal = pyqtSignal(dict)
    _instance_running = False

    def __init__(self) -> None:
        super().__init__()

    def run(self) -> None:
        version = self.get_latest_version()
        self.version_signal.emit(version)

    @classmethod
    def is_running(cls) -> bool:
        return cls._instance_running

    @staticmethod
    def get_latest_version() -> Dict[str, Any]:
        url = "https://classwidgets.rinlit.cn/version.json"
        try:
            logger.info("正在获取版本信息")
            response = requests.get(url, proxies=proxies, timeout=30)
            logger.debug(f"更新请求响应: {response.status_code}")
            if response.status_code == 200:
                return response.json()
            logger.error(
                f"无法获取版本信息 错误代码：{response.status_code}，响应内容: {response.text}"
            )
            return {'error': f"请求失败，错误代码：{response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败，错误详情：{e!s}")
            return {"error": f"请求失败\n{e!s}"}


class getDownloadUrl(QThread):
    # 定义信号，通知下载进度或完成
    geturl_signal = pyqtSignal(str)

    def __init__(self, username: str, repo: str) -> None:
        super().__init__()
        self.username = username
        self.repo = repo

    def run(self) -> None:
        try:
            url = f"https://api.github.com/repos/{self.username}/{self.repo}/releases/latest"
            response = requests.get(url, proxies=proxies)
            if response.status_code == 200:
                data = response.json()
                for asset in data['assets']:  # 遍历下载链接
                    if isinstance(asset, dict) and 'browser_download_url' in asset:
                        asset_url = asset['browser_download_url']
                        self.geturl_signal.emit(asset_url)
            elif response.status_code == 403:  # 触发API限制
                logger.warning("到达Github API限制，请稍后再试")
                response = requests.get('https://api.github.com/users/octocat', proxies=proxies)
                reset_time = response.headers.get('X-RateLimit-Reset')
                reset_time = datetime.fromtimestamp(int(reset_time))
                self.geturl_signal.emit(
                    f"ERROR: 由于请求次数过多，到达Github API限制，请在{reset_time.minute}分钟后再试"
                )
            else:
                logger.error(f"网络连接错误：{response.status_code}")
        except Exception as e:
            logger.error(f"获取下载链接错误: {e}")
            self.geturl_signal.emit(f"获取下载链接错误: {e}")


class DownloadAndExtract(QThread):  # 下载并解压插件
    progress_signal = pyqtSignal(float)  # 进度
    status_signal = pyqtSignal(str)  # 状态

    def __init__(self, url: str, plugin_name: str = 'test_114') -> None:
        super().__init__()
        self.download_url = url
        print(self.download_url)
        self.cache_dir = str(CACHE_HOME)
        self.plugin_name = plugin_name
        self.extract_dir = conf.PLUGIN_HOME  # 插件目录

    def run(self) -> None:
        try:
            enabled_plugins = conf.load_plugin_config()  # 加载启用的插件

            os.makedirs(self.cache_dir, exist_ok=True)
            os.makedirs(self.extract_dir, exist_ok=True)

            zip_path = os.path.join(self.cache_dir, f'{self.plugin_name}.zip')

            self.status_signal.emit("DOWNLOADING")
            self.download_file(zip_path)
            self.status_signal.emit("EXTRACTING")
            self.extract_zip(zip_path)
            os.remove(zip_path)
            print(enabled_plugins)

            if (
                self.plugin_name not in enabled_plugins['enabled_plugins']
                and config_center.read_conf('Plugin', 'auto_enable_plugin') == '1'
            ):
                logger.info(f"自动启用插件: {self.plugin_name}")
                enabled_plugins['enabled_plugins'].append(self.plugin_name)
                conf.save_plugin_config(enabled_plugins)

            self.status_signal.emit("DONE")
        except Exception as e:
            self.status_signal.emit(f"错误: {e}")
            logger.error(f"插件下载/解压失败: {e}")

    def stop(self) -> None:
        self._running = False
        self.terminate()

    def download_file(self, file_path: str) -> None:
        # time.sleep(555)  # 模拟下载时间
        try:
            self.download_url = (
                mirror_dict[config_center.read_conf('Plugin', 'mirror')] + self.download_url
            )
            print(self.download_url)
            response = requests.get(self.download_url, stream=True, proxies=proxies)
            if response.status_code != 200:
                logger.error(f"插件下载失败，错误代码: {response.status_code}")
                self.status_signal.emit(f'ERROR: 网络连接错误：{response.status_code}')
                return

            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0

            with open(file_path, 'wb') as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
                    downloaded_size += len(chunk)
                    progress = (
                        (downloaded_size / total_size) * 100 if total_size > 0 else 0
                    )  # 计算进度
                    self.progress_signal.emit(progress)
        except Exception as e:
            self.status_signal.emit(f'ERROR: {e}')
            logger.error(f"插件下载错误: {e}")

    def extract_zip(self, zip_path: str) -> None:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.extract_dir)

            for p_dir in os.listdir(self.extract_dir):
                if p_dir.startswith(self.plugin_name) and len(p_dir) > len(self.plugin_name):
                    new_name = p_dir.rsplit('-', 1)[0]
                    if os.path.exists(os.path.join(self.extract_dir, new_name)):
                        shutil.copytree(
                            os.path.join(self.extract_dir, p_dir),
                            os.path.join(self.extract_dir, new_name),
                            dirs_exist_ok=True,
                        )
                        shutil.rmtree(os.path.join(self.extract_dir, p_dir))
                    else:
                        os.rename(
                            os.path.join(self.extract_dir, p_dir),
                            os.path.join(self.extract_dir, new_name),
                        )
        except Exception as e:
            logger.error(f"解压失败: {e}")


def check_update() -> None:
    global threads

    if VersionThread.is_running():
        logger.debug("已存在版本检查线程在运行，跳过本检查")
        return

    # 清理已终止的线程
    threads = [t for t in threads if t.isRunning()]

    # 创建新的版本检查线程
    version_thread = VersionThread()
    threads.append(version_thread)
    version_thread.version_signal.connect(check_version)
    version_thread.start()


def check_version(version: Dict[str, Any]) -> bool:  # 检查更新
    global threads
    for thread in threads:
        thread.terminate()
    threads = []
    if 'error' in version:
        utils.tray_icon.push_error_notification(
            "检查更新失败！", f"检查更新失败！\n{version['error']}"
        )
        return False

    channel = int(
        '1'
        if (channel := config_center.read_conf("Version", "version_channel")) not in ['0', '1']
        else channel
    )
    server_version = version['version_release' if channel == 0 else 'version_beta']
    local_version = config_center.read_conf("Version", "version")
    if local_version != "__BUILD_VERSION__":
        logger.debug(f"服务端版本: {server_version}，本地版本: {local_version}")
        if Version(server_version.replace('-nightly', '')) > Version(
            local_version.replace('-nightly', '')
        ):
            utils.tray_icon.push_update_notification(
                f"新版本速递：{server_version}\n请在“设置”中了解更多。"
            )
    return None


class scheduleThread(QThread):  # 获取课表
    update_signal = pyqtSignal(dict)

    def __init__(self, url: str, method: str = 'GET', data: Optional[dict] = None):
        super().__init__()
        self.url = url
        self.method = method
        self.data = data

        for db in list_.schedule_dbs:
            if self.url.startswith(f"{db}/"):
                self.url = f"{list_.schedule_dbs[db]}/{self.url[len(db) + 1 :]}"
                break

    def run(self):
        # 获取
        if self.method == 'GET':
            data = self.get_schedule()
        elif self.method == 'POST':
            data = self.post_schedule()
        else:
            data = {'error': "method not supported"}

        if not isinstance(data, dict):
            logger.error(f"获取课表失败，返回数据不是字典类型: {data}")
            data = {'error': "获取课表失败，返回数据不是字典类型"}
        # 发射信号
        self.update_signal.emit(data)

    def get_schedule(self):
        try:
            logger.info(f"正在获取课表 {self.url}")
            response = requests.get(self.url, proxies=proxies, timeout=30)
            logger.debug(f"课表 {self.url} 请求响应: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    data = json.loads(data.get('data'))

                if 'timeline' not in data:
                    data['timeline'] = {
                        "default": [],
                        "0": [],
                        "1": [],
                        "2": [],
                        "3": [],
                        "4": [],
                        "5": [],
                        "6": [],
                    }
                for key, value in data['timeline'].items():
                    if isinstance(value, dict):
                        timeline = value

                        def sort_timeline_key(item):
                            item_name = item[0]
                            prefix = item_name[0]
                            if len(item_name) > 1:
                                try:
                                    # 提取节点序数
                                    part_num = int(item_name[1])
                                    # 提取课程序数
                                    class_num = 0
                                    if len(item_name) > 2:
                                        class_num = int(item_name[2:])
                                    if prefix == 'a':
                                        return part_num, class_num, 0
                                    return part_num, class_num, 1
                                except ValueError:
                                    # 如果转换失败，返回原始字符串
                                    return item_name
                            return item_name

                        new_timeline = []

                        # 对timeline排序后添加到timeline_data
                        sorted_timeline = sorted(timeline.items(), key=sort_timeline_key)
                        for item_name, item_time in sorted_timeline:
                            try:
                                new_timeline.append(
                                    [
                                        int(item_name[0] == 'f'),
                                        item_name[1],
                                        int(item_name[2:]),
                                        item_time,
                                    ]
                                )
                            except Exception as e:
                                logger.error(f'加载课程表文件[课程数据]出错：{e}')
                                return {'error': f'加载课程表文件[课程数据]出错：{e}'}
                        data['timeline'][key] = new_timeline.copy()
                    elif not isinstance(value, list):
                        logger.error(f"课程表时间线格式错误: {key}: {value}")
                        return {'error': f"课程表时间线格式错误: {key}: {value}"}

                if 'timeline_even' not in data:
                    data['timeline_even'] = {
                        "default": [],
                        "0": [],
                        "1": [],
                        "2": [],
                        "3": [],
                        "4": [],
                        "5": [],
                        "6": [],
                    }
                if data.get('url', None) is None:
                    data['url'] = self.url

                return data

            logger.error(
                f"无法获取课表 {self.url} 错误代码：{response.status_code}，响应内容: {response.text}"
            )
            return {'error': f"请求失败，错误代码：{response.status_code}"}
        except Exception as e:
            logger.error(f"请求失败，错误详情：{e!s}")
            return {"error": f"请求失败\n{e!s}"}

    def post_schedule(self):
        try:
            logger.info(f"正在上传课表 {self.url}")
            response = requests.post(
                self.url, proxies=proxies, timeout=30, json={"data": json.dumps(self.data)}
            )
            logger.debug(f"课表 {self.url} 请求响应: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    return json.loads(data.get('data'))
                return data
            logger.error(
                f"无法上传课表 {self.url} 错误代码：{response.status_code}，响应内容: {response.text}"
            )
            return {'error': f"请求失败，错误代码：{response.status_code}"}
        except Exception as e:
            logger.error(f"请求失败，错误详情：{e!s}")
            return {"error": f"请求失败\n{e!s}"}
