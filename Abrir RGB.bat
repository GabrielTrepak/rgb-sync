@echo off
rem Abre o RGB Sync. Se a inicializacao com o Windows estiver instalada,
rem abre sem pedir administrador (usa a tarefa agendada).
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" --abrir
