import asyncio
import builtins
import contextlib
import hashlib
import os
import platform
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import edge_tts
import pyttsx3
from loguru import logger
from PyQt5.QtCore import QCoreApplication, QObject, pyqtSignal

from basic_dirs import CACHE_HOME

_tts_playing = False
_tts_lock = threading.RLock()


class TTSEngine(Enum):
    """TTS 引擎"""

    EDGE = "edge"
    PYTTSX3 = "pyttsx3"


class TTSStatus(Enum):
    """TTS 任务状态"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TTSVoice:
    """TTS 语音信息"""

    id: str
    name: str
    language: str
    gender: str
    engine: TTSEngine
    locale: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.engine, str):
            self.engine = TTSEngine(self.engine)


@dataclass
class TTSTask:
    """TTS 任务"""

    id: str
    text: str
    engine: TTSEngine
    voice_id: Optional[str] = None
    filename: Optional[str] = None
    speed: float = 1.0
    timeout: float = 10.0
    auto_fallback: bool = True
    status: TTSStatus = TTSStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error_message: Optional[str] = None
    file_path: Optional[str] = None
    on_complete: Optional[Callable[[str], None]] = None
    on_error: Optional[Callable[[str], None]] = None

    def __post_init__(self):
        if isinstance(self.engine, str):
            self.engine = TTSEngine(self.engine)
        if isinstance(self.status, str):
            self.status = TTSStatus(self.status)


class TTSCache:
    """TTS 缓存管理器"""

    def __init__(self, cache_dir: str, max_size: int = 100):
        # 依旧缓存,,,,
        self.cache_dir = cache_dir
        self.max_size = max_size
        self._cache_info: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        os.makedirs(cache_dir, exist_ok=True)
        self._load_cache_info()

    def _load_cache_info(self) -> None:
        """加载缓存信息"""
        try:
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.mp3'):
                    file_path = os.path.join(self.cache_dir, filename)
                    stat = os.stat(file_path)
                    self._cache_info[filename] = {
                        'size': stat.st_size,
                        'created_at': stat.st_ctime,
                        'accessed_at': stat.st_atime,
                        'path': file_path,
                    }
        except Exception as e:
            logger.warning(f"加载缓存信息失败: {e}")

    def get_cache_key(
        self, text: str, engine: TTSEngine, voice_id: Optional[str], speed: float
    ) -> str:
        """生成缓存键"""
        content = f"{text}_{engine.value}_{voice_id or 'default'}_{speed}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def get_cached_file(self, cache_key: str) -> Optional[str]:
        """获取缓存文件路径"""
        with self._lock:
            filename = f"{cache_key}.mp3"
            if filename in self._cache_info:
                file_path = self._cache_info[filename]['path']
                if os.path.exists(file_path):
                    self._cache_info[filename]['accessed_at'] = time.time()
                    return file_path
                del self._cache_info[filename]
            return None

    def add_to_cache(self, cache_key: str, file_path: str) -> str:
        """添加文件到缓存"""
        with self._lock:
            filename = f"{cache_key}.mp3"
            cache_path = os.path.join(self.cache_dir, filename)

            try:
                if file_path != cache_path:
                    import shutil

                    shutil.copy2(file_path, cache_path)
                stat = os.stat(cache_path)
                self._cache_info[filename] = {
                    'size': stat.st_size,
                    'created_at': stat.st_ctime,
                    'accessed_at': time.time(),
                    'path': cache_path,
                }
                self._cleanup_if_needed()
                return cache_path
            except Exception as e:
                logger.error(f"添加缓存失败: {e}")
                return file_path

    def _cleanup_if_needed(self) -> None:
        """清理过期缓存"""
        # 欸这个有什么用()
        if len(self._cache_info) <= self.max_size:
            return
        sorted_files = sorted(self._cache_info.items(), key=lambda x: x[1]['accessed_at'])

        files_to_remove = len(self._cache_info) - self.max_size
        for filename, info in sorted_files[:files_to_remove]:
            try:
                if os.path.exists(info['path']):
                    os.remove(info['path'])
                del self._cache_info[filename]
                logger.debug(f"清理缓存文件: {filename}")
            except Exception as e:
                logger.warning(f"清理缓存文件失败 {filename}: {e}")

    def clear_cache(self) -> None:
        """清空所有缓存"""
        with self._lock:
            for filename, info in list(self._cache_info.items()):
                try:
                    if os.path.exists(info['path']):
                        os.remove(info['path'])
                except Exception as e:
                    logger.warning(f"删除缓存文件失败 {filename}: {e}")
            self._cache_info.clear()


class TTSVoiceProvider:
    """TTS 语音提供基类"""

    def __init__(self, engine: TTSEngine):
        self.engine = engine
        self._voices_cache: Optional[List[TTSVoice]] = None
        self._cache_time: Optional[float] = None
        self._cache_ttl = 300  # 5分钟缓存
        self._lock = threading.RLock()

    def get_voices(self, language_filter: Optional[str] = None) -> List[TTSVoice]:
        """获取语音列表"""
        with self._lock:
            # 检查缓存
            if (
                self._voices_cache is not None
                and self._cache_time is not None
                and time.time() - self._cache_time < self._cache_ttl
            ):
                return self._filter_voices(self._voices_cache, language_filter)
            voices = self._fetch_voices()
            self._voices_cache = voices
            self._cache_time = time.time()

            return self._filter_voices(voices, language_filter)

    def _fetch_voices(self) -> List[TTSVoice]:
        """获取语音列表的具体实现"""
        raise NotImplementedError

    def _filter_voices(
        self, voices: List[TTSVoice], language_filter: Optional[str]
    ) -> List[TTSVoice]:
        """筛选语音"""
        if not language_filter:
            return voices

        filtered = []
        for voice in voices:
            if voice.language.startswith(language_filter) or (
                voice.locale and voice.locale.startswith(language_filter)
            ):
                filtered.append(voice)

        return filtered

    def synthesize(self, text: str, voice_id: str, output_path: str, speed: float = 1.0) -> bool:
        """合成语音(同步)"""
        raise NotImplementedError

    def shutdown(self) -> None:
        """关闭提供器,清理资源(默认)"""
        pass  # noqa


class EdgeTTSProvider(TTSVoiceProvider):
    """Edge TTS 提供器"""

    def __init__(self):
        super().__init__(TTSEngine.EDGE)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="EdgeTTS")
        self._shutdown = False

    def shutdown(self) -> None:
        """关闭提供器,清理资源"""
        if not self._shutdown:
            self._shutdown = True
            try:
                self._executor.shutdown(wait=True)
            except Exception as e:
                logger.warning(f"关闭 EdgeTTS 提供器时出错: {e}")

    def __del__(self):
        """析构函数"""
        self.shutdown()

    def _safe_cleanup_loop(self, loop: Optional[asyncio.AbstractEventLoop]):
        """清理事件循环"""
        if not loop:
            return

        def _delayed_cleanup():
            """延迟清理"""
            time.sleep(0.1)
            try:
                if not loop.is_closed():
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        with contextlib.suppress(RuntimeError):
                            loop.run_until_complete(
                                asyncio.gather(*pending, return_exceptions=True)
                            )
                    loop.close()
            except Exception as e:
                logger.warning(f"清理事件循环时出错: {e}")
            try:
                asyncio.set_event_loop(None)
            except Exception as e:
                logger.warning(f"清理事件循环引用时出错: {e}")

        try:
            cleanup_thread = threading.Thread(target=_delayed_cleanup, daemon=True)
            cleanup_thread.start()
        except Exception as e:
            logger.warning(f"启动清理线程失败: {e}")
            try:
                if not loop.is_closed():
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.close()
            except Exception:
                pass
            with contextlib.suppress(Exception):
                asyncio.set_event_loop(None)

    def _fetch_voices(self) -> List[TTSVoice]:
        """获取 Edge TTS 语音列表"""
        try:
            try:
                current_loop = asyncio.get_running_loop()
                if current_loop and not current_loop.is_closed():
                    with ThreadPoolExecutor() as executor:
                        future = executor.submit(self._fetch_voices_sync)
                        return future.result(timeout=10.0)
            except RuntimeError:
                pass

            def _run_async():
                loop = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    return loop.run_until_complete(edge_tts.list_voices())
                except Exception:
                    raise
                finally:
                    self._safe_cleanup_loop(loop)

            future = self._executor.submit(_run_async)
            voices = future.result(timeout=10.0)

            result: List[TTSVoice] = []
            for voice in voices:
                voice_obj: Any = voice
                tts_voice = TTSVoice(
                    id=voice_obj['ShortName'],
                    name=voice_obj['FriendlyName'],
                    language=voice_obj['Locale'][:2],
                    gender=voice_obj['Gender'],
                    engine=TTSEngine.EDGE,
                    locale=voice_obj['Locale'],
                )
                result.append(tts_voice)

            return result
        except Exception as e:
            logger.error(f"获取 Edge TTS 语音列表失败: {e}")
            return []

    def _fetch_voices_sync(self) -> List[TTSVoice]:
        """同步方式获取 Edge TTS 语音列表"""
        try:
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                voices = loop.run_until_complete(edge_tts.list_voices())

                result: List[TTSVoice] = []
                for voice in voices:
                    voice_obj: Any = voice
                    tts_voice = TTSVoice(
                        id=voice_obj['ShortName'],
                        name=voice_obj['FriendlyName'],
                        language=voice_obj['Locale'][:2],
                        gender=voice_obj['Gender'],
                        engine=TTSEngine.EDGE,
                        locale=voice_obj['Locale'],
                    )
                    result.append(tts_voice)
                return result
            finally:
                self._safe_cleanup_loop(loop)
        except Exception as e:
            logger.error(f"同步获取 Edge TTS 语音列表失败: {e}")
            return []

    def synthesize(self, text: str, voice_id: str, output_path: str, speed: float = 1.0) -> bool:
        """合成 Edge TTS 语音"""
        try:

            def _run_synthesis():
                loop = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    rate_percent = int((speed - 1) * 100)
                    rate_str = f"{rate_percent:+d}%" if rate_percent != 0 else "+0%"
                    if not text or not text.strip():
                        raise ValueError(
                            QCoreApplication.translate("EdgeTTSProvider", "文本内容不能为空")
                        )
                    if not voice_id:
                        raise ValueError(
                            QCoreApplication.translate("EdgeTTSProvider", "语音ID不能为空")
                        )
                    communicate = edge_tts.Communicate(text=text, voice=voice_id, rate=rate_str)
                    result = loop.run_until_complete(communicate.save(output_path))
                    if not os.path.exists(output_path):
                        raise RuntimeError(
                            QCoreApplication.translate(
                                "EdgeTTSProvider", "语音文件生成失败，文件不存在"
                            )
                        )
                    if os.path.getsize(output_path) == 0:
                        raise RuntimeError(
                            QCoreApplication.translate(
                                "EdgeTTSProvider", "语音文件生成失败，文件为空"
                            )
                        )

                    return result
                except Exception as e:
                    error_msg = str(e)
                    if "No audio was received" in error_msg:
                        raise RuntimeError(
                            QCoreApplication.translate(
                                "EdgeTTSProvider",
                                "Edge TTS服务未返回音频数据,可能是网络问题或语音参数错误。语音ID: {}",
                            ).format(voice_id)
                        )
                    if "proxy" in error_msg.lower() or "https" in error_msg.lower():
                        raise RuntimeError(
                            QCoreApplication.translate(
                                "EdgeTTSProvider", "连接问题,可能是代理设置导致: {}"
                            ).format(error_msg)
                        )
                    if "timeout" in error_msg.lower():
                        raise RuntimeError(
                            QCoreApplication.translate(
                                "EdgeTTSProvider", "超时,请检查网络连接: {}"
                            ).format(error_msg)
                        )
                    raise RuntimeError(
                        QCoreApplication.translate(
                            "EdgeTTSProvider", "Edge TTS合成失败: {}"
                        ).format(error_msg)
                    )
                finally:
                    self._safe_cleanup_loop(loop)

            future = self._executor.submit(_run_synthesis)
            future.result(timeout=20.0)
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            logger.error(f"Edge TTS 合成失败: {e}")
            if os.path.exists(output_path) and os.path.getsize(output_path) == 0:
                with contextlib.suppress(builtins.BaseException):
                    os.remove(output_path)
            return False


class Pyttsx3Provider(TTSVoiceProvider):
    """Pyttsx3 TTS 提供器"""

    def __init__(self):
        super().__init__(TTSEngine.PYTTSX3)
        self._engine_lock = threading.Lock()

    def _fetch_voices(self) -> List[TTSVoice]:
        """获取 Pyttsx3 语音列表"""
        if platform.system() != "Windows":
            logger.warning("Pyttsx3 仅支持 Windows 系统")
            return []

        try:
            with self._engine_lock:
                engine: Any = pyttsx3.init()
                voices: Any = engine.getProperty('voices')
                engine.stop()

            result: List[TTSVoice] = []
            for voice in voices:
                voice_obj: Any = voice
                language = (
                    'zh'
                    if any(
                        keyword in voice_obj.name.lower() for keyword in ['chinese', 'zh', '中文']
                    )
                    else 'en'
                )
                tts_voice = TTSVoice(
                    id=voice_obj.id,
                    name=voice_obj.name,
                    language=language,
                    gender='unknown',
                    engine=TTSEngine.PYTTSX3,
                )
                result.append(tts_voice)

            return result
        except Exception as e:
            logger.error(f"获取 Pyttsx3 语音列表失败: {e}")
            return []

    def synthesize(self, text: str, voice_id: str, output_path: str, speed: float = 1.0) -> bool:
        """合成 Pyttsx3 语音"""
        if platform.system() != "Windows":
            logger.error("Pyttsx3 仅支持 Windows 系统")
            return False

        try:
            with self._engine_lock:
                engine: Any = pyttsx3.init()
                engine.setProperty('voice', voice_id)
                engine.setProperty('rate', int(200 * speed))
                temp_path = output_path + '.tmp'
                engine.save_to_file(text, temp_path)
                engine.runAndWait()
                engine.stop()
                if os.path.exists(temp_path):
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(temp_path, output_path)
                    return True

            return False
        except Exception as e:
            logger.error(f"Pyttsx3 合成失败: {e}")
            return False


class TTSManager:
    """TTS 管理器"""

    _instance: Optional['TTSManager'] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, cache_dir: Optional[str] = None) -> 'TTSManager':
        """获取单例实例"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(cache_dir or str(CACHE_HOME / "tts"))
            return cls._instance

    def __init__(self, cache_dir: str):
        if TTSManager._instance is not None:
            raise RuntimeError(
                QCoreApplication.translate(
                    "TTSManager", "热芝士: TTSManager.get_instance() 获取实例"
                )
            )
        self.cache_dir = cache_dir
        self.cache = TTSCache(cache_dir)
        self.providers: Dict[TTSEngine, TTSVoiceProvider] = {
            TTSEngine.EDGE: EdgeTTSProvider(),
            TTSEngine.PYTTSX3: Pyttsx3Provider(),
        }
        self.tasks: Dict[str, TTSTask] = {}
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="TTS")

    def stop(self) -> None:
        """停止 TTS 管理器"""
        try:
            for provider in self.providers.values():
                if hasattr(provider, 'shutdown'):
                    provider.shutdown()
            self.executor.shutdown(wait=True)
        except Exception as e:
            logger.warning(f"停止 TTS 管理器时出错: {e}")

    def get_voices(
        self, engine: Optional[TTSEngine] = None, language_filter: Optional[str] = None
    ) -> List[TTSVoice]:
        """获取语音列表"""
        if engine:
            if engine in self.providers:
                return self.providers[engine].get_voices(language_filter)
            return []
        all_voices = []
        for provider in self.providers.values():
            voices = provider.get_voices(language_filter)
            all_voices.extend(voices)
        return all_voices

    def get_available_engines(self) -> Dict[TTSEngine, str]:
        """获取可用的 TTS 引擎"""
        engines = {TTSEngine.EDGE: "Edge TTS"}
        if platform.system() == "Windows":
            engines[TTSEngine.PYTTSX3] = "系统语音 (Pyttsx3)"

        return engines

    def generate_speech(
        self,
        text: str,
        engine: TTSEngine = TTSEngine.EDGE,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        auto_fallback: bool = True,
    ) -> Optional[str]:
        """生成语音文件(同步)"""
        try:
            cache_key = self.cache.get_cache_key(text, engine, voice_id, speed)
            cached_file = self.cache.get_cached_file(cache_key)
            if cached_file:
                logger.debug(f"使用缓存文件: {cached_file}")
                return cached_file
            timestamp = int(time.time())
            unique_id = str(uuid.uuid4())[:8]
            text_hash = hashlib.md5(text.encode()).hexdigest()[:6]
            filename = f"{engine.value}_{text_hash}_{timestamp}_{unique_id}.mp3"
            output_path = os.path.join(self.cache_dir, filename)
            success = self._synthesize_speech(
                text, engine, voice_id, output_path, speed, auto_fallback
            )

            if success:
                cached_path = self.cache.add_to_cache(cache_key, output_path)
                logger.debug(f"语音生成成功: {cached_path}")
                return cached_path
            logger.error("语音生成失败")
            return None

        except Exception as e:
            logger.error(f"生成语音时出错: {e}")
            return None

    def _synthesize_speech(
        self,
        text: str,
        engine: TTSEngine,
        voice_id: Optional[str],
        output_path: str,
        speed: float,
        auto_fallback: bool,
    ) -> bool:
        """合成语音"""
        provider = self.providers.get(engine)
        if not provider:
            if auto_fallback:
                for fallback_engine, fallback_provider in self.providers.items():
                    if fallback_engine != engine:
                        # logger.debug(f"回退到引擎 {fallback_engine.value}")
                        voices = fallback_provider.get_voices()
                        if voices:
                            return fallback_provider.synthesize(
                                text, voices[0].id, output_path, speed
                            )
            return False

        if not voice_id:
            voices = provider.get_voices()
            if voices:
                voice_id = voices[0].id
            else:
                logger.error(f"无法获取 {engine.value} 的语音列表")
                return False

        return provider.synthesize(text, voice_id, output_path, speed)

    def clear_cache(self) -> None:
        """清空缓存"""
        self.cache.clear_cache()


