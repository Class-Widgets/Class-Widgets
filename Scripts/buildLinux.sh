#!/bin/bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install nuitka imageio
python -m nuitka main.py \
--enable-plugin=pyqt5 \
--mode=app \
-o"ClassWidgets" \
--include-data-dir=img=img \
--include-data-dir=ui=ui \
--include-data-dir=view=view \
--include-data-dir=i18n=i18n \
--include-data-dir=config=config \
--include-data-dir=font=font \
--include-data-dir=audio=audio \
--include-data-files=LICENSE=LICENSE \
--include-package=pyttsx3.drivers
