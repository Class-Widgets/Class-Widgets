import os
import time

import pygame
import pygame.mixer
from PyQt5.QtCore import QThread, pyqtSignal
from loguru import logger

import conf
from file import config_center, base_directory
from generate_speech import TTSEngine

sound_cache = {}
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
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=128)
            except pygame.error as e:
                logger.error(f"Pygame mixer 初始化失败: {e}")
                return

        # 检查文件是否可读
        if os.path.getsize(file_path) <= 0:
            start_time = time.time()
            while time.time() - start_time < 4:
                if os.path.getsize(file_path) > 0:
                    break
                time.sleep(0.1)
            else:
                raise IOError("音频文件写入超时")

        if file_path in sound_cache:
            sound = sound_cache[file_path]
            logger.debug(f'使用缓存音频: {file_path}')
        else:
            sound = pygame.mixer.Sound(file_path)
            sound_cache[file_path] = sound
            logger.debug(f'缓存音频: {file_path}')

        volume = int(config_center.read_conf('Audio', 'volume')) / 100
        sound.set_volume(volume)  # 设置Sound对象的音量
        channel = sound.play()
        channel.set_volume(volume)  # 设置Channel对象的音量
        while channel.get_busy():
            pygame.time.wait(100)

        logger.debug(f'成功播放音频: {file_path}')

        if tts_delete_after:
            tts = TTSEngine()
            tts.delete_audio_file(file_path)

    except Exception as e:
        logger.error(f'播放失败 | 路径: {file_path} | 错误: {str(e)}')
    finally:
        if sound:
            sound.stop()
        if not pygame.mixer.music.get_busy():   #防止同时播放多个音频时异常中断
               pygame.mixer.quit()
