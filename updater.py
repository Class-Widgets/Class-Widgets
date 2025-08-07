import json
import os
import platform
import time
import shutil
import subprocess
import sys
import threading
import traceback
import zipfile

from loguru import logger
from packaging.version import Version
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QEventLoop
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication
from PyQt5.uic import loadUi
from qfluentwidgets import FluentWindow, FluentIcon, CaptionLabel, ProgressBar
import requests

from file import config_center
import utils  # 导入utils模块用于托盘通知

class UpdateStatus(QObject):
    status_changed = pyqtSignal(bool, str)
    def __init__(self):
        super().__init__()
        self.enabled = True
        self.busy = False
        self.text = "检查更新"
    def set(self, enabled, text):
        self.enabled = enabled
        self.text = text
        self.status_changed.emit(enabled, text)
    def get(self):
        return self.enabled, self.text

update_status = UpdateStatus()

class UnifiedUpdateThread(QThread):
    """
    统一的更新线程，负责下载和解压
    """
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(bool, str)
    finish_signal = pyqtSignal(bool, str, dict)  # 修改为传递版本信息

    def __init__(self, version_info=None, silent=False, parent=None):
        super().__init__(parent)
        self.version_info = version_info
        self.silent = silent
        self.version_data = None  # 存储版本信息

    def run(self):
        self.status_signal.emit(False, "检查更新中...")
        update_status.set(False, "检查更新中...")
        logger.debug("检查更新中")
        try:
            if self.version_info is None:
                from network_thread import VersionThread
                vt = VersionThread()
                loop = QEventLoop()
                def on_version(version):
                    self._on_version(version)
                    loop.quit()
                vt.version_signal.connect(on_version)
                vt.start()
                loop.exec_()
            else:
                self._on_version(self.version_info)
        except Exception as e:
            logger.error(f"更新线程异常: {e}")
            update_status.set(True, "更新失败")
            self.status_signal.emit(True, "更新失败")
            self.finish_signal.emit(False, str(e), {})

    def _on_version(self, version):
        try:
            channel = int(config_center.read_conf("Version", "version_channel"))
            server_version = version['version_release' if channel == 0 else 'version_beta']
            local_version = config_center.read_conf("Version", "version")
            logger.debug(f"服务端版本: {server_version}，本地版本: {local_version}")
            
            # 存储版本信息用于后续处理
            self.version_data = {
                "channel": channel,
                "server_version": server_version,
                "local_version": local_version
            }
            
            if Version(server_version) <= Version(local_version):
                logger.info("暂无新版本可用")
                update_status.set(True, "暂无新版本可用")
                self.status_signal.emit(True, "暂无新版本可用")
                self.finish_signal.emit(True, "无需更新", self.version_data)
                return

            release_info = version["releases" if channel == 0 else "releases_beta"]
            system = platform.system()
            if system == "Windows":
                system = "x64" if platform.architecture()[0] == "64bit" else "x86"
            elif system == "Darwin":
                system = "macOS"
                
            if system not in release_info:
                logger.info("无可用更新包")
                update_status.set(True, "无可用更新包")
                self.status_signal.emit(True, "无可用更新包")
                self.finish_signal.emit(False, "无可用更新包", self.version_data)
                return

            release_to_upgrade = release_info[system]
            download_url = release_to_upgrade["url"]
            files_to_keep = release_to_upgrade.get("files_to_keep", [])
            base_dir = release_to_upgrade.get("base_dir","")
            executable_name = release_to_upgrade.get("executable", "")
            
            # 存储完整的发布信息
            self.version_data.update({
                "release_info": release_to_upgrade,
                "files_to_keep": files_to_keep,
                "executable_name": executable_name,
                "pack_basedir": base_dir,
                "system": system
            })
            
            self.status_signal.emit(False, "下载更新包中...")
            update_status.set(False,"正在更新")
            
            try:
                r = requests.get(download_url, stream=True)
                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                zip_path = os.path.join(os.getcwd(), "updpack.zip")
                
                with open(zip_path, 'wb') as f:
                    downloaded = 0
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = int(downloaded / total * 100) if total else 0
                        self.progress_signal.emit(percent)
                
                self.status_signal.emit(False, "解压更新包...")
                
                temp_path = os.path.join(os.getcwd(), "temp")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_path)
                os.rename(os.path.join(temp_path,base_dir),os.path.join(temp_path,"updpackage"))
                shutil.copytree(os.path.join(temp_path,"updpackage"), os.path.join(os.getcwd(),"updpackage"),dirs_exist_ok=True)
                shutil.rmtree(temp_path)
                updpackage_path = os.path.join(os.getcwd(), "updpackage")
                # 写入 update.json，设置 stage=0
                update_json_path = os.path.join(os.getcwd(), "update.json")
                update_data = {
                    "version": server_version,
                    "channel": channel,
                    "download_url": download_url,
                    "updpackage_path": updpackage_path,
                    "timestamp": time.time(),
                    "executable": sys.executable,  # 主程序路径
                    "files_to_keep": files_to_keep,
                    "executable_name": executable_name,
                    "stage": 0  # 添加 stage 字段
                }
                
                with open(update_json_path, "w", encoding="utf-8") as f:
                    json.dump(update_data, f, ensure_ascii=False, indent=2)
                
                # 删除下载的zip文件
                os.remove(zip_path)
                
            except Exception as e:
                logger.error(f"下载或解压失败: {e}")
                self.status_signal.emit(True, "下载或解压失败")
                self.finish_signal.emit(False, str(e), self.version_data)
                update_status.set(False,"更新错误")
                return

            self.status_signal.emit(True, "下载完成")
            update_status.set(False,"重启应用\n完成更新")
            self.finish_signal.emit(True, "下载完成", self.version_data)
            
        except Exception as e:
            logger.error(f"版本处理异常: {e}")
            self.status_signal.emit(True, "更新失败")
            self.finish_signal.emit(False, str(e), self.version_data)
            update_status.set("更新失败")

