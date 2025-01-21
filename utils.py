import os
import sys
from loguru import logger
from PyQt5.QtCore import QSharedMemory

share = QSharedMemory('ClassWidgets')


def restart():
    logger.debug('重启程序')
    share.detach()  # 释放共享内存
    os.execl(sys.executable, sys.executable, *sys.argv)
