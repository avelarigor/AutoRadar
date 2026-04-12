@echo off
REM AutoRadar - Launcher Script
REM Created by Igor Avelar - avelar.igor@gmail.com

taskkill /F /IM python.exe >nul 2>&1

cd /d "%~dp0"

echo.
echo ============================================
echo  AutoRadar - Launcher
echo ============================================
echo.

REM Verificar se venv existe
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado em .venv
    echo.
    echo Execute: python -m venv .venv
    echo.
    pause
    exit /b 1
)

echo [OK] Ambiente virtual encontrado
echo.

REM Usar Python do venv diretamente (nao depender de activate)
set PYTHON_EXE=%~dp0.venv\Scripts\python.exe

echo Python: %PYTHON_EXE%
echo.

REM Verificar dependencias
echo Verificando dependencias...
"%PYTHON_EXE%" -c "import playwright, requests" >nul 2>&1
if errorlevel 1 (
    echo [AVISO] Faltam dependencias. Instalando...
    echo.
    "%PYTHON_EXE%" -m pip install --upgrade pip
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRO] Erro ao instalar dependencias
        pause
        exit /b 1
    )
    echo.
    echo [OK] Dependencias instaladas
    echo.
) else (
    echo [OK] Dependencias verificadas
    echo.
)

echo.
echo ============================================
echo  Iniciando AutoRadar via Launcher...
echo ============================================
echo.

REM Usar _launcher.py: garante instancia unica, limpa lockfiles e redireciona logs
"%PYTHON_EXE%" _launcher.py

if errorlevel 1 (
    echo.
    echo [ERRO] AutoRadar encerrou com erro
    pause
)

exit /b %ERRORLEVEL%
