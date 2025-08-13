from qfluentwidgets import FluentTranslator
from PyQt5.QtCore import QLocale, QTranslator, Qt
from PyQt5.QtWidgets import QApplication

import os
from pathlib import Path
from loguru import logger
import sys
import json
from datetime import datetime

import utils
from file import config_center
from basic_dirs import CW_HOME, THEME_DIRS
from data_model import ThemeConfig, ThemeInfo

base_directory = Path(os.path.dirname(os.path.abspath(__file__)))

def __load_json(path: Path) -> ThemeConfig:
    with open(path, 'r', encoding='utf-8') as file:
        return ThemeConfig.model_validate_json(file.read())

def load_theme_config(theme: str) -> ThemeInfo:
    default_path = CW_HOME / 'ui' / 'default' / 'theme.json'
    try:
        config_path = next(
            (
                dir
                for theme_dir in THEME_DIRS
                if (dir := (theme_dir / theme / 'theme.json')).exists()
            ),
            default_path
        )
        return ThemeInfo(
            path=config_path.parent,
            config=__load_json(config_path)
        )
    except Exception as e:
        logger.error(f"加载主题数据时出错: {repr(e)}，返回默认主题")
        return ThemeInfo(
            path=default_path.parent,
            config=__load_json(default_path)
        )


