import json
import os
import time
import zipfile  # 解压插件zip
from datetime import datetime

import requests
from PyQt5.QtCore import QThread, pyqtSignal
from loguru import logger

import conf

headers = {"User-Agent": "Mozilla/5.0"}
proxies = {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}  # 加速访问
# proxies = {"http": None, "https": None}

MIRROR_PATH = "config/mirror.json"
PLAZA_REPO_URL = "https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/"
PLAZA_REPO_DIR = "https://api.github.com/repos/Class-Widgets/plugin-plaza/contents/"

# 读取镜像配置
mirror_list = []
try:
    with open(MIRROR_PATH, 'r', encoding='utf-8') as file:
        mirror_dict = json.load(file).get('gh_mirror')
except Exception as e:
    logger.error(f"读取镜像配置失败: {e}")

for name in mirror_dict:
    mirror_list.append(name)

if conf.read_conf('Plugin', 'mirror') not in mirror_list:  # 如果当前配置不在镜像列表中，则设置为默认镜像
    logger.warning(f"当前配置不在镜像列表中，设置为默认镜像: {mirror_list[0]}")
    conf.write_conf('Plugin', 'mirror', mirror_list[0])


class getRepoFileList(QThread):  # 获取仓库文件目录
    repo_signal = pyqtSignal(list)

    def __init__(self, path='Plugins', endswith='.json'):  # 目录
        super().__init__()
        self.path = path
        self.endswith = endswith

    def run(self):
        try:
            file_list = self.get_list()
            self.repo_signal.emit(file_list)
        except Exception as e:
            logger.error(f"触发所有插件信息失败: {e}")

    def get_list(self):
        try:
            # 获取目录内容
            url = f"{PLAZA_REPO_DIR}{self.path}"
            print(url)
            response = requests.get(url, proxies=proxies, headers=headers)
            if response.status_code == 200:
                response.raise_for_status()
                files = response.json()

                # 筛选出 JSON 文件
                json_files = [file['download_url'] for file in files if file['name'].endswith(self.endswith)]

                if not json_files:
                    logger.warning(f"插件广场内{self.path}的目录为空")
                    return []
                else:
                    logger.success(f"获取{self.path}目录成功")
                    return json_files
            elif response.status_code == 403 or response.status_code == 429:
                logger.warning("到达Github API限制，请稍后再试")
                return ['banner_1.png']
            else:
                logger.error(f"获取{self.path}目录失败：{response.status_code}")
                return []
        except Exception as e:
            logger.error(f"获取{self.path}目录错误: {e}")
            return []