class AutomaticUpdateThread(QThread):
    """
    自动更新线程，定时检查更新
    """
    def __init__(self,onstart=False, parent=None,version_info=None):
        super().__init__(parent)
        self.onstart = onstart
        self.version_info = version_info

    def run(self):
        try:
            silent_update_check(onstart=self.onstart, version_info=self.version_info)
        except Exception as e:
            logger.error(f"自动更新异常: {e}")

def silent_update_check(onstart=False,version_info=None):
    try:
        auto_check = config_center.read_conf('Version', 'auto_upgrade', '1')
        if auto_check != '1' and onstart == True:
            logger.info("未开启自动更新")
            return
            
        logger.debug("开始更新")
        
        from network_thread import VersionThread

        thread_holder = {}
        def on_version(version):
            thread = UnifiedUpdateThread(version_info=version, silent=True)
            thread_holder['thread'] = thread
            logger.debug("下载中")
            def finish_and_quit(ok, msg, version_data):
                if ok and msg == "下载完成":
                    # 下载成功后发送托盘通知
                    if version_data and "server_version" in version_data:
                        server_version = version_data["server_version"]
                        utils.tray_icon.push_update_notification(
                            f"新版本 {server_version} 的更新已经准备好，重启应用即可自动更新。"
                        )
                        logger.info(f"新版本 {server_version} 的更新已经准备好，重启应用即可自动更新。")
                loop.quit()
            
            thread.finish_signal.connect(finish_and_quit)
            thread.start()
        if not version_info:

            vt = VersionThread()
            loop = QEventLoop()
            vt.version_signal.connect(on_version)
            vt.start()
            loop.exec_()
        else:
            on_version(version_info)
        # 等待线程结束
        thread = thread_holder.get('thread')
        if thread and thread.isRunning():
            thread.wait()
            
    
    except Exception as e:
        logger.error(f"更新异常: {e}")

