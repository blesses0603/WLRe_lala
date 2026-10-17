# Android v0.0.1 開發驗證 — 2026-10-18

檢查基準：`c6ec340` 的 Kivy／Buildozer 實作。

- 使用假的網路 runner 重現鎖定角色欄位遺失、同角色重複入列，以及例外狀態被 finished 訊息覆蓋；修正後 9 項 session 測試通過。
- 在 Kivy 2.3.1 與虛擬桌面執行 5 項 UI 測試，驗證中文字形、鎖定／待選角色、錯誤保留／結束卡片移除、HP／SP 零值與未知位置、背景清空密碼及停線。
- 相同環境完整執行 191 項測試：189 通過、2 項略過（Windows DPAPI、macOS ditto）。
- Actions 工作流程通過 actionlint 1.7.12；語法與 diff 檢查通過。
- 沒有使用正式帳號、沒有連線遊戲伺服器。Android APK 的 Buildozer 編譯、手機安裝及真實登入結果，仍以 Actions 產物與手機實測為準。

本次保留既有 Kivy 多連線設計，未混入另一套 Android 原生／Chaquopy 入口。
