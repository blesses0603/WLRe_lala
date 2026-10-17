# Android v0.0.1 開發驗證 — 2026-10-18

檢查基準：`c6ec340` 的 Kivy／Buildozer 實作。

- 使用假的網路 runner 重現鎖定角色欄位遺失、同角色重複入列，以及例外狀態被 finished 訊息覆蓋；修正後 9 項 session 測試通過。
- 在 Kivy 2.3.1 與虛擬桌面執行 5 項 UI 測試，驗證中文字形、鎖定／待選角色、錯誤保留／結束卡片移除、HP／SP 零值與未知位置、背景清空密碼及停線。
- 相同環境完整執行 191 項測試：189 通過、2 項略過（Windows DPAPI、macOS ditto）。
- Actions 工作流程通過 actionlint 1.7.12；語法與 diff 檢查通過。
- 沒有使用正式帳號、沒有連線遊戲伺服器。Android APK 的 Buildozer 編譯、手機安裝及真實登入結果，仍以 Actions 產物與手機實測為準。

本次保留既有 Kivy 多連線設計，未混入另一套 Android 原生／Chaquopy 入口。

## v0.0.2 — 2026-10-18

- 完整 198 項測試：196 通過、2 項平台限定略過。Android 專用 22 項測試涵蓋獨立連線、私有 socket、畫面重新附接、背景生命週期、無畫面事件清理、保存帳號切換及刪除。
- 密文儲存測試使用桌面 AESGCM 驗證非明文、載入、刪除、竄改失敗與原檔保留；**不等同於 Android Keystore 真機測試**。
- 自訂 Java 前景通知／Android 15 超時服務，使用 Android 35 SDK 與 JDK 17 編譯檢查通過；測試時 PythonService／PythonActivity 使用最小介面 stub，完整整合仍須 APK 建置驗證。
- actionlint、Python compileall、diff whitespace 檢查通過。
- 上一輪 Actions 39050117226 失敗於 charset_normalizer 3.5.2 Android wheel 被 Linux 主機 pip 拒收；本版固定 charset-normalizer 3.4.2 及 python-for-android revision，重跑完整建置。
- 尚無正式帳號連線、手機 Keystore、背景或鎖屏時長的實測結果；15／30／60 分鐘測試仍需手機驗收。

- 後續追加暫停畫面的事件合併測試：10,000 次更新僅保留各帳號最新狀態；Android 專用 22 項全部通過。完整測試前次 198 項通過（含 2 略過），新增此項後未重跑完整套件。

## APK 建置結果 — v0.0.2

- GitHub Actions [39051241946](https://github.com/blesses0603/WLRe_lala/actions/runs/39051241946) 全部成功，原始碼 commit `405b1d5`，工作耗時 13 分 44 秒。
- CI 的 22 項 Android 專用測試、compileall、Buildozer／Gradle APK 編譯及上傳全部成功。
- 產物：[WLRe_LaLa-Android-v0.0.2-debug](https://github.com/blesses0603/WLRe_lala/actions/runs/39051241946/artifacts/12108650193)，包含 APK 與 SHA256SUMS；GitHub 回報壓縮產物大小 111,303,027 bytes。
- 此執行環境取回 GitHub Azure Blob 產物時收到 Forbidden，因此未在本地解開 APK 檢查 manifest／校驗碼，不能宣稱已做本地產物驗證。
- Android Keystore 實際加解密、手機安裝、正式服雙帳號、切 App、鎖屏與耗電仍待手機實測。