class Updater(QThread):
    """
    更新执行线程，负责备份、替换文件和重启应用
    包含原始版本的回滚机制
    """
    update_signal = pyqtSignal(list)
    finish_signal = pyqtSignal()
    
    def __init__(self, source_dir, files_to_keep=None, executable="", parent=None):
        super().__init__(parent)
        self.source_dir = source_dir
        self.files_to_keep = files_to_keep or []
        self.executable = executable
        self.stage = 1  # 更新阶段标识

    def backup(self):
        """备份除特定目录外的所有文件和文件夹"""
        # 确保备份目录存在
        backup_dir = os.path.join(self.source_dir, "backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        # 获取需要备份的文件列表
        exclude_dirs = {"backup", "updpackage", ".git"}
        files_to_backup = [
            f for f in os.listdir(self.source_dir) 
            if f not in exclude_dirs and not f.startswith(".")
        ]
        
        total = len(files_to_backup)
        progress = 0
        
        for file in files_to_backup:
            progress += 1
            src_path = os.path.join(self.source_dir, file)
            dst_path = os.path.join(backup_dir, file)
            
            try:
                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)
                
                logger.info(f"已备份: {file}")
            except Exception as e:
                logger.error(f"备份失败: {file}, {e}")
            
            percent = int(progress / total * 50)
            self.update_signal.emit([f"备份中 {progress}/{total} {file}", percent])
    
    def remove_old_files(self):
        """删除旧文件"""
        exclude_dirs = {"backup", "updpackage", ".git"}
        files_to_remove = [
            f for f in os.listdir(self.source_dir) 
            if f not in exclude_dirs and not f.startswith(".")
        ]
        
        total = len(files_to_remove)
        progress = 0
        
        for file in files_to_remove:
            progress += 1
            file_path = os.path.join(self.source_dir, file)
            
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
                else:
                    os.remove(file_path)
                logger.info(f"已删除: {file}")
            except Exception as e:
                logger.error(f"删除失败: {file}, {e}")
            
            percent = 50 + int(progress / total * 25)
            self.update_signal.emit([f"删除旧文件 {progress}/{total} {file}", percent])
    
    def copy_new_files(self):
        """从更新包复制新文件"""
        updpackage_dir = os.path.join(self.source_dir, "updpackage")
        if not os.path.exists(updpackage_dir):
            raise FileNotFoundError("更新包目录不存在")
        
        files_to_copy = [
            f for f in os.listdir(updpackage_dir) 
            if f not in {".git"} and not f.startswith(".")
        ]
        
        total = len(files_to_copy)
        progress = 0
        
        for file in files_to_copy:
            progress += 1
            src_path = os.path.join(updpackage_dir, file)
            dst_path = os.path.join(self.source_dir, file)
            
            try:
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_path, dst_path)
                logger.info(f"已更新: {file}")
            except Exception as e:
                logger.error(f"更新失败: {file}, {e}")
            
            percent = 75 + int(progress / total * 20)
            self.update_signal.emit([f"复制新文件 {progress}/{total} {file}", percent])
    
    def restore_configs(self):
        """恢复需要保留的配置文件"""
        backup_dir = os.path.join(self.source_dir, "backup")
        total = len(self.files_to_keep)
        
        if not total:
            self.update_signal.emit(["恢复配置 0/0 无配置需要保留", 95])
            return
            
        progress = 0
        
        for file in self.files_to_keep:
            progress += 1
            src_path = os.path.join(backup_dir, file)
            dst_path = os.path.join(self.source_dir, file)
            
            try:
                if os.path.exists(src_path):
                    if os.path.isdir(src_path):
                        shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_path, dst_path)
                    logger.info(f"已恢复配置: {file}")
                else:
                    logger.warning(f"配置不存在: {file}")
            except Exception as e:
                logger.error(f"恢复配置失败: {file}, {e}")
            
            percent = 95 + int(progress / total * 5)
            self.update_signal.emit([f"恢复配置 {progress}/{total} {file}", percent])
    
    def rollback(self):
        """更新失败时回滚到备份版本"""
        backup_dir = os.path.join(self.source_dir, "backup")
        if not os.path.exists(backup_dir):
            logger.error("回滚失败: 备份目录不存在")
            return False
        
        # 删除当前所有文件（保留备份和更新包）
        files_to_remove = [
            f for f in os.listdir(self.source_dir) 
            if f not in {"backup", "updpackage"} and not f.startswith(".")
        ]
        
        for file in files_to_remove:
            file_path = os.path.join(self.source_dir, file)
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
                else:
                    os.remove(file_path)
            except Exception:
                pass
        
        # 从备份恢复所有文件
        for file in os.listdir(backup_dir):
            src_path = os.path.join(backup_dir, file)
            dst_path = os.path.join(self.source_dir, file)
            
            try:
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)
            except Exception:
                pass
        
        logger.info("回滚完成")
        return True
    
    def run(self):
        """执行更新流程"""
        try:
            # 读取update.json获取参数
            update_json_path = os.path.join(self.source_dir, "update.json")
            if not os.path.exists(update_json_path):
                raise FileNotFoundError("未找到update.json")
            
            with open(update_json_path, "r", encoding="utf-8") as f:
                update_data = json.load(f)
            
            # 优先使用update.json中的参数
            self.files_to_keep = update_data.get("files_to_keep", self.files_to_keep)
            self.executable = update_data.get("executable", self.executable)
            stage = update_data.get("stage", 0)
            
            if stage == 2:
                # 阶段2：执行文件替换
                logger.info("执行文件替换操作")
                
                # 执行更新步骤
                self.stage = 1
                self.backup()
                
                self.stage = 2
                self.remove_old_files()
                
                self.stage = 3
                self.copy_new_files()
                
                self.stage = 4
                self.restore_configs()
                
                # 更新stage为3
                update_data["stage"] = 3
                with open(update_json_path, "w", encoding="utf-8") as f:
                    json.dump(update_data, f, ensure_ascii=False, indent=2)
                
                # 启动父目录中的新程序
                executable_name = update_data.get("executable_name", "").lstrip('/')
                new_executable = os.path.join(self.source_dir, executable_name)
                
                # 确保文件存在
                if not os.path.exists(new_executable):
                    raise FileNotFoundError(f"未找到新程序: {new_executable}")
                
                # 设置执行权限（Linux/Mac）
                if platform.system() != "Windows":
                    os.chmod(new_executable, 0o755)
                
                # 启动新程序
                subprocess.Popen([new_executable])
                
                # 退出当前程序
                self.finish_signal.emit()
                return
                
                # 重启应用
                if self.executable and os.path.exists(self.executable):
                    os.execv(self.executable, [self.executable])
                else:
                    logger.error("无法重启: 可执行文件不存在")
        
        except Exception as e:
            logger.error(f"更新失败: {e}")
            logger.error(traceback.format_exc())
            
            # 根据阶段执行回滚
            if self.stage >= 2:  # 如果在删除旧文件阶段或之后失败
                self.update_signal.emit(["更新失败，正在回滚...", 100])
                if self.rollback():
                    self.update_signal.emit(["已回滚到之前版本", 100])
                else:
                    self.update_signal.emit(["回滚失败，请手动恢复", 100])
            else:
                self.update_signal.emit(["更新失败", 100])
            
            # 清理临时文件
            try:
                updpackage_dir = os.path.join(self.source_dir, "updpackage")
                if os.path.exists(updpackage_dir):
                    shutil.rmtree(updpackage_dir, ignore_errors=True)
                
                update_json_path = os.path.join(self.source_dir, "update.json")
                if os.path.exists(update_json_path):
                    os.remove(update_json_path)
            except Exception:
                pass
            
            time.sleep(3)
            self.finish_signal.emit()

