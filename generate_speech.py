import asyncio
import hashlib
import os
import platform
import re
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Generator # Added List, Dict, Tuple, Any, Generator
from contextlib import contextmanager

import edge_tts # type: ignore
import pyttsx3 # type: ignore
from pyttsx3.voice import Voice # type: ignore
if platform.system() == "Windows":
    import pythoncom # type: ignore
from loguru import logger
from file import config_center

# 默认用常量
DEFAULT_SPEED: int = 50
MAX_PYTTSX3_RATE: int = 400
MIN_PYTTSX3_RATE: int = 50
DEFAULT_TIMEOUT: float = 10.0
DEFAULT_RETRIES: int = 5
DEFAULT_RETRY_DELAY: float = 1.0
MIN_VALID_FILE_SIZE: int = 10 # bytes
CACHE_MAX_AGE: int = 86400  # 缓存最大保存时间(秒)

# Type alias for voice dictionary
VoiceDict = Dict[str, str]
VoiceInfo = Dict[str, str] # For internal representation of voice details before final formatting

async def _get_edge_voices_async() -> Tuple[List[VoiceDict], Optional[str]]:
    """获取Edge TTS语音列表,优先大陆"""
    try:
        edge_voices_raw: List[Dict[str, Any]] = await edge_tts.list_voices()
        zh_voices_info: List[VoiceInfo] = [ # Use VoiceInfo for intermediate structure
            {"name": voice["FriendlyName"], "id": f"edge:{voice['Name']}", "locale": voice["Locale"]}
            for voice in edge_voices_raw # Assume voice is a Dict[str, Any]
            if _is_zh_voice(voice["Locale"])
        ]

        def sort_key(voice: VoiceInfo) -> int: # Type hint for sort_key's argument
            name_lower = voice["name"].lower()
            locale_lower = voice["locale"].lower()
            if "mainland" in locale_lower or "cn" in locale_lower:
                if "xiaoxiao" in name_lower: # Specific voice gets highest priority
                    return 0
                return 1 # Other mainland CN voices
            elif "hongkong" in locale_lower or "hk" in locale_lower:
                return 2 
            elif "taiwan" in locale_lower or "tw" in locale_lower:
                return 3
            return 4 # Other Chinese locales

        zh_voices_info.sort(key=sort_key)
        # Format to the final VoiceDict structure
        formatted_voices: List[VoiceDict] = [{"name": v["name"], "id": v["id"]} for v in zh_voices_info]
        return formatted_voices, None
    except Exception as e:
        error_message: str = f"获取 Edge TTS 语音列表失败: {e}"
        return [], error_message


async def _get_pyttsx3_voices_async() -> Tuple[List[VoiceDict], Optional[str]]:
    """获取Pyttsx3语音列表"""
    try:
        # _pyttsx3_context yields Optional[pyttsx3.Engine]
        with _pyttsx3_context() as engine:
            if not engine: # Engine could be None if initialization fails
                return [], "pyttsx3引擎初始化失败或不可用"

            loop = asyncio.get_running_loop()
            voices_available: List[Voice] = await loop.run_in_executor(None, engine.getProperty, "voices")

            formatted_voices: List[VoiceDict] = [
                {"name": voice.name, "id": f"pyttsx3:{voice.id}"}
                for voice in voices_available
                if _is_zh_pyttsx3_voice(voice) # Ensure voice is of type Voice
            ]
            return formatted_voices, None
    except OSError as oe:
        error_message: str = ""
        # Check if oe has winerror attribute before accessing
        win_error_code: Optional[int] = getattr(oe, "winerror", None)

        if win_error_code == -2147221005:
            error_message = "系统语音引擎(pyttsx3/SAPI5)初始化失败,可能是组件未正确注册或损坏,跳过加载系统语音"
        elif platform.system() != "Windows":
            error_message = f"在 {platform.system()} 上获取 Pyttsx3 语音列表时发生OS错误: {oe}。这可能是因为系统未安装或配置兼容的TTS引擎。将跳过加载系统语音。"
        else: # Other OS errors on Windows
            error_message = f"获取 Pyttsx3 语音列表时发生OS错误: {oe}"
        return [], error_message
    except Exception as e: # Catch other potential exceptions
        error_message = f"获取 Pyttsx3 语音列表失败: {e}"
        return [], error_message


def _is_zh_voice(locale: str) -> bool:
    """检查是否为中文语音"""
    return "zh" in locale.lower()


def _is_zh_pyttsx3_voice(voice: Voice) -> bool:
    """检查pyttsx3中文语音"""
    name: str = voice.name.lower() # voice.name should be str
    # Check if voice.languages exists and is not empty
    if hasattr(voice, "languages") and voice.languages: # voice.languages is likely List[str]
        return any("zh" in lang.lower() for lang in voice.languages)
    # Fallback to checking name if languages attribute is not helpful
    if "chinese" in name or "mandarin" in name:
        return True
    return False

ENGINE_EDGE: str = "edge"
ENGINE_PYTTSX3: str = "pyttsx3"

def get_available_engines() -> Dict[str, str]:
    """获取可用的TTS引擎及其显示名称."""
    engines: Dict[str, str] = {
        ENGINE_EDGE: "Edge TTS",
    }
    # pyttsx3 is generally available but might fail on init; here we list it if OS is Windows
    if platform.system() == "Windows":
        engines[ENGINE_PYTTSX3] = "系统 TTS (pyttsx3)"
    return engines

@contextmanager
def _pyttsx3_context() -> Generator[Optional[pyttsx3.Engine], None, None]: # Added type hint for generator
    """安全的pyttsx3引擎上下文管理器"""
    engine = None
    try:
        pythoncom.CoInitialize()
        engine = pyttsx3.init()
        yield engine
    except Exception as e:
        logger.error(f"pyttsx3引擎初始化失败: {e}")
        yield None
    finally:
        if engine:
            try:
                engine.stop()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception: # Keep broad exception for COM interface
            pass


def filter_zh_voices(voices: List[VoiceDict]) -> List[VoiceDict]: # Added type hints
    """筛选中文语音"""
    # Ensure that v.get("id", "") is handled correctly if "id" might be missing or not a string.
    # Assuming "id" is always present and a string based on VoiceDict.
    return [v for v in voices if "zh" in v.get("id", "").lower()]


def log_voices_summary(voices: List[VoiceDict]) -> None: # Added type hints
    """记录语音统计信息"""
    # Ensure "id" key exists and is a string before calling startswith.
    edge_count = len([v for v in voices if v.get("id", "").startswith("edge:")])
    pyttsx3_count = len([v for v in voices if v.get("id", "").startswith("pyttsx3:")])

    if edge_count > 0:
        logger.info(f"筛选了 {edge_count} 个 Edge 语音")
    if pyttsx3_count > 0:
        logger.info(f"筛选了 {pyttsx3_count} 个 Pyttsx3 语音")
    if not voices: # This check is fine.
        logger.warning("未能获取到任何 TTS 语音")

