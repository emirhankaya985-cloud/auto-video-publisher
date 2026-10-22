@echo off
cd /d "C:\Users\emirh\Desktop\mahmut\video-automation"
echo ======================================================== >> hourly_upload.log
echo [CALISMA ZAMANI]: %date% %time% >> hourly_upload.log
echo ======================================================== >> hourly_upload.log
py publish_to_both.py >> hourly_upload.log 2>&1
