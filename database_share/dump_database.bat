@echo off
REM ============================================================
REM  DUMP DATABASE - Export PostgreSQL ke file SQL untuk GitHub
REM  Jalankan ini di laptop yang punya data lengkap (laptop kamu)
REM ============================================================

setlocal

REM --- Konfigurasi (samakan dengan .env kamu) ---
set PGBIN=C:\laragon\bin\postgresql\postgresql-11.0-1\bin
set PGHOST=localhost
set PGPORT=5432
set PGUSER=idha_boga_user
set PGDATABASE=idha_boga_staging
set PGPASSWORD=IdhaBoga2026local

REM --- Output file ---
set OUTFILE=%~dp0idha_boga_staging_dump.sql

echo.
echo ============================================================
echo  Meng-export database "%PGDATABASE%" ke:
echo  %OUTFILE%
echo ============================================================
echo.

"%PGBIN%\pg_dump.exe" --host=%PGHOST% --port=%PGPORT% --username=%PGUSER% ^
  --no-owner --no-privileges --clean --if-exists ^
  --file="%OUTFILE%" %PGDATABASE%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUKSES] Dump berhasil dibuat: %OUTFILE%
    echo Sekarang commit file ini ke GitHub.
) else (
    echo.
    echo [GAGAL] Dump gagal. Cek path PGBIN dan kredensial database.
)

set PGPASSWORD=
endlocal
pause
