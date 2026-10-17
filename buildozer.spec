[app]
title = 飄流 RE LaLa
package.name = wlrelala
package.domain = org.lala.client
source.dir = .
source.include_exts = py,kv,json,zip,png,jpg,jpeg,webp,ttf,ttc
source.exclude_dirs = .git,.github,docs,tests,tools,.buildozer,bin,dist_nuitka
version = 0.0.1
requirements = python3,kivy==2.3.1
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 35
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
