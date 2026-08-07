@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Iniciando o Painel de Eventos Vesti...
start "" http://localhost:8000/painel-sintonia-001.html
python servidor.py 8000
pause
