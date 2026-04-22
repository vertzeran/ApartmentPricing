@echo off
if exist venv (
    echo Removing existing environment...
    rmdir /s /q venv
)
echo Creating new environment...
python -m venv venv
if errorlevel 1 (echo ERROR: Failed to create virtual environment. & exit /b 1)
echo Installing dependencies...
call venv\Scripts\activate && pip install -r requirements.txt
echo Done. Run "call venv\Scripts\activate" to activate.
