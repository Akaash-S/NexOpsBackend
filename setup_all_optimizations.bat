@echo off
echo ==========================================
echo   NexOps Complete Optimization Setup
echo ==========================================
echo.
echo This will:
echo 1. Add missing database columns
echo 2. Add performance indexes
echo 3. Verify all changes
echo.
echo Press Ctrl+C to cancel, or
pause

python setup_all_optimizations.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ==========================================
    echo   SUCCESS! All optimizations applied.
    echo ==========================================
    echo.
    echo IMPORTANT: Restart your backend server now!
    echo.
) else (
    echo.
    echo ==========================================
    echo   ERROR: Setup failed
    echo ==========================================
    echo.
    echo Please check the error messages above.
    echo.
)

pause
