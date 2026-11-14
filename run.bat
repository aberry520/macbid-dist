@echo off
REM MAC.BID Deal Finder — Windows launcher. Double-click run.bat
cd /d "%~dp0"
for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set MDATE=%%d%%b%%a
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set MTIME=%%a%%b
python macbid_deals.py --out "reports\%MDATE%-%MTIME%.md"
echo.
echo Report saved in the reports\ folder.
pause
