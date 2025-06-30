import asyncio
import hashlib
import os
import platform
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import edge_tts
import pyttsx3
from pyttsx3.voice import Voice

if platform.system() == "Windows":
    import pythoncom
from loguru import logger

from file import config_center

# 默认用常量
DEFAULT_SPEED = 50
MAX_PYTTSX3_RATE = 400
MIN_PYTTSX3_RATE = 50
DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 5
DEFAULT_RETRY_DELAY = 1.0
MIN_VALID_FILE_SIZE = 10
CACHE_MAX_AGE = 86400  # 缓存最大保存时间(秒)


async def _get_edge_voices_async() -> Tuple[List[Dict[str, str]], Optional[str]]:
    """获取Edge TTS语音列表,优先大陆"""
    try:
        edge_voices = await edge_tts.list_voices()
        zh_voices = [
            {"name": voice["FriendlyName"], "id": f"edge:{voice['Name']}", "locale": voice["Locale"]}
            for voice in edge_voices
            if _is_zh_voice(voice["Locale"])
        ]

        def sort_key(voice: Dict[str, str]) -> int:
            name_lower = voice["name"].lower()
            locale_lower = voice["locale"].lower()
            if "mainland" in locale_lower or "cn" in locale_lower:
                if "xiaoxiao" in name_lower:
                    return 0
                return 1
            elif "hongkong" in locale_lower or "hk" in locale_lower:
                return 2
            elif "taiwan" in locale_lower or "tw" in locale_lower:
                return 3
            return 4

        zh_voices.sort(key=sort_key)
        return [{"name": v["name"], "id": v["id"]} for v in zh_voices], None
    except Exception as e:
        error_message = f"获取 Edge TTS 语音列表失败: {e}"
        return [], error_message


async def _get_pyttsx3_voices_async() -> Tuple[List[Dict[str, str]], Optional[str]]:
    """获取Pyttsx3语音列表"""
    try:
        with _pyttsx3_context() as engine:
            if not engine:
                return [], "pyttsx3引擎初始化失败或不可用"
            loop = asyncio.get_running_loop()
            voices_available = await loop.run_in_executor(None, engine.getProperty, "voices")
            return [
                {"name": voice.name, "id": f"pyttsx3:{voice.id}"}
                for voice in voices_available
                if _is_zh_pyttsx3_voice(voice)
            ], None
    except OSError as oe:
        error_message = ""
        if hasattr(oe, "winerror") and oe.winerror == -2147221005:
            error_message = "系统语音引擎(pyttsx3/SAPI5)初始化失败,可能是组件未正确注册或损坏,跳过加载系统语音"
        elif platform.system() != "Windows":
            error_message = f"在 {platform.system()} 上获取 Pyttsx3 语音列表时发生OS错误: {oe}。这可能是因为系统未安装或配置兼容的TTS引擎。将跳过加载系统语音。"
        else:
            error_message = f"获取 Pyttsx3 语音列表时发生OS错误: {oe}"
        return [], error_message
    except Exception as e:
        error_message = f"获取 Pyttsx3 语音列表失败: {e}"
        return [], error_message


def _is_zh_voice(locale: str) -> bool:
    """检查是否为中文语音"""
    return "zh" in locale.lower()


def _is_zh_pyttsx3_voice(voice: Voice) -> bool:
    """检查pyttsx3中文语音"""
    name = voice.name.lower()
    if hasattr(voice, "languages") and voice.languages:
        return any("zh" in lang.lower() for lang in voice.languages)
    if "chinese" in name or "mandarin" in name:
        return True
    return False


ENGINE_EDGE = "edge"
ENGINE_PYTTSX3 = "pyttsx3"


def get_available_engines() -> Dict[str, str]:
    """获取可用的TTS引擎及其显示名称."""
    engines = {
        ENGINE_EDGE: "Edge TTS",
    }
    if platform.system() == "Windows":
        engines[ENGINE_PYTTSX3] = "系统 TTS (pyttsx3)"
    return engines


def get_supported_languages() -> Dict[str, str]:
    """获取支持的语言列表及其显示名称

    返回:
        Dict[str, str]: 语言代码到显示名称的映射
    """
    return {
        LANG_ZH: "中文（简体）",
        LANG_EN: "English (US)",
        LANG_JA: "日本語",
        LANG_KO: "한국어",
        LANG_FR: "Français",
        LANG_DE: "Deutsch",
        LANG_ES: "Español",
        LANG_IT: "Italiano",
        LANG_RU: "Русский",
        LANG_PT: "Português (BR)",
    }


