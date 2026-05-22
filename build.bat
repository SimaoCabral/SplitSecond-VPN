@echo off
REM Compila splitsecond_vpn.py num executavel Windows standalone.
setlocal enabledelayedexpansion

pushd "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [*] A criar venv...
    python -m venv .venv
    if errorlevel 1 (
        echo Falha a criar venv. Tens Python no PATH?
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :err

echo [*] A compilar com PyInstaller...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name splitsecond-vpn ^
    --uac-admin ^
    --collect-all customtkinter ^
    splitsecond_vpn.py
if errorlevel 1 goto :err

echo.
echo Executavel pronto em: %cd%\dist\splitsecond-vpn.exe
popd
exit /b 0

:err
echo.
echo Build falhou.
popd
exit /b 1
