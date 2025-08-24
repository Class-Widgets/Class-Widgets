import os
import pathlib
import time
from threading import Lock
from typing import Dict, Optional, Tuple

import pygame
import pygame.mixer
from loguru import logger
from PyQt5.QtCore import QThread, pyqtSignal

from basic_dirs import CW_HOME
import conf
from file import config_center


class AudioManager:
    """音频管理"""
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.sound_cache: Dict[str, pygame.mixer.Sound] = {}
        self.mixer_initialized = False
        self.mixer_failed = False
        self.cache_lock = Lock()
        self.mixer_lock = Lock()

    def _ensure_mixer_initialized(self) -> bool:
        """初始化pygame mixer"""
        if self.mixer_initialized and pygame.mixer.get_init():
            return True
        if self.mixer_failed:
            return False

        with self.mixer_lock:
            if self.mixer_initialized and pygame.mixer.get_init():
                return True
            if self.mixer_failed:
                return False
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
                self.mixer_initialized = True
                return True
            except pygame.error:
                try:
                    pygame.mixer.init(
                        frequency=22050, size=-16, channels=1, buffer=1024
                    )
                    self.mixer_initialized = True
                    logger.info("Pygame mixer 兼容模式初始化成功")
                    return True
                except pygame.error as e:
                    logger.error(f"Pygame mixer 初始化失败: {e}")
                    self.mixer_initialized = False
                    self.mixer_failed = True  # 标记失败
                    return False

    def _validate_audio_file(self, file_path: str) -> Tuple[bool, str]:
        if not os.path.exists(file_path):
            return False, f"音频文件不存在: {file_path}"
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            start_time = time.time()
            while time.time() - start_time < 4:
                file_size = os.path.getsize(file_path)
                if file_size > 0:
                    break
                time.sleep(0.1)
            else:
                return False, f"音频文件写入超时或为空: {file_path}"
        if file_size < 10:
            return False, (
                f"音频文件可能无效或不完整，"
                f"大小仅为 {file_size} 字节: {file_path}"
            )
        return True, file_path

    def _get_or_load_sound(self, file_path: str) -> Optional[pygame.mixer.Sound]:
        """加载内存音频"""
        is_cache_file = 'cache' in pathlib.Path(file_path).parts
        if not is_cache_file:
            with self.cache_lock:
                if file_path in self.sound_cache:
                    relative_path = str(pathlib.Path(file_path).relative_to(CW_HOME))
                    logger.debug(f'使用缓存音频: {relative_path}')
                    return self.sound_cache[file_path]
        try:
            sound = pygame.mixer.Sound(file_path)
            if not is_cache_file:
                with self.cache_lock:
                    self.sound_cache[file_path] = sound
            return sound
        except pygame.error as e:
            relative_path = str(pathlib.Path(file_path).relative_to(CW_HOME))
            logger.error(
                f"加载音频文件失败: {relative_path} | 错误: {e}"
            )
            return None

    def _get_volume(self, volume: Optional[float]) -> float:
        """计算音量"""
        if volume is not None:
            return max(0.0, min(1.0, volume))
        return int(config_center.read_conf('Audio', 'volume')) / 100

    def play_audio(self,
                   file_path: str,
                   volume: Optional[float] = None,
                   blocking: bool = True) -> bool:
        """播放音频文件

        Args:
            file_path: 音频文件路径
            volume: 音量 (0.0-1.0)，None时使用配置文件设置
            blocking: 是否阻塞等待播放完成

        Returns:
            bool: 播放是否成功启动
        """
        if not self._ensure_mixer_initialized():
            return False
        is_valid, relative_path = self._validate_audio_file(file_path)
        if not is_valid:
            logger.error(relative_path)
            return False
        sound = self._get_or_load_sound(file_path)
        if not sound:
            return False
        try:
            final_volume = self._get_volume(volume)
            sound.set_volume(final_volume)
            channel = sound.play()
            if not channel:
                logger.error(f"无法获取播放通道: {relative_path}")
                return False
            channel.set_volume(final_volume)
            if blocking:
                while channel.get_busy():
                    pygame.time.wait(100)

            logger.debug(f'成功播放音频: {relative_path} (是否阻塞: {blocking})')
            return True
        except (pygame.error, OSError) as e:
            logger.error(
                f'音频播放失败: {relative_path} | 错误: {e}'
            )
            return False

    def is_playing(self) -> bool:
        """检查是否有音频正在播放

        Returns:
            bool: 如果有音频正在播放返回True,反之返回False
        """
        return pygame.mixer.get_busy() if self.mixer_initialized else False

    def stop_all(self) -> None:
        """停止播放的音频"""
        if self.mixer_initialized:
            pygame.mixer.stop()

    def clear_cache(self) -> None:
        """清空音频缓存"""
        with self.cache_lock:
            self.sound_cache.clear()
            logger.debug("音频缓存已清空")

audio_manager = AudioManager()

class PlayAudio(QThread):
    """音频播放线程"""
    play_back_signal = pyqtSignal(bool)
    play_finished_signal = pyqtSignal(str, bool)  # (文件路径, 是否成功)

    def __init__(self,
                 file_path: str,
                 volume: Optional[float] = None,
                 cleanup_callback=None,
                 blocking: bool = True):
        super().__init__()
        self.file_path = file_path
        self.volume = volume
        self.cleanup_callback = cleanup_callback
        self.blocking = blocking

    def run(self) -> None:
        """线程播放音频"""
        success = audio_manager.play_audio(self.file_path, self.volume, self.blocking)
        if self.cleanup_callback:
            try:
                self.cleanup_callback(self.file_path, success)
            except Exception as e:
                logger.warning(f"清理回调执行失败: {e}")

        self.play_back_signal.emit(success)
        self.play_finished_signal.emit(self.file_path, success)

def _tts_cleanup_callback(file_path: str, success: bool) -> None:
    """TTS清理回调

    Args:
        file_path: 音频文件路径
        success: 是否成功
    """
    try:
        from generate_speech import on_audio_played
        on_audio_played(file_path)
    except ImportError:
        logger.warning("无法导入on_audio_played")

def play_audio(
    file_path: str,
    tts_delete_after: bool = False,
    volume: Optional[float] = None
) -> bool:
    """播放音频文件"""
    success = audio_manager.play_audio(file_path, volume, blocking=True)
    if tts_delete_after and success:
        _tts_cleanup_callback(file_path, success)

    return success

def play_audio_async(
    file_path: str,
    volume: Optional[float] = None,
    cleanup_callback=None
) -> PlayAudio:
    """异步播放音频文件

    Args:
        file_path: 音频文件路径
        volume: 音量 (0.0-1.0)
        cleanup_callback: 播放完成后的清理回调函数

    Returns:
        PlayAudio: 音频播放线程对象
    """
    thread = PlayAudio(file_path, volume, cleanup_callback, blocking=False)
    thread.start()
    return thread

def is_playing() -> bool:
    """检查音频播放

    Returns:
        bool: 音频播放返回True,反之返回False
    """
    return audio_manager.is_playing()

def stop_audio() -> None:
    """停止播放的音频"""
    audio_manager.stop_all()

def clear_audio_cache() -> None:
    """清空音频缓存"""
    audio_manager.clear_cache()

def reset_mixer() -> None:
    """重置mixer状态"""
    with audio_manager.mixer_lock:
        audio_manager.mixer_initialized = False
        audio_manager.mixer_failed = False
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        logger.info("Mixer状态已重置")
