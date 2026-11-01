# 隨附資源的 SQLite 替代來源

PR #63 後續整合：新增 `wlre.storage.resource_migration`，完整匯入 resources 根目錄的 JSON／ZIP／GZ。所有寫入在同一交易完成，核對既有 active BLOB 與新增內容，保留歷史版本；任何損壞都拒絕繼續。

一般 `load_bundled_bytes/json` 優先讀取並校驗資料庫，不再開啟仍存在的原始檔。來源更新須明確使用 `refresh=True` 或重新執行全量匯入。物品圖示及表情目錄／ZIP 已使用同一資料庫讀取路徑。

```bat
py -3 -m wlre.storage.resource_migration
py -3 -m tools.audit_all_resource_database
```

此環境已完整匯入 27 項，唯讀稽核得到 `identical=27`、`all_identical=true`。另以全新暫存資料庫匯入實際全部資源，再以空資源目錄逐項讀取，27 項內容均與原始檔一致。這不代表使用者電腦已完成匯入。

新增測試涵蓋原始檔移除後讀取、損壞資料拒絕回退、明確更新來源，以及沒有原始圖檔／ZIP 時仍能開啟圖示與表情資料庫來源。

本次補齊資料庫儲存與讀取替代來源，未刪除倉庫原始資源。乾淨安裝首次建立資料庫仍須來源檔或另外交付的已驗證種子；現有打包資源清單及初始種子流程尚未改為全量資料庫交付。程式相容性政策、伺服器清單等設定檔與必要 PNG 圖片仍保留。正式動態遊戲資料及協定核准流程保持獨立，隨附資料匯入不代表最新官方資料或正式服操作已驗收。

## 完整初始資料庫補齊

新增 `full_resource_seed` 及獨立固定來源清單 `resource_seed_manifest.py`，完整收錄上述 27 項資源的名稱、長度及 SHA-256。可執行：

```bat
py -3 -m wlre.storage.full_resource_seed --output resource_catalog_seed.sqlite3
```

種子與原始資料不同位置亦可驗證。當 resources 目錄只保留 `resource_catalog_seed.sqlite3`、原始資料已缺少時，資料讀取器會先驗證種子並補齊新使用者或既有資料庫的缺少項目，保留既有有效版本及其他使用者資料。種子內容與自行修改的 SHA 不符合獨立固定清單時拒絕安裝。

已實際生成完整種子，並加入乾淨安裝無原始檔、既有資料庫補齊及偽造內容／雜湊拒絕載入測試。這補齊資料庫內容及種子載入能力；EXE 打包清單尚未改造為只交付種子，倉庫原始檔仍保留。歷史資料不冒充最新官方遊戲資料。
