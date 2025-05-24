import asyncio
import hashlib
import os
import platform
import re
import time
from pathlib import Path
from typing import Optional

import edge_tts
import pyttsx3
from loguru import logger
from file import config_center

def get_tts_voices():
    """获取可用的TTS语音列表(中文)，包括Edge和Pyttsx3."""
    voices = []
    try:
        edge_voices = asyncio.run(edge_tts.list_voices())
        for voice in edge_voices:
            if 'zh' in voice['Locale'].lower(): # 筛选中文语音
                voices.append({'name': f"{voice['FriendlyName']} (Edge)", 'id': f"edge:{voice['Name']}"})
        logger.debug(f"筛选了 {len(voices)} 个 Edge 语音")
    except Exception as e:
        logger.error(f"获取 Edge TTS 语音列表失败: {e}")
    pyttsx3_voices_count = 0
    try:
        engine = pyttsx3.init()
        pyttsx3_voices = engine.getProperty('voices')
        engine.stop() # 释放引擎资源
        for voice in pyttsx3_voices:
            name = voice.name
            # Tip：pyttsx3语言信息不标准
            lang_check_passed = False
            if hasattr(voice, 'languages') and voice.languages:
                if any('zh' in lang.lower() for lang in voice.languages):
                    lang_check_passed = True
            elif 'chinese' in name.lower() or 'mandarin' in name.lower(): # 备用
                 lang_check_passed = True
            if not hasattr(voice, 'languages') or not voice.languages or lang_check_passed:
                 voices.append({'name': f"{name} (System)", 'id': f"pyttsx3:{voice.id}"})
        pyttsx3_voices_count = len(pyttsx3_voices)
    except OSError as oe:
        if oe.winerror == -2147221005:
            logger.warning("系统语音引擎(pyttsx3/SAPI5)初始化失败，可能是组件未正确注册或损坏。将跳过加载系统语音。")
        else:
            logger.error(f"获取 Pyttsx3 语音列表时发生OS错误: {oe}")
    except Exception as e:
        logger.error(f"获取 Pyttsx3 语音列表失败: {e}")
    if pyttsx3_voices_count > 0:
        logger.debug(f"筛选了 {pyttsx3_voices_count} 个 Pyttsx3 语音")

    if not voices:
        logger.warning("未能获取到任何 TTS 语音")

    return voices

def get_voice_id_by_name(name: str, engine: str = "edge"):
    """
    根据语音名称查找语音ID
    参数：name (str): 语音显示名称
    返回：str，语音ID
    """
    voices = get_tts_voices()
    for v in voices:
        if v["name"] == name:
            return v["id"]
    return None

def get_voice_name_by_id(voice_id: str, available_voices: Optional[list] = None) -> Optional[str]:
    """
    根据语音ID查找语音名称.
    参数：
        voice_id (str): 语音ID
        available_voices (list, optional): 预先获取的语音列表,默认None(重新获取)
    返回：
        str or None: 语音名称,如果未找到则返回None
    """
    if available_voices is None:
        voices = get_tts_voices()
    else:
        voices = available_voices

    for v in voices:
        if v["id"] == voice_id:
            return v["name"]
    return None


