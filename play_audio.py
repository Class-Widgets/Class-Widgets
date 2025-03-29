import os
import time
import platform
import threading

import pygame
import pygame.mixer
from PyQt5.QtCore import QThread, pyqtSignal
from loguru import logger

import conf
from file import config_center
from generate_speech import TTSEngine

system = platform.system()
if system == 'Windows':
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        WINDOWS_VOLUME_SUPPORT = True
    except ImportError:
        logger.warning("pycaw库不可用,灵动通知受限制")
        WINDOWS_VOLUME_SUPPORT = False
        config_center.write_conf('Toast', 'smooth_volume', '0')
elif system == 'Linux':
    try:
        import pulsectl
        LINUX_VOLUME_SUPPORT = True
    except ImportError:
        logger.warning("pulsectl库不可用,灵动通知受限制")
        LINUX_VOLUME_SUPPORT = False
        config_center.write_conf('Toast', 'smooth_volume', '0')
elif system == 'Darwin':  # macOS
    try:
        import subprocess
        MACOS_VOLUME_SUPPORT = True
        config_center.write_conf('Toast', 'smooth_volume', '0')
    except ImportError:
        logger.warning("subprocess模块不可用,灵动通知受限制")
        MACOS_VOLUME_SUPPORT = False
        config_center.write_conf('Toast', 'smooth_volume', '0')
else:
    logger.warning(f"不支持的操作系统: {system},灵动通知受限制")
    config_center.write_conf('Toast', 'smooth_volume', '0')
    WINDOWS_VOLUME_SUPPORT = False
    LINUX_VOLUME_SUPPORT = False
    MACOS_VOLUME_SUPPORT = False

# 初始化pygame混音器 - 使用最小缓冲区以减少延迟
pygame.mixer.pre_init(44100, -16, 2, 16)
pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=16)
# 忽略警告(一些莫名的警告)
import warnings
warnings.filterwarnings("ignore", message="COMError attempting to get property")
sound = None
audio_cache = {} # 音频缓存

# 预加载常用音频文件
def preload_audio_files():
    try:
        from file import base_directory
        audio_files = {
            'attend_class': os.path.join(base_directory, 'audio', config_center.read_conf('Audio', 'attend_class')),
            'finish_class': os.path.join(base_directory, 'audio', config_center.read_conf('Audio', 'finish_class')),
            'prepare_class': os.path.join(base_directory, 'audio', config_center.read_conf('Audio', 'prepare_class'))
        }
        
        for key, file_path in audio_files.items():
            if os.path.exists(file_path):
                audio_cache[key] = pygame.mixer.Sound(file_path)
                logger.debug(f'成功预加载音频文件: {key}')
    except Exception as e:
        logger.error(f'预加载音频文件失败: {e}')

# 应用启动时预加载音频
try:
    preload_audio_files()
except Exception as e:
    logger.error(f'初始化预加载音频失败: {e}')

