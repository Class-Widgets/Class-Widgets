#!/usr/bin/env bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install nuitka imageio
python -m nuitka main.py \
--enable-plugin=pyqt5 \
--mode=app \
-o"ClassWidgets" \
--macos-app-icon=img/favicon.icns \
--product-name="Class Widgets" \
--product-version="1.1.7.1" \
--file-description="全新桌面课表" \
--include-data-dir=img=img \
--include-data-dir=ui=ui \
--include-data-dir=view=view \
--include-data-dir=config=config \
--include-data-dir=plugins=plugins \
--include-data-dir=font=font \
--include-data-dir=audio=audio \
--include-data-files=LICENSE=LICENSE \
--include-package=pyttsx3.drivers

mv main.app Class\ Widgets.app
