@echo off
setlocal EnableDelayedExpansion

set "SCRIPT=%~dp0main.py"
set "PYTHON=C:\Users\amami\AppData\Local\Programs\Python\Python313\pythonw.exe"
set "PIDFILE=%~dp0main.pid"

if exist "%PIDFILE%" (
    set /p SAVED_PID=<"%PIDFILE%"

    powershell -NoProfile -Command ^
      "$pid_val = !SAVED_PID!; $proc = Get-Process -Id $pid_val -ErrorAction SilentlyContinue; exit $(if ($proc) { 1 } else { 0 })"

    if !errorlevel! == 1 (
        powershell -NoProfile -Command ^
          "Start-Process powershell -ArgumentList '-NoProfile -Command Stop-Process -Id !SAVED_PID! -Force' -Verb RunAs -Wait"
        del "%PIDFILE%"
        goto :EOF
    ) else (
        del "%PIDFILE%"
    )
)

powershell -NoProfile -Command ^
  "$p = Start-Process '%PYTHON%' -ArgumentList '\"%SCRIPT%\"' -Verb RunAs -PassThru; $p.Id | Out-File -FilePath '%PIDFILE%' -Encoding ascii -NoNewline"

goto :EOF