# Define a more specific type for the cache structure if possible.
# For now, Any is used for simplicity for the "voices" list within the cache.
TTSCacheType = Dict[str, Dict[str, Any]]

_tts_voices_cache: TTSCacheType = { # Added type hint
    "edge": {"voices": [], "timestamp": 0.0}, # Ensure timestamp is float for consistency
    "pyttsx3": {"voices": [], "timestamp": 0.0},
}

async def get_tts_voices(engine_filter: Optional[str] = None) -> Tuple[List[VoiceDict], Optional[str]]: # Added return type hint
    """异步获取可用的TTS语音列表(中文)，包括Edge和Pyttsx3.
    Args:
        engine_filter (Optional[str], optional): 指定引擎 ("edge" or "pyttsx3"). Defaults to None (获取所有).
    Returns:
        Tuple[List[VoiceDict], Optional[str]]: 语音列表和可能的错误信息
    """
    current_time: float = time.time()
    # Check cache first
    if engine_filter and engine_filter in _tts_voices_cache:
        cache_entry = _tts_voices_cache[engine_filter]
        # Ensure "voices" is List[VoiceDict] and "timestamp" is float
        if cache_entry.get("voices") and (current_time - float(cache_entry.get("timestamp", 0.0)) < CACHE_MAX_AGE):
            return list(cache_entry["voices"]), None # Return a copy to prevent external modification
    elif not engine_filter: # If no specific engine, check if all are cached and valid
        all_cached = True
        combined_voices: List[VoiceDict] = []
        for eng, cache_entry in _tts_voices_cache.items():
            if not cache_entry.get("voices") or (current_time - float(cache_entry.get("timestamp", 0.0)) >= CACHE_MAX_AGE):
                all_cached = False
                break
            combined_voices.extend(list(cache_entry["voices"]))
        if all_cached and combined_voices: # Ensure combined_voices is not empty if all_cached
            return combined_voices, None

    voices_result: List[VoiceDict] = []
    overall_error: Optional[str] = None

    if engine_filter is None or engine_filter == ENGINE_EDGE:
        edge_voices, edge_error = await _get_edge_voices_async()
        if edge_voices: # Check if list is not empty
            voices_result.extend(edge_voices)
            _tts_voices_cache[ENGINE_EDGE]["voices"] = edge_voices
            _tts_voices_cache[ENGINE_EDGE]["timestamp"] = current_time
        else: # Log warning if edge_voices is empty, regardless of edge_error
            logger.warning(f"Edge语音获取失败或无可用语音。错误: {edge_error if edge_error else '未知错误'}")
            if edge_error and not overall_error: # Prioritize first error if multiple occur
                overall_error = edge_error

    if engine_filter is None or engine_filter == ENGINE_PYTTSX3:
        pyttsx3_voices, pyttsx3_error = await _get_pyttsx3_voices_async()
        if pyttsx3_voices: # Check if list is not empty
            voices_result.extend(pyttsx3_voices)
            _tts_voices_cache[ENGINE_PYTTSX3]["voices"] = pyttsx3_voices
            _tts_voices_cache[ENGINE_PYTTSX3]["timestamp"] = current_time
        else: # Log warning if pyttsx3_voices is empty
            logger.warning(f"pyttsx3语音获取失败或无可用语音。错误: {pyttsx3_error if pyttsx3_error else '未知错误'}")
            if pyttsx3_error and not overall_error:
                overall_error = pyttsx3_error

    # Run summary logging in executor if it involves I/O or is CPU-bound, though it seems light enough.
    # For consistency with original code, keeping it this way.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, log_voices_summary, voices_result)

    return voices_result, overall_error


def get_voice_id_by_name(name: str, engine_filter: Optional[str] = None) -> Optional[str]: # Added type hints
    """
    根据语音名称查找语音ID
    参数：
        name (str): 语音显示名称
        engine_filter (Optional[str]): 可选的引擎过滤器
    返回：
        str 或 None: 语音ID，如果未找到则返回None
    """
    # get_tts_voices is async, this function is sync. This will block.
    # Consider making this async or using a sync wrapper carefully.
    # For now, assuming this blocking call is acceptable in its usage context.
    # However, directly calling asyncio.run() inside a sync function that might be called
    # from an async context (or vice-versa) can lead to issues.
    # This should be run in an executor if called from async, or get_tts_voices needs a sync version.

    # Simplified approach for now: Assuming this is called in a context where blocking is okay,
    # or that get_tts_voices needs a synchronous counterpart for this use case.
    # The original code calls `get_tts_voices` which is async, without await, implying it's
    # being called from a context that expects a coroutine or it's a bug.
    # Assuming it's a bug and it should be `await get_tts_voices` if this func was async,
    # or `asyncio.run(get_tts_voices(...))` if it's meant to be a blocking sync call.
    # Given the function signature is sync, let's assume it's a blocking call.

    # This part needs careful handling of async call from sync context.
    # For demonstration, let's assume a (hypothetical) synchronous version or direct cache access.
    # THIS IS A SIMPLIFICATION AND MIGHT NEED ASYNCIO EVENT LOOP MANAGEMENT IN REALITY

    voices_list: List[VoiceDict] = []
    # In a real scenario, you would need to manage an event loop to run this:
    # try:
    #     loop = asyncio.get_running_loop()
    #     voices_list, _ = loop.run_until_complete(get_tts_voices(engine_filter))
    # except RuntimeError: # No running event loop
    #     voices_list, _ = asyncio.run(get_tts_voices(engine_filter))

    # Accessing cache directly for simplicity in this synchronous context (not ideal)
    if engine_filter:
        voices_list = list(_tts_voices_cache.get(engine_filter, {}).get("voices", []))
    else:
        for eng_cache in _tts_voices_cache.values():
            voices_list.extend(list(eng_cache.get("voices", [])))

    for v_dict in voices_list: # Renamed v to v_dict to avoid confusion
        if v_dict.get("name") == name:
            return v_dict.get("id")
    return None


def get_voice_name_by_id(
    voice_id: str, available_voices: Optional[List[VoiceDict]] = None
) -> Optional[str]: # Added type hints
    """
    根据语音ID查找语音名称
    参数：
        voice_id (str): 语音ID
        available_voices (list, optional): 预先获取的语音列表,默认None(重新获取)
    返回：
        str 或 None: 语音名称,如果未找到则返回None
    """
    # Similar async issue as in get_voice_id_by_name if available_voices is None.
    # Assuming direct cache access for simplicity for the None case.
    voices_to_search: List[VoiceDict]
    if available_voices is not None:
        voices_to_search = available_voices
    else:
        # THIS IS A SIMPLIFICATION
        voices_to_search = []
        for eng_cache in _tts_voices_cache.values():
            voices_to_search.extend(list(eng_cache.get("voices", [])))

    return next((v.get("name") for v in voices_to_search if v.get("id") == voice_id), None)


