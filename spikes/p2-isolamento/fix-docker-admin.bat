@echo off
REM ============================================================
REM P2 - Reparo do Docker Desktop (executar COMO ADMINISTRADOR)
REM Diagnostico: com.docker.service STOPPED + backend zumbi
REM segurando o pipe dockerBackendApiServer.
REM ============================================================
echo [1/4] Subindo o servico com.docker.service (SYSTEM)...
sc start com.docker.service
echo.
echo [2/4] Matando processos zumbis do Docker...
taskkill /F /IM "com.docker.backend.exe" 2>nul
taskkill /F /IM "Docker Desktop.exe" 2>nul
taskkill /F /IM "com.docker.build.exe" 2>nul
timeout /t 3 /nobreak >nul
echo.
echo [3/4] Relancando Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
echo.
echo [4/4] Aguardando engine (ate ~3 min). Quando o whale da
echo  bandeja ficar estavel, rodar como usuario normal:
echo     cd spikes\p2-isolamento
echo     docker compose up
echo ============================================================
pause
