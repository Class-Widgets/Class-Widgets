"""
ui加载中间层

*没有什么是不能通过增加一个中间层来解决的(
"""

import importlib.util
from pathlib import Path
from typing import Optional, Union

from loguru import logger
from PyQt5 import uic
from PyQt5.QtWidgets import QWidget

from basic_dirs import CW_HOME


class UILoader:
    """
    ui加载类
    """

    @staticmethod
    def get_py_path_from_ui_path(ui_path: Union[str, Path]) -> Optional[Path]:
        """
        路径转换

        1. view/**/*.ui -> view/py/**/*.py
        2. ui/xxx/*.ui -> ui/xxx/py/*.py
        3. ui/xxx/dark/*.ui -> ui/xxx/dark/py/*.py
        """
        ui_path = Path(ui_path)
        if ui_path.is_absolute():
            try:
                ui_path = ui_path.relative_to(CW_HOME)
            except ValueError:
                return None

        parts = ui_path.parts
        if parts[0] == "view":
            # view/**/*.ui -> view/py/**/*.py
            py_parts = ["view", "py", *list(parts[1:])]
            py_path = Path(*py_parts).with_suffix(".py")
            return CW_HOME / py_path
        # 主题ui处理
        if parts[0] == "ui" and len(parts) >= 2:
            theme_name = parts[1]
            if len(parts) >= 3 and parts[2] == "dark":
                # ui/xxx/dark/*.ui -> ui/xxx/dark/py/*.py
                py_parts = ["ui", theme_name, "dark", "py", *list(parts[3:])]
            else:
                # ui/xxx/*.ui -> ui/xxx/py/*.py
                py_parts = ["ui", theme_name, "py", *list(parts[2:])]
            return CW_HOME / Path(*py_parts).with_suffix(".py")

        return None

    @staticmethod
    def load_py_ui(py_file: Path, widget: QWidget) -> bool:
        """
        加载.py格式的ui文件到widget
        """
        try:
            # 唯一的模块名
            module_name = f"ui_{py_file.stem}_{abs(hash(py_file))}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                return False

            ui_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ui_module)

            # 查找Ui_开头的类(邪修(?
            ui_class = None
            for attr_name in dir(ui_module):
                attr = getattr(ui_module, attr_name)
                if (
                    isinstance(attr, type)
                    and attr_name.startswith("Ui_")
                    and hasattr(attr, "setupUi")
                ):
                    ui_class = attr
                    break
            if ui_class is None:
                return False
            # 创建ui实例设置到widget上
            ui_instance = ui_class()
            ui_instance.setupUi(widget)
            if hasattr(ui_instance, "retranslateUi"):
                ui_instance.retranslateUi(widget)
            widget.ui = ui_instance

            return True

        except Exception as e:
            logger.error(f"加载ui文件失败: {py_file} - {e}")
            return False

    @staticmethod
    def loadUi(ui_path: Union[str, Path], widget: Optional[QWidget] = None) -> Optional[QWidget]:
        """
        加载ui文件方法,直接替代uic.loadUi

        Args:
            ui_path: ui文件路径(.ui / .py)
            widget: 目标widget

        Returns:
            加载ui后的widget
        """
        ui_path = Path(ui_path)
        if widget is None:
            widget = QWidget()
        if ui_path.suffix == ".py" and ui_path.exists():
            if UILoader.load_py_ui(ui_path, widget):
                return widget
            raise RuntimeError(f"无法加载ui文件: {ui_path}")
        py_path = UILoader.get_py_path_from_ui_path(ui_path)
        if py_path and py_path.exists():
            if UILoader.load_py_ui(py_path, widget):
                return widget
            logger.warning(f".py文件存在但加载失败: {py_path}")
        # fallback
        try:
            if not ui_path.is_absolute():
                ui_path = CW_HOME / ui_path

            if ui_path.exists():
                uic.loadUi(str(ui_path), widget)
                return widget
            raise FileNotFoundError(f"ui文件不存在: {ui_path}")

        except Exception as e:
            raise RuntimeError(f"无法加载ui文件: {ui_path}") from e


def loadUi(ui_path: Union[str, Path], widget: Optional[QWidget] = None) -> Optional[QWidget]:
    """
    直接替换uic.loadUi

    Args:
        ui_path: ui文件路径
        widget: 目标widget

    Returns:
        加载了ui的widget对象
    """
    return UILoader.loadUi(ui_path, widget)


def load_ui_type(ui_path: Union[str, Path]):
    """
    这啥啊这是
    Retuen: (form_class, base_class)
    """
    ui_path = Path(ui_path)
    py_path = ui_path if ui_path.suffix == '.py' else UILoader.get_py_path_from_ui_path(ui_path)

    if py_path and py_path.exists():
        try:
            # 生成唯一的模块名
            module_name = f"ui_{py_path.stem}_{abs(hash(py_path))}"
            spec = importlib.util.spec_from_file_location(module_name, py_path)
            if spec is not None and spec.loader is not None:
                ui_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ui_module)
                for attr_name in dir(ui_module):
                    attr = getattr(ui_module, attr_name)
                    if (
                        isinstance(attr, type)
                        and attr_name.startswith("Ui_")
                        and hasattr(attr, "setupUi")
                    ):
                        base_class = attr.__bases__[0] if attr.__bases__ else QWidget
                        return attr, base_class
        except Exception as e:
            logger.error(f"从.py文件加载ui类型失败: {py_path} - {e}")
    if ui_path.suffix == '.ui':
        if not ui_path.is_absolute():
            ui_path = CW_HOME / ui_path
        return uic.loadUiType(str(ui_path))

    raise RuntimeError(f"无法加载ui文件: {ui_path}")


loadUiType = load_ui_type
