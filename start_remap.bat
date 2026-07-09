@echo off
setlocal EnableDelayedExpansion

set "SCRIPT=%~dp0main.py"
set "PYTHON=C:\Users\amami\AppData\Local\Programs\Python\Python313\pythonw.exe"

powershell -NoProfile -Command ^
  "Start-Process '%PYTHON%' -ArgumentList '\"%SCRIPT%\"' -Verb RunAs"

goto :EOF