class TTSEngine:
    """支持多平台和智能语音选择的多引擎TTS工具类"""

    def __init__(self):
        """
        初始化TTS引擎实例
        属性：
        - cache_dir: 音频缓存目录路径（软件运行目录下 cache/audio文件夹）
        - engine_priority: 引擎优先级列表
        - voice_mapping: 跨平台语音映射配置表
        """
        self.cache_dir = os.path.join(os.getcwd(), "cache", "audio")
        self._ensure_cache_dir()
        self.engine_priority = ['edge', 'pyttsx3']

        # 跨平台语音映射表
        self.voice_mapping = {
            'edge': {
                'zh-CN': 'zh-CN-YunxiNeural',
                'en-US': 'en-US-AriaNeural'
            },
            'pyttsx3': self._get_platform_voices()
        }

    @staticmethod
    def _get_platform_voices():
        """
        获取当前平台的默认语音配置

        返回：
        - dict: 包含中英文语音ID的字典，结构为{'zh-CN': voice_id, 'en-US': voice_id}

        平台支持：
        - Windows: 使用注册表路径标识语音
        - macOS: 使用Apple语音标识符
        - Linux: 使用espeak语音名称
        """
        current_os = platform.system()

        # Windows默认配置
        if current_os == 'Windows':
            return {
                'zh-CN': 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_ZH-CN_HUIHUI_11.0',
                #'en-US': 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_EN-US_DAVID_11.0'
            }
        # macOS默认配置
        elif current_os == 'Darwin':
            return {
                'zh-CN': 'com.apple.speech.synthesis.voice.ting-ting.premium',
                #'en-US': 'com.apple.speech.synthesis.voice.Alex'
            }
        # Linux默认配置 (espeak)
        else:
            return {
                'zh-CN': 'chinese',
                #'en-US': 'english-us'
            }

    def _ensure_cache_dir(self):
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _generate_filename(text: str, engine: str) -> str:
        timestamp = str(int(time.time()))
        hash_str = hashlib.md5(text.encode()).hexdigest()[:8]
        return f"{engine}_{hash_str}_{timestamp}.mp3"

    @staticmethod
    async def _edge_tts(text: str, voice: str, file_path: str) -> str:
        # 语速范围 0-100
        speed_value = int(config_center.read_conf('TTS', 'speed'))
        rate_percentage = (speed_value - 50) * 2
        rate_str = f"{rate_percentage:+}%"
        logger.debug(f"Edge TTS Rate: {rate_str} (Slider: {speed_value})")
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        await communicate.save(file_path)
        return file_path

    async def _pyttsx3_tts(self, text: str, voice: str, file_path: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._sync_pyttsx3(text, voice, file_path)
        )

    @staticmethod
    def _sync_pyttsx3(text: str, voice: str, file_path: str):
        engine = None
        try:
            try:
                engine = pyttsx3.init()
            except OSError as oe:
                if oe.winerror == -2147221005:
                    logger.error("系统语音引擎(pyttsx3/SAPI5)初始化失败，无法使用此引擎生成语音。请检查系统语音组件。")
                    raise RuntimeError("pyttsx3/SAPI5 初始化失败") from oe
                else:
                    logger.error(f"pyttsx3 初始化时发生OS错误: {oe}")
                    raise RuntimeError("pyttsx3 初始化OS错误") from oe
            except Exception as init_e:
                logger.error(f"pyttsx3 初始化失败: {init_e}")
                raise RuntimeError("pyttsx3 初始化异常") from init_e

            engine.connect('started-utterance', lambda name: None)
            engine.connect('finished-utterance', lambda name, completed: engine.stop())

            # 应用语音设置
            if voice:
                voices = engine.getProperty('voices')
                found_voice = next((v for v in voices if v.id == voice), None)
                if not found_voice:
                    # 尝试忽略引擎前缀查找 (例如，如果传入的是 edge:xxx)
                    voice_id_only = voice.split(':', 1)[-1]
                    found_voice = next((v for v in voices if v.id == voice_id_only), None)
                    if not found_voice:
                        logger.warning(f"pyttsx3: 无效或不匹配的语音ID '{voice}'，将使用默认语音")
                    else:
                         engine.setProperty('voice', found_voice.id)
                else:
                    engine.setProperty('voice', found_voice.id)

            # 应用语速设置
            speed_value = int(config_center.read_conf('TTS', 'speed'))
            default_rate = engine.getProperty('rate')
            # 50 -> default_rate, 0 -> default_rate/2, 100 -> default_rate*1.5
            if speed_value == 50:
                pyttsx3_rate = default_rate
            elif speed_value < 50:
                pyttsx3_rate = int(default_rate / 2 + (default_rate / 2) * (speed_value / 50))
            else:
                pyttsx3_rate = int(default_rate + (default_rate * 0.5) * ((speed_value - 50) / 50))
            # 速率50到400内，防止超出范围
            pyttsx3_rate = max(50, min(pyttsx3_rate, 400))
            logger.debug(f"pyttsx3 Rate: {pyttsx3_rate} (Slider: {speed_value}, Default: {default_rate})")
            engine.setProperty('rate', pyttsx3_rate)

            engine.save_to_file(text, file_path)
            start_time = time.time()
            engine.startLoop(False)
            while engine.isBusy():
                if time.time() - start_time > 10:
                    raise TimeoutError("pyttsx3生成超时")
                time.sleep(0.1)
                engine.iterate()
            engine.endLoop()
        finally:
            if engine:
                engine.stop()

    @staticmethod
    def _detect_language(text: str) -> str:
        """改进的语言检测方法"""
        if re.search(u'[\u4e00-\u9fff]', text):
            return 'zh-CN'
        return 'en-US'

    @staticmethod
    def _validate_pyttsx3_voice(voice_id: str, lang: str) -> str:
        """验证语音有效性，自动回退"""
        try:
            try:
                engine = pyttsx3.init()
            except OSError as oe:
                if oe.winerror == -2147221005:
                    logger.warning("系统语音引擎(pyttsx3/SAPI5)初始化失败，无法验证或选择系统语音。")
                    return '' # 返回空表示无法使用pyttsx3
                else:
                    logger.error(f"验证语音时 pyttsx3 初始化发生OS错误: {oe}")
                    return ''
            except Exception as init_e:
                logger.error(f"验证语音时 pyttsx3 初始化失败: {init_e}")
                return ''

            voices = engine.getProperty('voices')

            if any(v.id == voice_id for v in voices):
                return voice_id

            lang_voices = [v for v in voices if lang in str(v.languages)]
            if lang_voices:
                return lang_voices[0].id

            return engine.getProperty('voice')
        except Exception as e:
            logger.error(f"语音验证失败: {str(e)}")
            return ''

    async def _execute_engine(
            self,
            engine: str,
            text: str,
            voice: str,
            file_path: str,
            timeout: float
    ) -> str:
        """
        生成语音文件的核心异步方法

        参数：
        text (str): 要转换的文本内容（支持中英文自动检测）
        engine (str): 首选TTS引擎（默认edge）
        voice (str): 指定语音ID（可选），不指定则根据语言自动选择
        auto_fallback (bool): 引擎失败时是否自动回退（默认False）
        timeout (float): 单引擎超时时间（秒，默认10）
        filename (str): 自定义文件名（可选），不指定则自动生成

        返回：
        str: 生成的音频文件绝对路径

        异常：
        ValueError: 如果提供的语音ID与指定的引擎不匹配
        RuntimeError: 所有尝试的引擎均失败时抛出
        """
        if voice and not voice.startswith(f"{engine}:"):
            raise ValueError(f"语音ID '{voice}' 与引擎 '{engine}' 不匹配")

        actual_voice_id = voice.split(':', 1)[1] if voice and ':' in voice else voice
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

    async def generate_speech(
            self,
            text: str,
            engine: str = "edge",
            voice: Optional[str] = None,
            auto_fallback: bool = False,
            timeout: float = 10.0,
            filename: Optional[str] = None
    ) -> str:
        """核心生成方法"""

        # 自动语音选择逻辑
        lang = self._detect_language(text)
        if not voice:
            if engine == 'pyttsx3':
                voice = self.voice_mapping[engine].get(lang)
                voice = self._validate_pyttsx3_voice(voice, lang)
            else:
                voice = self.voice_mapping[engine][lang]

        _filename = filename or self._generate_filename(text, engine)
        _file_path = os.path.join(self.cache_dir, _filename)

        if os.path.exists(_file_path):
            logger.info(f"语音文件已存在于缓存中，直接返回: {_file_path}")
            return _file_path
        if not voice:
            lang = self._detect_language(text)
            if engine == 'pyttsx3':
                selected_voice = self.voice_mapping[engine].get(lang)
                voice = self._validate_pyttsx3_voice(selected_voice, lang)
            elif engine in self.voice_mapping:
                voice = self.voice_mapping[engine].get(lang)
            if not voice:
                 logger.warning(f"无法为语言 '{lang}' 和引擎 '{engine}' 自动选择语音")

        engines_to_try = [engine] # 只尝试指定的引擎
        if auto_fallback:
            for e in self.engine_priority:
                if e != engine and e not in engines_to_try:
                    engines_to_try.append(e)

        errors = []
        attempted_engines = set()
        engines_to_try = [engine]
        if auto_fallback:
            for e in self.engine_priority:
                if e != engine and e not in engines_to_try:
                    engines_to_try.append(e)

        for current_engine in engines_to_try:
            if current_engine in attempted_engines:
                 continue
            attempted_engines.add(current_engine)

            if voice and ':' in voice and not voice.startswith(current_engine + ':'):
                logger.debug(f"跳过引擎 '{current_engine}'")
                continue
            final_filename = filename if filename else self._generate_filename(text, current_engine)
            final_file_path = os.path.join(self.cache_dir, final_filename)

            if os.path.exists(final_file_path):
                logger.info(f"目标语音文件 '{final_filename}' 在执行前已存在，直接返回.")
                return final_file_path

            logger.debug(f"尝试使用 {current_engine} 生成 {final_filename}")

            try:
                await self._execute_engine(
                    engine=current_engine,
                    text=text,
                    voice=voice,
                    file_path=final_file_path,
                    timeout=timeout
                )

                # 验证文件是否成功创建
                if not os.path.exists(final_file_path):
                    raise RuntimeError(f"语音文件生成后未找到: {final_file_path}")

                logger.success(f"成功生成语音 | 引擎: {current_engine} | 文件: {final_filename}")
                return final_file_path

            except ValueError as ve:
                 logger.debug(f"跳过引擎 '{current_engine}") # 通常是语音ID不匹配，由 _execute_engine 内部抛出
            except Exception as e:
                error_msg = f"{current_engine}: {str(e)}" # 其他错误
                errors.append(error_msg)
                # logger.error(f"引擎 {current_engine} 生成失败: {e}")
                if os.path.exists(final_file_path):
                    try:
                        os.remove(final_file_path)
                        logger.debug(f"清理错误生成的文件: {final_file_path}")
                    except OSError as rm_err:
                        logger.warning(f"清理失败文件时出错: {rm_err}")
                if not auto_fallback:
                    logger.info(f"引擎 '{current_engine}' 失败后停止尝试。")
                    break
                continue

        raise RuntimeError(
            f"引擎尝试失败\n" +
            "\n".join(errors)
        )

    def cleanup(self, max_age: int = 86400):
        now = time.time()
        for f in Path(self.cache_dir).glob("*.*"):
            if f.is_file() and (now - f.stat().st_mtime) > max_age:
                f.unlink()

    @staticmethod
    def delete_audio_file(file_path: str, retries: int = 3, delay: float = 0.5):
        """
        安全删除音频文件
        参数:
            retries: 重试次数
            delay: 重试间隔(秒)
        """
        relative_path = os.path.relpath(file_path, os.path.join(os.getcwd(), "cache", "audio"))
        for attempt in range(retries):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.success(f"成功删除音频: {relative_path}")
                    return True
                else:
                    logger.debug(f"删除时文件已不存在: {relative_path}")
                    return True
            except PermissionError as pe:
                if attempt < retries - 1:
                    logger.warning(f"删除失败(权限错误),重试: ({attempt + 1}/{retries}): {relative_path} | 错误: {pe}")
                    time.sleep(delay)
                else:
                    logger.error(f"最终删除失败(权限错误): {relative_path} | 错误: {pe}")
            except OSError as oe:
                if attempt < retries - 1:
                    logger.warning(f"删除失败(OS错误),重试 ({attempt + 1}/{retries}): {relative_path} | 错误: {oe}")
                    time.sleep(delay)
                else:
                    logger.error(f"最终删除失败(OS错误): {relative_path} | 错误: {oe}")
            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(f"删除时发生未知错误,重试({attempt + 1}/{retries}): {relative_path} | 错误: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"删除失败: {relative_path} | 错误: {e}")
        return False


def generate_speech_sync(
        text: str,
        engine: str = "edge",
        voice: Optional[str] = None,
        auto_fallback: bool = False,
        timeout: float = 10.0,
        filename: Optional[str] = None
) -> str:
    """同步生成方法"""
    tts = TTSEngine()
    return asyncio.run(tts.generate_speech(
        text=text,
        engine=engine,
        voice=voice,
        auto_fallback=auto_fallback,
        timeout=timeout,
        filename=filename
    ))


def list_pyttsx3_voices():
    """列出所有可用的 Pyttsx3 语音."""
    try:
        try:
            engine = pyttsx3.init()
        except OSError as oe:
            if oe.winerror == -2147221005:
                logger.warning("系统语音引擎(pyttsx3/SAPI5)初始化失败，无法列出系统语音。")
                return []
            else:
                logger.error(f"列出语音时 pyttsx3 初始化发生OS错误: {oe}")
                return []
        except Exception as init_e:
            logger.error(f"列出语音时 pyttsx3 初始化失败: {init_e}")
            return []

        voices = engine.getProperty('voices')
        engine.stop()
        voice_list = []
        for voice in voices:
            voice_list.append({'name': voice.name, 'id': voice.id})
        return voice_list
    except Exception as e:
        logger.error(f"列出 Pyttsx3 语音时出错: {e}")
        return []
