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
from file import base_directory


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
                'en-US': 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_EN-US_DAVID_11.0'
            }
        # macOS默认配置
        elif current_os == 'Darwin':
            return {
                'zh-CN': 'com.apple.speech.synthesis.voice.ting-ting.premium',
                'en-US': 'com.apple.speech.synthesis.voice.Alex'
            }
        # Linux默认配置 (espeak)
        else:
            return {
                'zh-CN': 'chinese',
                'en-US': 'english-us'
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
        communicate = edge_tts.Communicate(text, voice)
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
            engine = pyttsx3.init()
            engine.connect('started-utterance', lambda name: None)
            engine.connect('finished-utterance', lambda name, completed: engine.stop())

            # 应用语音设置
            if voice:
                voices = engine.getProperty('voices')
                found_voice = next((v for v in voices if v.id == voice), None)
                if not found_voice:
                    raise ValueError(f"无效语音ID：{voice}")
                engine.setProperty('voice', found_voice.id)

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
            engine = pyttsx3.init()
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
        RuntimeError: 所有尝试的引擎均失败时抛出
        """
        try:
            if engine == "edge":
                task = self._edge_tts(text, voice, file_path)
            elif engine == "pyttsx3":
                task = self._pyttsx3_tts(text, voice, file_path)
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

        filename = filename or self._generate_filename(text, engine)
        file_path = os.path.join(self.cache_dir, filename)

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
            if current_engine not in self.engine_priority:
                continue

            attempted_engines.add(current_engine)

            try:
                await self._execute_engine(
                    engine=current_engine,
                    text=text,
                    voice=voice,
                    file_path=file_path,
                    timeout=timeout
                )

                actual_filename = self._generate_filename(text, current_engine)
                actual_path = os.path.join(self.cache_dir, actual_filename)
                os.rename(file_path, actual_path)

                if not os.path.exists(actual_path):
                    raise RuntimeError(f"语音文件生成失败: {actual_path}")

                logger.info(f"成功生成语音 | 引擎: {current_engine} | 路径: {actual_path}")
                return actual_path

            except Exception as e:
                errors.append(f"{current_engine}: {str(e)}")
                continue

        raise RuntimeError(
            f"所有引擎尝试失败\n" +
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
        for attempt in range(retries):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"成功删除音频文件: {file_path}")
                    return True
            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(f"删除失败，正在重试 ({attempt + 1}/{retries}): {str(e)}")
                    time.sleep(delay)
                else:
                    logger.error(f"最终删除失败: {file_path} | 错误: {str(e)}")
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
    """跨平台语音列表显示"""
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    current_os = platform.system()

    for idx, voice in enumerate(voices):
        logger.info(f"\n[{current_os} 平台Pyttsx3可用语音包]"
                    f"\n{idx + 1}. ID: {voice.id}"
                    f"\n   名称: {voice.name}"
                    f"\n   语言: {voice.languages[0] if voice.languages else '未知'}"
                    f"\n   性别: {voice.gender}"
                    f"\n" + "-" * 60)

# 示例修改：将语音文件路径拼接
speech_output = os.path.normpath(os.path.join(base_directory, "output", "speech.mp3"))
