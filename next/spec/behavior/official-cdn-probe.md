# 官方 CDN 目錄列表與 manifest（0-6 探測工具的規格）

> 工具：`next/tools-python/probe_official.py`；離線測試：`next/tools-python/test_probe_official.py`。
> 2026-10-27 實際對官方 CDN 執行過兩次 `scan`（見文末「執行紀錄」）。

## 1. 入口與轉址（實際觀察）

| 請求 | 回應 |
|---|---|
| 入口網址**含**結尾 `/` | 直接 `200`，目錄頁標題顯示的主機是 `wlreftpsrc…`（伺服器內部重寫，用戶端看不到轉址） |
| 入口網址**不含**結尾 `/` | `301`，轉到 `wlreftpsrc…` 主機、路徑補上 `/` |

`PLAN.md` 原本記載的是 `302`。這次觀察到的是 `301`，而且只在少了結尾斜線時才發生。

**規則：** 轉址要跟隨，但每一次轉址的目標都要檢查：必須是 `https`、主機屬於入口網址的同一個上層網域
（由入口主機名稱的最後兩段推得，**不寫死**），而且不能有埠號、帳密、query、fragment。不符合就拒絕整次掃描。
之後所有子連結都以「轉址後的最終根目錄」為基準。

## 2. 目錄列表頁格式（IIS 10 目錄瀏覽）

- `Content-Type: text/html; charset=UTF-8`，內容在 `<pre>` 內，每列以 `<br>` 結尾。
- 第一個連結是 `[移至上層目錄]`，沒有日期與大小。
- 其餘每列：`日期 上午|下午 時:分 大小或&lt;dir&gt; <A HREF="絕對路徑">名稱</A>`。
  - 日期 `YYYY/M/D`（月、日不補零），時間是 12 小時制，以「上午／下午」表示，是**伺服器當地時間**，沒有時區。
  - 換成 24 小時制時：`下午 12:xx` → 12 點、`上午 12:xx` → 0 點。
  - 檔案的大小是位元組數；資料夾顯示 `<dir>`，HREF 以 `/` 結尾。
- **拒絕條件：** 沒有 `<pre>`；或除了上層目錄那一個之外，還有連結對不上列的格式。
- `web.config` 會出現在列表中，但 GET 會回 `404`（IIS 預設封鎖），屬於預期情況，但工具仍把它記為 `error`。

## 3. 掃描順序與限制

1. **先列目錄**：廣度優先，只對資料夾發請求。
2. **再下載檔案**：依列表大小由小到大，讓設定檔與清單先下載。
3. 每次請求之間至少間隔 0.5 秒（每秒最多 2 個請求）；只用 GET。

| 參數（預設） | 意義 |
|---|---|
| `--max-depth 3` | 超過深度的資料夾記為 `not_listed_depth` |
| `--skip-dir AssetBundle Voice Lua` | 不展開，記為 `not_listed_skipped`；`--include-dir` 可強制展開 |
| `--skip-file *.png *.jpg` | 不下載，但保留列表大小與時間，記為 `not_downloaded_skipped`；`--skip-file none` 全部下載 |
| `--hash-max-bytes 1048576` | 列表大小超過上限的檔案不下載，記為 `not_downloaded_size` |
| `--max-requests 400` | 用完後，剩下的資料夾記為 `not_listed_request_limit`、檔案記為 `not_downloaded_request_limit` |

下載後的實際長度必須等於列表大小，否則不記雜湊、狀態記為 `error`，避免把不完整的內容當成某個版本。

## 4. manifest.json（schema 1）

只存在本機快取：`~/.lala-cache/official/manifests/manifest-<UTC時間>.json`，另存一份 `latest.json`。
下載的檔案在 `~/.lala-cache/official/files/<相對路徑>`。**兩者都不得放進 repo。**

```json
{
  "schema": 1,
  "generated_at": "2026-10-27T04:07:14Z",
  "entry_url": "<入口網址>",
  "resolved_root": "<轉址後的根目錄>",
  "settings": { "max_depth": 3, "hash_max_bytes": 1048576, "...": "..." },
  "requests": 63,
  "entries": [
    { "path": "1.3.21", "kind": "dir", "listed_time": "2026-10-22T08:37", "status": "listed" },
    { "path": "ResourcePath_PC.dat", "kind": "file", "listed_size": 164,
      "listed_time": "2026-10-15T11:19", "size": 164, "sha256": "…", "status": "hashed" }
  ],
  "problems": [ { "path": "web.config", "problem": "HTTP 404" } ]
}
```

- `path` 是相對於根目錄的 posix 路徑，依字母排序；不含 `.`、`..`、`\`。
- `sha256` 只在 `status == "hashed"` 時有值。

## 5. 差異比對（`diff`，以及 `scan` 時自動和 `latest.json` 比對）

| 欄位 | 規則 |
|---|---|
| `added`／`removed` | 只出現在新／舊 manifest 的檔案路徑 |
| `changed` | 兩邊都有 `sha256` 且不同（`reason: sha256`）；或任一邊沒雜湊，但列表大小不同（`reason: listed_size`） |
| `unchanged` | 兩邊都有雜湊而且相同 |
| `size_same_unverified` | 至少一邊沒有雜湊、列表大小相同：**不能斷言內容沒變** |
| `dirs_added`／`dirs_removed` | 資料夾路徑的差異 |

schema 不同就拒絕比對。

## 6. 執行紀錄（2026-10-27，雲端沙箱，可以連到官方 CDN）

| 次數 | 設定 | 結果 |
|---|---|---|
| 第 1 次 | 舊版工具：邊列目錄邊下載，沒有略過圖片 | 400 個請求用完，10 個資料夾沒有列到。**發現問題後改成兩階段掃描** |
| 第 2 次 | 目前的預設值 | 63 個請求、約 34 秒；28 個資料夾全部列出（13 個依設定略過）、421 個檔案；46 個已計算雜湊、374 個圖片略過、1 個 404（`web.config`） |

第 2 次和第 1 次的 diff：`changed` 0、`unchanged` 20。第 1 次沒有掃到的部分顯示為 `added` 26、`dirs_added` 10。
這證明 diff 在真實資料上能正確運作，但**還沒有**觀察過官方真正改版時的 diff。

## 未決事項

- `AssetBundle/`、`Lua/`、`Voice/` 的完整列表與雜湊：工具支援（`--include-dir`），但**尚未執行**（請求數量大，要另外估算）。
- 圖片類公告檔只記錄列表大小，沒有雜湊。
- 列表時間沒有時區；只拿來做參考，不拿來判斷新舊。