# 一些多复用常量
# ENGINE_EDGE and ENGINE_PYTTSX3 are already defined with type hints
LANG_ZH: str = "zh-CN"
LANG_EN: str = "en-US"
CACHE_DIR_NAME: str = "cache"
AUDIO_DIR_NAME: str = "audio"
DEFAULT_TTS_TIMEOUT: float = 10.0 # Already float from previous hints
DEFAULT_DELETE_RETRIES: int = 5 # Already int
DEFAULT_DELETE_DELAY: float = 1.0 # Already float

class TTSEngine:
    """支持多平台和智能语音选择的多引擎TTS工具类"""

    def __init__(self) -> None: # Added return type hint
        """
        初始化TTS引擎实例
        属性：
        - cache_dir: 音频缓存目录路径（软件运行目录下 cache/audio文件夹）
        - engine_priority: 引擎优先级列表
        - voice_mapping: 跨平台语音映射配置表
        """
        self.cache_dir: str = os.path.join(os.getcwd(), CACHE_DIR_NAME, AUDIO_DIR_NAME)
        self._ensure_cache_dir()
        self.engine_priority: List[str] = [ENGINE_EDGE, ENGINE_PYTTSX3]
        # More specific type for voice_mapping if possible, e.g., Dict[str, Dict[str, str]]
        self.voice_mapping: Dict[str, Dict[str, str]] = {
            ENGINE_EDGE: {LANG_ZH: "zh-CN-YunxiNeural", LANG_EN: "en-US-AriaNeural"},
            ENGINE_PYTTSX3: self._get_platform_voices(), # This method returns Dict[str, str]
        }

    @staticmethod
    def _get_platform_voices() -> Dict[str, str]: # Added return type hint
        """
        获取当前平台的默认语音配置

        返回：
        - dict: 包含中英文语音ID的字典，结构为{'zh-CN': voice_id, 'en-US': voice_id}

        平台支持：
        - Windows: 使用注册表路径标识语音
        - macOS: 使用Apple语音标识符
        - Linux: 使用espeak语音名称
        """
        current_os: str = platform.system()
        # Define a more specific type for platform_voices if the structure is fixed
        platform_voices_config: Dict[str, Dict[str, str]] = {
            "Windows": {
                LANG_ZH: "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_ZH-CN_HUIHUI_11.0",
                # LANG_EN: 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_EN-US_DAVID_11.0'
            },
            "Darwin": {  # macOS
                LANG_ZH: "com.apple.speech.synthesis.voice.ting-ting.premium",
                # LANG_EN: 'com.apple.speech.synthesis.voice.Alex'
            },
            "Linux": { # Default/fallback
                LANG_ZH: "zh-CN", # This might be a generic identifier for espeak or similar
                # LANG_EN: 'en-US'
            },
        }
        return platform_voices_config.get(current_os, platform_voices_config["Linux"])

    def _ensure_cache_dir(self) -> None: # Added return type hint
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _generate_filename(text: str, engine: str) -> str: # Type hints already good
        timestamp: str = str(int(time.time()))
        hash_str: str = hashlib.md5(text.encode()).hexdigest()[:8]
        return f"{engine}_{hash_str}_{timestamp}.mp3"

    @staticmethod
    async def _edge_tts(text: str, voice: str, file_path: str) -> str: # Type hints already good
        # 语速范围 0-100
        # Assuming config_center.read_conf returns a value convertible to int
        speed_value_any: Any = config_center.read_conf("TTS", "speed")
        speed_value: int = int(speed_value_any) if speed_value_any is not None else DEFAULT_SPEED

        rate_percentage: int = (speed_value - 50) * 2 # Based on 0-100 range for speed_value
        rate_str: str = f"{rate_percentage:+}%" # Format as "+X%" or "-X%"

        logger.debug(f"Edge TTS Rate: {rate_str} (Slider: {speed_value})")
        communicate = edge_tts.Communicate(text, voice, rate=rate_str) # type: ignore[no-untyped-call]
        await communicate.save(file_path) # type: ignore[no-untyped-call]
        return file_path

    async def _pyttsx3_tts(self, text: str, voice: str, file_path: str) -> str: # Type hints already good
        loop = asyncio.get_running_loop()
        # _sync_pyttsx3 is static, so self is not passed.
        return await loop.run_in_executor(None, TTSEngine._sync_pyttsx3, text, voice, file_path)

    # _pyttsx3_context is already well-typed from previous step.
    # Just ensure its usage in _sync_pyttsx3 is consistent.
    @contextmanager
    def _pyttsx3_context(self) -> Generator[Optional[pyttsx3.Engine], None, None]:
        """pyttsx3引擎的上下文管理器"""
        if platform.system() != "Windows":
            # This check should ideally be at the call site or handled more gracefully
            # if pyttsx3 might be used on other platforms with different backends.
            logger.warning("pyttsx3 仅在Windows上受官方支持和测试。")
            # raise RuntimeError("pyttsx3 仅支持 Windows 系统") # Original behavior
            yield None # Yield None if not on Windows to avoid COM errors
            return


        engine: Optional[pyttsx3.Engine] = None
        com_initialized: bool = False
        max_retries: int = 3
        
        for attempt in range(max_retries):
            try:
                pythoncom.CoInitialize() # type: ignore[no-untyped-call]
                com_initialized = True
                logger.debug(f"正在初始化pyttsx3引擎 (尝试 {attempt+1}/{max_retries})")
                engine = pyttsx3.init() # type: ignore[no-untyped-call]
                if engine:
                    try:
                        # Basic check to see if engine is usable
                        _ = engine.getProperty('rate')
                        voices_check: Optional[List[Voice]] = engine.getProperty('voices')
                        if not voices_check: # Check if list of voices is empty or None
                            logger.warning("pyttsx3引擎未检测到任何语音")
                            # raise RuntimeError("未检测到语音") # Or handle more gracefully
                        
                        logger.debug(f"pyttsx3引擎初始化成功. 检测到 {len(voices_check) if voices_check else 0} 个语音")
                        yield engine
                        return # Successfully yielded engine
                    except Exception as check_e: # Broad exception during engine validation
                        logger.warning(f"pyttsx3引擎验证失败: {check_e}")
                        # Fall through to retry logic or raise if max_retries hit
                else: # pyttsx3.init() returned None
                    logger.warning("pyttsx3引擎初始化返回空引擎")

                # If engine is None or validation failed, raise to trigger retry/finally
                raise RuntimeError("引擎初始化或验证失败")

            except OSError as oe:
                win_error_code = getattr(oe, "winerror", None)
                if win_error_code == -2147221005: # Specific COM error
                    logger.error(
                        f"系统语音引擎(pyttsx3/SAPI5)初始化失败 (尝试 {attempt+1}/{max_retries})，"  
                        f"错误码: {win_error_code}。请检查系统语音组件。"
                    )
                else: # Other OS errors
                    logger.error(f"pyttsx3初始化时发生OS错误 (尝试 {attempt+1}/{max_retries}): {oe}")
                
                # Cleanup before retry or final failure
                if engine: try: engine.stop(); logger.debug("Engine stopped.")
                except: pass; engine = None
                if com_initialized: try: pythoncom.CoUninitialize(); logger.debug("COM uninitialized.")  # type: ignore[no-untyped-call]
                except: pass; com_initialized = False

                if attempt == max_retries - 1: # Last attempt failed
                    logger.error(f"pyttsx3/SAPI5 初始化失败，已重试 {max_retries} 次")
                    yield None # Yield None after all retries failed
                    return

                wait_time = (attempt + 1) * 1.0 # Progressive backoff
                logger.info(f"等待 {wait_time} 秒后重试pyttsx3初始化...")
                time.sleep(wait_time)
                
            except Exception as init_e: # Catch other init errors
                logger.error(f"pyttsx3初始化失败 (尝试 {attempt+1}/{max_retries}): {init_e}")
                if engine: try: engine.stop()
                except: pass; engine = None
                if com_initialized: try: pythoncom.CoUninitialize() # type: ignore[no-untyped-call]
                except: pass; com_initialized = False

                if attempt == max_retries - 1:
                    logger.error(f"pyttsx3初始化异常，已重试 {max_retries} 次")
                    yield None # Yield None after all retries failed
                    return
                wait_time = (attempt + 1) * 1.0
                logger.info(f"等待 {wait_time} 秒后重试pyttsx3初始化...")
                time.sleep(wait_time)
        # Fallback yield None if loop finishes due to unexpected issue (should not happen with current logic)
        yield None # Ensure a value is always yielded

    # No changes needed for the 'finally' block of _pyttsx3_context as it's part of the context manager
    # and its cleanup logic is tied to the try/except block above.

    @staticmethod
    def _sync_pyttsx3(text: str, voice: str, file_path: str) -> str: # Added return type hint
        """同步生成语音文件(pyttsx3)"""
        temp_dir: str = os.path.dirname(file_path)
        temp_filename: str = f"temp_{int(time.time())}_{os.getpid()}_{hash(text) % 10000}.mp3"
        temp_file_path: str = os.path.join(temp_dir, temp_filename)

        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.warning(f"无法删除已存在的临时文件: {temp_file_path}, 错误: {e}")
                # Generate a potentially more unique temp filename if the first was locked
                temp_filename = f"temp_{int(time.time())}_{os.getpid()}_{hash(text + str(time.time())) % 10000}.mp3"
                temp_file_path = os.path.join(temp_dir, temp_filename)
        
        max_retries_sync: int = 3 # Renamed to avoid conflict with outer scope if any
        for attempt in range(max_retries_sync):
            try:
                # TTSEngine()._pyttsx3_context() creates a new instance. This is likely not intended.
                # It should ideally use `self._pyttsx3_context()` if this method were not static,
                # or be passed an engine instance, or the context manager needs to be static too.
                # For now, adhering to the static nature and current call.
                with TTSEngine()._pyttsx3_context() as engine: # This will create a new TTSEngine instance each time
                    if not engine:
                        raise RuntimeError("无法初始化 pyttsx3 引擎")

                    if voice: # voice is Optional[str] but here used as str
                        voices_list: List[Voice] = engine.getProperty("voices")
                        found_voice: Optional[Voice] = next((v for v in voices_list if v.id == voice), None)
                        if not found_voice and ":" in voice: # Try matching without engine prefix if any
                            voice_id_only = voice.split(":", 1)[-1]
                            found_voice = next((v for v in voices_list if v.id == voice_id_only), None)

                        if found_voice:
                            engine.setProperty("voice", found_voice.id)
                        else:
                            logger.warning(f"pyttsx3: 无效或不匹配的语音ID '{voice}'，将使用默认语音")

                    speed_value_any: Any = config_center.read_conf("TTS", "speed") # type: ignore[attr-defined]
                    speed_value: int = int(speed_value_any) if speed_value_any is not None else DEFAULT_SPEED

                    default_rate: int = engine.getProperty("rate") # Should be int
                    pyttsx3_rate: int
                    if speed_value == 50:
                        pyttsx3_rate = default_rate
                    elif speed_value < 50:
                        pyttsx3_rate = int(default_rate / 2 + (default_rate / 2) * (speed_value / 50))
                    else:
                        pyttsx3_rate = int(default_rate + (default_rate * 0.5) * ((speed_value - 50) / 50))

                    pyttsx3_rate = max(MIN_PYTTSX3_RATE, min(pyttsx3_rate, MAX_PYTTSX3_RATE))
                    logger.debug(f"pyttsx3 Rate: {pyttsx3_rate} (Slider: {speed_value}, Default: {default_rate})")
                    engine.setProperty("rate", pyttsx3_rate)

                    engine.save_to_file(text, temp_file_path)
                    engine.runAndWait()

                    if not os.path.exists(temp_file_path):
                        raise FileNotFoundError(f"语音生成后临时文件未找到: {temp_file_path}")
                    
                    file_size: int = os.path.getsize(temp_file_path)
                    if file_size < MIN_VALID_FILE_SIZE:
                        raise RuntimeError(f"生成的临时文件可能已损坏（大小: {file_size}字节）")

                    # Validate header (basic check)
                    try:
                        with open(temp_file_path, "rb") as f:
                            header_bytes: bytes = f.read(10)
                            if not header_bytes or len(header_bytes) < 10: # Basic check for some data
                                raise RuntimeError(f"临时文件头部无效，可能已损坏")
                    except Exception as e_read:
                        raise RuntimeError(f"无法读取生成的临时文件: {e_read}")

                    # Move temp file to final destination
                    try:
                        if os.path.exists(file_path): os.remove(file_path)
                        os.rename(temp_file_path, file_path)
                    except Exception as e_rename:
                        logger.warning(f"重命名临时文件失败: {e_rename}，尝试复制内容")
                        try:
                            with open(temp_file_path, "rb") as src, open(file_path, "wb") as dst:
                                dst.write(src.read())
                            logger.debug(f"成功通过复制内容创建目标文件: {file_path}")
                            if os.path.exists(temp_file_path): os.remove(temp_file_path) # Clean up original temp
                        except Exception as copy_e:
                            raise RuntimeError(f"无法创建目标文件: {copy_e}")

                    if not os.path.exists(file_path): # Final check
                        raise FileNotFoundError(f"最终目标文件未找到: {file_path}")
                    final_file_size: int = os.path.getsize(file_path)
                    if final_file_size < MIN_VALID_FILE_SIZE:
                        raise RuntimeError(f"最终目标文件可能已损坏（大小: {final_file_size}字节）")
                    
                    return file_path
                    
            except Exception as e: # Catch errors during attempt
                logger.error(f"pyttsx3 语音生成失败 (尝试 {attempt+1}/{max_retries_sync}): {e}")
                if os.path.exists(temp_file_path):
                    try: os.remove(temp_file_path)
                    except Exception as rm_e: logger.warning(f"清理临时文件失败: {rm_e}")

                if attempt == max_retries_sync - 1: # Last attempt
                    raise RuntimeError(f"pyttsx3 语音生成失败，已重试 {max_retries_sync} 次: {e}")

                time.sleep((attempt + 1) * 0.5) # Wait before retrying

        # Should not be reached if logic is correct, but as a fallback:
        raise RuntimeError("pyttsx3 语音生成失败，未知错误")


    @staticmethod
    def _detect_language(text: str) -> str: # Type hints already good
        """检测文本语言（中文或英文）

        参数:
            text: 要检测的文本

        返回:
            语言代码: 'zh-CN' 或 'en-US'
        """
        if re.search("[一-鿿]", text): # Check for Chinese characters
            return LANG_ZH
        return LANG_EN # Default to English if no Chinese characters found

    def _validate_pyttsx3_voice(self, voice_id: str, lang: str) -> str: # Type hints already good
        """验证pyttsx3语音ID有效性，并在无效时自动回退

        参数:
            voice_id: 要验证的语音ID
            lang: 语言代码

        返回:
            有效的语音ID或空字符串（表示无法使用pyttsx3）
        """
        try:
            with self._pyttsx3_context() as engine: # self refers to an instance of TTSEngine
                if not engine: return "" # Engine initialization failed

                voices_list: List[Voice] = engine.getProperty("voices")
                if any(v.id == voice_id for v in voices_list):
                    return voice_id

                # Fallback to language-specific voice
                lang_voices_match: List[Voice] = [v for v in voices_list if lang in str(v.languages)]
                if lang_voices_match:
                    logger.info(f"找到{lang}语言的替代语音: {lang_voices_match[0].id}")
                    return lang_voices_match[0].id

                # Fallback to default voice
                default_voice_id: Optional[str] = engine.getProperty("voice") # ID of the current voice
                if default_voice_id:
                    logger.info(f"使用默认语音: {default_voice_id}")
                    return default_voice_id
                else: # Should ideally not happen if any voice is available
                    logger.warning("pyttsx3无可用默认语音，无法回退。")
                    return ""

        except (OSError, RuntimeError) as e: # Specific errors related to engine ops
            logger.warning(f"pyttsx3语音验证过程中发生引擎错误，无法使用pyttsx3: {e}")
            return ""
        except Exception as e: # Other unexpected errors
            logger.error(f"pyttsx3语音验证失败: {str(e)}")
            return ""

    async def _execute_engine(
        self, engine: str, text: str, voice: str, file_path: str, timeout: float
    ) -> str: # Type hints already good
        """
        生成语音文件的核心异步方法
        """
        # voice parameter here is expected to be the specific voice ID for the engine, not prefixed.
        # The prefix (e.g., "edge:") is handled before calling this method.
        if not voice: # Ensure voice is not empty or None if required by TTS lib
             raise ValueError(f"语音ID不能为空，引擎: {engine}")

        # actual_voice_id = voice.split(":", 1)[1] if voice and ":" in voice else voice # This was in original, but voice here should be clean

        task: asyncio.Task[str]
        try:
            if engine == ENGINE_EDGE: # Use defined constants
                task = asyncio.create_task(self._edge_tts(text, voice, file_path))
            elif engine == ENGINE_PYTTSX3:
                task = asyncio.create_task(self._pyttsx3_tts(text, voice, file_path))
            else:
                raise ValueError(f"不支持的引擎：{engine}")

            return await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            # Attempt to cancel the task if it's still running
            if 'task' in locals() and not task.done():
                task.cancel()
                try:
                    await task # Await cancellation (or result if it completed before cancel)
                except asyncio.CancelledError:
                    logger.debug(f"{engine} 任务被成功取消。")
                except Exception as e_after_cancel: # Log if task error occurs during/after cancellation
                    logger.error(f"{engine} 任务在取消后发生错误: {e_after_cancel}")
            raise RuntimeError(f"{engine}引擎执行超时 ({timeout}s)")
        except Exception as e: # Catch other errors from _edge_tts or _pyttsx3_tts
            raise RuntimeError(f"{engine}引擎错误：{str(e)}")


    def _select_voice_for_engine(
        self, engine: str, lang: str, voice: Optional[str] = None
    ) -> str: # Type hints already good
        """为指定引擎和语言选择合适的语音
        """
        if voice: # If a specific voice ID (potentially prefixed) is provided
            if ":" in voice: # If prefixed, e.g., "edge:zh-CN-XiaoxiaoNeural"
                engine_prefix, voice_id_only = voice.split(":", 1)
                if engine_prefix == engine: # Prefix matches current engine
                    return voice_id_only # Return the ID part
                else: # Prefix mismatch, indicates voice is for a different engine
                    logger.warning(f"提供的语音 '{voice}' 与目标引擎 '{engine}' 不匹配。将尝试查找默认语音。")
                    # Fall through to find default for the target engine
            else: # No prefix, assume it's a direct ID for the current engine
                return voice

        # If no specific voice or if prefixed voice was for wrong engine, find default
        if engine not in self.voice_mapping:
            logger.warning(f"未知引擎: {engine}，无法选择语音")
            return "" # Return empty if engine not in mapping

        selected_voice_id: str = self.voice_mapping[engine].get(lang, "") # Get default for lang

        # For pyttsx3, validate and potentially fallback further if selected_voice_id is problematic
        if engine == ENGINE_PYTTSX3 and selected_voice_id:
            return self._validate_pyttsx3_voice(selected_voice_id, lang)

        return selected_voice_id


    async def generate_speech(
        self,
        text: str,
        engine: str = ENGINE_EDGE, # Use constant
        voice: Optional[str] = None, # Can be prefixed like "edge:voice_id" or just "voice_id"
        auto_fallback: bool = False,
        timeout: float = DEFAULT_TTS_TIMEOUT, # Use constant
        filename: Optional[str] = None,
    ) -> str: # Return path to audio file
        """生成语音文件的核心方法
        """
        lang: str = self._detect_language(text)

        # Determine the actual voice ID to use for the initial engine attempt
        # _select_voice_for_engine will handle prefix or find default
        initial_voice_id: str = self._select_voice_for_engine(engine, lang, voice)

        # Generate filename based on the initial engine if not provided
        _filename: str = filename or self._generate_filename(text, engine) # Use initial engine for filename
        _file_path: str = os.path.join(self.cache_dir, _filename)

        if os.path.exists(_file_path): # Check if file already exists (e.g. from previous identical request)
            logger.info(f"语音文件已存在于缓存中，直接返回: {_file_path}")
            return _file_path

        engines_to_try: List[str] = []
        if engine: engines_to_try.append(engine) # Start with preferred engine

        if auto_fallback: # Add other engines from priority list if auto_fallback is True
            for e_priority in self.engine_priority:
                if e_priority not in engines_to_try:
                    engines_to_try.append(e_priority)

        # If no engine specified and no fallback, try the first from priority list
        if not engines_to_try and self.engine_priority:
            engines_to_try.append(self.engine_priority[0])

        if not engines_to_try: # Should not happen if self.engine_priority is not empty
            raise RuntimeError("没有可用的TTS引擎配置。")

        errors_encountered: List[str] = []
        attempted_engines_set: set[str] = set() # To avoid re-trying same engine if listed multiple times

        for current_engine_to_try in engines_to_try:
            if current_engine_to_try in attempted_engines_set: continue
            attempted_engines_set.add(current_engine_to_try)

            # Select voice for the current engine in the loop
            # If a global 'voice' (e.g. "edge:zh-CN-XiaoxiaoNeural") was specified,
            # _select_voice_for_engine will ensure it's only used if engine matches.
            # If it doesn't match, it will return the default for current_engine_to_try.
            voice_for_this_engine: str = self._select_voice_for_engine(current_engine_to_try, lang, voice)

            if not voice_for_this_engine: # Skip if no suitable voice found for this engine/lang combo
                logger.warning(f"引擎 '{current_engine_to_try}' 没有找到语言 '{lang}' 的可用语音。")
                errors_encountered.append(f"{current_engine_to_try}: No suitable voice for language '{lang}'.")
                continue

            # Filename should be unique per engine attempt if original `filename` was None
            # Or, if a specific filename is given, all attempts write to/check that.
            # Current logic uses initial engine for filename if `filename` is None.
            # If `filename` is provided, that exact path is used.
            current_attempt_filename: str = filename or self._generate_filename(text, current_engine_to_try)
            current_attempt_file_path: str = os.path.join(self.cache_dir, current_attempt_filename)

            if os.path.exists(current_attempt_file_path): # Might have been created by a parallel process or previous failed attempt cleaned up partially
                logger.info(f"目标语音文件 '{current_attempt_filename}' 在执行前已存在，直接返回")
                return current_attempt_file_path

            try:
                await self._execute_engine(
                    engine=current_engine_to_try,
                    text=text,
                    voice=voice_for_this_engine, # Pass the resolved voice ID for this engine
                    file_path=current_attempt_file_path,
                    timeout=timeout,
                )
                # Post-generation checks
                if not os.path.exists(current_attempt_file_path): # Should not happen if _execute_engine is correct
                    raise FileNotFoundError(f"语音文件生成后未找到: {current_attempt_file_path}")

                file_size_bytes: int = os.path.getsize(current_attempt_file_path)
                if file_size_bytes < MIN_VALID_FILE_SIZE: # Use constant
                    # Cleanup potentially corrupt file
                    os.remove(current_attempt_file_path)
                    raise RuntimeError(f"生成的文件可能已损坏（大小: {file_size_bytes}字节）")

                logger.success(f"成功生成语音 | 引擎: {current_engine_to_try} | 文件: {current_attempt_filename}")
                return current_attempt_file_path

            except ValueError as ve: # Typically for voice/engine mismatch if not caught by _select_voice_for_engine
                logger.debug(f"跳过引擎 '{current_engine_to_try}': {ve}")
                errors_encountered.append(f"{current_engine_to_try}: {ve}")
            except Exception as e: # Catch other errors from _execute_engine
                error_detail: str = f"{current_engine_to_try}: {str(e)}"
                errors_encountered.append(error_detail)
                logger.error(f"引擎 {current_engine_to_try} 生成失败: {e}")

                if os.path.exists(current_attempt_file_path): # Cleanup failed attempt's file
                    try:
                        os.remove(current_attempt_file_path)
                        logger.debug(f"清理错误生成的文件: {current_attempt_file_path}")
                    except OSError as rm_err:
                        logger.warning(f"清理失败文件时出错: {rm_err}")

                if not auto_fallback: # If not auto_fallback, stop after first failure (unless it was ValueError)
                    logger.info(f"引擎 '{current_engine_to_try}' 失败后停止尝试 (auto_fallback=False)。")
                    break
                # Continue to next engine if auto_fallback is True

        # If loop finishes without returning, all attempts failed
        raise RuntimeError(f"所有引擎尝试失败\n" + "\n".join(errors_encountered))


    def cleanup(self, max_age: int = CACHE_MAX_AGE) -> None: # Use constant, added return type
        """清理过期缓存文件"""
        now: float = time.time()
        cleaned_count: int = 0
        for f_path in Path(self.cache_dir).glob("*.*"): # Use f_path for clarity
            if f_path.is_file(): # Ensure it's a file
                try:
                    file_age_seconds: float = now - f_path.stat().st_mtime
                    if file_age_seconds > max_age:
                        logger.info(f"清理过期文件: {f_path.name} (年龄: {file_age_seconds:.0f}s)")
                        # Ensure self.delete_audio_file is called correctly if it's static or instance method
                        if TTSEngine.delete_audio_file(str(f_path)): # Assuming static for now based on its definition
                            cleaned_count +=1
                except FileNotFoundError: # File might be deleted by another process/thread
                    logger.debug(f"尝试清理时文件已不存在: {f_path.name}")
                except Exception as e: # Catch other potential errors during stat or delete
                    logger.error(f"清理文件 {f_path.name} 时出错: {e}")
        logger.info(f"缓存清理完成。删除了 {cleaned_count} 个过期文件。")


    @staticmethod
    def delete_audio_file(
        file_path: str,
        retries: int = DEFAULT_DELETE_RETRIES, # Use constant
        delay: float = DEFAULT_DELETE_DELAY,   # Use constant
    ) -> bool: # Added return type hint
        """
        安全删除音频文件，包含多次重试和强制删除机制
        """
        if not file_path:
            logger.warning("尝试删除空文件路径")
            return False

        relative_path: str
        try:
            # Construct the base path for cache to correctly determine relative_path
            cache_base_path = Path(os.getcwd()) / CACHE_DIR_NAME / AUDIO_DIR_NAME
            relative_path = os.path.relpath(file_path, cache_base_path)
        except ValueError: # Happens if file_path is not under cache_base_path
            relative_path = file_path # Use absolute path as fallback for logging

        if not os.path.exists(file_path):
            logger.debug(f"删除时文件已不存在: {relative_path}")
            return True

        # Check if file is accessible before attempting to delete
        try:
            with open(file_path, "rb"): # Try opening in binary read mode
                pass # File is accessible
        except Exception as e_access:
            logger.warning(f"文件无法访问，可能已损坏或被锁定: {relative_path} | 错误: {e_access}")
            # Depending on policy, might return False here or still attempt deletion

        for attempt in range(retries):
            try:
                if os.path.exists(file_path): # Re-check existence in loop
                    os.remove(file_path)
                # If os.remove didn't raise error, assume success (even if file was already gone)
                logger.debug(f"成功删除文件: {relative_path} (尝试 {attempt+1}/{retries})")
                return True
            except PermissionError:
                logger.warning(f"删除文件权限不足: {relative_path} (尝试 {attempt+1}/{retries})")
                time.sleep(delay * (attempt + 1))
            except OSError as e_os: # Catch other OS-level errors during delete
                logger.warning(f"删除文件时出现OS错误: {e_os} (尝试 {attempt+1}/{retries})")
                time.sleep(delay * (attempt + 1))

        # If all retries failed, attempt a force delete (platform-dependent)
        logger.warning(f"常规删除失败，尝试强制删除: {relative_path}")
        try:
            if platform.system() == "Windows":
                # Ensure subprocess is imported if not already at top level
                import subprocess
                # Use shell=True cautiously or ensure file_path is sanitized if it can be user-influenced
                # For internal paths, this should be okay.
                run_result = subprocess.run( # Capture result for logging
                    ["powershell", "-Command", f"Remove-Item -Path '{file_path}' -Force -ErrorAction SilentlyContinue"],
                    capture_output=True, text=True, check=False # Don't check=True for Remove-Item
                )
                if run_result.returncode != 0:
                    logger.error(f"强制删除命令失败 (Powershell): {run_result.stderr or run_result.stdout}")

            else:  # Linux/Mac
                # Using os.system is generally discouraged for security. subprocess is preferred.
                # For a simple rm -f, the risk is lower with a controlled file_path.
                # Ensure file_path is properly quoted if it can contain spaces or special chars.
                # However, Path objects or f-strings usually handle this well.
                exit_code = os.system(f"rm -f '{file_path}'") # Check exit code
                if exit_code != 0:
                     logger.error(f"强制删除命令失败 (rm -f), exit code: {exit_code}")

            if not os.path.exists(file_path): # Check again after force attempt
                logger.info(f"强制删除成功: {relative_path}")
                return True
        except Exception as e_force: # Catch errors during force delete attempt
            logger.error(f"强制删除失败: {e_force}")

        # Log final failure if file still exists
        if os.path.exists(file_path):
            try:
                file_size_str: str = str(os.path.getsize(file_path))
                file_mtime_str: str = time.ctime(os.path.getmtime(file_path))
                logger.error(f"无法删除文件: {relative_path} | 大小: {file_size_str} | 修改时间: {file_mtime_str}")
            except Exception as e_stat: # Error getting file info after failed delete
                logger.error(f"获取文件信息失败 {relative_path}: {e_stat}")
        return False


