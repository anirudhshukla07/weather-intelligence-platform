@echo off
REM Start the backend the GPU-safe way (python main.py), so Ctrl+C force-exits
REM instantly instead of hanging on CUDA/CTranslate2 teardown.
"%~dp0venv\Scripts\python.exe" "%~dp0main.py" %*
