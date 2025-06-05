import json
import os
import shutil
import zipfile  # 解压插件zip
from datetime import datetime
from typing import Dict, Any, Optional, List, Union # Added for type hints

import requests
from PyQt5.QtCore import QThread, pyqtSignal, QEventLoop, QObject # Added QObject
from loguru import logger
from packaging.version import Version

import conf
import utils
import weather_db as db
from conf import base_directory
from file import config_center

headers: Dict[str, str] = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}  # 设置请求头
proxies: Dict[str, Optional[str]] = {"http": None, "https": None}  # 加速访问

MIRROR_PATH: str = f"{base_directory}/config/mirror.json" # type: ignore[attr-defined]
PLAZA_REPO_URL: str = "https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/"
PLAZA_REPO_DIR: str = "https://api.github.com/repos/Class-Widgets/plugin-plaza/contents/"
threads: List[QThread] = [] # List of QThread instances

# 读取镜像配置
mirror_list: List[str] = []
mirror_dict: Dict[str, str] = {}
try:
    with open(MIRROR_PATH, 'r', encoding='utf-8') as file:
        loaded_json: Dict[str, Any] = json.load(file)
        mirror_data_from_json = loaded_json.get('gh_mirror')
        if isinstance(mirror_data_from_json, dict):
            mirror_dict = mirror_data_from_json
        else:
            logger.error("gh_mirror in mirror.json is not a dictionary.")
except Exception as e:
    logger.error(f"读取镜像配置失败: {e}")

name: str
for name in mirror_dict:
    mirror_list.append(name)

current_mirror_conf: Optional[str] = config_center.read_conf('Plugin', 'mirror') # type: ignore[no-untyped-call]
if current_mirror_conf not in mirror_list:
    default_mirror = mirror_list[0] if mirror_list else ""
    logger.warning(f"当前配置不在镜像列表中，设置为默认镜像: {default_mirror}")
    config_center.write_conf('Plugin', 'mirror', default_mirror) # type: ignore[no-untyped-call]


class getRepoFileList(QThread):  # 获取仓库文件目录
    repo_signal = pyqtSignal(dict) # pyqtSignal(Dict[str, Any])

    def __init__(
            self,
            url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Banner/banner.json',
            parent: Optional[QObject] = None # Added parent
    ) -> None: # Added types
        super().__init__(parent)
        self.download_url: str = url

    def run(self) -> None: # Added return type
        try:
            plugin_info_data: Dict[str, Any] = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发banner信息失败: {e}")

    def get_plugin_info(self) -> Dict[str, Any]: # Added return type
        try:
            mirror_name: Optional[str] = config_center.read_conf('Plugin', 'mirror') # type: ignore[no-untyped-call]
            mirror_url_base: Optional[str] = mirror_dict.get(mirror_name) if mirror_name else None

            if not mirror_url_base:
                logger.error(f"镜像URL未找到，请检查配置: {mirror_name}")
                return {"error": "Mirror URL not found"}

            url: str = f"{mirror_url_base}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)
            if response.status_code == 200:
                data: Dict[str, Any] = response.json()
                return data
            else:
                logger.error(f"获取banner信息失败：{response.status_code}")
                return {"error": response.status_code}
        except Exception as e:
            logger.error(f"获取banner信息失败：{e}")
            return {"error": str(e)}


class getPluginInfo(QThread):  # 获取插件信息(json)
    repo_signal = pyqtSignal(dict) # pyqtSignal(Dict[str, Any])

    def __init__(
            self,
            url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Plugins/plugin_list.json',
            parent: Optional[QObject] = None # Added parent
    ) -> None: # Added types
        super().__init__(parent)
        self.download_url: str = url

    def run(self) -> None: # Added return type
        try:
            plugin_info_data: Dict[str, Any] = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发插件信息失败: {e}")

    def get_plugin_info(self) -> Dict[str, Any]: # Added return type
        try:
            mirror_name: Optional[str] = config_center.read_conf('Plugin', 'mirror') # type: ignore[no-untyped-call]
            mirror_url_base: Optional[str] = mirror_dict.get(mirror_name) if mirror_name else None

            if not mirror_url_base:
                logger.error(f"镜像URL未找到，请检查配置: {mirror_name}")
                return {} # Return empty dict on error as per original logic

            url: str = f"{mirror_url_base}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)
            if response.status_code == 200:
                data: Dict[str, Any] = response.json()
                return data
            else:
                logger.error(f"获取插件信息失败：{response.status_code}")
                return {}
        except Exception as e:
            logger.error(f"获取插件信息失败：{e}")
            return {}


