# 飄流 RE:LaLa Android

**Android 測試版本：v0.0.1** ｜ **開發分支：`android-development`**

本分支用於開發《飄流 RE:LaLa》的 **Android 直式手機客戶端**，與 Windows／macOS 桌面版分開管理版本與建置流程。桌面正式版本請參閱 [`main` 分支](https://github.com/blesses0603/WLRe_lala/tree/main)。

## 📱 Android v0.0.1

第一階段以能在 Android 手機安裝、啟動及驗證基本連線流程為目標，目前包含：

- **直式操作介面**：手機登入表單與地球／水星分流選擇。
- **多帳號工作階段**：同一個 App 可以建立多個獨立連線，並逐一停止。
- **角色選擇與連線狀態**：沿用 Python 遊戲通訊核心，提供初步選角和狀態顯示。
- **測試 APK 建置**：使用 Buildozer，透過 GitHub Actions 產生測試 APK（以工作流程成功為準）。
- **帳號隱私**：測試版不提供記住密碼功能，也不應將帳號密碼放入 GitHub 專案。

> **開發中**：正式遊戲登入仍需 Android 實機驗證；鎖屏後持續連線、Android 前景服務、自動戰鬥／徘徊的完整整合，以及安全記住密碼尚未完成。v0.0.1 不代表這些功能已可使用。

## 🧪 取得與測試 APK

1. 前往 [GitHub Actions](https://github.com/blesses0603/WLRe_lala/actions/workflows/android-apk.yml)。
2. 選擇 **Android v0.0.1 Test APK**，並確認使用 `android-development` 分支。
3. 工作流程成功後，打開該次執行，從 **Artifacts** 下載 `WLRE-LaLa-Android-v0.0.1-debug`。
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

Windows／macOS 的版本說明及發布流程仍以 [**桌面主分支 `main`**](https://github.com/blesses0603/WLRe_lala/tree/main) 為準；本分支的 Android 版號 **v0.0.1** 不會取代桌面版號。