@contextmanager
def _pyttsx3_context() -> Any:
    """安全的pyttsx3引擎上下文管理器"""
    engine = None
    try:
        if platform.system() == "Windows":
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
        if platform.system() == "Windows":
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def filter_zh_voices(voices: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """筛选中文语音"""
    return [v for v in voices if "zh" in v.get("id", "").lower()]


def log_voices_summary(voices: List[Dict[str, str]]) -> None:
    """记录语音统计信息"""
    edge_count = len([v for v in voices if v["id"].startswith("edge:")])
    pyttsx3_count = len([v for v in voices if v["id"].startswith("pyttsx3:")])

    if edge_count > 0:
        logger.info(f"筛选了 {edge_count} 个 Edge 语音")
    if pyttsx3_count > 0:
        logger.info(f"筛选了 {pyttsx3_count} 个 Pyttsx3 语音")
    if not voices:
        logger.warning("未能获取到任何 TTS 语音")


_tts_voices_cache: Dict[str, Dict[str, Any]] = {
    "edge": {"voices": [], "timestamp": 0.0},
    "pyttsx3": {"voices": [], "timestamp": 0.0},
}


async def get_tts_voices(engine_filter: Optional[str] = None) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """异步获取可用的TTS语音列表(中文), 包括Edge和Pyttsx3.
    Args:
        engine_filter (Optional[str], optional): 指定引擎 ("edge" or "pyttsx3"). Defaults to None (获取所有).
    Returns:
        list: 语音列表,每个元素是 {'name': '显示名称', 'id': '引擎:语音ID'}
    """
    current_time = time.time()
    if engine_filter and engine_filter in _tts_voices_cache:
        cache_entry = _tts_voices_cache[engine_filter]
        if cache_entry["voices"] and (current_time - cache_entry["timestamp"] < CACHE_MAX_AGE):
            return cache_entry["voices"], None
    elif not engine_filter:
        all_cached = True
        combined_voices: List[Dict[str, str]] = []
        for eng, cache_entry in _tts_voices_cache.items():
            if not cache_entry["voices"] or (current_time - cache_entry["timestamp"] >= CACHE_MAX_AGE):
                all_cached = False
                break
            combined_voices.extend(cache_entry["voices"])
        if all_cached:
            return combined_voices, None
    voices = []
    overall_error = None

    if engine_filter is None or engine_filter == ENGINE_EDGE:
        edge_voices, edge_error = await _get_edge_voices_async()
        if edge_voices:
            voices.extend(edge_voices)
            _tts_voices_cache[ENGINE_EDGE]["voices"] = edge_voices
            _tts_voices_cache[ENGINE_EDGE]["timestamp"] = current_time
        else:
            logger.warning("Edge语音获取失败, 不缓存其结果。")
            if edge_error:
                overall_error = overall_error or edge_error

    if engine_filter is None or engine_filter == ENGINE_PYTTSX3:
        pyttsx3_voices, pyttsx3_error = await _get_pyttsx3_voices_async()
        if pyttsx3_voices:
            voices.extend(pyttsx3_voices)
            _tts_voices_cache[ENGINE_PYTTSX3]["voices"] = pyttsx3_voices
            _tts_voices_cache[ENGINE_PYTTSX3]["timestamp"] = current_time
        else:
            logger.warning("pyttsx3语音获取失败, 不缓存其结果。")
            if pyttsx3_error:
                overall_error = overall_error or pyttsx3_error

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, log_voices_summary, voices)

    return voices, overall_error


async def get_voice_id_by_name(name: str, engine_filter: Optional[str] = None) -> Optional[str]:
    """
    根据语音名称查找语音ID
    参数：
        name (str): 语音显示名称
        engine_filter (Optional[str]): 可选的引擎过滤器
    返回：
        str 或 None: 语音ID, 如果未找到则返回None
    """
    voices, _ = await get_tts_voices(engine_filter)
    for v in voices:
        if v["name"] == name:
            return v["id"]
    return None


