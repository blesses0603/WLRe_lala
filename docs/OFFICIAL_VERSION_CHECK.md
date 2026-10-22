# WLRe_LaLa｜電腦版登入前檢查官方線上遊戲資源版本

## 檢測目標：官方伺服器，不是本機遊戲或 LaLa 版本

LaLa 目前支援的 **遊戲資源基準為 1262**（與 LaLa 應用程式版本 `v0.5.17` 完全不同）。

啟動 LaLa 時先顯示獨立「官方伺服器遊戲資源版本檢測」視窗。工具需從已核實的**官方公開更新來源**取得 MainPackage 和 DataPackage 當前版本字串，再與內建的 1262 相比。檢測完全不讀取本機遊戲安裝目錄、Unity Manifest、LaLa EXE 版本、帳密或登入封包；使用者不必安裝原版遊戲，亦不必選取檔案。

| 官方查詢結果 | 登入前動作 |
| --- | --- |
| 官方兩個資源版本都等於 1262 | 顯示版本識別值符合基準，進入登入畫面；不表示協定相容性已驗證 |
| 官方任一資源版本不同於 1262 | **停在檢測視窗，禁止進入登入頁與送出登入封包；提示請等待 LaLa 更新** |
| 來源未設定、斷網、URL 未確認、只有部分成功且沒有確認版本異動 | **明確顯示「無法驗證」**，須由使用者按「了解風險，繼續登入」才能進入登入頁；絕不可顯示「已同步」 |
| 正在查詢 | 檢測視窗顯示進度、停用登入入口 |

檢測採背景工作執行，避免 Tk 主執行緒凍結；按「重新查詢官方版本」會撤銷之前登入許可，過期工作結果不會覆蓋新的檢測結果。登入按鈕本身以 `App.connect()` 重新確認檢測許可；已設定遠端來源時，查詢超過 5 分鐘則必須重檢。

## 官方版本查詢網址：仍待確認

已分析的遊戲 1262 `global-metadata.dat` 內包含
`https://wlreupload.chinesegamer.net/wln/TW/`，但這只是候選 CDN 根目錄，**不是已核實可取得當前版本的 URL**。

先前提供的封包擷取包含 `wlreftp.chinesegamer.net` 連線資訊，但一般 HTTPS 封包看不到加密的請求檔案路徑；不能因此推測 `.version` 完整網址。**不允許猜網址或暴力掃描官方伺服器**。

確認來源後，可在電腦環境中設定：

```powershell
$env:WLRE_OFFICIAL_MAIN_VERSION_URL = "https://<官方已驗證的 MainPackage 完整版本端點>"
$env:WLRE_OFFICIAL_DATA_VERSION_URL = "https://<官方已驗證的 DataPackage 完整版本端點>"
```

上述為格式示意，**不是可直接使用的正式 URL**。目前 `wlre/services/official_version.py` 只允許已觀測到的 `wlreupload.chinesegamer.net` /wln/TW/ HTTPS 版本文字或 JSON 檔案路徑，具 5 秒 timeout、4 KiB 回應上限及轉址主機驗證。若實際端點是其他官方主機，須先取得確切證據後再調整白名單與解析格式。

## 如何找正式來源（不讀取本機版本）

- `tools/find_official_version_urls.ps1` 是**診斷用途**，只搜尋原版遊戲的 Log 中可能出現的更新請求 URL，並移除 URL query/fragment，避免洩露 Session Token；**這個檔案不參與 LaLa 每次登入前的版本判斷**。
- 如原版遊戲日誌沒有網址，請從官方遊戲的更新階段確認實際連線請求及回應格式，或尋找官方公開文件。找到完整 URL 前，程式必須保持「無法驗證」。
- 官方遊戲維護公告可以當提示，但不應直接當作 MainPackage/DataPackage 的實際版號或協定相容性證據。

## 驗收

```powershell
python -m unittest discover -s tests -p "test_game_version_gate.py" -v
python -m unittest discover -s tests -p "test_official_version.py" -v
python -m unittest discover -s tests -p "test_prelogin_version_window.py" -v
```

測試要覆蓋以下保證：本機遊戲即使存在 1275 Manifest，也不能單獨造成封鎖；只有**可信官方遠端來源**確認 1275 與 1262 不符才阻擋登入。尚未取得真正官方 URL 前，模擬回應測試不能宣稱完成正式伺服器 E2E 驗收。

此改動僅限 Windows/macOS 電腦版，**不修改 Android、不合併 main、不發布 Release**。現行開發版號仍為 v0.5.17。