class UpgradeProgressWindow(FluentWindow):
    """更新进度窗口"""
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.upgradeui = loadUi("./view/upgrade_progress.ui")
        self.addSubInterface(self.upgradeui, FluentIcon.SYNC, "更新")
        self.resize(800, 100)
        self.setWindowIcon(QIcon("./img/logo/favicon-update.png"))
        self.setWindowTitle("更新中")
        self.upgradeprograsslabel = self.findChild(CaptionLabel, "updprogresslabel")
        self.prograssbar = self.findChild(ProgressBar, "progressBar")
        
    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.do_upgrade()
            
    def do_upgrade(self):
        self.worker.update_signal.connect(self.update_status)
        self.worker.finish_signal.connect(self.finish)
        self.worker.start()
        
    def update_status(self, message):
        self.upgradeprograsslabel.setText(message[0])
        self.prograssbar.setValue(message[1])
        
    def finish(self):
        self.close()
        
    def closeEvent(self, event):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        super().closeEvent(event)

def start_update_process():
    """启动更新二阶段（文件替换）"""
    # 创建更新器
    updater = Updater(
        source_dir=os.getcwd(),
        executable=sys.executable
    )
    
    # 创建并显示进度窗口
    app = QApplication.instance() or QApplication(sys.argv)
    window = UpgradeProgressWindow(worker=updater)
    window.show()
    
    # 如果是独立的更新进程，启动事件循环
    if not QApplication.instance():
        app.exec_()