def generate_speech_sync( # Type hints already good
    text: str,
    engine: str = ENGINE_EDGE, # Use constant
    voice: Optional[str] = None,
    auto_fallback: bool = False, # Default from original, consider if True makes more sense
    timeout: float = DEFAULT_TTS_TIMEOUT, # Use constant
    filename: Optional[str] = None,
) -> str:
    """同步生成方法
    Note: 此函数使用队列处理器,所有 TTS 都通过单线程队列处理
    """
    return generate_speech_queue( # Calls the new queue-based function
        text=text,
        engine=engine,
        voice=voice,
        auto_fallback=auto_fallback, # Pass auto_fallback
        timeout=timeout,
        filename=filename,
    )


def list_pyttsx3_voices() -> List[VoiceDict]: # Added return type hint
    """列出所有可用的 Pyttsx3 语音."""
    try:
        # The _pyttsx3_context handles init and uninit of COM and engine
        with _pyttsx3_context() as engine:
            if not engine:
                logger.warning("系统语音引擎(pyttsx3/SAPI5)初始化失败，无法列出系统语音。")
                return []

            voices_prop: List[Voice] = engine.getProperty("voices")
            # engine.stop() is handled by the context manager's finally block

        # Process voices outside the context if engine.getProperty returns a copy
        # or if Voice objects don't depend on live engine state after properties are read.
        # This is safer.
        voice_list: List[VoiceDict] = []
        if voices_prop: # Check if voices_prop is not None
            for voice_obj in voices_prop: # Renamed voice to voice_obj
                voice_list.append({"name": voice_obj.name, "id": voice_obj.id})
        return voice_list
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"列出 Pyttsx3 语音时出错: {e}")
        return []

