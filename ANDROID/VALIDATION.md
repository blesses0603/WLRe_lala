# Android v0.0.1 開發驗證 — 2026-10-18

檢查基準：`c6ec340` 的 Kivy／Buildozer 實作。

- 使用假的網路 runner 重現鎖定角色欄位遺失、同角色重複入列，以及例外狀態被 finished 訊息覆蓋；修正後 9 項 session 測試通過。
- 在 Kivy 2.3.1 與虛擬桌面執行 5 項 UI 測試，驗證中文字形、鎖定／待選角色、錯誤保留／結束卡片移除、HP／SP 零值與未知位置、背景清空密碼及停線。
- 相同環境完整執行 191 項測試：189 通過、2 項略過（Windows DPAPI、macOS ditto）。
- Actions 工作流程通過 actionlint 1.7.12；語法與 diff 檢查通過。
- 沒有使用正式帳號、沒有連線遊戲伺服器。Android APK 的 Buildozer 編譯、手機安裝及真實登入結果，仍以 Actions 產物與手機實測為準。

本次保留既有 Kivy 多連線設計，未混入另一套 Android 原生／Chaquopy 入口。

## v0.0.2 — 2026-10-18

- 完整 198 項測試：196 通過、2 項平台限定略過。Android 專用 21 項測試涵蓋獨立連線、私有 socket、畫面重新附接、背景生命週期、無畫面事件清理、保存帳號切換及刪除。
- 密文儲存測試使用桌面 AESGCM 驗證非明文、載入、刪除、竄改失敗與原檔保留；**不等同於 Android Keystore 真機測試**。
- 自訂 Java 前景通知／Android 15 超時服務，使用 Android 35 SDK 與 JDK 17 編譯檢查通過；測試時 PythonService／PythonActivity 使用最小介面 stub，完整整合仍須 APK 建置驗證。
- actionlint、Python compileall、diff whitespace 檢查通過。
- 上一輪 Actions 39050117226 失敗於 charset_normalizer 3.5.2 Android wheel 被 Linux 主機 pip 拒收；本版固定 charset-normalizer 3.4.2 及 python-for-android revision，重跑完整建置。
- 尚無正式帳號連線、手機 Keystore、背景或鎖屏時長的實測結果；15／30／60 分鐘測試仍需手機驗收。