def get_tts_manager(cache_dir: Optional[str] = None) -> TTSManager:
    return TTSManager.get_instance(cache_dir)


def generate_speech_sync(
    text: str,
    engine: str = "edge",
    voice_id: Optional[str] = None,
    speed: float = 1.0,
    timeout: float = 10.0,
    auto_fallback: bool = True,
    filename: Optional[str] = None,
) -> str:
    """同步生成语音"""
    manager = get_tts_manager()
    try:
        engine_enum = TTSEngine(engine)
    except ValueError:
        engine_enum = TTSEngine.EDGE
    file_path = manager.generate_speech(
        text=text, engine=engine_enum, voice_id=voice_id, speed=speed, auto_fallback=auto_fallback
    )
    if not file_path:
        raise RuntimeError("TTS 生成失败")

    return file_path


class TTSService(QObject):
    """
    TTS服务
    """

    speech_generated = pyqtSignal(str, str)  # 语音生成完成格式:(文本, 文件路径)
    generation_error = pyqtSignal(str, str)  # 生成错误,格式:(文本, 错误信息)

    _instance: Optional['TTSService'] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'TTSService':
        """获取单例实例"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        if TTSService._instance is not None:
            raise RuntimeError(
                QCoreApplication.translate(
                    "TTSService", "热芝士: 使用 TTSService.get_instance() 获取实例"
                )
            )

        super().__init__()
        self._manager = TTSManager.get_instance()
        self._generation_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="TTSGeneration"
        )
        self._active_generations: Dict[str, bool] = {}  # 跟踪活跃的生成任务
        self._generation_lock = threading.Lock()

    def generate_speech_async(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        auto_fallback: bool = True,
        on_complete: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """
        异步生成TTS语音文件

        Args:
            text: 要合成的文本
            voice_id: 语音ID(格式: engine:voice_id)
            speed: 语速倍率
            auto_fallback: 是否自动回退
            on_complete: 完成回调函数(text, file_path)
            on_error: 错误回调函数(text, error_msg)

        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())

        with self._generation_lock:
            self._active_generations[task_id] = True
        if voice_id and ':' in voice_id:
            engine_name, voice_id_only = voice_id.split(':', 1)
            try:
                engine = TTSEngine(engine_name)
            except ValueError:
                # logger.warning(f"未知的TTS引擎: {engine_name}, 使用Edge TTS")
                engine = TTSEngine.EDGE
                voice_id_only = voice_id
        else:
            engine = TTSEngine.EDGE
            voice_id_only = voice_id
        if engine == TTSEngine.PYTTSX3 and platform.system() != "Windows":
            if auto_fallback:
                # logger.info("当前系统不支持Pyttsx3, 回退到Edge TTS")
                engine = TTSEngine.EDGE
                voice_id_only = None
            else:
                error_msg = QCoreApplication.translate("TTSService", "当前系统不支持Pyttsx3")
                logger.error(error_msg)
                self.generation_error.emit(text, error_msg)
                if on_error:
                    on_error(text, error_msg)
                return task_id

        def _generate_in_background():
            try:
                with self._generation_lock:
                    if not self._active_generations.get(task_id, False):
                        return
                file_path = self._manager.generate_speech(
                    text=text,
                    engine=engine,
                    voice_id=voice_id_only,
                    speed=speed,
                    auto_fallback=auto_fallback,
                )
                with self._generation_lock:
                    if not self._active_generations.get(task_id, False):
                        return
                if not file_path:
                    raise RuntimeError("语音生成失败")
                with self._generation_lock:
                    self._active_generations.pop(task_id, None)

                self.speech_generated.emit(text, file_path)
                # logger.success(f"TTS生成完成: {file_path}")
                if on_complete:
                    try:
                        on_complete(text, file_path)
                    except Exception as e:
                        logger.error(f"执行TTS完成回调失败: {e}")

            except Exception as e:
                error_msg = str(e)
                with self._generation_lock:
                    self._active_generations.pop(task_id, None)

                self.generation_error.emit(text, error_msg)
                logger.error(f"TTS生成失败: {error_msg}")
                if on_error:
                    try:
                        on_error(text, error_msg)
                    except Exception as e:
                        logger.error(f"执行TTS错误回调失败: {e}")

        self._generation_executor.submit(_generate_in_background)
        return task_id

    def generate_speech_sync(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        auto_fallback: bool = False,
        timeout: float = 15.0,
    ) -> Optional[str]:
        """
        同步生成TTS语音文件

        Args:
            text: 要合成的文本
            voice_id: 语音ID(格式: engine:voice_id)
            speed: 语速倍率
            auto_fallback: 是否自动回退
            timeout: 超时时间(秒)

        Returns:
            生成的文件路径, 失败返回None
        """
        if voice_id and ':' in voice_id:
            engine_name, voice_id_only = voice_id.split(':', 1)
            try:
                engine = TTSEngine(engine_name)
            except ValueError:
                # logger.warning(f"未知的TTS引擎: {engine_name}, 使用Edge TTS")
                engine = TTSEngine.EDGE
                voice_id_only = voice_id
        else:
            engine = TTSEngine.EDGE
            voice_id_only = voice_id
        if engine == TTSEngine.PYTTSX3 and platform.system() != "Windows":
            if auto_fallback:
                # logger.info("当前系统不支持Pyttsx3, 回退到Edge TTS")
                engine = TTSEngine.EDGE
                voice_id_only = None
            else:
                logger.error("当前系统不支持Pyttsx3")
                return None
        return self._manager.generate_speech(
            text=text,
            engine=engine,
            voice_id=voice_id_only,
            speed=speed,
            auto_fallback=auto_fallback,
        )

    def cancel_generation(self, task_id: str) -> bool:
        """
        取消语音生成任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消
        """
        with self._generation_lock:
            if task_id in self._active_generations:
                self._active_generations[task_id] = False
                logger.info(f"已取消TTS生成任务: {task_id}")
                return True
            return False

    def get_active_generations(self) -> List[str]:
        """
        获取活跃的生成任务列表

        Returns:
            任务ID列表
        """
        with self._generation_lock:
            return [task_id for task_id, active in self._active_generations.items() if active]

    def clear_cache(self) -> None:
        """清空TTS缓存"""
        self._manager.cache.clear_cache()
        logger.info("TTS缓存已清空")

    def play_tts(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        auto_fallback: bool = True,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """播放TTS语音(生成并播放)"""
        try:
            return self.generate_speech_async(
                text=text,
                voice_id=voice_id,
                speed=speed,
                auto_fallback=auto_fallback,
                on_complete=lambda text, file_path: self._handle_play_complete(
                    file_path, on_complete
                ),
                on_error=lambda text, error: self._handle_play_error(error, on_error),
            )
        except Exception as e:
            error_msg = f"TTS播放失败: {e!s}"
            logger.error(error_msg)
            if on_error:
                on_error(error_msg)
            return None

    def _handle_play_complete(
        self, file_path: str, on_complete: Optional[Callable[[str], None]]
    ) -> None:
        """处理播放完成"""
        try:
            from play_audio import play_audio

            success = play_audio(file_path, tts_delete_after=True)
            if success and on_complete:
                on_complete(file_path)
        except Exception as e:
            logger.error(f"播放音频文件失败: {e}")

    def _handle_play_error(self, error: str, on_error: Optional[Callable[[str], None]]) -> None:
        """处理播放错误"""
        if on_error:
            on_error(error)

    def shutdown(self) -> None:
        """关闭TTS服务"""
        with self._generation_lock:
            for task_id in list(self._active_generations.keys()):
                self._active_generations[task_id] = False
        self._generation_executor.shutdown(wait=True)
        self._manager.stop()
        logger.info("TTS服务已关闭")


def get_tts_service() -> TTSService:
    """获取TTS服务实例"""
    return TTSService.get_instance()


def generate_tts_async(
    text: str,
    voice_id: Optional[str] = None,
    speed: float = 1.0,
    auto_fallback: bool = False,
    on_complete: Optional[Callable[[str, str], None]] = None,
    on_error: Optional[Callable[[str, str], None]] = None,
) -> str:
    """
    异步生成TTS语音文件

    Args:
        text: 要合成的文本
        voice_id: 语音ID
        speed: 语速倍率
        auto_fallback: 是否自动回退
        on_complete: 完成回调函数(text, file_path)
        on_error: 错误回调函数(text, error_msg)

    Returns:
        任务ID
    """
    service = get_tts_service()
    return service.generate_speech_async(
        text, voice_id, speed, auto_fallback, on_complete, on_error
    )


def generate_tts_sync(
    text: str,
    voice_id: Optional[str] = None,
    speed: float = 1.0,
    auto_fallback: bool = False,
    timeout: float = 15.0,
) -> Optional[str]:
    """
    同步生成TTS语音文件

    Args:
        text: 要合成的文本
        voice_id: 语音ID
        speed: 语速倍率
        auto_fallback: 是否自动回退
        timeout: 超时时间(秒)

    Returns:
        生成的文件路径, 失败返回None
    """
    service = get_tts_service()
    return service.generate_speech_sync(text, voice_id, speed, auto_fallback, timeout)


def play_tts_with_audio(
    text: str,
    voice_id: Optional[str] = None,
    speed: float = 1.0,
    auto_fallback: bool = False,
    tts_delete_after: bool = True,
    volume: Optional[float] = None,
) -> bool:
    """
    生成并播放TTS语音

    Args:
        text: 要合成的文本
        voice_id: 语音ID
        speed: 语速倍率
        auto_fallback: 是否自动回退
        tts_delete_after: 播放后是否删除文件
        volume: 音量(0.0-1.0), None表示使用配置文件中的音量

    Returns:
        是否成功播放
    """
    global _tts_playing
    try:
        file_path = generate_tts_sync(text, voice_id, speed, auto_fallback)
        if not file_path:
            logger.error("TTS语音生成失败")
            return False
        with _tts_lock:
            _tts_playing = True

        from play_audio import play_audio

        success = play_audio(file_path, tts_delete_after=tts_delete_after, volume=volume)
        with _tts_lock:
            _tts_playing = False

        if success:
            logger.info(f"成功播放TTS: {file_path}")
        else:
            logger.error(f"播放TTS失败: {file_path}")

        return success

    except Exception as e:
        logger.error(f"TTS播放失败: {e}")
        with _tts_lock:
            _tts_playing = False
        return False


def cancel_tts_generation(task_id: str) -> bool:
    """取消TTS生成任务"""
    service = get_tts_service()
    return service.cancel_generation(task_id)


def get_active_tts_generations() -> List[str]:
    """获取活跃的TTS生成任务列表"""
    service = get_tts_service()
    return service.get_active_generations()


async def get_tts_voices(
    engine_filter: Optional[str] = None, language_filter: Optional[str] = None
) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """获取TTS语音列表(ui特供版)"""
    try:
        manager = get_tts_service()._manager
        engine_enum = None
        if engine_filter:
            try:
                engine_enum = TTSEngine(engine_filter)
            except ValueError:
                return [], f"未知的TTS引擎: {engine_filter}"
        voices = manager.get_voices(engine_enum, language_filter)
        voice_list: List[Dict[str, str]] = []
        for voice in voices:
            voice_list.append(
                {
                    'id': voice.id,
                    'name': voice.name,
                    'language': voice.language,
                    'gender': voice.gender,
                    'engine': voice.engine.value,
                }
            )

        return voice_list, None

    except Exception as e:
        error_msg = f"获取TTS语音列表失败: {e!s}"
        logger.error(error_msg)
        return [], error_msg


def get_voice_name_by_id_sync(
    voice_id: str, available_voices: List[Dict[str, str]]
) -> Optional[str]:
    """根据语音ID获取语音名称(同步)"""
    try:
        for voice in available_voices:
            if voice.get('id') == voice_id:
                return voice.get('name')
        return None
    except Exception as e:
        logger.error(f"获取语音名称失败: {e}")
        return None


def get_voice_id_by_name(voice_name: str, available_voices: List[Dict[str, str]]) -> Optional[str]:
    """根据语音名称获取语音ID"""
    try:
        for voice in available_voices:
            if voice.get('name') == voice_name:
                return voice.get('id')
        return None
    except Exception as e:
        logger.error(f"获取语音ID失败: {e}")
        return None


def get_available_engines() -> Dict[str, str]:
    """获取可用的TTS引擎(ui特供版)"""
    try:
        manager = get_tts_service()._manager
        engines = manager.get_available_engines()
        result = {}
        for engine_enum, name in engines.items():
            result[engine_enum.value] = name
        return result
    except Exception as e:
        logger.error(f"获取可用引擎失败: {e}")
        return {'edge': 'Edge TTS'}


def get_supported_languages() -> Dict[str, str]:
    """获取支持的语言列表"""
    return {
        'zh-CN': '中文(简体)',
        'zh-TW': '中文(繁体)',
        'en-US': 'English (US)',
        'en-GB': 'English (UK)',
        'ja-JP': '日本語',
        'ko-KR': '한국어',
        'fr-FR': 'Français',
        'de-DE': 'Deutsch',
        'es-ES': 'Español',
        'it-IT': 'Italiano',
        'pt-BR': 'Português (Brasil)',
        'ru-RU': 'Русский',
    }


def list_pyttsx3_voices() -> List[Dict[str, str]]:
    """列出 Pyttsx3 可用的语音(兼容处理(lazy)"""
    try:
        manager = get_tts_service()._manager
        if TTSEngine.PYTTSX3 in manager.providers:
            voices = manager.providers[TTSEngine.PYTTSX3].get_voices()
            voice_list: List[Dict[str, str]] = []
            for voice in voices:
                voice_list.append(
                    {
                        'id': voice.id,
                        'name': voice.name,
                        'language': voice.language,
                        'gender': voice.gender,
                        'engine': voice.engine.value,
                    }
                )

            return voice_list
        logger.warning("Pyttsx3 引擎不可用")
        return []
    except Exception as e:
        logger.error(f"获取 Pyttsx3 语音列表失败: {e}")
        return []


def on_audio_played(file_path: str) -> None:
    """音频播放完成后的回调函数"""
    try:
        if os.path.exists(file_path) and 'cache' in file_path:
            os.remove(file_path)
            logger.debug(f"已删除TTS临时文件: {file_path}")
    except Exception as e:
        logger.warning(f"删除TTS临时文件失败 {file_path}: {e}")


def is_tts_playing() -> bool:
    """检查是否有TTS正在播放"""
    try:
        with _tts_lock:
            return _tts_playing
    except Exception as e:
        logger.warning(f"检查TTS播放状态失败: {e}")
        return False


def stop_tts() -> bool:
    """停止TTS播放"""
    global _tts_playing
    try:
        from play_audio import stop_audio

        stop_audio()
        with _tts_lock:
            _tts_playing = False
        return True
    except Exception as e:
        logger.warning(f"停止TTS播放失败: {e}")
        with _tts_lock:
            _tts_playing = False
        return False
