[app]
title = WLRe_LaLa
package.name = wlrelala
package.domain = org.lala.client
source.dir = .
source.include_exts = py,kv,json,zip,png,jpg,jpeg,webp,ttf,ttc,txt
source.exclude_dirs = .git,.github,docs,tests,tools,.buildozer,bin,dist_nuitka
version = 0.0.2
requirements = python3,kivy==2.3.1,pyjnius,charset-normalizer==3.4.2
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,WAKE_LOCK,FOREGROUND_SERVICE,FOREGROUND_SERVICE_DATA_SYNC,POST_NOTIFICATIONS
services = Connections:android_app/service.py:foreground:foregroundServiceType=dataSync
android.allow_backup = False
android.add_src = android_app/java
android.service_class_name = org.lala.client.ConnectionService
p4a.commit = 8ef9d1dbbf769d2c14681dbc3c116c85e2e93bae
android.api = 35
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