class getTags(QThread):  # 获取插件标签(json)
    repo_signal = pyqtSignal(dict) # pyqtSignal(Dict[str, Any])

    def __init__(
            self,
            url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Plugins/plaza_detail.json',
            parent: Optional[QObject] = None # Added parent
    ) -> None: # Added types
        super().__init__(parent)
        self.download_url: str = url

    def run(self) -> None: # Added return type
        try:
            plugin_info_data: Dict[str, Any] = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发Tag信息失败: {e}")

    def get_plugin_info(self) -> Dict[str, Any]: # Added return type
        try:
            mirror_name: Optional[str] = config_center.read_conf('Plugin', 'mirror') # type: ignore[no-untyped-call]
            mirror_url_base: Optional[str] = mirror_dict.get(mirror_name) if mirror_name else None

            if not mirror_url_base:
                logger.error(f"镜像URL未找到，请检查配置: {mirror_name}")
                return {}

            url: str = f"{mirror_url_base}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)
            if response.status_code == 200:
                data: Dict[str, Any] = response.json()
                return data
            else:
                logger.error(f"获取Tag信息失败：{response.status_code}")
                return {}
        except Exception as e:
            logger.error(f"获取Tag信息失败：{e}")
            return {}


class getImg(QThread):  # 获取图片
    repo_signal = pyqtSignal(bytes)

    def __init__(self, url: str = 'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Banner/banner_1.png', parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self.download_url: str = url

    def run(self) -> None: # Added return type
        try:
            banner_data: Optional[bytes] = self.get_banner()
            if banner_data is not None:
                self.repo_signal.emit(banner_data)
            else:
                # base_directory is Path
                default_img_path = Path(base_directory) / "img" / "plaza" / "banner_pre.png" # type: ignore[attr-defined]
                with open(default_img_path, 'rb') as default_img:
                    self.repo_signal.emit(default_img.read())
        except Exception as e:
            logger.error(f"触发图片失败: {e}")

    def get_banner(self) -> Optional[bytes]: # Added return type
        try:
            mirror_name: Optional[str] = config_center.read_conf('Plugin', 'mirror') # type: ignore[no-untyped-call]
            mirror_url_base: Optional[str] = mirror_dict.get(mirror_name) if mirror_name else None
            if not mirror_url_base:
                logger.error(f"镜像URL未找到，请检查配置: {mirror_name}")
                return None

            url: str = f"{mirror_url_base}{self.download_url}"
            response = requests.get(url, proxies=proxies, headers=headers)
            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"获取图片失败：{response.status_code}")
                return None
        except Exception as e:
            logger.error(f"获取图片失败：{e}")
            return None


