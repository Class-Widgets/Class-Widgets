"""
ui->py

view/**/*.ui -> view/py/**/*.py
ui/xxx/*.ui -> ui/xxx/py/*.py
ui/xxx/dark/*.ui -> ui/xxx/dark/py/*.py
"""

import subprocess
import sys
from pathlib import Path
from typing import List

from loguru import logger

sys.path.append(str(Path(__file__).resolve().parents[1]))
from basic_dirs import CW_HOME


class UIConverter:
    def __init__(self):
        self.converted_files = []
        self.failed_files = []

    def convert_ui_to_py(self, ui_file: Path, output_file: Path) -> bool:
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, "-m", "PyQt5.uic.pyuic", str(ui_file), "-o", str(output_file),]
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.success(f"转换成功: {ui_file.relative_to(CW_HOME)} -> {output_file.relative_to(CW_HOME)}")
            self.converted_files.append((ui_file, output_file))
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"转换失败: {ui_file.relative_to(CW_HOME)} - {e.stderr}")
            self.failed_files.append((ui_file, str(e)))
            return False
        except Exception as e:
            logger.error(f"转换失败: {ui_file.relative_to(CW_HOME)} - {e!s}")
            self.failed_files.append((ui_file, str(e)))
            return False

    def find_ui_files(self, directory: Path) -> List[Path]:
        ui_files = []
        if directory.exists():
            for ui_file in directory.rglob("*.ui"):
                ui_files.append(ui_file)
        return ui_files

    def convert_view_files(self):
        """
        转换view的ui文件

        rule: view/**/*.ui -> view/py/**/*.py
        """
        view_dir = CW_HOME / "view"
        ui_files = self.find_ui_files(view_dir)
        for ui_file in ui_files:
            rel_path = ui_file.relative_to(view_dir)
            output_path = view_dir / "py" / rel_path.with_suffix(".py")
            self.convert_ui_to_py(ui_file, output_path)

    def convert_ui_theme_files(self):
        """
        转换主题的ui文件

        rule:
        - ui/xxx/*.ui -> ui/xxx/py/*.py
        - ui/xxx/dark/*.ui -> ui/xxx/dark/py/*.py
        """
        ui_dir = CW_HOME / "ui"
        if not ui_dir.exists():
            return

        for theme_dir in ui_dir.iterdir():
            if not theme_dir.is_dir():
                continue
            theme_name = theme_dir.name
            logger.debug(f"处理主题: {theme_name}")
            # ui/xxx/目录下
            light_ui_files = list(theme_dir.glob("*.ui"))
            for ui_file in light_ui_files:
                output_path = theme_dir / "py" / ui_file.with_suffix(".py").name
                self.convert_ui_to_py(ui_file, output_path)
            # ui/xxx/dark目录下
            dark_dir = theme_dir / "dark"
            if dark_dir.exists():
                dark_ui_files = list(dark_dir.glob("*.ui"))
                for ui_file in dark_ui_files:
                    output_path = dark_dir / "py" / ui_file.with_suffix(".py").name
                    self.convert_ui_to_py(ui_file, output_path)

    def generate_summary(self):
        if self.failed_files:
            logger.error("转换失败的文件:")
            for ui_file, error in self.failed_files:
                logger.error(f"- {ui_file.relative_to(CW_HOME)}: {error}")

    def run(self):
        logger.debug(f"根目录: {CW_HOME}")
        self.convert_view_files()
        self.convert_ui_theme_files()
        self.generate_summary()
        return len(self.failed_files) == 0


def main():
    converter = UIConverter()
    success = converter.run()
    if success:
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
