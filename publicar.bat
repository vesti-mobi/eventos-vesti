@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   Publicar relatorios Vesti  (atualiza dados + GitHub Pages)
echo ============================================================
echo.
echo [1/2] Gerando dados novos (usa suas chaves locais)...
python publicar.py
if errorlevel 1 (
  echo.
  echo Falhou ao gerar os dados. Verifique o config.json e a internet.
  pause
  exit /b 1
)
echo.
echo [2/2] Enviando para o GitHub Pages...
git add dados/sintonia-001.json dados/satisfacao-001.json painel-sintonia-001.html satisfacao-sintonia-001.html
git commit -m "Atualiza dados do relatorio"
git push
echo.
echo Pronto! O site publicado atualiza sozinho em cerca de 1 minuto.
pause
