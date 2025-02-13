import os
import time

import pygame
import pygame.mixer
from PyQt5.QtCore import QThread, pyqtSignal
from loguru import logger

import conf
from file import config_center
from generate_speech import TTSEngine

# 初始化pygame混音器
pygame.mixer.init()
sound = None


class PlayAudio(QThread):
    play_back_signal = pyqtSignal(bool)

    def __init__(self, file_path: str, tts_delete_after: bool = False):
        super().__init__()
        self.file_path = file_path
        self.tts_delete_after = tts_delete_after

    def run(self):
        play_audio(self.file_path, self.tts_delete_after)
        self.play_back_signal.emit(True)


def play_audio(file_path: str, tts_delete_after: bool = False):
    global sound
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"音频文件不存在: {file_path}")

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)

        start_time = time.time()
        while time.time() - start_time < 5:
            if os.path.getsize(file_path) > 0:
                break
            time.sleep(0.1)
        else:
            raise IOError("音频文件写入超时")

        sound = pygame.mixer.Sound(file_path)
        volume = int(config_center.read_conf('Audio', 'volume')) / 100
        pygame.mixer.music.set_volume(volume)
        channel = sound.play()
        while channel.get_busy():
            pygame.time.wait(100)

        logger.debug(f'成功播放音频: {file_path}')

        if tts_delete_after:
            tts = TTSEngine()
            tts.delete_audio_file(file_path)

    except Exception as e:
        logger.error(f'播放失败 | 路径: {file_path} | 错误: {str(e)}')
    finally:
        # 确保释放音频资源
        if 'sound' in locals():
            sound.stop()
        pygame.mixer.quit()
