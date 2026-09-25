@echo off
rem Jarvis arayuzunu (statik site) derler ve cPanel'e yuklenecek zip'i uretir.
rem Kullanim:   build_web.cmd https://api.ozglobaltrade.com
rem Cikti:      webapp\dist\erp-web.zip   (icindekiler, alt alanin belge kok dizinine cikarilir)
rem API adresi derleme aninda arayuze gomulur; API adresi degisirse yeniden derleyin.
setlocal
if "%~1"=="" (
  echo API adresini verin, ornek: build_web.cmd https://api.ozglobaltrade.com
  exit /b 1
)
set "NEXT_PUBLIC_API_URL=%~1"
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0frontend"
call npm run build || exit /b 1
if not exist "%~dp0dist" mkdir "%~dp0dist"
rem Windows'un Compress-Archive'i zip icinde ters egik cizgi kullanir (Linux'ta bozulur); Python'un zipfile'i dogru yazar.
py -c "import os,sys,zipfile; out=os.path.join(r'%~dp0dist','erp-web.zip'); z=zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(d,f), os.path.relpath(os.path.join(d,f),'out').replace(os.sep,'/')) for d,_,fs in os.walk('out') for f in fs]; z.close(); print('Hazir:',out, os.path.getsize(out)//1024,'KB')" || exit /b 1
echo Tamam. Bu API adresi gomuldu: %NEXT_PUBLIC_API_URL%