async def get_voice_name_by_id(voice_id: str, available_voices: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """
    根据语音ID查找语音名称
    参数：
        voice_id (str): 语音ID
        available_voices (list, optional): 预先获取的语音列表,默认None(重新获取)
    返回：
        str 或 None: 语音名称,如果未找到则返回None
    """
    if available_voices is not None:
        voices = available_voices
    else:
        voices, _ = await get_tts_voices()
    return next((v["name"] for v in voices if v["id"] == voice_id), None)


# 一些多复用常量
ENGINE_EDGE = "edge"
ENGINE_PYTTSX3 = "pyttsx3"

# 支持的语言常量
LANG_ZH = "zh-CN"  # 中文（简体）
LANG_EN = "en-US"  # 英语（美国）
LANG_JA = "ja-JP"  # 日语
LANG_KO = "ko-KR"  # 韩语
LANG_FR = "fr-FR"  # 法语
LANG_DE = "de-DE"  # 德语
LANG_ES = "es-ES"  # 西班牙语
LANG_IT = "it-IT"  # 意大利语
LANG_RU = "ru-RU"  # 俄语
LANG_PT = "pt-BR"  # 葡萄牙语（巴西）

CACHE_DIR_NAME = "cache"
AUDIO_DIR_NAME = "audio"
DEFAULT_TTS_TIMEOUT = 10.0
DEFAULT_DELETE_RETRIES = 5
DEFAULT_DELETE_DELAY = 1.0


class TTSEngine:
    """支持多平台和智能语音选择的多引擎TTS工具类"""

    def __init__(self) -> None:
        """
        初始化TTS引擎实例
        属性：
        - cache_dir: 音频缓存目录路径（软件运行目录下 cache/audio文件夹）
        - engine_priority: 引擎优先级列表
        - voice_mapping: 跨平台语音映射配置表
        """
        self.cache_dir = os.path.join(os.getcwd(), CACHE_DIR_NAME, AUDIO_DIR_NAME)
        self._ensure_cache_dir()
        self.engine_priority = [ENGINE_EDGE, ENGINE_PYTTSX3]
        self.voice_mapping = {
            ENGINE_EDGE: {
                LANG_ZH: "zh-CN-YunxiNeural",
                LANG_EN: "en-US-AriaNeural",
                LANG_JA: "ja-JP-NanamiNeural",
                LANG_KO: "ko-KR-SunHiNeural",
                LANG_FR: "fr-FR-DeniseNeural",
                LANG_DE: "de-DE-KatjaNeural",
                LANG_ES: "es-ES-ElviraNeural",
                LANG_IT: "it-IT-ElsaNeural",
                LANG_RU: "ru-RU-SvetlanaNeural",
                LANG_PT: "pt-BR-FranciscaNeural",
            },
            ENGINE_PYTTSX3: self._get_platform_voices(),
        }

    @staticmethod
    def _get_platform_voices() -> Dict[str, str]:
        """
        获取当前平台的默认语音配置

        返回：
        - dict: 包含多语言语音ID的字典

        平台支持：
        - Windows: 使用注册表路径标识语音
        - macOS: 使用Apple语音标识符
        - Linux: 使用espeak语音名称
        """
        current_os = platform.system()
        platform_voices = {
            "Windows": {
                LANG_ZH: "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_ZH-CN_HUIHUI_11.0",
                LANG_EN: "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_EN-US_ZIRA_11.0",
                LANG_JA: "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_JA-JP_HARUKA_11.0",
            },
            "Darwin": {  # macOS
                LANG_ZH: "com.apple.speech.synthesis.voice.ting-ting.premium",
                LANG_EN: "com.apple.speech.synthesis.voice.Alex",
                LANG_JA: "com.apple.speech.synthesis.voice.kyoko.premium",
                LANG_FR: "com.apple.speech.synthesis.voice.thomas.premium",
                LANG_DE: "com.apple.speech.synthesis.voice.anna.premium",
                LANG_ES: "com.apple.speech.synthesis.voice.monica.premium",
                LANG_IT: "com.apple.speech.synthesis.voice.alice.premium",
                LANG_RU: "com.apple.speech.synthesis.voice.milena.premium",
            },
            "Linux": {
                LANG_ZH: "zh-CN",
                LANG_EN: "en-US",
                LANG_JA: "ja-JP",
                LANG_KO: "ko-KR",
                LANG_FR: "fr-FR",
                LANG_DE: "de-DE",
                LANG_ES: "es-ES",
                LANG_IT: "it-IT",
                LANG_RU: "ru-RU",
                LANG_PT: "pt-BR",
            },
        }
        return platform_voices.get(current_os, platform_voices["Linux"])

    def _ensure_cache_dir(self) -> None:
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _generate_filename(text: str, engine: str) -> str:
        timestamp = str(int(time.time()))
        hash_str = hashlib.md5(text.encode()).hexdigest()[:8]
        return f"{engine}_{hash_str}_{timestamp}.mp3"

    @staticmethod
    async def _edge_tts(text: str, voice: str, file_path: str) -> str:
        # 语速范围 0-100
        speed_value = int(config_center.read_conf("TTS", "speed"))
        rate_percentage = (speed_value - 50) * 2
        rate_str = f"{rate_percentage:+}%"
        logger.debug(f"Edge TTS Rate: {rate_str} (Slider: {speed_value})")
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        await communicate.save(file_path)
        return file_path

    async def _pyttsx3_tts(self, text: str, voice: str, file_path: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_pyttsx3, text, voice, file_path)

    @contextmanager
    def _pyttsx3_context(self) -> Generator[Any, None, None]:
        """pyttsx3引擎的上下文管理器"""
        if platform.system() != "Windows":
            raise RuntimeError("pyttsx3 仅支持 Windows 系统")

        engine = None
        com_initialized = False
        max_retries = 3

        for attempt in range(max_retries):
            try:
                pythoncom.CoInitialize()
                com_initialized = True
                logger.debug(f"正在初始化pyttsx3引擎 (尝试 {attempt + 1}/{max_retries})")
                engine = pyttsx3.init()
                if engine:
                    try:
                        rate = engine.getProperty("rate")
                        logger.debug(f"pyttsx3引擎初始化成功, 当前语速: {rate}")
                        voices = engine.getProperty("voices")
                        if not voices or len(voices) == 0:
                            logger.warning("pyttsx3引擎未检测到任何语音")
                            raise RuntimeError("未检测到语音")

                        logger.debug(f"pyttsx3引擎检测到 {len(voices)} 个语音")
                        yield engine
                        return
                    except Exception as check_e:
                        logger.warning(f"pyttsx3引擎验证失败: {check_e}")
                        raise RuntimeError(f"引擎验证失败: {check_e}")
                else:
                    logger.warning("pyttsx3引擎初始化返回空引擎")
                    raise RuntimeError("初始化返回空引擎")

            except OSError as oe:
                if hasattr(oe, "winerror") and oe.winerror == -2147221005:
                    logger.error(
                        f"系统语音引擎(pyttsx3/SAPI5)初始化失败 (尝试 {attempt + 1}/{max_retries}), "
                        f"错误码: {oe.winerror}。请检查系统语音组件。"
                    )
                else:
                    logger.error(f"pyttsx3初始化时发生OS错误 (尝试 {attempt + 1}/{max_retries}): {oe}")
                if engine:
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    engine = None

                if com_initialized:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass
                    com_initialized = False
                if attempt == max_retries - 1:
                    raise RuntimeError(f"pyttsx3/SAPI5 初始化失败, 已重试 {max_retries} 次") from oe
                wait_time = (attempt + 1) * 1.0
                logger.info(f"等待 {wait_time} 秒后重试pyttsx3初始化...")
                time.sleep(wait_time)

            except Exception as init_e:
                logger.error(f"pyttsx3初始化失败 (尝试 {attempt + 1}/{max_retries}): {init_e}")
                if engine:
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    engine = None

                if com_initialized:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass
                    com_initialized = False
                if attempt == max_retries - 1:
                    raise RuntimeError(f"pyttsx3初始化异常, 已重试 {max_retries} 次") from init_e
                wait_time = (attempt + 1) * 1.0
                logger.info(f"等待 {wait_time} 秒后重试pyttsx3初始化...")
                time.sleep(wait_time)
            finally:
                if engine:
                    try:
                        engine.stop()
                    except Exception as e:
                        logger.warning(f"关闭pyttsx3引擎时出错: {e}")
                    engine = None

                if com_initialized:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception as e:
                        logger.warning(f"释放COM环境时出错: {e}")
                    com_initialized = False

    @staticmethod
    def _sync_pyttsx3(text: str, voice: str, file_path: str) -> str:
        """同步生成语音文件(pyttsx3)"""
        temp_dir = os.path.dirname(file_path)
        temp_filename = f"temp_{int(time.time())}_{os.getpid()}_{hash(text) % 10000}.mp3"
        temp_file_path = os.path.join(temp_dir, temp_filename)
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.warning(f"无法删除已存在的临时文件: {temp_file_path}, 错误: {e}")
                temp_filename = f"temp_{int(time.time())}_{os.getpid()}_{hash(text + str(time.time())) % 10000}.mp3"
                temp_file_path = os.path.join(temp_dir, temp_filename)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with TTSEngine()._pyttsx3_context() as engine:
                    if not engine:
                        raise RuntimeError("无法初始化 pyttsx3 引擎")
                    if voice:
                        voices = engine.getProperty("voices")
                        found_voice = next((v for v in voices if v.id == voice), None)
                        if not found_voice:
                            voice_id_only = voice.split(":", 1)[-1]
                            found_voice = next((v for v in voices if v.id == voice_id_only), None)
                        if found_voice:
                            engine.setProperty("voice", found_voice.id)
                        else:
                            logger.warning(f"pyttsx3: 无效或不匹配的语音ID '{voice}', 将使用默认语音")
                    speed_value = int(config_center.read_conf("TTS", "speed"))
                    default_rate = engine.getProperty("rate")
                    if speed_value == 50:
                        pyttsx3_rate = default_rate
                    elif speed_value < 50:
                        # 0-50范围映射到0.5-1.0倍速
                        pyttsx3_rate = int(default_rate / 2 + (default_rate / 2) * (speed_value / 50))
                    else:
                        # 50-100范围映射到1.0-1.5倍速
                        pyttsx3_rate = int(default_rate + (default_rate * 0.5) * ((speed_value - 50) / 50))
                    pyttsx3_rate = max(MIN_PYTTSX3_RATE, min(pyttsx3_rate, MAX_PYTTSX3_RATE))
                    logger.debug(f"pyttsx3 Rate: {pyttsx3_rate} (Slider: {speed_value}, Default: {default_rate})")
                    engine.setProperty("rate", pyttsx3_rate)
                    engine.save_to_file(text, temp_file_path)
                    # logger.debug(f"开始生成语音到临时文件: {temp_file_path}")
                    engine.runAndWait()
                    if not os.path.exists(temp_file_path):
                        raise FileNotFoundError(f"语音生成后临时文件未找到: {temp_file_path}")

                    file_size = os.path.getsize(temp_file_path)
                    if file_size < MIN_VALID_FILE_SIZE:
                        raise RuntimeError(f"生成的临时文件可能已损坏（大小: {file_size}字节）")
                    try:
                        with open(temp_file_path, "rb") as f:
                            header = f.read(10)
                            if not header or len(header) < 10:
                                raise RuntimeError(f"临时文件头部无效, 可能已损坏")
                    except Exception as e:
                        raise RuntimeError(f"无法读取生成的临时文件: {e}")
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        os.rename(temp_file_path, file_path)
                    except Exception as e:
                        logger.warning(f"重命名临时文件失败: {e}, 尝试复制内容")
                        try:
                            with open(temp_file_path, "rb") as src, open(file_path, "wb") as dst:
                                dst.write(src.read())
                            logger.debug(f"成功通过复制内容创建目标文件: {file_path}")
                        except Exception as copy_e:
                            raise RuntimeError(f"无法创建目标文件: {copy_e}")
                    if not os.path.exists(file_path):
                        raise FileNotFoundError(f"最终目标文件未找到: {file_path}")
                    file_size = os.path.getsize(file_path)
                    if file_size < MIN_VALID_FILE_SIZE:
                        raise RuntimeError(f"最终目标文件可能已损坏（大小: {file_size}字节）")

                    return file_path

            except Exception as e:
                logger.error(f"pyttsx3 语音生成失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except Exception as rm_e:
                        logger.warning(f"清理临时文件失败: {rm_e}")
                if attempt == max_retries - 1:
                    raise RuntimeError(f"pyttsx3 语音生成失败, 已重试 {max_retries} 次: {e}")
                wait_time = (attempt + 1) * 0.5
                time.sleep(wait_time)
        raise RuntimeError("pyttsx3 语音生成失败, 未知错误")

    @staticmethod
    def _detect_language(text: str) -> str:
        """检测文本语言, 优先使用配置中的语言设置

        参数:
            text: 要检测的文本

        返回:
            语言代码: 支持的语言代码之一
        """
        # 优先从配置中读取语言设置
        config_language = config_center.read_conf("TTS", "language")
        if config_language:
            # 这里不应该是我做,但是我还是留一下吧
            # 标准化语言代码映射
            lang_mapping = {
                "zh-cn": LANG_ZH,
                "zh": LANG_ZH,
                "chinese": LANG_ZH,
                "en-us": LANG_EN,
                "en": LANG_EN,
                "english": LANG_EN,
                "ja-jp": LANG_JA,
                "ja": LANG_JA,
                "japanese": LANG_JA,
                "ko-kr": LANG_KO,
                "ko": LANG_KO,
                "korean": LANG_KO,
                "fr-fr": LANG_FR,
                "fr": LANG_FR,
                "french": LANG_FR,
                "de-de": LANG_DE,
                "de": LANG_DE,
                "german": LANG_DE,
                "es-es": LANG_ES,
                "es": LANG_ES,
                "spanish": LANG_ES,
                "it-it": LANG_IT,
                "it": LANG_IT,
                "italian": LANG_IT,
                "ru-ru": LANG_RU,
                "ru": LANG_RU,
                "russian": LANG_RU,
                "pt-br": LANG_PT,
                "pt": LANG_PT,
                "portuguese": LANG_PT,
            }

            config_lang_lower = config_language.lower().strip()
            if config_lang_lower in lang_mapping:
                return lang_mapping[config_lang_lower]
        # 如果配置中没有设置或无效, 则回退到文本检测
        # 检测中文字符
        if re.search("[一-鿿]", text):
            return LANG_ZH
        # 检测日文字符（平假名、片假名）
        elif re.search("[ひ-ゟ]|[ァ-ヿ]", text):
            return LANG_JA
        # 检测韩文字符
        elif re.search("[가-힣]", text):
            return LANG_KO
        # 检测俄文字符
        elif re.search("[а-яё]", text, re.IGNORECASE):
            return LANG_RU
        # 默认返回英语
        return LANG_EN

    def _validate_pyttsx3_voice(self, voice_id: str, lang: str) -> str:
        """验证pyttsx3语音ID有效性, 并在无效时自动回退

        参数:
            voice_id: 要验证的语音ID
            lang: 语言代码

        返回:
            有效的语音ID或空字符串（表示无法使用pyttsx3）
        """
        try:
            with self._pyttsx3_context() as engine:
                voices = engine.getProperty("voices")
                if any(v.id == voice_id for v in voices):
                    return voice_id
                lang_voices = [v for v in voices if lang in str(v.languages)]
                if lang_voices:
                    logger.info(f"找到{lang}语言的替代语音: {lang_voices[0].id}")
                    return lang_voices[0].id

                default_voice = engine.getProperty("voice")
                if default_voice and isinstance(default_voice, str):
                    logger.info(f"使用默认语音: {default_voice}")
                    return default_voice
                else:
                    logger.warning("pyttsx3无可用默认语音, 无法回退。")
                    return ""

        except (OSError, RuntimeError) as e:
            logger.warning(f"pyttsx3语音验证过程中发生引擎错误, 无法使用pyttsx3: {e}")
            return ""
        except Exception as e:
            logger.error(f"pyttsx3语音验证失败: {str(e)}")
            return ""

    async def _execute_engine(self, engine: str, text: str, voice: str, file_path: str, timeout: float) -> str:
        """
        生成语音文件的核心异步方法

        参数：
        text (str): 要转换的文本内容（支持中英文自动检测）
        engine (str): 首选TTS引擎（默认edge）
        voice (str): 指定语音ID（可选）, 不指定则根据语言自动选择
        auto_fallback (bool): 引擎失败时是否自动回退（默认False）
        timeout (float): 单引擎超时时间（秒, 默认10）
        filename (str): 自定义文件名（可选）, 不指定则自动生成

        返回：
        str: 生成的音频文件绝对路径

        异常：
        ValueError: 如果提供的语音ID与指定的引擎不匹配
        RuntimeError: 所有尝试的引擎均失败时抛出
        """
        if voice and not voice.startswith(f"{engine}:"):
            raise ValueError(f"语音ID '{voice}' 与引擎 '{engine}' 不匹配")

        actual_voice_id = voice.split(":", 1)[1] if voice and ":" in voice else voice
        try:
            if engine == "edge":
                task = self._edge_tts(text, actual_voice_id, file_path)
            elif engine == "pyttsx3":
                task = self._pyttsx3_tts(text, actual_voice_id, file_path)
            else:
                raise ValueError(f"不支持的引擎：{engine}")

            return await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"{engine}引擎执行超时")
        except Exception as e:
            raise RuntimeError(f"{engine}引擎错误：{str(e)}")

    def _select_voice_for_engine(self, engine: str, lang: str, voice: Optional[str] = None) -> str:
        """为指定引擎和语言选择合适的语音

        参数:
            engine: 引擎名称
            lang: 语言代码
            voice: 可选的指定语音ID

        返回:
            选择的语音ID
        """
        if voice:
            return voice
        if engine not in self.voice_mapping:
            logger.warning(f"未知引擎: {engine}, 无法选择语音")
            return ""

        selected_voice = self.voice_mapping[engine].get(lang, "")
        if engine == ENGINE_PYTTSX3 and selected_voice:
            return self._validate_pyttsx3_voice(selected_voice, lang)

        return selected_voice

    async def generate_speech(
        self,
        text: str,
        engine: str = ENGINE_EDGE,
        voice: Optional[str] = None,
        auto_fallback: bool = False,
        timeout: float = DEFAULT_TTS_TIMEOUT,
        filename: Optional[str] = None,
    ) -> str:
        """生成语音文件的核心方法

        参数：
            text: 要转换的文本内容
            engine: 首选TTS引擎（默认edge）
            voice: 指定语音ID（可选）
            auto_fallback: 引擎失败时是否自动回退
            timeout: 单引擎超时时间（秒）
            filename: 自定义文件名（可选）

        返回：
            生成的音频文件绝对路径

        异常：
            RuntimeError: 所有尝试的引擎均失败时抛出
        """
        lang = self._detect_language(text)
        voice = self._select_voice_for_engine(engine, lang, voice)
        _filename = filename or self._generate_filename(text, engine)
        _file_path = os.path.join(self.cache_dir, _filename)
        if os.path.exists(_file_path):
            logger.info(f"语音文件已存在于缓存中, 直接返回: {_file_path}")
            return _file_path
        engines_to_try = []
        if engine:
            engines_to_try.append(engine)
        if auto_fallback:
            for e in self.engine_priority:
                if e not in engines_to_try:
                    engines_to_try.append(e)
        if not engines_to_try and self.engine_priority:
            engines_to_try.append(self.engine_priority[0])

        if not engines_to_try:
            raise RuntimeError("没有可用的TTS引擎配置。")
        errors = []
        attempted_engines = set()
        for current_engine in engines_to_try:
            if current_engine in attempted_engines:
                continue
            attempted_engines.add(current_engine)
            if voice and ":" in voice and not voice.startswith(current_engine + ":"):
                logger.debug(f"跳过引擎 '{current_engine}', 语音ID不匹配")
                continue
            current_filename = filename if filename else self._generate_filename(text, current_engine)
            current_file_path = os.path.join(self.cache_dir, current_filename)

            if os.path.exists(current_file_path):
                logger.info(f"目标语音文件 '{current_filename}' 在执行前已存在, 直接返回")
                return current_file_path

            try:
                await self._execute_engine(
                    engine=current_engine,
                    text=text,
                    voice=voice,
                    file_path=current_file_path,
                    timeout=timeout,
                )
                if not os.path.exists(current_file_path):
                    raise RuntimeError(f"语音文件生成后未找到: {current_file_path}")
                file_size = os.path.getsize(current_file_path)
                if file_size < 10:  # 小于10kb应该是损坏的
                    raise RuntimeError(f"生成的文件可能已损坏（大小: {file_size}字节）")

                logger.success(f"成功生成语音 | 引擎: {current_engine} | 文件: {current_filename}")
                return current_file_path
            except ValueError as ve:
                # 一般都是是语音ID不匹配
                logger.debug(f"跳过引擎 '{current_engine}': {ve}")
            except Exception as e:
                error_msg = f"{current_engine}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"引擎 {current_engine} 生成失败: {e}")
                if os.path.exists(current_file_path):
                    try:
                        os.remove(current_file_path)
                        logger.debug(f"清理错误生成的文件: {current_file_path}")
                    except OSError as rm_err:
                        logger.warning(f"清理失败文件时出错: {rm_err}")
                if not auto_fallback:
                    logger.info(f"引擎 '{current_engine}' 失败后停止尝试")
                    break
                continue
        raise RuntimeError(f"所有引擎尝试失败\n" + "\n".join(errors))

    def cleanup(self, max_age: int = 86400) -> None:
        """清理过期缓存文件"""
        now = time.time()
        for f in Path(self.cache_dir).glob("*.*"):
            if f.is_file() and (now - f.stat().st_mtime) > max_age:
                logger.info(f"清理过期文件: {f.name}")
                self.delete_audio_file(str(f))

    @staticmethod
    def delete_audio_file(
        file_path: str,
        retries: int = DEFAULT_DELETE_RETRIES,
        delay: float = DEFAULT_DELETE_DELAY,
    ) -> bool:
        """
        安全删除音频文件, 包含多次重试和强制删除机制

        参数:
            file_path: 要删除的文件路径
            retries: 重试次数
            delay: 重试间隔(秒)

        返回:
            bool: 删除是否成功
        """
        if not file_path:
            logger.warning("尝试删除空文件路径")
            return False
        try:
            relative_path = os.path.relpath(file_path, os.path.join(os.getcwd(), CACHE_DIR_NAME, AUDIO_DIR_NAME))
        except ValueError:
            relative_path = file_path
        if not os.path.exists(file_path):
            logger.debug(f"删除时文件已不存在: {relative_path}")
            return True
        try:
            with open(file_path, "rb") as _:
                pass
        except Exception as e:
            logger.warning(f"文件无法访问, 可能已损坏或被锁定: {relative_path} | 错误: {e}")
        for attempt in range(retries):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"成功删除文件: {relative_path} (尝试 {attempt + 1}/{retries})")
                return True
            except PermissionError:
                logger.warning(f"删除文件权限不足, 等待后重试: {relative_path} (尝试 {attempt + 1}/{retries})")
                time.sleep(delay * (attempt + 1))
            except OSError as e:
                logger.warning(f"删除文件时出现OS错误: {e} (尝试 {attempt + 1}/{retries})")
                time.sleep(delay * (attempt + 1))
        try:
            logger.warning(f"常规删除失败, 尝试强制删除: {relative_path}")

            if platform.system() == "Windows":
                import subprocess

                subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        f"Remove-Item -Path '{file_path}' -Force",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:  # Linux/Mac
                os.system(f"rm -f '{file_path}'")
            if not os.path.exists(file_path):
                logger.info(f"强制删除成功: {relative_path}")
                return True
        except Exception as e:
            logger.error(f"强制删除失败: {e}")
        try:
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else "未知"
            file_mtime = time.ctime(os.path.getmtime(file_path)) if os.path.exists(file_path) else "未知"
            logger.error(f"无法删除文件: {relative_path} | 大小: {file_size} | 修改时间: {file_mtime}")
        except Exception as e:
            logger.error(f"获取文件信息失败: {e}")

        return False