# 音量控制器
class VolumeController:
    def __init__(self):
        self.original_volumes = {}
        self.system = platform.system()
        self.is_supported = False
        # Windows平台
        if self.system == 'Windows' and WINDOWS_VOLUME_SUPPORT:
            try:
                self.devices = AudioUtilities.GetAllDevices()
                self.sessions = [s for s in AudioUtilities.GetAllSessions() if s.Process]
                self.is_supported = True
            except Exception as e:
                logger.error(f"Windows音量控制初始化失败: {e}")
        # Linux
        elif self.system == 'Linux' and LINUX_VOLUME_SUPPORT:
            try:
                self.pulse = pulsectl.Pulse('class-widgets-volume-control')
                self.is_supported = True
            except Exception as e:
                logger.error(f"Linux音量控制初始化失败: {e}")
        # macos
        elif self.system == 'Darwin' and MACOS_VOLUME_SUPPORT:
            self.is_supported = True
    
    def is_any_app_playing_audio(self):
        """检测是否有应用正在播放音频"""
        if not self.is_supported:
            return False
            
        try:
            # Windows
            if self.system == 'Windows':
                try:
                    self.sessions = [s for s in AudioUtilities.GetAllSessions() if s.Process]
                    for session in self.sessions:
                        if session.Process and session.Process.name() != "python.exe" and session.Process.name() != "pythonw.exe":
                            try:
                                volume = session.SimpleAudioVolume
                                if volume and volume.GetMasterVolume() > 0 and session.State == 1:    # 1:正在播放音频
                                    return True
                            except Exception:
                                # 忽略,不log会爆
                                continue
                except Exception as e:
                    logger.debug(f"获取音频会话列表失败: {e}")
                    return False
            # 此处简单判断:有程序运行就认为有播放音频
            # Linux
            elif self.system == 'Linux':
                sink_inputs = self.pulse.sink_input_list()
                for sink in sink_inputs:
                    app_name = sink.proplist.get('application.name', '')
                    if app_name and 'python' not in app_name.lower():
                        return True
            # macos
            elif self.system == 'Darwin':
                return True
                
            return False
        except Exception as e:
            logger.error(f"检测应用播放状态失败: {e}")
            return False
    
    def lower_other_apps_volume(self, target_ratio=0.1, duration=0.2):
        """平滑降低音量"""
        if not self.is_supported or config_center.read_conf('Toast', 'smooth_volume') != '1':
            return
        if not self.is_any_app_playing_audio():
            return
        
        try:
            # Windows
            if self.system == 'Windows':
                for session in self.sessions:
                    if session.Process and session.Process.name() != "python.exe" and session.Process.name() != "pythonw.exe":
                        volume = session.SimpleAudioVolume if hasattr(session, "SimpleAudioVolume") else None
                        if volume:
                            current_vol = volume.GetMasterVolume()
                            self.original_volumes[session.Process.name()] = current_vol
                            # 平滑降低
                            self._smooth_volume_change(volume, current_vol, 
                                                     current_vol * target_ratio, duration)
            # Linux
            elif self.system == 'Linux':
                sink_inputs = self.pulse.sink_input_list()
                for sink in sink_inputs:
                    app_name = sink.proplist.get('application.name', '')
                    if app_name and 'python' not in app_name.lower():
                        self.original_volumes[sink.index] = sink.volume.value_flat
                        
                        # 平滑降低
                        steps = int(duration * 10)
                        original_vol = sink.volume.value_flat
                        target_vol = original_vol * target_ratio
                        for i in range(1, steps + 1):
                            current_vol = original_vol - (original_vol - target_vol) * (i / steps)
                            self.pulse.volume_set_all_chans(sink, current_vol)
                            time.sleep(duration / steps)
            
            # Macos
            elif self.system == 'Darwin':
                result = subprocess.run(['osascript', '-e', 'tell application "System Events" to get name of every application process whose background only is false'], 
                                        capture_output=True, text=True)
                apps = result.stdout.strip().split(', ')
                
                for app in apps:
                    if app and 'python' not in app.lower():
                        vol_cmd = f'tell application "System Events" to tell application process "{app}" to get volume'
                        result = subprocess.run(['osascript', '-e', vol_cmd], capture_output=True, text=True)
                        try:
                            current_vol = float(result.stdout.strip())
                            self.original_volumes[app] = current_vol
                            # 平滑降低
                            steps = int(duration * 10)
                            target_vol = current_vol * target_ratio
                            for i in range(1, steps + 1):
                                new_vol = current_vol - (current_vol - target_vol) * (i / steps)
                                vol_set_cmd = f'tell application "System Events" to tell application process "{app}" to set volume to {new_vol}'
                                subprocess.run(['osascript', '-e', vol_set_cmd], capture_output=True)
                                time.sleep(duration / steps)
                        except ValueError:
                            continue
                            
        except Exception as e:
            logger.error(f"降低其他应用音量失败: {e}")
    
    def restore_other_apps_volume(self, duration=0.5):
        """平滑恢复音量"""
        if not self.is_supported or config_center.read_conf('Toast', 'smooth_volume') != '1':
            return
        try:
            # Windows
            if self.system == 'Windows':
                for session in self.sessions:
                    if session.Process and session.Process.name() in self.original_volumes:
                        volume = session.SimpleAudioVolume
                        current_vol = volume.GetMasterVolume()
                        original_vol = self.original_volumes[session.Process.name()]
                        self._smooth_volume_change(volume, current_vol, original_vol, duration)
            # Linux
            elif self.system == 'Linux':
                sink_inputs = self.pulse.sink_input_list()
                for sink in sink_inputs:
                    if sink.index in self.original_volumes:
                        current_vol = sink.volume.value_flat
                        original_vol = self.original_volumes[sink.index]
                        # 平滑恢复
                        steps = int(duration * 10)
                        for i in range(1, steps + 1):
                            new_vol = current_vol + (original_vol - current_vol) * (i / steps)
                            self.pulse.volume_set_all_chans(sink, new_vol)
                            time.sleep(duration / steps)
                self.pulse.close()
            # Macos
            elif self.system == 'Darwin':
                for app, original_vol in self.original_volumes.items():
                    vol_cmd = f'tell application "System Events" to tell application process "{app}" to get volume'
                    result = subprocess.run(['osascript', '-e', vol_cmd], capture_output=True, text=True)
                    try:
                        current_vol = float(result.stdout.strip())
                        # 平滑恢复
                        steps = int(duration * 10)
                        for i in range(1, steps + 1):
                            new_vol = current_vol + (original_vol - current_vol) * (i / steps)
                            vol_set_cmd = f'tell application "System Events" to tell application process "{app}" to set volume to {new_vol}'
                            subprocess.run(['osascript', '-e', vol_set_cmd], capture_output=True)
                            time.sleep(duration / steps)
                    except ValueError:
                        continue
            self.original_volumes = {}
        except Exception as e:
            logger.error(f"恢复其他应用音量失败: {e}")
    
    def _smooth_volume_change(self, volume_obj, start_vol, end_vol, duration):
        """Windows:平滑修改音量"""
        steps = max(3, int(duration * 8))
        for i in range(1, steps + 1):
            current_vol = start_vol + (end_vol - start_vol) * (i / steps)
            volume_obj.SetMasterVolume(current_vol, None)
            time.sleep(duration / steps / 2 if i < steps else 0)


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
    volume_controller = None
    volume_adjusted = False
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"音频文件不存在: {file_path}")

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=128)

        # 检查文件是否可读
        if os.path.getsize(file_path) <= 0:
            start_time = time.time()
            while time.time() - start_time < 4:
                if os.path.getsize(file_path) > 0:
                    break
                time.sleep(0.1)
            else:
                raise IOError("音频文件写入超时")

        sound = pygame.mixer.Sound(file_path)
        volume = int(config_center.read_conf('Audio', 'volume')) / 100
        sound.set_volume(volume)  # 设置Sound对象的音量
        if config_center.read_conf('Toast', 'smooth_volume') == '1':
            try:
                volume_controller = VolumeController()
                if volume_controller.is_any_app_playing_audio():
                    volume_controller.lower_other_apps_volume(0.2, 0.2)
                    volume_adjusted = True
            except Exception as e:
                logger.error(f"降低音量失败: {e}")

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
        if volume_controller and config_center.read_conf('Toast', 'smooth_volume') == '1':
            try:
                if volume_adjusted:
                    threading.Thread(target=volume_controller.restore_other_apps_volume,args=(0.3,), daemon=True).start() # 给一些恢复时间
            except Exception as e:
                logger.error(f"恢复音量失败: {e}")
            # 确保释放音频资源
            if 'sound' in locals():
                sound.stop()
            pygame.mixer.quit()
