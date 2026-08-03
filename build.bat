@echo off
REM Build the Live Screen Translator into a Windows executable.
REM Run this in a Windows "cmd" prompt with Python 3.9-3.12 installed.

setlocal
echo == Installing dependencies ==
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt pyinstaller || goto :error

echo == Building executable ==
python -m PyInstaller --noconfirm live_translate.spec || goto :error

echo.
echo Done. Run:  dist\LiveScreenTranslator\LiveScreenTranslator.exe
goto :eof

:error
echo.
echo Build failed. See the output above.
exit /b 1
