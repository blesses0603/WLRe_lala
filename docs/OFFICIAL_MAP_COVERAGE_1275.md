# 1275 官方小地圖覆蓋檢查（2026-10-26）

已讀取使用者先前提供的官方 MainPackage 1275 Manifest，核對固定 SHA-256：
`65da10fab29b8ce96247a18e611ee0ba3c5c3bc5cb71a42c4e177001a8c4ba49`。
這是已審核的 1275 清單，尚未在線上重新確認今天的官方最新版本。

| 比對項目 | 結果 |
| --- | ---: |
| 清單中的一般場景模型 Bundle | 775 |
| 明確 SmallMap2D 圖像資產 | 550 |
| LaLa 具備的對應圖像 ID | 550 |
| 缺少的官方圖像 ID | 0 |
| 未列出官方小地圖資產的模型 | 225 |

已逐張核對 LaLa 圖像存在性、索引記錄的編碼雜湊、1024×1024 尺寸與 RGBA 解碼。
場景模型 ID 不等於邏輯地圖 ID；不同邏輯場景可能共用模型。
225 個未列 SmallMap2D 的模型不代表 LaLa 漏下載，不使用猜測圖像代填。

## 圖像內容尚待核對

1262 `mainpackage_texture_s.bundle` 的 FileHash 為 `7487d27d8d44d99a0b8ca3e479e856fa`；
1275 為 `969661064721a97d6dccf64967b0947c`，大小 43,060,498 bytes。
Bundle 指紋變更可能包括包裝／metadata 或像素變更，不能單憑雜湊斷言哪張圖已更新。
因此沒有把「550 個 ID 齊全」標為「550 張新版像素相同」，也未直接替換現有地圖。

目前官方 CDN `wlreftp.chinesegamer.net` 下載失敗；執行環境白名單不含此主機。
已保存加入該主機的網路設定草稿，需使用者於環境設定儲存並發佈，尚未套用。

## 可重跑工具

`tools.audit_official_maps` 離線模式只接受固定 SHA 的 1275 MainPackage `.bytes`。
報告逐模型列出存在性、官方資產與是否完成像素對照，原始資料僅留私人目錄。

```bash
python -m tools.audit_official_maps --manifest /private/MainPackage_1275.bytes --output-dir /private/map-audit
```

官方網路可用後，不需使用者準備資料 ZIP：

```bash
python -m tools.audit_official_maps --online --output-dir /private/map-pixel-comparison
```

線上流程重用官方版本觀測、Manifest .hash／.bytes、固定 SHA、Bundle MD5／CRC
與下載預算機制，只選明確的 SmallMap2D 資產及依賴。版本不支援或中途變更即拒絕。
解碼器按完整資產路徑與名稱匹配，拒絕未知尺寸／圖像類型；逐張比較 RGBA 像素，
並輸出私人 `official_smallmaps_1275.zip` 供後續核對。輸出資料夾不得已存在，
失敗時刪除本次不完整圖像封裝；不覆寫使用者快取與既有 `smallmaps.zip`。
線上下載與真實官方 Texture2D 解碼尚未執行成功，未宣稱圖像已替換或投影已驗證。

離線 550 張圖像實際掃描成功；比對工具 2 項單元測試通過。
上述完整回歸同輪 1126 通過、2 跳過；線上官方 Bundle 下載與像素比對仍未通過驗收。
