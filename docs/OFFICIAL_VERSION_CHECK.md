# 電腦版：官方 YooAsset 版本閘門 + LaLa 正式版更新檢測

## 目標與兩種版本的區別

- **官方遊戲資源（1262 相容基準）**：用來判斷登入是否需要暫停，來源是官方 Fiddler 實際觀察的三個 HTTPS 端點，不讀取電腦上的遊戲檔案。
- **LaLa 程式自身（目前 v0.5.17 開發候選）**：由 `wlre.__version__` 定義；只和 **blesses0603/WLRe_lala GitHub 正式 Release** 比較；不拿開發中 PR、main 或標籤當已發布更新。兩種版本完全不能混比。
- 使用者提供的 1262 MainPackage／DataPackage Manifest 可以供**離線內容差異分析**，但登入前只需把經驗證的完整版本識別值記錄在 LaLa 內建 JSON。目前不嵌入官方 BundleFiles 或 Manifest 原始二進位，以避免體積與版權問題。

## LaLa 內建相容性基準：唯一來源

由 `wlre/resources/lala_supported_resources.json` 宣告當前 **LaLa 已驗證支援的官方遊戲資源**，而不是以當下官方伺服器版本覆寫設定。程式啟動時讀取此檔，`resource_compatibility.py` 驗證 schema、兩包 revision／完整 Manifest 識別值一致性，再衍生下列用途：

- 官方資源查詢和 **DataPackage／MainPackage 完整 Manifest** 比對。
- 版本檢測視窗「LaLa 支援基準」、每包「與 X 不同／相同」及確認相容時的標題。
- 禁止登入警示、無法驗證提示、版本一致提示。若兩包支援數字不同，標示為 `DataPackage X／MainPackage Y`，不錯誤合併。
- `official_game_exe_version` 也從相同的 JSON 讀取，用於官方 `ResourcePath_PC.dat` 的 ExeVer 映射。它與 **LaLa 程式版本 0.5.x** 不同。

### 維護範例

```json
{
  "schema_version": 1,
  "official_game_exe_version": "1.3.0",
  "packages": {
    "DataPackage": {"revision": "1262", "manifest": "1262_2026_10_14_15_00_34_84"},
    "MainPackage": {"revision": "1262", "manifest": "1262_2026_10_14_15_02_22_47"}
  }
}
```

只有**完成對應官方資料解碼、LaLa 程式和相容性驗收**，並準備隨新 LaLa 正式版一起發布時，才更新支援基準。僅修改此 JSON **不會自動更新** LaLa 的遊戲封包、圖片、NPC、製作配方等實際相依內容，也不是官方自動升版。官方 1275 變更時，LaLa 仍持續以經過驗收的 1262 比對並阻擋登入。

這個 JSON 已列入原生打包必要資源與建置前格式驗證，不允許欄位缺失、版本／Manifest 數字不一致或格式錯誤。實際讀取發行程式內建資源，不從環境變數或使用者安裝的遊戲目錄取值。更新檔案後需重新啟動或重新建置 LaLa 才會生效。

## 官方 YooAsset 實際三階段來源

來源證據：2026-10-22 官方遊戲 Fiddler Everywhere 實際連線，網域 `wlreftp.chinesegamer.net`、HTTP 200、TLS：

1. `https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat`：回傳 `[{"ExeVer":"1.1.3","DataVer":"1.3.21"}, {"ExeVer":"1.1.4","DataVer":"1.3.21"}, {"ExeVer":"1.2.0","DataVer":"1.3.21"}, {"ExeVer":"1.3.0","DataVer":"1.3.21"}]`。
2. 解析映射，使用目前已確認官方 PC ExeVer `1.3.0`；若公告的新遊戲 ExeVer 有不同 DataVer，採最新版本的資源路徑並直接標記需要等待 LaLa 相容性更新，避免永遠查舊 `1.3.21` 目錄。
3. `https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/MainPackage.version`。2026-10-22 觀測回覆 `1275_2026_10_21_18_29_38_49`。
4. `https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/DataPackage.version`。2026-10-22 觀測回覆 `1275_2026_10_21_18_27_33_84`。

### 2026-10-23：DataVer 優先查詢與官方回應格式相容

使用者在 Fiddler 擷取的第一階段請求帶有小數形式的動態查詢參數，例如：

`https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat?46317.9367265972`

參數僅用來避免舊快取，不代表 DataVer、不能固定使用某次擷取值，程式產生自己的時間戳，並僅接受數字或小數的單一查詢參數。實際的 DataVer 必須透過伺服器回應的 `ExeVer`、`DataVer` 對照表取得。

2026-10-23 使用者實機的 `ResourcePath_PC.dat` 回應長度為 **164 bytes**，嚴格 JSON 解析報錯。將先前 Fiddler 顯示的四筆對照資料加上 CRLF 換行及最後一筆後方的尾逗號，**可重建 164 bytes 的 JSON-like 格式**。這是符合證據的格式假說，尚未直接取得本次實機的原始 bytes；修正只移除最外層陣列結尾的**單一尾逗號**，不放寬其他 JSON 語法、路徑格式、版本欄位驗證。

正式查詢順序：`ResourcePath_PC.dat` → 對照 `ExeVer=1.3.0` 取得 `DataVer` → `{DataVer}/ResourcesPC/AssetBundle/DataPackage.version` → 相同 DataVer 的 `MainPackage.version`。以雙包完整 1262 Manifest 識別值作為登入前比對基準。如果對照表仍不可讀，結果標為無法驗證，不得直接套用之前的 `1.3.21`。

以上回覆只代表**當時**已觀測到的值，不得寫死為未來官方最新版本。每次啟動／重新查詢都使用 HTTPS GET 查公開檔案，不需遊戲帳密。下載請求附帶隨機時間參數、no-cache/no-store 標頭降低 CDN 快取誤用風險；但不能保證 CDN 任意延遲都不存在。

只允許 `wlreftp.chinesegamer.net` 的已觀測 URL 型態、TLS、不帶帳密/非預期參數/任意路徑。最多讀取 4 KiB，遇到錯誤格式、轉址、過大檔案不當成版本一致；查不到映射時**不使用上次快取**當最新版本。這裡不使用 `wlreupload.chinesegamer.net` 的舊猜測路徑。

### 登入前行為

| 官方證據 | 結果 |
|---|---|
| MainPackage 和 DataPackage 都與 LaLa 內建完整基準一致且路徑無異動 | 版本識別值一致，顯示登入按鈕 |
| 任一 Package 與 LaLa 內建基準不同，或官方新版資源路徑不同 | **停止登入、顯示「請等待 LaLa 更新」** |
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
python -m unittest discover -s tests -p "test_resource_compatibility.py" -v
python -m unittest discover -s tests -p "test_official_version.py" -v
python -m unittest discover -s tests -p "test_game_version_gate.py" -v
python -m unittest discover -s tests -p "test_lala_updater.py" -v
python -m unittest discover -s tests -p "test_prelogin_version_window.py" -v
```

官方查詢 CLI：`python -m tools.check_official_version --strict`，狀態碼 0 為一致、1 為異動、2 為未知。

測試利用模擬 HTTPS 回應，覆蓋：官方 1.3.21→1275、未來路徑改版、斷線不誤判、非法主機拒絕、版本回應嚴格比對；LaLa 發布檢查不降版、錯誤下載連結拒絕、SHA256 和 ZIP 驗證。CI 通過不等於使用者 Windows 原版環境測試通過，也不等於官方正式服登入 E2E 完成。

**範圍：只改電腦版 PR #48，不改 Android、不合併 main、不建立 Tag/Release。**
