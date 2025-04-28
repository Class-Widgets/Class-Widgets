import os
import time

import pygame
import pygame.mixer
from PyQt5.QtCore import QThread, pyqtSignal
from loguru import logger

import conf
from file import config_center
from generate_speech import TTSEngine

sound_cache = {}


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
    # global sound # Removed global sound variable
    sound = None # Use local variable
    channel = None # Initialize channel
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"音频文件不存在: {file_path}")

        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            except pygame.error:
                logger.warning("标准 Mixer 初始化失败，尝试兼容模式...")
                try:
                    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)
                    logger.info("使用兼容设置成功初始化 Mixer")
                except pygame.error as e_fallback:
                    logger.error(f"Pygame mixer 初始化失败: {e_fallback}")
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

        try:
            if file_path in sound_cache:
                sound = sound_cache[file_path]
                logger.debug(f'使用缓存音频: {file_path}')
            else:
                sound = pygame.mixer.Sound(file_path)
                sound_cache[file_path] = sound
                logger.debug(f'缓存音频: {file_path}')
        except pygame.error as e_load:
            logger.error(f"加载音频文件失败: {file_path} | 错误: {e_load}")
            return

        volume = int(config_center.read_conf('Audio', 'volume')) / 100
        sound.set_volume(volume)  # 设置Sound对象的音量
        channel = sound.play()
        if channel:
            channel.set_volume(volume)  # 设置Channel对象的音量
            while channel.get_busy():
                pygame.time.wait(100)
        else:
            logger.error(f"无法获取播放通道: {file_path}")

        logger.debug(f'成功播放音频: {file_path}')

        if tts_delete_after:
            tts = TTSEngine()
            tts.delete_audio_file(file_path)

    except FileNotFoundError as e:
        logger.error(f'音频文件未找到 | 路径: {file_path} | 错误: {str(e)}')
    except IOError as e:
        logger.error(f'音频文件读取错误或超时 | 路径: {file_path} | 错误: {str(e)}')
    except pygame.error as e:
        logger.error(f'Pygame 播放错误 | 路径: {file_path} | 错误: {str(e)}')
    except Exception as e:
        logger.error(f'未知播放失败 | 路径: {file_path} | 错误: {str(e)}')
    finally:
        if channel:
             channel.stop()
        if sound:
            sound.stop()
