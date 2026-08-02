@echo off
REM Build and push all images to ECR for Week 6.
REM Usage: scripts\build_and_push_all.bat [tag]
REM Default tag: latest

setlocal

set TAG=%1
if "%TAG%"=="" set TAG=latest

echo ==========================================
echo Building and pushing all images with tag: %TAG%
echo ==========================================

echo.
echo 1/3 Building predict-service...
call scripts\push_predict_service.bat %TAG%
if errorlevel 1 goto :error

echo.
echo 2/3 Building training-job...
call scripts\push_training_job.bat %TAG%
if errorlevel 1 goto :error

echo.
echo 3/3 Building operator...
call scripts\push_operator.bat %TAG%
if errorlevel 1 goto :error

echo.
echo ==========================================
echo All images built and pushed successfully!
echo ==========================================
goto :end

:error
echo.
echo ==========================================
echo Error occurred during build/push!
echo ==========================================
exit /b 1

:end
endlocal
