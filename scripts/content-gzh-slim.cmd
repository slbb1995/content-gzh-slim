@echo off
setlocal
rem Windows shim: forward to the same Python launcher; never rely on file associations.
set PYTHONUTF8=1
if defined CONTENT_GZH_PYTHON (
  "%CONTENT_GZH_PYTHON%" -B "%~dp0content-gzh-slim" %*
  exit /b %ERRORLEVEL%
)
where py >nul 2>nul && (
  py -3 -B "%~dp0content-gzh-slim" %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>nul && (
  python -B "%~dp0content-gzh-slim" %*
  exit /b %ERRORLEVEL%
)
echo content-gzh-slim requires Python 3. Set CONTENT_GZH_PYTHON to its executable path. 1>&2
exit /b 9009