def generate_speech_sync(
    text: str,
    engine: str = "edge",
    voice: Optional[str] = None,
    auto_fallback: bool = False,
    timeout: float = 10.0,
    filename: Optional[str] = None,
) -> str:
    """同步生成方法

    Note: 此函数使用队列处理器,所有 TTS 都通过单线程队列处理
    """
    return generate_speech_queue(
        text=text,
        engine=engine,
        voice=voice,
        auto_fallback=auto_fallback,
        timeout=timeout,
        filename=filename,
    )


def list_pyttsx3_voices() -> List[Dict[str, str]]:
    """列出所有可用的 Pyttsx3 语音."""
    try:
        try:
            engine = pyttsx3.init()
        except OSError as oe:
            if hasattr(oe, "winerror") and oe.winerror == -2147221005:
                logger.warning("系统语音引擎(pyttsx3/SAPI5)初始化失败, 无法列出系统语音。")
                return []
            else:
                logger.error(f"列出语音时 pyttsx3 初始化发生OS错误: {oe}")
                return []
        except Exception as init_e:
            logger.error(f"列出语音时 pyttsx3 初始化失败: {init_e}")
            return []

        voices = engine.getProperty("voices")
        engine.stop()
        voice_list = []
        for voice in voices:
            voice_list.append({"name": voice.name, "id": voice.id})
        return voice_list
    except Exception as e:
        logger.error(f"列出 Pyttsx3 语音时出错: {e}")
        return []


