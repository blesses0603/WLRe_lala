# 飄流 RE:LaLa Android

**Android 測試版本：v0.0.2** ｜ **開發分支：`android-development`**

本分支用於開發《飄流 RE:LaLa》的 **Android 直式手機客戶端**，與 Windows／macOS 桌面版分開管理版本與建置流程。桌面正式版本請參閱 [`main` 分支](https://github.com/blesses0603/WLRe_lala/tree/main)。

## 📱 Android v0.0.2

v0.0.2 加入前景服務與安全帳號管理，目前包含：

- **直式操作介面**：手機登入表單與地球／水星分流選擇。
- **多帳號工作階段**：同一個 App 可以建立多個獨立連線，並逐一停止。
- **角色選擇與連線狀態**：沿用 Python 遊戲通訊核心，提供初步選角和狀態顯示。
- **測試 APK 建置**：使用 Buildozer，透過 GitHub Actions 產生測試 APK（以工作流程成功為準）。
- **帳號隱私**：可選用 Keystore AES-GCM 加密保存、切換及刪除帳密；未勾選時不保存。
- **背景服務**：獨立程序管理連線，常駐通知可返回或停止；畫面重建可重新附接。
- **資源監控**：連線數、畫面／服務記憶體、裝置電量／溫度與取樣時間。

> **待實機驗收**：正式服登入、Keystore、切 App 與鎖屏仍須在手機驗證。Android 15 dataSync 背景服務有累計時限；不保證永久在線。自動戰鬥／徘徊 UI 整合不屬於本次 8 項基礎驗收。

## 🧪 取得與測試 APK

1. 前往 [GitHub Actions](https://github.com/blesses0603/WLRe_lala/actions/workflows/android-apk.yml)。
2. 選擇 **Android v0.0.2 Test APK**，並確認使用 `android-development` 分支。
3. 工作流程成功後，打開該次執行，從 **Artifacts** 下載 `WLRe_LaLa-Android-v0.0.2-debug`。
4. 解壓 ZIP，將 APK 安裝到 Android 手機，先確認 App 能開啟、直式版面與分流選單正常。
5. 之後再以測試帳號驗證伺服器連線與選角流程。

**APK 必須等 GitHub Actions 編譯成功才會產生；本說明不表示已編譯成功。**

📖 **[完整 Android 開發狀態、安全注意事項及測試步驟](ANDROID/README.md)**

## 📂 主要檔案

| 路徑 | 用途 |
| --- | --- |
| `ANDROID/README.md` | Android 專用詳細說明 |
| `android_app/` | Android 直式介面、多帳號工作階段 |
| `main.py` | Android 啟動入口 |
| `buildozer.spec` | Android APK 打包設定 |
| `.github/workflows/android-apk.yml` | GitHub Actions 安卓測試建置流程 |
| `wlre/` | 沿用中的遊戲通訊及服務核心 |

## 🖥️ 桌面版本

Windows／macOS 的版本說明及發布流程仍以 [**桌面主分支 `main`**](https://github.com/blesses0603/WLRe_lala/tree/main) 為準；本分支的 Android 版號 **v0.0.2** 不會取代桌面版號。

完整目標與逐項驗收規格見 [Android 驗收規格](ANDROID/ACCEPTANCE.md)，目前測試結果見 [開發驗證](ANDROID/VALIDATION.md)。