class getPluginInfo(QThread):  # 获取插件信息(json)
    repo_signal = pyqtSignal(dict)

    def __init__(
            self, url='https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Plugins/plugin_list.json'
    ):
        super().__init__()
        self.download_url = url

    def run(self):
        try:
            plugin_info_data = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发插件信息失败: {e}")

    def get_plugin_info(self):
        try:
            mirror_url = mirror_dict[conf.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            response = requests.get(url, proxies=proxies)  # 禁用代理
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                logger.error(f"获取插件信息失败：{response.status_code}")
                return {}
        except Exception as e:
            logger.error(f"获取插件信息失败：{e}")
            return {}


class getTags(QThread):  # 获取插件标签(json)
    repo_signal = pyqtSignal(dict)

    def __init__(
            self, url='https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Plugins/tags.json'
    ):
        super().__init__()
        self.download_url = url

    def run(self):
        try:
            plugin_info_data = self.get_plugin_info()
            self.repo_signal.emit(plugin_info_data)
        except Exception as e:
            logger.error(f"触发Tag信息失败: {e}")

    def get_plugin_info(self):
        try:
            mirror_url = mirror_dict[conf.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            response = requests.get(url, proxies=proxies)  # 禁用代理
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                logger.error(f"获取Tag信息失败：{response.status_code}")
                return {}
        except Exception as e:
            logger.error(f"获取Tag信息失败：{e}")
            return {}


class getImg(QThread):  # 获取图片
    repo_signal = pyqtSignal(bytes)

    def __init__(self, url='https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Banner/banner_1.png'):
        super().__init__()
        self.download_url = url

    def run(self):
        try:
            banner_data = self.get_banner()
            if banner_data is not None:
                self.repo_signal.emit(banner_data)
            else:
                with open("img/plaza/banner_pre.png", 'rb') as default_img:  # 读取默认图片
                    self.repo_signal.emit(default_img.read())
        except Exception as e:
            logger.error(f"触发图片失败: {e}")

    def get_banner(self):
        try:
            mirror_url = mirror_dict[conf.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            response = requests.get(url, proxies=proxies)
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

    def __init__(self, url='https://raw.githubusercontent.com/Class-Widgets/Class-Widgets/main/README.md'):
        super().__init__()
        self.download_url = url

    def run(self):
        try:
            readme_data = self.get_readme()
            self.html_signal.emit(readme_data)
        except Exception as e:
            logger.error(f"触发README失败: {e}")

    def get_readme(self):
        try:
            mirror_url = mirror_dict[conf.read_conf('Plugin', 'mirror')]
            url = f"{mirror_url}{self.download_url}"
            print(url)
            response = requests.get(url, proxies=proxies)
            if response.status_code == 200:
                return response.text
            else:
                logger.error(f"获取README失败：{response.status_code}")
                return ''
        except Exception as e:
            logger.error(f"获取README失败：{e}")
            return ''


class VersionThread(QThread):  # 获取最新版本号
    version_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

    def run(self):
        version = self.get_latest_version()
        self.version_signal.emit(version)

    def get_latest_version(self):
        url = "https://api.github.com/repos/RinLit-233-shiroko/Class-Widgets/releases/latest"
        try:
            response = requests.get(url, proxies=proxies)
            if response.status_code == 200:
                data = response.json()
                return data.get("tag_name")
            else:
                logger.error(f"无法获取版本信息 错误代码：{response.status_code}")
                return "请求失败"
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败，错误代码：{e}")
            return f"请求失败"


class getDownloadUrl(QThread):
    # 定义信号，通知下载进度或完成
    geturl_signal = pyqtSignal(str)

    def __init__(self, username, repo):
        super().__init__()
        self.username = username
        self.repo = repo

    def run(self):
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
                self.geturl_signal.emit(f"ERROR: 由于请求次数过多，到达Github API限制，请在{reset_time.minute}分钟后再试")
            else:
                logger.error(f"网络连接错误：{response.status_code}")
        except Exception as e:
            logger.error(f"获取下载链接错误: {e}")
            self.geturl_signal.emit(f"获取下载链接错误: {e}")


class DownloadAndExtract(QThread):  # 下载并解压插件
    progress_signal = pyqtSignal(float)  # 进度
    status_signal = pyqtSignal(str)  # 状态

    def __init__(self, url, plugin_name='test_114'):
        super().__init__()
        self.download_url = url
        print(self.download_url)
        self.cache_dir = "cache"
        self.plugin_name = plugin_name
        self.extract_dir = f'Plugins'

    def run(self):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            os.makedirs(self.extract_dir, exist_ok=True)

            zip_path = os.path.join(self.cache_dir, f'{self.plugin_name}.zip')

            self.status_signal.emit("DOWNLOADING")
            self.download_file(zip_path)
            self.status_signal.emit("EXATRACTING")
            self.extract_zip(zip_path)
            os.remove(zip_path)
            self.status_signal.emit("DONE")
        except Exception as e:
            self.status_signal.emit(f"错误: {e}")
            logger.error(f"插件下载/解压失败: {e}")

    def stop(self):
        self.terminate()

    def download_file(self, file_path):
        # time.sleep(555)  # 模拟下载时间
        try:
            self.download_url = mirror_dict[conf.read_conf('Plugin', 'mirror')] + self.download_url
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
                    progress = (downloaded_size / total_size) * 100 if total_size > 0 else 0  # 计算进度
                    self.progress_signal.emit(progress)
        except Exception as e:
            self.status_signal.emit(f'ERROR: {e}')
            logger.error(f"插件下载错误: {e}")

    def extract_zip(self, zip_path):
        try:
            before = set(os.listdir(self.extract_dir))
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.extract_dir)
            after_extract = set(os.listdir(self.extract_dir))

            # 找出新增的文件夹
            new_folder = after_extract - before
            if new_folder:
                folder_name = new_folder.pop()  # 取出集合中的一个元素
                new_name = folder_name.rsplit('-', 1)[0]
                os.rename(os.path.join(self.extract_dir, folder_name), os.path.join(self.extract_dir, new_name))
        except Exception as e:
            logger.error(f"解压失败: {e}")


if __name__ == '__main__':
    # version_thread = VersionThread()
    # version_thread.version_signal.connect(lambda data: print(data))
    # version_thread.start()
    img_thread = getImg('https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Banner/banner_1.png')
    img_thread.repo_signal.connect(lambda data: print(data))
    img_thread.start()
    time.sleep(2222)
