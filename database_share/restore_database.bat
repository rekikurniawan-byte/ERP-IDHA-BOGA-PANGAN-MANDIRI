@echo off
REM ============================================================
REM  RESTORE DATABASE - Import file SQL ke PostgreSQL
REM  Jalankan ini di laptop teman (setelah git clone)
REM
REM  PRASYARAT:
REM  1. PostgreSQL sudah terinstall
REM  2. Sudah membuat user & database kosong (lihat SETUP_TEMAN.md)
REM ============================================================

setlocal

REM --- Konfigurasi (sesuaikan dengan instalasi PostgreSQL teman) ---
set PGBIN=C:\laragon\bin\postgresql\postgresql-11.0-1\bin
set PGHOST=localhost
set PGPORT=5432
set PGUSER=idha_boga_user
set PGDATABASE=idha_boga_staging
set PGPASSWORD=IdhaBoga2026local

REM --- Input file ---
set INFILE=%~dp0idha_boga_staging_dump.sql

if not exist "%INFILE%" (
    echo [GAGAL] File dump tidak ditemukan: %INFILE%
    echo Pastikan file idha_boga_staging_dump.sql ada di folder ini.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Meng-import data ke database "%PGDATABASE%"
echo  Dari file: %INFILE%
echo ============================================================
echo.

"%PGBIN%\psql.exe" --host=%PGHOST% --port=%PGPORT% --username=%PGUSER% ^
  --dbname=%PGDATABASE% --file="%INFILE%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUKSES] Database berhasil di-restore.
) else (
    echo.
    echo [GAGAL] Restore gagal. Cek apakah database "%PGDATABASE%" sudah dibuat.
)

set PGPASSWORD=
endlocal
pause
