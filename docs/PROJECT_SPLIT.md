# 電腦與 Android 專案拆分

2026-10-18：Android 程式、資源字型、測試、Java 前景服務、Buildozer 與 Android Actions 已移到 https://github.com/blesses0603/WLRe_lala_Android 的 main。

本專案 main 僅維護 Windows／macOS 桌面版，保留 Nuitka 發布流程。原 android-development 分支更新到同一個清理後提交，停止 Android 開發；過去提交可在 Git 歷史查閱，未刪除舊版歷史。

桌面保留原 main 的所有修改及 f38bd2a 的長時間更新、連線診斷、容量上限與兩小時清理修正。沒有更改版號、推送發布標籤或重建桌面安裝包。

Android 建置需要的核心及遊戲資源是新專案內的獨立副本。日後核心修正需要明確同步及兩邊測試，不會自動跨專案傳遞。新 Android 專案不包含 Tk 桌面介面、BAT 或 Nuitka Actions。

本次獨立測試：桌面 194 項中 192 通過、2 略過；Android 94 項全部通過。Actions 靜態檢查與 Python 語法檢查通過。新 APK 建置與模擬器結果以新專案 Actions 為準。
