# 官方遊戲資源版本檢測｜第一階段（唯讀、尚待確認實際 Manifest URL）

## 證據與限制

- 從使用者提供的 **1262** `global-metadata.dat` 看到 `https://wlreupload.chinesegamer.net/wln/TW/`，這是**候選官方資源主機目錄**，**不是**已確認可下載的 Manifest 端點。
- 1262 `Lua/Logic/Resource.lua` 使用 `CGResource.DownloadAndLoadAssets(0)` 並監控下載錯誤及版本錯誤。IL2CPP metadata 含 `UpdatePackageVersion`、`PackageManifest` 等符號；無法由此推定實際版本檔路徑。
- 官方首頁 `https://wlre.chinesegamer.net/` 可用來人工追蹤更新，**公告內容不能用來證明協定相容**。
- 現階段**禁止**把公開版本路徑的推測值當成已驗證網址；1262 為本專案基準，不代表官方目前版本。

## 執行方式（桌面與 Android 的 Python 原始碼開發環境）

```bash
python -m tools.check_official_version
```

未設定可確認的網址時回應 `unverified`，不會嘗試亂猜或掃描路徑；可在取得可信的官方 MainPackage/DataPackage `.version` 網址後執行：

```bash
python -m tools.check_official_version --main-url 'https://wlreupload.chinesegamer.net/wln/TW/<已確認的MainPackage檔案>.version' --data-url 'https://wlreupload.chinesegamer.net/wln/TW/<已確認的DataPackage檔案>.version' --strict
```

上述路徑為**填寫格式示意**，非實際可用 URL；請不要直接執行帶 `<...>` 的示例。只向官方 host 的 `/wln/TW/` 路徑發出唯讀 HTTPS GET，5 秒 timeout、4 KiB 回應大小上限、不帶帳號密碼、不發遊戲封包、拒絕跳轉至其他主機。

`status` 僅是**資源版本識別值**的比較：

- `same_resources`：兩個已驗證來源的版本字串都等於本專案 1262 基準，**不保證**伺服器協定、活動與帳號狀態相容。
- `resources_changed`：至少一個取得的版本字串不等於 1262，且兩個來源皆可確認，需另行比對 Lua、資料庫與封包。
- `unverified`：網址未知、只有部分來源成功、回應不符預期或連線失敗；**不得**顯示已同步。

`--strict` 下 0 = 相同資源版本、1 = 資源變更、2 = 無法驗證。非 strict 模式提供可查看的 JSON 報告，無論版本狀態均退出 0。

## 第二階段待辦

1. 從最新官方原版客戶端可驗證的更新流程取得 **PC/Android 各自的完整 `.version` URL**，記錄 HTTPS 實際回應及版本格式，確認是否為公開唯讀資源。
2. 將驗證過的來源設為各平台不同配置，再整合到 GUI 設定頁與 Android 主畫面，非同步更新狀態、保留最近一次成功檢測時間，網路錯誤時轉成 `unverified`。
3. 確認是否需要第二層 Manifest 雜湊比較以避免僅版本字串相同卻資源不同。
4. 新增在 GitHub Actions 定期唯讀執行的流程；來源未確認前不啟用排程，不暴力探測伺服器。

本階段**沒有**進行正式伺服器端對端驗證、沒有修改遊戲協定或自動升級官方資料，且不要求更新桌面／Android 程式版本號。