def post_upgrade():
    """更新后清理"""
    try:
        shutil.rmtree("updpackage", ignore_errors=True)
        shutil.rmtree("backup", ignore_errors=True)
        
        update_json_path = os.path.join(os.getcwd(), "update.json")
        if os.path.exists(update_json_path):
            os.remove(update_json_path)
    except Exception as e:
        logger.error(f"清理失败: {e}")

def handle_update_args():
    """
    处理更新相关的参数和状态
    需要在main.py的主函数开始处调用
    """
    # 检查update.json是否存在
    update_json_path = os.path.join(os.getcwd(), "update.json")
    if not os.path.exists(update_json_path):
        return False
    
    try:
        with open(update_json_path, "r", encoding="utf-8") as f:
            update_data = json.load(f)
        
        stage = update_data.get("stage", 0)
        
        if stage == 0:
            # 阶段1：准备调用updpackage中的程序
            logger.info("进入更新阶段1：准备调用updpackage程序")
            
            # 更新stage为2
            update_data["stage"] = 2
            with open(update_json_path, "w", encoding="utf-8") as f:
                json.dump(update_data, f, ensure_ascii=False, indent=2)
            
            # 启动updpackage中的程序
            executable_name = update_data.get("executable_name", "").lstrip('/')
            updpackage_executable = os.path.join(os.getcwd(), "updpackage", executable_name)
            
            # 确保文件存在
            if not os.path.exists(updpackage_executable):
                raise FileNotFoundError(f"未找到更新程序: {updpackage_executable}")
            
            # 设置执行权限（Linux/Mac）
            if platform.system() != "Windows":
                os.chmod(updpackage_executable, 0o755)
            
            # 启动新程序
            subprocess.Popen([updpackage_executable])
            
            # 退出当前程序
            return True
            
        elif stage == 2:
            # 阶段2：updpackage中的程序执行更新
            logger.info("进入更新阶段2：执行文件替换")
            
            # 从update.json中读取必要参数
            files_to_keep = update_data.get("files_to_keep", [])
            executable = update_data.get("executable", sys.executable)
            
            # 创建并显示更新窗口
            app = QApplication(sys.argv)
            # 将参数传递给Updater
            upd = Updater(
                source_dir=os.getcwd(),
                files_to_keep=files_to_keep,
                executable=executable
            )
            progress_window = UpgradeProgressWindow(upd)
            progress_window.show()
            
            app.exec_()
            return True
            
        elif stage == 3:
            # 阶段3：新程序清理updpackage
            logger.info("进入更新阶段3：清理updpackage")
            
            # 清理updpackage目录
            updpackage_dir = os.path.join(os.getcwd(), "updpackage")
            if os.path.exists(updpackage_dir):
                shutil.rmtree(updpackage_dir, ignore_errors=True)
                logger.info("已清理updpackage目录")
            
            # 删除update.json
            if os.path.exists(update_json_path):
                os.remove(update_json_path)
                logger.info("已删除update.json")
            
            return False
    
    except Exception as e:
        logger.error(f"更新流程处理异常: {e}")
        logger.error(traceback.format_exc())
        return False
