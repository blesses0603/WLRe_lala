# 飄流 RE:LaLa Android v0.0.1（第一階段測試）

這是 **Android 測試版**，與 Windows／macOS 的 v0.5.0 分開管理。僅在
`android-development` 分支開發，沒有修改桌面版入口。

## 已加入

- 使用 Kivy 建立 **直式觸控登入介面**。
- 使用既有 `wlre.storage.server_lines` 官方伺服器／分流表，不自訂猜測端點。
- 共用 `wlre.network.client.run_client` 進行帳號驗證、遊戲連線和角色選擇。
- 同一個 APP 可建立多個獨立連線執行緒，沒有寫死帳號數量上限。
- 各帳號可獨立停止連線，互不共用命令佇列。
- 密碼只用於目前的登入嘗試；**沒有密碼記憶、雲端同步或封包記錄功能**。
- 透過 GitHub Actions 手動建置供側載的 Android arm64 debug APK。

## 已知限制

**此階段尚未在 Android 真機／正式伺服器驗證成功，也未聲稱 APK 已建置成功。**
本階段重點是確立打包流程、直式登入入口與連線基礎。
尚未完成：Android 前景服務、鎖屏背景作業、斷線自動重連、
Android Keystore 保存密碼、完整遊戲功能介面、記憶體負載控制。

原有 Python 核心的非 ASCII 帳號／密碼編碼尚未驗證。
首次測試請使用專用測試帳號，避免在未驗證程式上使用主要帳號。
APK 會包含現有遊戲核心需要的資源檔，初次編譯可能花較久時間。

## 如何取得第一個測試 APK

1. 開啟 [Android Actions](https://github.com/blesses0603/WLRe_lala/actions/workflows/android-apk.yml)。
2. 點 **Run workflow**，**Branch 選擇 `android-development`**，按 Run workflow。
3. 等待 Android v0.0.1 Test APK 工作流程成功完成。
4. 開啟該次執行，在 **Artifacts** 下載 `WLRE-LaLa-Android-v0.0.1-debug`。
5. 解壓縮後把 `.apk` 傳到 Android 手機，允許該來源安裝測試應用程式並安裝。
6. 開啟 APP，先確認直式介面、地球／水星分流選單與帳號欄位正常。
7. 使用測試帳號登入，查看驗證結果、角色清單及是否能個別停止連線。

**不需 root，也不需要在手機上安裝 Python。**
僅當 workflow 成功且產生 Artifact 時才代表有可下載的 APK。

## 安全與偵錯

- 測試版不寫入帳號密碼，不能沿用 Windows DPAPI 資料。
- 角色名稱及狀態僅在 APP 記憶體顯示。
- GitHub Actions 編譯時 **不需要、也不要上傳任何遊戲帳密或個人設定檔**。
- Debug APK 供私下測試；正式釋出前需另外規劃版本簽章、權限與安全審核。
