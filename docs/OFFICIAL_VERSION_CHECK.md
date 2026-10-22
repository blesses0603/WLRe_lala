# 電腦版：官方 YooAsset 版本閘門 + LaLa 正式版更新檢測

## 目標與兩種版本的區別

- **官方遊戲資源（1262 相容基準）**：用來判斷登入是否需要暫停，來源是官方 Fiddler 實際觀察的三個 HTTPS 端點，不讀取電腦上的遊戲檔案。
- **LaLa 程式自身（目前 v0.5.17 開發候選）**：由 `wlre.__version__` 定義；只和 **blesses0603/WLRe_lala GitHub 正式 Release** 比較；不拿開發中 PR、main 或標籤當已發布更新。兩種版本完全不能混比。
- 使用者提供的 1262 MainPackage／DataPackage Manifest 可以供**離線內容差異分析**，但登入前只需要內建 `{"MainPackage":"1262","DataPackage":"1262"}`。目前不嵌入官方 BundleFiles 或 Manifest 原始二進位，以避免體積與版權問題。

## 官方 YooAsset 實際三階段來源

來源證據：2026-10-22 官方遊戲 Fiddler Everywhere 實際連線，網域 `wlreftp.chinesegamer.net`、HTTP 200、TLS：

1. `https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat`：回傳 `[{"ExeVer":"1.1.3","DataVer":"1.3.21"}, {"ExeVer":"1.1.4","DataVer":"1.3.21"}, {"ExeVer":"1.2.0","DataVer":"1.3.21"}, {"ExeVer":"1.3.0","DataVer":"1.3.21"}]`。
2. 解析映射，使用目前已確認官方 PC ExeVer `1.3.0`；若公告的新遊戲 ExeVer 有不同 DataVer，採最新版本的資源路徑並直接標記需要等待 LaLa 相容性更新，避免永遠查舊 `1.3.21` 目錄。
3. `https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/MainPackage.version`。2026-10-22 觀測回覆 `1275_2026_10_21_18_29_38_49`。
4. `https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/DataPackage.version`。2026-10-22 觀測回覆 `1275_2026_10_21_18_27_33_84`。

以上回覆只代表**當時**已觀測到的值，不得寫死為未來官方最新版本。每次啟動／重新查詢都使用 HTTPS GET 查公開檔案，不需遊戲帳密。下載請求附帶隨機時間參數、no-cache/no-store 標頭降低 CDN 快取誤用風險；但不能保證 CDN 任意延遲都不存在。

只允許 `wlreftp.chinesegamer.net` 的已觀測 URL 型態、TLS、不帶帳密/非預期參數/任意路徑。最多讀取 4 KiB，遇到錯誤格式、轉址、過大檔案不當成版本一致；查不到映射時**不使用上次快取**當最新版本。這裡不使用 `wlreupload.chinesegamer.net` 的舊猜測路徑。

### 登入前行為

| 官方證據 | 結果 |
|---|---|
| MainPackage 和 DataPackage 都是 1262 且路徑無異動 | 版本識別值一致，顯示登入按鈕 |
| 任一 Package 與 1262 不同，或官方新版資源路徑不同 | **停止登入、顯示「請等待 LaLa 更新」** |
| 官方來源失敗／版本不完整，且沒有已確認的異動 | **顯示「無法驗證」**，需要使用者明確確認風險才可進入登入頁 |
| 正在查詢 | 不可登入；UI 由 Tk 主執行緒維護 |

`App.connect()` 也會檢查版本閘門；超過 5 分鐘須重新檢測。1275 是已知不相容**資源版本基準**，不宣稱全部遊戲協定一定失效。

## LaLa 程式更新：自動檢測、經確認後下載驗證

啟動版本檢測視窗時另開背景執行緒讀取 GitHub API：

`https://api.github.com/repos/blesses0603/WLRe_lala/releases/latest`

只接受已發布、非預覽 Release 的 `vX.Y.Z`，使用數字式三段比較。例如目前開發版 0.5.17 **不得降版**至正式 v0.5.0。需有目前作業系統對應 ZIP 與 `SHA256SUMS.txt`，且 URL 必須是正確 GitHub Repository + Tag + 預期檔名。

如確有較新 Release，登入前視窗顯示新版與「下載並驗證新版」；使用者同意後：

1. 先讀取發布的 `SHA256SUMS.txt`，比對唯一對應的 ZIP SHA-256 值。
2. 分段下載到 LaLa 使用者資料下 `updates/<tag>/*.partial`（有容量上限），計算 SHA-256 與 ZIP CRC。
3. 驗證安裝包結構與 ZIP 路徑安全，通過後以原子重新命名保存在 `updates/<tag>/`。
4. 顯示「開啟更新資料夾」，使用者**關閉舊 LaLa 後**另行解壓、啟動新版。不可直接覆蓋執行中的 EXE、變更登入資料或靜默執行新檔案。

**狀態定義：** 此階段是**自動查新版 + 需同意的安全下載準備**；尚未實作已驗證的無人值守原位替換／回滾安裝，不可以宣稱「新版已自動安裝成功」。若網路離線或 GitHub API 無法存取，只影響 LaLa 更新提示，不會替換遊戲資源檢查結果。

檔案來源同源校驗：GitHub 的 SHA256SUMS 和 ZIP 都來自同一 Release，能偵測損壞或錯誤來源；但並非額外的軟體簽章或抵禦 GitHub 帳號被接管的證明。

## 測試與驗收

```powershell
python -m unittest discover -s tests -p "test_official_version.py" -v
python -m unittest discover -s tests -p "test_game_version_gate.py" -v
python -m unittest discover -s tests -p "test_lala_updater.py" -v
python -m unittest discover -s tests -p "test_prelogin_version_window.py" -v
```

官方查詢 CLI：`python -m tools.check_official_version --strict`，狀態碼 0 為一致、1 為異動、2 為未知。

測試利用模擬 HTTPS 回應，覆蓋：官方 1.3.21→1275、未來路徑改版、斷線不誤判、非法主機拒絕、版本回應嚴格比對；LaLa 發布檢查不降版、錯誤下載連結拒絕、SHA256 和 ZIP 驗證。CI 通過不等於使用者 Windows 原版環境測試通過，也不等於官方正式服登入 E2E 完成。

**範圍：只改電腦版 PR #48，不改 Android、不合併 main、不建立 Tag/Release。**
