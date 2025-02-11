from os import environ, makedirs
from pathlib import Path
from sys import platform

from loguru import logger

APP_NAME = "Class Widgets"
CW_HOME = Path(__file__).parent

if str(CW_HOME).endswith('MacOS'):
    CW_HOME = Path(__file__).absolute().parent.parent / 'Resources'

def get_is_portable() -> bool:
    tmp = environ.get("CLASSWIDGETS_IS_PORTABLE")
    return tmp is not None and tmp.lower() in ["true", "1"]


IS_PORTABLE = get_is_portable


def _empty_then_create(path: Path) -> Path:
    if not path.exists():
        makedirs(path)
    return path


def get_config_home() -> Path:
    default = CW_HOME / "config"
    if IS_PORTABLE:
        return _empty_then_create(default)

    custom = environ.get("CLASSWIDGETS_CUSTOM_CONFIG_HOME")
    if custom is not None:
        return _empty_then_create(Path(custom))

    if platform == "win32":
        appdata = environ.get("APPDATA")
        if appdata is None:
            logger.error("找不到  %APPDATA%")
            return _empty_then_create(default)
        return _empty_then_create(Path(appdata) / APP_NAME / "config")

    # no win32
    xdg_config_home = environ.get("XDG_CONFIG_HOME")
    if xdg_config_home is not None and platform != "darwin":
        return _empty_then_create(Path(xdg_config_home) / APP_NAME)

    home = environ.get("HOME")
    if home is None:
        logger.error("找不到 $HOME")
        return _empty_then_create(default)
    if platform != "darwin":
        return Path(home) / ".config" / APP_NAME
    else:
        return Path(home) / "Library/Application Support" / APP_NAME / "config"


def get_log_home() -> Path:
    default = CW_HOME / "log"
    if IS_PORTABLE:
        return _empty_then_create(default)

    custom = environ.get("CLASSWIDGETS_CUSTOM_LOG_HOME")
    if custom is not None:
        return _empty_then_create(Path(custom))

    if platform == "win32":
        tmp = environ.get("TMP")
        if tmp is None:
            logger.error("找不到  %TMP%")
            return _empty_then_create(default)
        return _empty_then_create(Path(tmp) / APP_NAME / "log")

    # no win32
    xdg_cache_home = environ.get("XDG_CONFIG_HOME")
    if xdg_cache_home is not None and platform != "darwin":
        return _empty_then_create(Path(xdg_cache_home) / APP_NAME / "log")

    home = environ.get("HOME")
    if home is None:
        logger.error("找不到 $HOME")
        return _empty_then_create(default)
    if platform != "darwin":
        return Path(home) / ".cache" / APP_NAME
    else:
        return Path(home) / "Library/Cache" / APP_NAME / "log"


def get_plugin_home() -> Path:
    default = CW_HOME / "plugins"
    if IS_PORTABLE:
        return _empty_then_create(default)

    custom = environ.get("CLASSWIDGETS_CUSTOM_PLUGIN_HOME")
    if custom is not None:
        return _empty_then_create(Path(custom))

    if platform == "win32":
        appdata = environ.get("APPDATA")
        if appdata is None:
            logger.error("找不到  %APPDATA%")
            return _empty_then_create(default)
        return _empty_then_create(Path(appdata) / APP_NAME / "plugins")

    # no win32
    xdg_data_home = environ.get("XDG_DATA_HOME")
    if xdg_data_home is not None and platform != "darwin":
        return _empty_then_create(Path(xdg_data_home) / APP_NAME / "plugins")

    home = environ.get("HOME")
    if home is None:
        logger.error("找不到 $HOME")
        return _empty_then_create(default)
    if platform != "darwin":
        return Path(home) / ".local/share" / APP_NAME / "plugins"
    else:
        return Path(home) / "Library/Application Support" / APP_NAME / "plugins"


CONFIG_HOME = get_config_home()
LOG_HOME = get_log_home()
PLUGIN_HOME = get_plugin_home()
