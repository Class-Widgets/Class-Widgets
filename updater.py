#import network_thread
import os
import shutil
import zipfile

class Updater:
    def __init__(self, source_dir, logger, files_to_keep):
        # 初始化，设置源目录、日志记录器和需要保留的文件列表
        self.source_dir = source_dir
        self.logger = logger
        self.files_to_keep = files_to_keep

    def backup(self):
        # 备份除 backup 和 updpackage 目录外的所有文件和文件夹
        files_to_backup = [dir for dir in os.listdir(self.source_dir) if dir != "backup" and dir != "updpackage"]
        shutil.rmtree(os.path.join(self.source_dir, "backup"), ignore_errors=True)  # 清空旧备份
        for file in files_to_backup:
            file_path = os.path.join(self.source_dir, file)
            if os.path.isdir(file_path):
                backup_path = os.path.join(self.source_dir, "backup", file)
                if not os.path.exists(backup_path):
                    shutil.copytree(file_path, backup_path)
                    self.logger.info(f"已备份 {file} -> {backup_path}")
            elif os.path.isfile(file_path):
                backup_path = os.path.join(self.source_dir, "backup", file)
                if not os.path.exists(backup_path):
                    shutil.copy2(file_path, backup_path)
                    self.logger.info(f"已备份 {file} -> {backup_path}")
        self.logger.info("备份完成")

    def update(self, executable):
        try:
            self.logger.info("更新开始")
            # 删除除 backup 和 updpackage 目录外的所有文件和文件夹
            files_to_remove = [dir for dir in os.listdir(self.source_dir) if dir != "backup" and dir != "updpackage"]
            for file in files_to_remove:
                file_path = os.path.join(self.source_dir, file)
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
                    self.logger.info(f"已删除目录 {file}")
                elif os.path.isfile(file_path):
                    os.remove(file_path)
                    self.logger.info(f"已删除文件 {file}")
            # 从 updpackage 目录复制新文件到源目录
            files_to_copy = [dir for dir in os.listdir(os.path.join(self.source_dir, "updpackage")) if dir != "backup"]
            for file in files_to_copy:
                src_path = os.path.join(self.source_dir, "updpackage", file)
                dst_path = os.path.join(self.source_dir, file)
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                    self.logger.info(f"已更新目录 {file} -> {dst_path}")
                elif os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
                    self.logger.info(f"已更新文件 {file} -> {dst_path}")
            # 复制需要保留的文件到 backup 目录
            for file in self.files_to_keep:
                shutil.copy(os.path.join(self.source_dir, file), os.path.join(self.source_dir, "backup", file))
            self.logger.info("更新完成")
            # 重启程序，传递 --finish-update 参数
            os.execv(executable, [executable, "--finish-update"])
        except:
            import sys
            logger.error("更新失败！")
            logger.error(' '.join(sys.exc_info()))
            # 更新失败时，清理已删除的文件和目录
            files_to_remove = [dir for dir in os.listdir(self.source_dir) if dir != "backup" and dir != "updpackage"]
            for file in files_to_remove:
                file_path = os.path.join(self.source_dir, file)
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
                    self.logger.info(f"已删除目录 {file}")
                elif os.path.isfile(file_path):
                    os.remove(file_path)
                    self.logger.info(f"已删除文件 {file}")
        else:
            # 更新成功后，删除备份目录
            shutil.rmtree(os.path.join(self.source_dir, "backup"))

    def extract_updpackage(self, packdir):
        # 解压更新包到 updpackage 目录
        self.logger.debug("开始解压")
        with zipfile.ZipFile(packdir, 'r') as zip_ref:
            zip_ref.extractall("updpackage")
        self.logger.debug("解压完成")

if __name__ == "__main__":
    from loguru import logger
    source_dir = "./"#测backup和update的时候../，测extract_updpackage用./
    # 实例化 Updater，注意这里缺少 files_to_keep 参数，需补充
    updater = Updater(source_dir, logger,[])
    updater.extract_updpackage("Class-Widgets.zip")
    updater.backup()
    updater.update("")