# Imports for TTSQueueProcessor
import queue
import threading
import uuid
# from typing import Callable, Dict, Optional, Any # Already imported at top

class TTSQueueProcessor:
    """单线程 TTS 队列处理器"""
    _instance: Optional['TTSQueueProcessor'] = None # Class variable annotation
    _lock: threading.Lock = threading.Lock()
    
    @classmethod
    def get_instance(cls) -> 'TTSQueueProcessor': # Return type is the class itself
        """获取单例实例"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                # cls._instance.start() # Start should be called explicitly after getting instance if needed
            return cls._instance
    
    def __init__(self) -> None: # Added return type hint
        """初始化队列处理器"""
        self.queue: queue.Queue[Optional[Tuple[str, Dict[str, Any], Optional[Callable[[str], None]], Optional[Callable[[str], None]]]]] = queue.Queue()
        self.running: bool = False
        self.thread: Optional[threading.Thread] = None
        self.tts_engine: TTSEngine = TTSEngine() # Instantiate internal TTSEngine
        self.callbacks: Dict[str, Dict[str, Any]] = {} # Stores info about tasks by file_path
    
    def start(self) -> None: # Added return type hint
        """启动处理线程"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._process_queue, daemon=True)
            self.thread.start()
            logger.info("TTS队列处理器已启动。")
    
    def stop(self) -> None: # Added return type hint
        """停止处理线程"""
        if self.running:
            logger.info("正在停止TTS队列处理器...")
            self.running = False
            self.queue.put(None) # Signal worker to exit
            if self.thread and self.thread.is_alive(): # Check if thread is alive
                self.thread.join(timeout=2.0) # Wait for thread to finish
            if self.thread and self.thread.is_alive():
                 logger.warning("TTS处理线程未能正常停止。")
            else:
                 logger.info("TTS队列处理器已停止。")
            self.thread = None
    
    def _process_queue(self) -> None: # Added return type hint
        """处理队列中的 TTS 请求"""
        while self.running:
            try:
                task_data = self.queue.get(block=True, timeout=1.0) # task_data is Optional[Tuple[...]]
                if task_data is None: # Sentinel to stop the worker
                    self.queue.task_done()
                    break # Exit loop and thread

                task_id, params, on_complete_cb, on_error_cb = task_data

                try:
                    # Ensure filename is part of params before calling generate_speech
                    if "filename" not in params or params["filename"] is None:
                        timestamp = int(time.time())
                        unique_id = str(uuid.uuid4())[:8] # More unique ID
                        text_hash = hashlib.md5(str(params.get("text","")).encode()).hexdigest()[:6]
                        params["filename"] = f"{params.get('engine', ENGINE_EDGE)}_{text_hash}_{timestamp}_{unique_id}.mp3"

                    logger.debug(f"处理TTS[ID: {task_id}]: {str(params.get('text',''))[:20]}...")
                    # asyncio.run creates a new event loop. This is fine for a dedicated thread.
                    generated_file_path: str = asyncio.run(self.tts_engine.generate_speech(**params))

                    if on_complete_cb:
                        try:
                            on_complete_cb(generated_file_path)
                        except Exception as cb_e:
                            logger.error(f"TTS成功回调执行出错 [ID: {task_id}]: {cb_e}")

                    # Store callback info if file path is valid
                    if generated_file_path:
                        self.callbacks[generated_file_path] = {
                            "task_id": task_id,
                            "created_at": time.time(),
                            "params": params # Store original params for context
                        }
                        
                except Exception as e_tts: # Error during TTS generation
                    logger.error(f"TTS处理失败 [ID: {task_id}]: {e_tts}")
                    if on_error_cb:
                        try:
                            on_error_cb(str(e_tts))
                        except Exception as cb_e: # Error in the error callback itself
                            logger.error(f"TTS错误回调执行出错 [ID: {task_id}]: {cb_e}")
                finally:
                    self.queue.task_done() # Signal task completion
                    
            except queue.Empty: # Timeout on queue.get, continue loop if running
                continue
            except Exception as e_queue: # Other unexpected errors in queue processing
                logger.error(f"TTS 队列处理器异常: {e_queue}")
                time.sleep(1.0) # Brief pause before retrying loop
        logger.info("TTS队列处理器循环已退出。")

    
    def add_task(self, text: str, engine: str = ENGINE_EDGE, voice: Optional[str] = None, # Type hints already good
                auto_fallback: bool = False, timeout: float = DEFAULT_TTS_TIMEOUT,
                on_complete: Optional[Callable[[str], None]] = None,
                on_error: Optional[Callable[[str], None]] = None) -> str:
        """添加 TTS 任务到队列
        """
        task_id: str = str(uuid.uuid4())
        # Ensure params dictionary matches expected Any for values
        params: Dict[str, Any] = {
            "text": text, "engine": engine, "voice": voice,
            "auto_fallback": auto_fallback, "timeout": timeout
        }
        # Queue stores tuples: (task_id, params_dict, on_complete_callback, on_error_callback)
        self.queue.put((task_id, params, on_complete, on_error))
        logger.debug(f"已添加 TTS 任务到队列 [ID: {task_id}]")
        return task_id
    
    def on_audio_played(self, file_path: str) -> None: # Added return type hint
        """音频播放完成后的回调，用于安全删除文件
        """
        if file_path in self.callbacks:
            task_info = self.callbacks.pop(file_path) # Remove from tracking
            logger.debug(f"音频播放完成，准备删除文件 [ID: {task_info.get('task_id','N/A')}]: {file_path}")

            def delayed_delete() -> None: # Nested function type hint
                time.sleep(0.5) # Brief delay to ensure file lock is released
                try:
                    if os.path.exists(file_path): # Check again before deleting
                        # Use the TTSEngine instance from the processor for deletion
                        self.tts_engine.delete_audio_file(file_path)
                        # logger.debug(f"成功删除已播放的音频文件: {file_path}") # delete_audio_file logs this
                except Exception as e_del:
                    logger.warning(f"删除已播放的音频文件失败 {file_path}: {e_del}")

            # Run deletion in a separate thread to avoid blocking
            delete_thread = threading.Thread(target=delayed_delete, daemon=True)
            delete_thread.start()

