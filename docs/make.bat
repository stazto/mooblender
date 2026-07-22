@ECHO OFF

pushd %~dp0

if "%SPHINXBUILD%" == "" set SPHINXBUILD=sphinx-build
if "%SPHINXOPTS%" == "" set SPHINXOPTS=-W --keep-going
if "%1" == "" set BUILDER=html
if not "%1" == "" set BUILDER=%1

%SPHINXBUILD% -M %BUILDER% . _build %SPHINXOPTS%
popd