import queue
import threading
import uuid
from typing import Any, Callable, Dict, Optional


class TTSQueueProcessor:
    """单线程 TTS 队列处理器"""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TTSQueueProcessor":
        """获取单例实例"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                cls._instance.start()
            return cls._instance

    def __init__(self) -> None:
        """初始化队列处理器"""
        self.queue: "queue.Queue[Optional[Tuple[str, Dict[str, Any], Optional[Callable[[str], None]], Optional[Callable[[str], None]]]]]" = queue.Queue()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.tts_engine = TTSEngine()
        self.callbacks: Dict[str, Dict[str, Any]] = {}

    def start(self) -> None:
        """启动处理线程"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._process_queue, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        """停止处理线程"""
        if self.running:
            self.running = False
            self.queue.put(None)
            if self.thread:
                self.thread.join(timeout=2.0)

    def _process_queue(self) -> None:
        """处理队列中的 TTS 请求"""
        while self.running:
            try:
                task = self.queue.get(block=True, timeout=1.0)
                if task is None:
                    self.queue.task_done()
                    continue
                task_id, params, on_complete, on_error = task
                try:
                    if "filename" not in params:
                        timestamp = int(time.time())
                        unique_id = str(uuid.uuid4())[:8]
                        text_hash = hashlib.md5(params["text"].encode()).hexdigest()[:6]
                        params["filename"] = f"{params.get('engine', 'edge')}_{text_hash}_{timestamp}_{unique_id}.mp3"
                    text_preview = params.get("text", "")
                    logger.debug(f"处理TTS[ID: {task_id}]: {text_preview[:20] if text_preview else ''}...")
                    file_path = asyncio.run(self.tts_engine.generate_speech(**params))
                    if on_complete:
                        try:
                            on_complete(file_path)
                        except Exception as cb_e:
                            logger.error(f"TTS成功回调执行出错 [ID: {task_id}]: {cb_e}")
                    if file_path:
                        self.callbacks[file_path] = {"task_id": task_id, "created_at": time.time(), "params": params}

                except Exception as e:
                    logger.error(f"TTS处理失败 [ID: {task_id}]: {e}")
                    if on_error:
                        try:
                            on_error(str(e))
                        except Exception as cb_e:
                            logger.error(f"TTS错误回调执行出错 [ID: {task_id}]: {cb_e}")

                finally:
                    self.queue.task_done()

            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"TTS 队列处理器异常: {e}")
                time.sleep(1.0)

    def add_task(
        self,
        text: str,
        engine: str = ENGINE_EDGE,
        voice: Optional[str] = None,
        auto_fallback: bool = False,
        timeout: float = DEFAULT_TTS_TIMEOUT,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> str:
        """添加 TTS 任务到队列

        参数:
            text: 要转换的文本
            engine: TTS 引擎
            voice: 语音 ID
            auto_fallback: 是否自动回退到其他引擎
            timeout: 超时时间
            on_complete: 成功回调函数, 参数为生成的文件路径
            on_error: 错误回调函数, 参数为错误信息

        返回:
            任务 ID
        """
        task_id = str(uuid.uuid4())
        params = {"text": text, "engine": engine, "voice": voice, "auto_fallback": auto_fallback, "timeout": timeout}

        self.queue.put((task_id, params, on_complete, on_error))
        logger.debug(f"已添加 TTS 任务到队列 [ID: {task_id}]")
        return task_id

    def on_audio_played(self, file_path: str) -> None:
        """音频播放完成后的回调, 用于安全删除文件

        参数:
            file_path: 播放完成的音频文件路径
        """
        if file_path in self.callbacks:
            task_info = self.callbacks.pop(file_path)
            logger.debug(f"音频播放完成, 准备删除文件 [ID: {task_info['task_id']}]: {file_path}")

            def delayed_delete() -> None:
                time.sleep(0.5)
                try:
                    if os.path.exists(file_path):
                        self.tts_engine.delete_audio_file(file_path)
                        logger.debug(f"成功删除已播放的音频文件: {file_path}")
                except Exception as e:
                    logger.warning(f"删除已播放的音频文件失败: {e}")

            threading.Thread(target=delayed_delete, daemon=True).start()


def queue_tts_request(
    text: str,
    engine: str = ENGINE_EDGE,
    voice: Optional[str] = None,
    auto_fallback: bool = True,
    timeout: float = DEFAULT_TTS_TIMEOUT,
    on_complete: Optional[Callable[[str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> str:
    """将 TTS 请求加入队列处理

    参数:
        text: 要转换的文本
        engine: TTS 引擎
        voice: 语音 ID
        auto_fallback: 是否自动回退到其他引擎
        timeout: 超时时间
        on_complete: 成功回调函数, 参数为生成的文件路径
        on_error: 错误回调函数, 参数为错误信息

    返回:
        任务 ID
    """
    processor = TTSQueueProcessor.get_instance()
    return processor.add_task(
        text=text,
        engine=engine,
        voice=voice,
        auto_fallback=auto_fallback,
        timeout=timeout,
        on_complete=on_complete,
        on_error=on_error,
    )


def generate_speech_queue(
    text: str,
    engine: str = ENGINE_EDGE,
    voice: Optional[str] = None,
    auto_fallback: bool = True,
    timeout: float = DEFAULT_TTS_TIMEOUT,
    filename: Optional[str] = None,
) -> str:
    """队列版本的语音生成函数, 与原 generate_speech 函数参数兼容

    这个函数是 generate_speech 的队列版本, 将请求放入队列中串行处理,
    避免并发问题。它会阻塞直到语音生成完成, 与原函数行为一致。

    参数:
        text: 要转换的文本
        engine: TTS 引擎
        voice: 语音 ID
        auto_fallback: 是否自动回退到其他引擎
        timeout: 超时时间
        filename: 自定义文件名

    返回:
        生成的音频文件路径
    """
    result_event = threading.Event()
    result_container = {"file_path": None, "error": None}

    def on_complete(file_path) -> None:
        result_container["file_path"] = file_path
        result_event.set()

    def on_error(error_msg) -> None:
        result_container["error"] = error_msg
        result_event.set()

    params = {"text": text, "engine": engine, "voice": voice, "auto_fallback": auto_fallback, "timeout": timeout}

    if filename:
        params["filename"] = filename
    processor = TTSQueueProcessor.get_instance()
    processor.add_task(
        text=text,
        engine=engine,
        voice=voice,
        auto_fallback=auto_fallback,
        timeout=timeout,
        on_complete=on_complete,
        on_error=on_error,
    )
    result_event.wait()
    if result_container["error"]:
        raise RuntimeError(f"TTS生成失败: {result_container['error']}")

    file_path = result_container["file_path"]
    if file_path is None:
        raise RuntimeError("TTS生成失败: 未获取到文件路径")
    return file_path


def on_audio_played(file_path: str) -> None:
    """音频播放完成后调用此函数, 用于安全删除文件

    参数:
        file_path: 播放完成的音频文件路径
    """
    processor = TTSQueueProcessor.get_instance()
    processor.on_audio_played(file_path)
