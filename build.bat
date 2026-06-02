@echo off
setlocal
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --windowed --name KojiReportPetNext --add-data "data;data" --add-data "assets;assets" main.py
endlocal