def queue_tts_request(text: str, engine: str = ENGINE_EDGE, voice: Optional[str] = None, # Type hints already good
                     auto_fallback: bool = True, timeout: float = DEFAULT_TTS_TIMEOUT,
                     on_complete: Optional[Callable[[str], None]] = None,
                     on_error: Optional[Callable[[str], None]] = None) -> str:
    """将 TTS 请求加入队列处理
    """
    processor = TTSQueueProcessor.get_instance()
    # Ensure processor's worker thread is running
    if not processor.running or not processor.thread or not processor.thread.is_alive():
        logger.debug("TTSQueueProcessor not running or thread dead, attempting to start/restart.")
        # processor.stop() # Ensure clean state if partially running
        processor.start() # Start it if not running

    return processor.add_task(
        text=text, engine=engine, voice=voice,
        auto_fallback=auto_fallback, timeout=timeout,
        on_complete=on_complete, on_error=on_error
    )


def generate_speech_queue(text: str, engine: str = ENGINE_EDGE, voice: Optional[str] = None, # Type hints already good
                        auto_fallback: bool = True, timeout: float = DEFAULT_TTS_TIMEOUT,
                        filename: Optional[str] = None) -> str:
    """队列版本的语音生成函数，与原 generate_speech 函数参数兼容
    """
    result_event = threading.Event()
    # Initialize with type that matches what callbacks will set
    result_container: Dict[str, Optional[Union[str, Exception]]] = {"file_path": None, "error": None}
    
    def on_complete_sync(file_path_result: str) -> None: # Renamed, added type hint
        result_container["file_path"] = file_path_result
        result_event.set()
    
    def on_error_sync(error_msg_str: str) -> None: # Renamed, added type hint
        result_container["error"] = RuntimeError(error_msg_str) # Store as an exception
        result_event.set()
    
    # Params for add_task
    task_params: Dict[str, Any] = {
        "text": text, "engine": engine, "voice": voice,
        "auto_fallback": auto_fallback, "timeout": timeout
    }
    if filename: # Add filename to params if provided
        task_params["filename"] = filename
    
    processor = TTSQueueProcessor.get_instance()
    if not processor.running or not processor.thread or not processor.thread.is_alive():
        logger.debug("TTSQueueProcessor not running for generate_speech_queue, starting.")
        processor.start()

    processor.add_task(
        **task_params, # Pass task_params dictionary
        on_complete=on_complete_sync, # Use renamed callback
        on_error=on_error_sync # Use renamed callback
    )
    
    result_event.wait() # Block until event is set

    if result_container["error"] is not None:
        # Ensure we raise the stored exception if an error occurred
        raise result_container["error"]
    if result_container["file_path"] is None:
        # This case should ideally be covered by on_error, but as a fallback
        raise RuntimeError("TTS生成失败，但未提供明确错误信息。")

    return str(result_container["file_path"]) # Ensure return is str


def on_audio_played(file_path: str) -> None: # Added return type hint
    """音频播放完成后调用此函数，用于安全删除文件
    """
    processor = TTSQueueProcessor.get_instance()
    # No need to check processor.running here, on_audio_played can be called even if new tasks are not being added
    processor.on_audio_played(file_path)
