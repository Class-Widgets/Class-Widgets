rem *GB2312
@echo off
echo 创建虚拟环境
uv venv
call .venv\Scripts\activate
echo 安装依赖
uv pip install -r requirements.txt
uv pip install nuitka imageio
echo 打包
python -m nuitka main.py ^
--enable-plugin=pyqt5 ^
--disable-console ^
--mode=app ^
-o"ClassWidgets" ^
--windows-icon-from-ico=img/favicon.icns ^
--product-name="Class Widgets" ^
--product-version="1.2.0.1" ^
--file-description="全新桌面课表" ^
--include-data-dir=img=img ^
--include-data-dir=ui=ui ^
--include-data-dir=view=view ^
--include-data-dir=i18n=i18n ^
--include-data-dir=config=config ^
--include-data-dir=font=font ^
--include-data-dir=audio=audio ^
--include-data-files=LICENSE=LICENSE ^
--include-package=pyttsx3.drivers
