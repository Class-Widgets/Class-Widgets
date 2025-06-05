import os
import time
import pathlib

import pygame
import pygame.mixer # Explicit import for mixer
from PyQt5.QtCore import QThread, pyqtSignal, QObject # Added QObject
from loguru import logger
from typing import Dict, Optional # Added for type hints

import conf
from file import config_center
# Assuming on_audio_played is correctly defined elsewhere and handles file cleanup
from generate_speech import TTSEngine, on_audio_played

# sound_cache stores pygame.mixer.Sound objects, keyed by file path
sound_cache: Dict[str, pygame.mixer.Sound] = {}


class PlayAudio(QThread):
    play_back_signal = pyqtSignal(bool)

    def __init__(self, file_path: str, tts_delete_after: bool = False, parent: Optional[QObject] = None) -> None: # Added parent and return type
        super().__init__(parent)
        self.file_path: str = file_path
        self.tts_delete_after: bool = tts_delete_after

    def run(self) -> None: # Added return type
        play_audio(self.file_path, self.tts_delete_after)
        self.play_back_signal.emit(True)


def play_audio(file_path: str, tts_delete_after: bool = False) -> None: # Added return type
    sound: Optional[pygame.mixer.Sound] = None
    channel: Optional[pygame.mixer.Channel] = None
    # conf.base_directory is Path
    relative_path: str = os.path.relpath(file_path, str(conf.base_directory)) # type: ignore[attr-defined]

    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"音频文件不存在: {relative_path}")

        if not pygame.mixer.get_init():
            try:
                pygame.mixer.quit() # Quit any previous initialization
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            except pygame.error:
                logger.warning("标准 Mixer 初始化失败，尝试兼容模式...")
                try:
                    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)
                    logger.info("使用兼容设置成功初始化 Mixer")
                except pygame.error as e_fallback:
                    logger.error(f"Pygame mixer 初始化失败: {e_fallback}")
                    return

        # 检查文件是否可读和大小
        file_size: int = os.path.getsize(file_path)
        if file_size == 0: # File might still be writing
            start_time: float = time.time()
            while time.time() - start_time < 4: # Wait up to 4 seconds
                if os.path.getsize(file_path) > 0:
                    break
                time.sleep(0.1)
            else: # If loop finishes and size is still 0
                logger.error(f"音频文件写入超时或为空: {relative_path}")
                if tts_delete_after:
                    on_audio_played(file_path) # type: ignore[no-untyped-call]
                return

        file_size = os.path.getsize(file_path) # Re-check size
        if file_size < 10: # Arbitrary small size check
            logger.warning(f"音频文件可能无效或不完整，大小仅为 {file_size} 字节: {relative_path}")
            if tts_delete_after:
                on_audio_played(file_path) # type: ignore[no-untyped-call]
            return

        try:
            is_in_cache_dir: bool = 'cache' in pathlib.Path(file_path).parts
            if not is_in_cache_dir and file_path in sound_cache:
                sound = sound_cache[file_path]
                logger.debug(f'调用缓存音频: {relative_path}')
            else:
                sound = pygame.mixer.Sound(file_path)
                if not is_in_cache_dir: # Only cache non-cache directory sounds
                    sound_cache[file_path] = sound
        except pygame.error as e_load:
            logger.error(f"加载音频文件失败: {relative_path} | 错误: {e_load}")
            if tts_delete_after:
                on_audio_played(file_path) # type: ignore[no-untyped-call]
            return

        volume_conf: Optional[str] = config_center.read_conf('Audio', 'volume') # type: ignore[no-untyped-call]
        volume_float: float = int(volume_conf) / 100.0 if volume_conf and volume_conf.isdigit() else 1.0 # Default to 1.0

        sound.set_volume(volume_float)
        channel = sound.play()

        if channel:
            # channel.set_volume(volume_float) # Volume is already set on sound object
            while channel.get_busy():
                pygame.time.wait(100) # milliseconds
        else:
            logger.error(f"无法获取播放通道: {relative_path}")
            if tts_delete_after: # Still attempt cleanup
                on_audio_played(file_path) # type: ignore[no-untyped-call]
            return # Return early if channel is None

        logger.debug(f'成功播放音频: {relative_path}')
        if tts_delete_after:
            on_audio_played(file_path) # type: ignore[no-untyped-call]

    except FileNotFoundError as e:
        logger.error(f'音频文件未找到 | 路径: {relative_path} | 错误: {str(e)}')
    except IOError as e: # Catches more general I/O errors including permission issues
        logger.error(f'音频文件读取错误或超时 | 路径: {relative_path} | 错误: {str(e)}')
    except pygame.error as e: # Catch Pygame specific errors
        logger.error(f'Pygame 播放错误 | 路径: {relative_path} | 错误: {str(e)}')
    except Exception as e: # Catch-all for any other unexpected errors
        logger.error(f'未知播放失败 | 路径: {relative_path} | 错误: {str(e)}')
    finally:
        # Ensure resources are released if they were acquired
        if channel and channel.get_busy(): # Check if channel exists and is busy
            channel.stop()
        # Sound objects don't necessarily need to be explicitly stopped if played via channel,
        # but it doesn't hurt if done after channel is stopped.
        # if sound:
        #     sound.stop() # This might cut off sound abruptly if channel didn't finish.
        pass # No explicit sound.stop() needed if channel handled playback.