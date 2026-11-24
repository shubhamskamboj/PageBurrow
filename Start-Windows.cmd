@echo off
rem PageBurrow for Windows. Double-click this file to start.
rem The Windows package brings its own Python (runtime folder), so nothing needs installing.
rem Without that folder, an installed Python 3.10+ is used and set up on the first start.
setlocal
cd /d "%~dp0"
if not exist "app.py" goto :notextracted
set "PY=runtime\windows-x64\python.exe"
if exist "%PY%" (
    "%PY%" -E -s -c "import pymupdf, PIL" >nul 2>nul && goto :portable
    echo The Python in the runtime folder could not start. Trying an installed Python instead...
)
set "PY="
call :find py -3
if not defined PY call :find python
if not defined PY call :find python3
if not defined PY goto :nopython
%PY% launch.py %*
goto :finished

:portable
"%PY%" -E -s app.py %*

:finished
if errorlevel 1 (
    echo.
    echo PageBurrow stopped because of the problem shown above.
    pause
)
exit /b

:find
rem Skips the Microsoft Store placeholder and Python versions older than 3.10.
%* -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b

:nopython
echo PageBurrow needs Python 3.10 or newer, or a package that includes it
echo (PageBurrow.zip or PageBurrow-Windows.zip). Install Python from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH", then double-click this file again.
pause
exit /b 1

:notextracted
echo PageBurrow's files are not next to this file. This happens when it is started
echo from inside the zip. Right-click the zip, choose "Extract All", then double-click
echo Start-Windows.cmd in the extracted PageBurrow folder.
pause
exit /b 1
