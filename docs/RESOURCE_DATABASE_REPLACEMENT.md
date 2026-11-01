# 隨附資源的 SQLite 替代來源

## 舊資源移除

PR #63 將 resources 根目錄的 27 項舊 JSON／ZIP／GZ 移除，改為版本控制中的 `wlre/resources/resource_catalog_seed.sqlite3`。完整資料庫在刪檔前由原始來源生成、逐項驗證並提交；乾淨 checkout 或下載分支 ZIP 都包含資料庫，啟動及打包不需要 Git 歷史、原始檔、本機既有快取或額外下載。

`resource_seed_manifest.py` 保留 27 項邏輯資源的名稱、長度與固定 SHA-256，供獨立校驗。這些名稱是資料庫鍵，不代表仍需交付同名實體檔案。資料庫保留原始位元組於 bundled_resources／bundled_active；既有 JSON／ZIP／GZ 解析器從 BLOB 解析，沒有遺失圖示、表情、導航或歷史 NPC 資料。

Git 既有歷史保留，未改寫 main 或清除歷史提交；使用者設定、帳號資料、官方動態快取與必要 PNG／ICO 不在本次刪除範圍。

## 執行及建置

一般啟動直接使用已隨附、固定來源校驗的資料庫。預設連線設定、伺服器清單與版本相容性政策讀取固定種子，政策不採用可編輯的使用者資料庫。缺少種子時拒絕回退到未校驗設定檔。

Windows／macOS Nuitka 清單僅交付完整資料庫與必要圖片。複製種子時會先後驗證來源與成品；不還原舊原始檔：

```bat
py -3 -m wlre.storage.full_resource_seed --output resource_catalog_seed.sqlite3
py -3 -m wlre.storage.resource_migration
py -3 -m tools.audit_all_resource_database
py -3 WLRE_Client.py --self-test
```

resource_migration 在只有種子的情況補齊新使用者或既有資料庫的缺少項目，保留有效既有版本及其他使用者資料。唯讀稽核以固定種子對照，不會把已刪除的檔案當成空清單而誤報成功。維護者仍可明確指定離線原始資料目錄匯入更新；這不屬於一般啟動的依賴。

## 驗證與邊界

回歸包含：checkout 不含 27 項舊檔、完整種子校驗、資料庫複製、全新安裝、既有資料補缺、偽造內容與自行重算 SHA 拒絕載入、種子式資料匯入及唯讀稽核，以及獨立無原始檔程式目錄的自檢與 GUI 主視窗啟動／關閉。Windows、Ubuntu、macOS CI 重新執行完整測試。

隨附資料不冒充最新官方遊戲資料；正式動態 Runtime 與協定核准保持獨立。原生 EXE／APP 實際編譯安裝與正式服登入／製作／交易／換圖／戰鬥 E2E 尚未驗收，不能由初始化或建置規劃成功推定。
