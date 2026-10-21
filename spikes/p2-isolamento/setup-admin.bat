@echo off
REM ============================================================
REM P2 - Preparacao do ambiente Docker (executar COMO ADMINISTRADOR)
REM Clique com botao direito -> "Executar como administrador"
REM ============================================================
echo [1/3] Adicionando Jonata ao grupo docker-users...
net localgroup docker-users Jonata /add
echo.
echo [2/3] Atualizando o subsistema WSL2 (necessario p/ engine do Docker)...
wsl --update
echo.
echo [3/3] Verificando...
wsl -l -v
echo.
echo ============================================================
echo  Se tudo correu bem: FAZER LOGOFF/LOGIN (ou reiniciar)
echo  para a associacao ao grupo docker-users valer.
echo  Depois, rodar:  docker compose up   em  spikes\p2-isolamento
echo ============================================================
pause
