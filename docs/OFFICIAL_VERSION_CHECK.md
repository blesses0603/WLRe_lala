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


## 電腦版第二階段：登入前 1262 強制版本閘門

此階段**僅修改電腦版**。不涉及 Android，且不改變程式版號、遊戲封包或帳密儲存。

### 啟用流程

1. 開啟 `WLRe_LaLa` 後自動以背景執行緒掃描原版遊戲 `*_Data/yoo/MainPackage/ManifestFiles` 與 `DataPackage/ManifestFiles`；檢查完成前「登入」按鈕不可使用。
2. 自動尋找失敗時，在登入頁按「遊戲目錄」選擇遊戲資料夾或 `*_Data/yoo`，設定只保存在 LaLa 使用者本機資料目錄的 `official_game_yoo_root.txt`；不儲存遊戲帳密。
3. 檢測 `MainPackage_1262_...bytes` / `.hash` 成對、`DataPackage_1262_...bytes` / `.hash` 成對，選擇觀測到的**最高完整檔案版本**，避免誤把 1076 等較舊快取當成新版。
4. **只要其中任一資源包的最高完整檔名版本不等於 1262**，標示「遊戲版本異動，禁止登入，請等待 LaLa 更新與相容性驗證」，停用按鈕，也在 `App.connect` 執行前重掃本機清單並封鎖，阻止繞過介面的登入請求。
5. 官方遠端版本來源尚未驗證。若未找到本機資料、資料不完整或沒有已確認的遠端 URL，顯示「無法完整驗證」；此情況**不會冒充已同步**，但不會因為單純斷網或未設定目錄就一律停用既有登入。
6. 如已由官方客戶端實證 `.version` 來源，可透過 **`WLRE_OFFICIAL_MAIN_VERSION_URL`** 和 **`WLRE_OFFICIAL_DATA_VERSION_URL`** 環境變數指定，沿用第一階段白名單 HTTPS 唯讀檢測；**任何一個遠端來源明確顯示與 1262 不同就禁止登入**，即使另一個來源不可用。未取得完整官方 URL 之前不可自行猜測。
7. 顯示「重新檢查」按鈕，並在登入嘗試時重掃本機；已設定雙遠端來源且上次檢測超過五分鐘，會先重新檢測再允許新登入。

**限制：** 檔名版本不是包體的完整 SHA-256 驗證；舊快取可能仍在目錄中，取最高完整版本是保守選擇。即使 1262 與線上版本字串相同，也不能保證伺服器協定相容。

### 如何擷取正式版本查詢網址

原版遊戲啟動並進入更新檢查階段（**不要登入帳號**）後，在 PowerShell 於專案根目錄執行：

```powershell
.\tools\find_official_version_urls.ps1
```

腳本會只讀搜尋 `%USERPROFILE%\AppData\LocalLow\**\Player.log` 與已知遊戲安裝路徑下的 Log，擷取官方 `chinesegamer.net` 網域、包含 Manifest／version／package／update 等字樣的 URL，並將**可能包含 Token 的 query/fragment 移除**後保存成 `WLRE_官方版本網址候選.txt`。如無候選 URL，可能官方不將完整 URL 記錄在日誌中；此時尚需從官方客戶端可見的更新連線事件中確認，不能使用未經驗證的猜測網址。

首次擷取到 URL 後，仍需在不登入帳號的情況下確認來源真正為官網、HTTPS 回傳正常、內容為正式資源版本字串，才能寫入檢測來源配置。不要傳送含有帳號密碼、Session Cookie 或授權 Token 的完整封包日誌。

## 第三階段：獨立登入前版本檢測視窗（桌面版）

- LaLa 啟動時先建立獨立的「官方遊戲資源版本檢測」視窗，**登入表單會先隱藏**。
- 顯示預設 1262、MainPackage／DataPackage 已偵測到的本機版號、遊戲資源路徑、官方遠端版號是否可驗證。
- 背景檢查期間顯示不定進度條，且「進入登入畫面」按鈕停用；沒有使用遊戲帳號或封包。
- **確認版本異動**時停留在版本視窗，顯示「遊戲版本異動 · 請等待 LaLa 更新」並禁止進入登入頁；同時保留原本的 `App.connect()` 實際連線前再次掃描及阻擋。
- **遠端無法驗證**時明確顯示未知，不提供虛假的「已同步」結論；使用者必須自行按「了解風險，繼續登入」，才會出現登入表單。
- 使用者可在此視窗「選擇遊戲目錄」、「重新檢查」或「結束程式」；返回登入頁後仍可從「版本檢測」按鈕回到獨立視窗。
- 仍需驗證官方實際 YooAsset 遠端查詢路徑與回應格式，目前的本機 Manifest 檢測**不等於**官方即時版本比對。

驗收重點：啟動時登入表單不可見、未檢查完不可進入登入、1262／1275 不同時阻擋並提示等待更新、無法驗證時明確揭示風險、重檢結果不會被舊背景工作覆蓋。涵蓋 `tests/test_prelogin_version_window.py`。
