@echo off
REM ============================================================
REM  Suivi PEA — script de build (PyInstaller)
REM  Produit : dist\Suivi_PEA.exe
REM ============================================================

setlocal
cd /d "%~dp0\.."

echo.
echo  ============================================================
echo   Suivi PEA — Build  (PyInstaller)
echo  ============================================================
echo.

REM -- 1. Verifie Python --
where python >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable. Installe-le depuis https://www.python.org/
    pause
    exit /b 1
)

REM -- 2. Installe les dependances --
echo [1/4] Installation des dependances...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] pip install a echoue.
    pause
    exit /b 1
)

REM -- 3. Genere l'icone si absente --
if not exist "assets\icon.ico" (
    echo [2/4] Generation de l'icone...
    python assets\make_icon.py
) else (
    echo [2/4] Icone deja presente, ok.
)

REM -- 4. Nettoyage des anciens builds --
echo [3/4] Nettoyage...
if exist "build\build"   rmdir /s /q "build\build"
if exist "dist"          rmdir /s /q "dist"

REM -- 5. Build --
echo [4/4] PyInstaller...
python -m PyInstaller build\suivi_pea.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERREUR] Build PyInstaller a echoue.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   OK : dist\Suivi_PEA.exe est pret.
echo  ============================================================
echo.
echo  Pour creer l'installateur Setup.exe :
echo    1. Installe Inno Setup : https://jrsoftware.org/isdl.php
echo    2. Ouvre build\installer.iss avec Inno Setup
echo    3. Menu Build -^> Compile (F9)
echo    4. Le Suivi_PEA_Setup.exe sera dans le dossier dist\.
echo.
pause
