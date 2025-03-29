import os
from pathlib import Path
from sys import platform
from loguru import logger

APP_NAME = "Class Widgets"
CW_HOME = Path(__file__).parent

if str(CW_HOME).endswith("MacOS"):
    CW_HOME = Path(__file__).absolute().parent.parent / "Resources"

IS_PORTABLE = os.environ.get("CLASSWIDGETS_NOT_PORTABLE", "") == ""


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# 公共基础函数
def _get_app_dir(
    purpose: str,
    default_subdir: str,
    win_env_var: str,
    mac_subpath: str,
    xdg_env_var: str,
    xdg_fallback: str,
) -> Path:
    """获取应用目录的通用实现"""
    if IS_PORTABLE:
        return _ensure_dir(CW_HOME / default_subdir)

    # 处理自定义路径
    if custom := os.environ.get(f"CLASSWIDGETS_CUSTOM_{purpose.upper()}_HOME"):
        return _ensure_dir(Path(custom))

    # Windows 逻辑
    if platform == "win32":
        if base := os.environ.get(win_env_var):
            return _ensure_dir(Path(base) / APP_NAME / default_subdir)
        logger.error(f"Missing Windows environment variable: {win_env_var}")
        return _ensure_dir(CW_HOME / default_subdir)

    # macOS 逻辑
    if platform == "darwin":
        return _ensure_dir(Path.home() / mac_subpath / APP_NAME / default_subdir)

    # Linux/Unix 逻辑
    base = os.environ.get(xdg_env_var) or str(Path.home() / xdg_fallback)
    return _ensure_dir(Path(base) / APP_NAME / default_subdir)


# 最终路径
CONFIG_HOME = _get_app_dir(
    purpose="CONFIG",
    default_subdir="config",
    win_env_var="APPDATA",
    mac_subpath="Library/Application Support",
    xdg_env_var="XDG_CONFIG_HOME",
    xdg_fallback=".config",
)
LOG_HOME = _get_app_dir(
    purpose="LOG",
    default_subdir="log",
    win_env_var="TMP",
    mac_subpath="Library/Caches",
    xdg_env_var="XDG_CACHE_HOME",
    xdg_fallback=".cache",
)
PLUGIN_HOME = _get_app_dir(
    purpose="PLUGIN",
    default_subdir="plugins",
    win_env_var="APPDATA",
    mac_subpath="Library/Application Support",
    xdg_env_var="XDG_DATA_HOME",
    xdg_fallback=".local/share",
)