class I18nManager:
    """i18n"""
    def __init__(self):
        self.translators = []
        self.available_languages_view = {}
        self.available_languages_widgets = {}
        self.current_language_view = 'zh_CN'
        self.completed_i18n_config = {}
        self.config_file_path = base_directory / 'config' / 'completed_i18n.json'
        self.load_completed_i18n_config()
        self.scan_available_languages()
        
    def scan_available_languages(self):
        try:
            completed_main = self.completed_i18n_config.get('completed_languages', {}).get('main', [])
            completed_themes = self.completed_i18n_config.get('completed_languages', {}).get('themes', {})
            for lang_code in completed_main:
                if display_name := self._get_language_display_name(lang_code):
                    self.available_languages_view[lang_code] = display_name
            theme_languages = completed_themes.get(config_center.read_conf('General', 'theme'), [])
            for lang_code in theme_languages:
                if display_name := self._get_language_display_name(lang_code):
                    self.available_languages_widgets[lang_code] = display_name
            logger.info(f"可用界面语言: {list(self.available_languages_view.keys())}")
            logger.info(f"可用组件语言: {list(self.available_languages_widgets.keys())}")
        except Exception as e:
            logger.error(f"扫描语言包时出错: {e}")

        if not self.available_languages_view:
            self.available_languages_view['zh_CN'] = '简体中文'
        if not self.available_languages_widgets:
            self.available_languages_widgets['zh_CN'] = '简体中文'

    def load_completed_i18n_config(self):
        """加载完整翻译配置文件"""
        try:
            if self.config_file_path.exists():
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    self.completed_i18n_config = json.load(f)
                # logger.debug(f"已加载完整翻译配置: {self.config_file_path}")
            else:
                logger.warning(f"完整翻译配置文件不存在: {self.config_file_path}")
                self.completed_i18n_config = {
                    "last_updated": "",
                    "completed_languages": {"main": [], "themes": {}}
                }
        except Exception as e:
            logger.error(f"加载完整翻译配置时出错: {e}")
            self.completed_i18n_config = {
                "last_updated": "", 
                "completed_languages": {"main": [], "themes": {}}
            }

    def _get_language_display_name(self, lang_code):
        """获取语言代码对应的显示名称"""
        language_names = {
            'zh_CN': '简体中文',
            'zh_HK': '繁體中文（HK）',
            'zh_SIMPLIFIED': '梗体中文',
            'en_US': 'English',
            'ja_JP': '日本語',
            'ko_KR': '한국어',
            'fr_FR': 'Français',
            'de_DE': 'Deutsch',
            'es_ES': 'Español',
            'ru_RU': 'Русский',
            'pt_BR': 'Português (Brasil)',
            'it_IT': 'Italiano',
            'ar_SA': 'العربية',
            'bo': 'བོད་ཡིག',  # 藏语
            'ug': 'ئۇيغۇرچە'   # 维吾尔语
        }
        return language_names.get(lang_code, None)

    def get_available_languages_QLocale(self, lang_code):
        locale_list = {
            'zh_CN': QLocale(QLocale.Chinese, QLocale.China),
            'zh_HK': QLocale(QLocale.Chinese, QLocale.HongKong),
            'en_US': QLocale(QLocale.English, QLocale.UnitedStates),
            'ja_JP': QLocale(QLocale.Japanese, QLocale.Japan),
        }
        return locale_list.get(lang_code, QLocale(QLocale.English, QLocale.UnitedStates))
        
    def get_available_languages_view(self):
        """获取可用界面语言列表仅(完整翻译的语言)"""
        completed_main = set(self.completed_i18n_config.get('completed_languages', {}).get('main', []))
        current_theme = config_center.read_conf('General', 'theme', 'default')
        completed_theme = set(self.completed_i18n_config.get('completed_languages', {}).get('themes', {}).get(current_theme, []))
        completed_languages = completed_main & completed_theme
        if not completed_languages:
            completed_languages = {'zh_CN'}
            logger.warning("没有找到完整翻译的语言")
        available_keys = set(self.available_languages_view.keys()) & set(self.available_languages_widgets.keys())
        filtered_keys = available_keys & completed_languages

        return {key: self.available_languages_view[key] for key in filtered_keys if key in self.available_languages_view}
        
    def get_current_language_view_name(self):
        """获取当前界面语言名称"""
        return self._get_language_display_name(self.current_language_view)

    def get_current_language_widgets_name(self):
        """获取当前组件语言名称"""
        return self._get_language_display_name(self.current_language_widgets)
        
    def load_language_view(self, lang_code):
        """加载界面语言文件"""
        current_lang = self.current_language_view
        try:
            from pathlib import Path
            app = QApplication.instance()
            if not app:
                return False
            self.clear_translators()

            main_translator = self._load_translation_file(
                Path(base_directory) / 'i18n' / f'{lang_code}.qm'
            )
            if main_translator:
                self.translators.append(main_translator)
                app.installTranslator(main_translator)
                self.current_language_view = lang_code
                # config_center.write_conf('General', 'language_view', lang_code)
                logger.success(f"成功加载界面语言: {lang_code} ({self.available_languages_view.get(lang_code, lang_code)})")
            else:
                logger.warning(f"无法加载界面语言: {lang_code} ({self.available_languages_view.get(lang_code, lang_code)})")
                self.load_language_view(current_lang)
                return False

            current_theme = load_theme_config(config_center.read_conf('General', 'theme'))
            theme_translator = self._load_translation_file(
                Path(current_theme.path / 'i18n' / f'{lang_code}.qm')
            )
            if theme_translator:
                self.translators.append(theme_translator)
                app.installTranslator(theme_translator)
                self.current_language_widgets = lang_code
                logger.success(f"成功加载组件语言: {lang_code} ({self.available_languages_widgets.get(lang_code, lang_code)})")
            else:
                logger.warning(f"无法加载组件语言: {lang_code} ({self.available_languages_widgets.get(lang_code, lang_code)})")
                self.load_language_view(current_lang)
                return False
            
            translator_qfw = FluentTranslator(self.get_available_languages_QLocale(lang_code))
            if translator_qfw:
                self.translators.append(translator_qfw)
                app.installTranslator(translator_qfw)
                logger.success(f"成功加载 FluentWidgets 语言: {lang_code}")

            import list_
            import importlib
            importlib.reload(list_)

            if not utils.main_mgr is None:
                utils.main_mgr.clear_widgets()
            
            return True

        except Exception as e:
            logger.error(f"加载界面语言包 {lang_code} 时出错: {e}")
            self.load_language_view(current_lang)
            return False

    def _load_translation_file(self, qm_path):
        """加载翻译"""
        try:
            if qm_path.exists():
                translator = QTranslator()
                if translator.load(str(qm_path)):
                    #logger.debug(f"成功加载文件: {qm_path}")
                    return translator
                else:
                    logger.warning(f"无法加载文件: {qm_path}")
            else:
                logger.warning(f"文件不存在: {qm_path}")
                
        except Exception as e:
            logger.error(f"加载文件 {qm_path} 时出错: {e}")
            
        return None
        
    def clear_translators(self):
        """清除翻译器"""
        app = QApplication.instance()
        if app:
            for translator in self.translators:
                app.removeTranslator(translator)
        self.translators.clear()
           
    def init_from_config(self):
        """初始化设置"""
        try:
            saved_language_view = config_center.read_conf('General', 'language_view', 'system')
            if saved_language_view == 'system':
                saved_language_view = QLocale.system().name()
            logger.debug(f"从配置加载界面语言: {saved_language_view}")
            if saved_language_view in self.get_available_languages_view():
                self.load_language_view(saved_language_view)
            else:
                logger.warning(f"配置的界面语言 {saved_language_view} 不可用")
                self.load_language_view('zh_CN')
        except Exception as e:
            logger.error(f"从配置初始化语言时出错: {e}")
            self.load_language_view('zh_CN')

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

os.environ['QT_SCALE_FACTOR'] = config_center.read_conf('General', 'scale')

app = QApplication(sys.argv)
global_i18n_manager = I18nManager()
global_i18n_manager.init_from_config()