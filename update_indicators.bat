@echo off
REM ============================================================
REM Market Indicators Website - Weekly Auto-Update
REM Runs every Monday 8 AM (or on next wake if missed)
REM ============================================================

set PYTHON=C:\Users\rider\AppData\Local\Programs\Python\Python313\python.exe
set GIT="C:\Program Files\Git\cmd\git.exe"
set WEBSITE=C:\Users\rider\Desktop\my-website
set BTC_DIR=C:\Users\rider\Desktop\BitcoinProjectionIndex
set FCI_DIR=C:\Users\rider\Desktop\FinancialConditionsIndex
set LOG=%WEBSITE%\update_log.txt

echo ============================================================ >> "%LOG%"
echo Update started: %date% %time% >> "%LOG%"
echo ============================================================ >> "%LOG%"

REM --- Step 1: Run Financial Conditions Index ---
echo Running Financial Conditions Index... >> "%LOG%"
cd /d "%FCI_DIR%"
"%PYTHON%" financial_conditions_index.py >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] FCI script failed >> "%LOG%"
) else (
    echo [OK] FCI script completed >> "%LOG%"
    copy /Y "%FCI_DIR%\financial_conditions_index.html" "%WEBSITE%\indicators\fci\" >> "%LOG%" 2>&1
)

REM --- Step 2: Run BTC Mean Reversion ---
echo Running BTC Mean Reversion... >> "%LOG%"
cd /d "%BTC_DIR%"
"%PYTHON%" btc_mean_reversion_analysis.py >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] BTC Mean Reversion script failed >> "%LOG%"
) else (
    echo [OK] BTC Mean Reversion completed >> "%LOG%"
    copy /Y "%BTC_DIR%\btc_mean_reversion.html" "%WEBSITE%\indicators\btc\" >> "%LOG%" 2>&1
)

REM --- Step 3: Run BTC Liquidity Backtest ---
echo Running BTC Liquidity Backtest... >> "%LOG%"
cd /d "%BTC_DIR%"
"%PYTHON%" btc_liquidity_backtest.py >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] BTC Liquidity Backtest script failed >> "%LOG%"
) else (
    echo [OK] BTC Liquidity Backtest completed >> "%LOG%"
    copy /Y "%BTC_DIR%\btc_liquidity_backtest.html" "%WEBSITE%\indicators\btc\" >> "%LOG%" 2>&1
)

REM --- Step 4: Run BTC Correlation ---
echo Running BTC Correlation... >> "%LOG%"
cd /d "%BTC_DIR%"
"%PYTHON%" btc_correlation.py >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] BTC Correlation script failed >> "%LOG%"
) else (
    echo [OK] BTC Correlation completed >> "%LOG%"
    copy /Y "%BTC_DIR%\btc_correlation.html" "%WEBSITE%\indicators\btc\" >> "%LOG%" 2>&1
)

REM --- Step 5: Commit and push to GitHub ---
echo Pushing to GitHub... >> "%LOG%"
cd /d "%WEBSITE%"
%GIT% add indicators/
%GIT% commit -m "Weekly indicator update %date%" >> "%LOG%" 2>&1
%GIT% push >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Git push failed >> "%LOG%"
) else (
    echo [OK] Pushed to GitHub >> "%LOG%"
)

echo Update finished: %date% %time% >> "%LOG%"
echo. >> "%LOG%"