class getReadme(QThread):  # 获取README
    html_signal = pyqtSignal(str)

    def __init__(self, url: str = 'https://raw.githubusercontent.com/Class-Widgets/Class-Widgets/main/README.md', parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self.download_url: str = url

    def run(self) -> None: # Added return type
        try:
            readme_data: str = self.get_readme()
            self.html_signal.emit(readme_data)
        except Exception as e:
            logger.error(f"触发README失败: {e}")

    def get_readme(self) -> str: # Added return type
        try:
            mirror_name: Optional[str] = config_center.read_conf('Plugin', 'mirror') # type: ignore[no-untyped-call]
            mirror_url_base: Optional[str] = mirror_dict.get(mirror_name) if mirror_name else None
            if not mirror_url_base:
                logger.error(f"镜像URL未找到，请检查配置: {mirror_name}")
                return ""

            url: str = f"{mirror_url_base}{self.download_url}"
            response = requests.get(url, proxies=proxies)
            if response.status_code == 200:
                return response.text
            else:
                logger.error(f"获取README失败：{response.status_code}")
                return ''
        except Exception as e:
            logger.error(f"获取README失败：{e}")
            return ''

class getCity(QThread):
    city_data_signal = pyqtSignal(tuple) # Emits (city, district)

    def __init__(self, url: str = 'https://qifu-api.baidubce.com/ip/local/geo/v1/district', parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self.download_url: str = url

    def run(self) -> None: # Added return type
        try:
            city_data_tuple: Tuple[str, str] = self.get_city()
            # Emit the signal with city data for other parts of the application to use if needed
            self.city_data_signal.emit(city_data_tuple)
            # The original code directly writes to config, which might be okay
            # but emitting a signal allows more flexibility.
            # For now, keeping direct write to config as per original logic.
            config_center.write_conf('Weather', 'city', db.search_code_by_name(city_data_tuple)) # type: ignore[no-untyped-call]
        except Exception as e:
            logger.error(f"获取城市失败: {e}")

    def get_city(self) -> Tuple[str, str]: # Added return type
        try:
            req = requests.get(self.download_url, proxies=proxies)
            if req.status_code == 200:
                data: Dict[str, Any] = req.json()
                if data.get('code') == 'Success':
                    city_info: Dict[str, str] = data.get('data', {})
                    city: str = city_info.get('city', '')
                    district: str = city_info.get('district', '')
                    logger.info(f"获取城市成功：{city}, {district}")
                    return (city, district)
                else:
                    logger.error(f"获取城市失败：{data.get('message', 'Unknown error')}")
                    return ('', '')
            else:
                logger.error(f"获取城市失败：{req.status_code}")    
                return ('', '')
            
        except Exception as e:
            logger.error(f"获取城市失败：{e}")
            return ('', '')

class VersionThread(QThread):  # 获取最新版本号
    version_signal = pyqtSignal(dict) # pyqtSignal(Dict[str, Any])
    _instance_running: bool = False # Class variable to track if an instance is running

    def __init__(self, parent: Optional[QObject] = None) -> None: # Added parent type
        super().__init__(parent)

    def run(self) -> None: # Added return type
        VersionThread._instance_running = True
        try:
            version: Dict[str, Any] = self.get_latest_version()
            self.version_signal.emit(version)
        finally:
            VersionThread._instance_running = False # Reset flag when thread finishes
    
    @classmethod
    def is_running(cls) -> bool: # Added return type
        return cls._instance_running

    @staticmethod
    def get_latest_version() -> Dict[str, Any]: # Added return type
        url: str = "https://classwidgets.rinlit.cn/version.json"
        try:
            logger.info(f"正在获取版本信息")
            response = requests.get(url, proxies=proxies, timeout=30)
            logger.debug(f"更新请求响应: {response.status_code}")
            if response.status_code == 200:
                data: Dict[str, Any] = response.json()
                return data
            else:
                logger.error(f"无法获取版本信息 错误代码：{response.status_code}，响应内容: {response.text}")
                return {'error': f"请求失败，错误代码：{response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败，错误详情：{str(e)}")
            return {"error": f"请求失败\n{str(e)}"}


class getDownloadUrl(QThread):
    geturl_signal = pyqtSignal(str)

    def __init__(self, username: str, repo: str, parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self.username: str = username
        self.repo: str = repo

    def run(self) -> None: # Added return type
        try:
            url: str = f"https://api.github.com/repos/{self.username}/{self.repo}/releases/latest"
            response = requests.get(url, proxies=proxies)
            if response.status_code == 200:
                data: Dict[str, Any] = response.json()
                asset: Dict[str, Any]
                for asset in data.get('assets', []):
                    if isinstance(asset, dict) and 'browser_download_url' in asset:
                        asset_url: Optional[str] = asset['browser_download_url']
                        if asset_url:
                           self.geturl_signal.emit(asset_url)
                           return # Assuming only one asset URL is needed
            elif response.status_code == 403:
                logger.warning("到达Github API限制，请稍后再试")
                # Check rate limit reset time
                # This request to /users/octocat is just to get headers, might not be necessary
                # if the original 403 response already contains rate limit headers.
                rate_limit_response = requests.get('https://api.github.com/users/octocat', proxies=proxies)
                reset_time_str: Optional[str] = rate_limit_response.headers.get('X-RateLimit-Reset')
                reset_time_msg: str = ""
                if reset_time_str:
                    reset_datetime = datetime.fromtimestamp(int(reset_time_str))
                    reset_time_msg = f"请在{reset_datetime.strftime('%Y-%m-%d %H:%M:%S')}后再试"
                self.geturl_signal.emit(f"ERROR: 由于请求次数过多，到达Github API限制，{reset_time_msg}")
            else:
                logger.error(f"网络连接错误：{response.status_code}")
                self.geturl_signal.emit(f"ERROR: 网络连接错误：{response.status_code}")
        except Exception as e:
            logger.error(f"获取下载链接错误: {e}")
            self.geturl_signal.emit(f"获取下载链接错误: {str(e)}")


class DownloadAndExtract(QThread):  # 下载并解压插件
    progress_signal = pyqtSignal(float)  # 进度
    status_signal = pyqtSignal(str)  # 状态
    _running: bool # For stopping the thread, though QThread.requestInterruption is better

    def __init__(self, url: str, plugin_name: str = 'test_114', parent: Optional[QObject] = None) -> None: # Added types
        super().__init__(parent)
        self.download_url: str = url
        self._running = True
        self.cache_dir: str = "cache"
        self.plugin_name: str = plugin_name
        # conf.PLUGINS_DIR is str
        self.extract_dir: str = str(conf.PLUGINS_DIR) # type: ignore[attr-defined]

    def run(self) -> None: # Added return type
        try:
            # enabled_plugins is Dict[str, List[str]]
            enabled_plugins_data: Dict[str, List[str]] = conf.load_plugin_config() # type: ignore[no-untyped-call]

            os.makedirs(self.cache_dir, exist_ok=True)
            os.makedirs(self.extract_dir, exist_ok=True)

            zip_path: str = os.path.join(self.cache_dir, f'{self.plugin_name}.zip')

            self.status_signal.emit("DOWNLOADING")
            self.download_file(zip_path)
            if not self._running: return # Check if stopped during download

            self.status_signal.emit("EXTRACTING")
            self.extract_zip(zip_path)
            if not self._running: return # Check if stopped during extraction

            if os.path.exists(zip_path): # Ensure file exists before removing
                os.remove(zip_path)

            # enabled_plugins_list is List[str]
            enabled_plugins_list = enabled_plugins_data.get('enabled_plugins', [])
            auto_enable_conf: Optional[str] = config_center.read_conf('Plugin', 'auto_enable_plugin') # type: ignore[no-untyped-call]

            if (
                self.plugin_name not in enabled_plugins_list
                and auto_enable_conf == '1'
            ):
                logger.info(f"自动启用插件: {self.plugin_name}")
                enabled_plugins_list.append(self.plugin_name)
                enabled_plugins_data['enabled_plugins'] = enabled_plugins_list
                conf.save_plugin_config(enabled_plugins_data) # type: ignore[no-untyped-call]

            self.status_signal.emit("DONE")
        except Exception as e:
            self.status_signal.emit(f"错误: {str(e)}")
            logger.error(f"插件下载/解压失败: {e}")

    def stop(self) -> None: # Added return type
        logger.info(f"停止下载/解压线程: {self.plugin_name}")
        self._running = False
        if self.isRunning(): # Check if the thread is actually running
            self.requestInterruption() # Use QThread's interruption mechanism
            self.wait(5000) # Wait for thread to finish, with timeout
            if self.isRunning(): # If still running, terminate
                 logger.warning(f"线程 {self.plugin_name} 未能在超时后正常退出，强制终止。")
                 self.terminate()


    def download_file(self, file_path: str) -> None: # Added types
        try:
            download_url_actual: str = self.download_url # Default to original URL
            mirror_name_dl: Optional[str] = config_center.read_conf('Plugin', 'mirror') # type: ignore[no-untyped-call]
            mirror_url_base_dl: Optional[str] = mirror_dict.get(mirror_name_dl) if mirror_name_dl else None
            if mirror_url_base_dl:
                 download_url_actual = f"{mirror_url_base_dl}{self.download_url}"

            logger.info(f"开始下载插件 {self.plugin_name} from {download_url_actual}")
            response = requests.get(download_url_actual, stream=True, proxies=proxies, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.error(f"插件下载失败，错误代码: {response.status_code} for URL: {download_url_actual}")
                self.status_signal.emit(f'ERROR: 网络连接错误：{response.status_code}')
                self._running = False
                return

            total_size_str: Optional[str] = response.headers.get('content-length')
            total_size: int = 0
            if total_size_str and total_size_str.isdigit():
                total_size = int(total_size_str)

            downloaded_size: int = 0

            with open(file_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192): # Use a common chunk size
                    if not self._running: # Check for stop request during download
                        logger.info(f"下载中断: {self.plugin_name}")
                        self.status_signal.emit("CANCELLED")
                        return
                    if chunk: # filter out keep-alive new chunks
                        file.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            progress: float = (downloaded_size / total_size) * 100
                            self.progress_signal.emit(progress)
                        else: # If total size is unknown, emit -1 or handle differently
                            self.progress_signal.emit(-1) # Indicate unknown total size
            if total_size != 0 and downloaded_size < total_size:
                 logger.warning(f"下载未完成: {self.plugin_name}. Expected {total_size}, got {downloaded_size}")
                 self.status_signal.emit("ERROR: 下载未完成")
                 self._running = False

        except requests.exceptions.RequestException as e: # More specific exception
            self.status_signal.emit(f'ERROR: {str(e)}')
            logger.error(f"插件下载错误: {e}")
            self._running = False
        except Exception as e: # Generic exception for other issues
            self.status_signal.emit(f'ERROR: {str(e)}')
            logger.error(f"插件下载时发生未知错误: {e}")
            self._running = False


    def extract_zip(self, zip_path: str) -> None: # Added type
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.extract_dir)

            # Post-extraction renaming/moving logic
            # This logic assumes the zip file might contain a top-level folder
            # that includes a version number (e.g., plugin_name-1.0.0)
            p_dir: str
            for p_dir in os.listdir(self.extract_dir):
                if not self._running: return # Check for stop request

                source_path: str = os.path.join(self.extract_dir, p_dir)
                # Check if p_dir is related to the current plugin and is a directory
                if os.path.isdir(source_path) and p_dir.startswith(self.plugin_name):
                    # Potentially, the extracted folder has a version suffix, e.g., "myplugin-1.2.3"
                    # The target is to have the folder named just "myplugin"
                    # The original logic `new_name = p_dir.rsplit('-', 1)[0]` might be too aggressive
                    # if plugin_name itself contains hyphens.
                    # A safer way might be to check if p_dir is `plugin_name` or `plugin_name-version`.

                    target_plugin_path: str = os.path.join(self.extract_dir, self.plugin_name)

                    if source_path != target_plugin_path: # If extracted folder is not already the target name
                        if os.path.exists(target_plugin_path):
                            # If target (e.g. "myplugin") already exists, merge contents
                            logger.info(f"合并插件文件夹: {source_path} -> {target_plugin_path}")
                            shutil.copytree(source_path, target_plugin_path, dirs_exist_ok=True)
                            shutil.rmtree(source_path) # Remove original versioned folder
                        else:
                            # Rename versioned folder to target name
                            logger.info(f"重命名插件文件夹: {source_path} -> {target_plugin_path}")
                            os.rename(source_path, target_plugin_path)
        except Exception as e:
            logger.error(f"解压失败: {e}")
            self.status_signal.emit(f"ERROR: 解压失败 - {str(e)}")
            self._running = False


def check_update() -> None: # Added return type
    global threads

    if VersionThread.is_running():
        logger.debug("已存在版本检查线程在运行，跳过本检查")
        return
    
    # 清理已终止的线程
    threads = [t for t in threads if t.isRunning()]
    
    # 创建新的版本检查线程
    version_thread = VersionThread() # parent can be set if needed, e.g. to app instance
    threads.append(version_thread)
    version_thread.version_signal.connect(check_version)
    version_thread.start()


def check_version(version: Dict[str, Any]) -> None:  # 检查更新. Added type for version
    global threads # This global might not be necessary if threads list is managed elsewhere or passed
    # Terminate all threads in the list - this seems aggressive if threads are doing other work.
    # Consider if only this specific type of thread should be terminated.
    # For now, replicating original logic.
    # thread: QThread
    # for thread in threads:
    #     if thread.isRunning(): # Check before terminating
    #         thread.requestInterruption() # Prefer requestInterruption
    #         if not thread.wait(1000): # Wait for it to finish
    #             thread.terminate() # Force terminate if it doesn't stop
    # threads = [] # Clear the list

    # More robustly, if `threads` is only for VersionThread instances:
    for i in range(len(threads) -1, -1, -1): # Iterate backwards for safe removal
        thread = threads[i]
        if isinstance(thread, VersionThread) and thread.isRunning():
            thread.requestInterruption()
            thread.wait(500) # Give some time to finish
            if thread.isRunning(): thread.terminate()
            threads.pop(i)


    if 'error' in version:
        if utils.tray_icon: # Check if tray_icon is initialized
            utils.tray_icon.push_error_notification( # type: ignore[attr-defined]
                "检查更新失败！",
                f"检查更新失败！\n{version['error']}"
            )
        return # Return False was original, but function is None, so just return

    channel_conf: Optional[str] = config_center.read_conf("Version", "version_channel") # type: ignore[no-untyped-call]
    channel: int = int(channel_conf) if channel_conf and channel_conf.isdigit() else 0

    server_version_key: str = 'version_release' if channel == 0 else 'version_beta'
    server_version_str: Optional[str] = version.get(server_version_key)
    
    local_version_str: Optional[str] = config_center.read_conf("Version", "version") # type: ignore[no-untyped-call]
    if not local_version_str: local_version_str = "0.0.0" # Default if not set

    if not server_version_str:
        logger.error(f"服务器版本信息中未找到key: {server_version_key}")
        if utils.tray_icon: utils.tray_icon.push_error_notification("检查更新失败！", "无法解析服务器版本。") # type: ignore[attr-defined]
        return

    logger.debug(f"服务端版本: {Version(server_version_str)}，本地版本: {Version(local_version_str)}")
    if Version(server_version_str) > Version(local_version_str):
        if utils.tray_icon: # Check if tray_icon is initialized
            utils.tray_icon.push_update_notification(f"新版本速递：{server_version_str}\n请在“设置”中了解更多。") # type: ignore[attr-defined]

class weatherReportThread(QThread):  # 获取最新天气信息
    weather_signal = pyqtSignal(dict) # pyqtSignal(Dict[str, Any])

    def __init__(self, parent: Optional[QObject] = None) -> None: # Added parent type
        super().__init__(parent)

    def run(self) -> None: # Added return type
        try:
            weather_data: Dict[str, Any] = self.get_weather_data()
            self.weather_signal.emit(weather_data)
        except Exception as e:
            logger.error(f"触发天气信息失败: {e}")
            self.weather_signal.emit({'error': {'info': {'value': '错误', 'unit': str(e)}}})


    @staticmethod
    def get_weather_data() -> Dict[str, Any]: # Added return type
        location_key_conf: Optional[str] = config_center.read_conf('Weather', 'city') # type: ignore[no-untyped-call]
        location_key: str = location_key_conf if location_key_conf and location_key_conf != '0' else ""

        if not location_key: # If '0' or empty after read_conf
            city_thread = getCity() # Create instance, no parent needed for short-lived thread if managed
            loop = QEventLoop()
            city_thread.finished.connect(loop.quit)
            city_thread.city_data_signal.connect(lambda city_tuple: config_center.write_conf('Weather', 'city', db.search_code_by_name(city_tuple))) # type: ignore[no-untyped-call]
            city_thread.start()
            loop.exec_()

            location_key_conf_updated: Optional[str] = config_center.read_conf('Weather', 'city') # type: ignore[no-untyped-call]
            location_key = location_key_conf_updated if location_key_conf_updated and location_key_conf_updated != '0' else "101010100" # Default to Beijing if still not set

        days: int = 1
        key: Optional[str] = config_center.read_conf('Weather', 'api_key') # type: ignore[no-untyped-call]

        weather_url_template: Optional[str] = db.get_weather_url() # type: ignore[no-untyped-call]
        if not weather_url_template:
            logger.error("天气API URL模板未找到。")
            return {'error': {'info': {'value': '错误', 'unit': 'API URL missing'}}}

        url: str = weather_url_template.format(location_key=location_key, days=days, key=key if key else "")

        alert_url_template: Optional[str] = db.get_weather_alert_url() # type: ignore[no-untyped-call]
        data_group: Dict[str, Any] = {'now': {}, 'alert': {}}

        try:
            response_now = requests.get(url, proxies=proxies, timeout=15)
            if response_now.status_code == 200:
                data_group['now'] = response_now.json()
            else:
                logger.error(f"获取天气信息失败：{response_now.status_code}")
                data_group['now'] = {'error': {'info': {'value': '错误', 'unit': str(response_now.status_code)}}}

            if alert_url_template and alert_url_template != 'NotSupported':
                alert_url_formatted: str = alert_url_template.format(location_key=location_key, key=key if key else "")
                response_alert = requests.get(alert_url_formatted, proxies=proxies, timeout=15)
                if response_alert.status_code == 200:
                    data_group['alert'] = response_alert.json()
                else:
                    logger.error(f"获取天气预警信息失败：{response_alert.status_code}")
                    # Optionally add error info to data_group['alert']
            elif alert_url_template == 'NotSupported':
                logger.warning(f"当前API不支持天气预警信息")
            else: # None or empty
                logger.warning(f"无单独天气预警信息API")

            return data_group

        except requests.exceptions.RequestException as e:
            logger.error(f"获取天气信息RequestException：{e}")
            return {'error': {'info': {'value': '错误', 'unit': '请求失败'}}}
        except Exception as e:
            logger.error(f"获取天气信息时发生未知错误：{e}")
            return {'error': {'info': {'value': '错误', 'unit': '未知错误'}}}
