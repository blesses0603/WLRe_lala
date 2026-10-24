# LaLa 版本無關的官方 NPC／商店／製作／場景資料架構

## 原則

**1275 只是 2026-10-24 已知且可驗證的測試版本，不是檔名、目錄、登入或更新流程的永久常數。** 飄流幻境 Re 每次發布可能修改 NPC、商店、製作、場景其中一部分，也可能只更新其中一個 YooAsset Package，或在同一數字版號下重新發布不同時間戳的 Manifest。

舊程式 `wlre.services.world.runtime_1275` 和 `preview_1275` 使用 `1275_DataCatalog.zip`、`1275_EveNpcIndex.zip`、`version == 1275`；它們是暫時性的固定版本驗證入口，**不能成為往後每週官方更新的終點**。替換它們前必須保留登入前版本閘門及資料校驗，不能把新 Bundle 下載成功誤認為內容已相容。

## 來源識別碼

新版正式使用 `wlre.services.world.catalog_identity.OfficialCatalogIdentity`：

- 官方 `DataVer`：`ResourcePath_PC.dat` 所指向的遊戲資源根版本。
- 官方 `ExeVer`：同一筆版本對照表的客戶端版本。
- `DataPackage.version` 和 `MainPackage.version`：**各自完整**的 `數字_日期_時間` 修訂識別碼，不預設兩包一定同號或同時間。
- 兩包各自經 HTTPS、CRC32LE 及完整 YooAsset parser 驗證的 Manifest **SHA-256**：同一數字版號或同一完整修訂識別碼若重新發布不同內容，仍須生成不同 Catalog 身分。
- Catalog schema 版本：用來標識 LaLa 對衍生資料的儲存格式，不等同遊戲版本。

以上欄位組合成確定性的 SHA-256 `catalog_key`，只使用於個人資料夾中的私有快取：

```
WLRE_LaLa/official_sync/derived_catalogs/<catalog_key>/
```

不再使用固定 `official_resources_1275/` 作為未來新版資料的永久目錄。現有 1275 資料保持不動，直到新的通用 runtime 經過完整測試後才遷移。

## 每次官方更新應執行的完整流程

1. **觀察官方版本**：依官方發布確認兩份 Package 完整修訂號；不是只看 `1275`、`1276` 這個數字。
2. **驗證 Manifest**：在玩家本機下載／重用 `.hash/.bytes`，計算新的 `catalog_key`。
3. **比對必要資源**：由 LaLa 解析器為 NPC、商店、製作、場景提供經審核的確切 AssetPath／BundleName；比較新舊 Manifest 並計算遞迴依賴。
4. **安全增量下載**：僅取得實際欠缺的 Bundle；內容相同者重用本機已驗證檔案；超額或缺檔則停止，不將遊戲素材上傳 GitHub。
5. **版本化解碼器**：依每個來源資料表的實際格式執行可版本演進的 parser／schema adapter。來源欄位增減、格式未知或內容校驗失敗，必須回報具體阻擋原因，不能默默套用 1275 欄位偏移。
6. **逐功能驗收**：分別驗證 NPC、商店、製作、場景四項資料的來源、筆數、參照關聯與版本對應；未通過的功能保持不可用。
7. **原子啟用**：所有登入所需的功能資料都通過回歸測試、且 LaLa 當前程式協定基準確認相容，才切換 active Catalog。不得因官方版本號符合或檔案下載成功就放行登入。

對某項功能而言，若其所依賴的 Bundle 的內容雜湊完全未變，且該功能的 parser schema 未變，可以直接重用經驗證的舊衍生資料，無需每週重新解析所有 21,000 多筆資產。反之應只重建受影響功能及相依索引。

## 功能來源的既有線索（非永久規格）

1275 的 `preview_1275.py` 曾依賴以下來源。這些只是目前供建立**經審核資產需求表**的起點；後續版號必須再核對來源與格式。

| 功能 | 目前已知解析來源類別 | 後續驗收要點 |
| --- | --- | --- |
| NPC | Eve／TalkData_C／TextData_C 等 | 場景 NPC ID、對話、互動索引映射 |
| 商店 | ItemData_C 加 NPC 互動關聯 | 商品 ID、商店關聯與交易條件 |
| 製作 | SmithData_C | 配方欄位寬度、材料／產物與前置條件 |
| 場景 | ScenesData_C／Eve 的門與活動事件 | 場景 ID、門條件、傳送目的地、導航幾何來源 |

1275 的 `SmithData` 33-byte parser 是一個**版本特定 adapter**。未來官方修改欄位或 record size 時，必須新增／調整 adapter 並經單元測試；不能僅更換 ZIP 名稱就當成新版本完成。

## 實作與遷移邊界

- **已完成的底層能力**：版本化官方觀測、YooAsset Manifest 解析、差異計畫、依賴閉包、有配額的單 Bundle 下載、本機 Manifest 收據；新增通用 Catalog 身分可區分 1275、1276、不同 Package 時間戳及同數字版號重發布。
- **未完成**：從官方 Unity Bundle／Lua 資料實際轉換出四項業務 Catalog、feature-specific schema validators、無固定版號的 runtime、GUI 背景同步、週四排程與協定相容性回歸。
- **保持現況**：`runtime_1275` 登入閘門及原有使用者 ZIP 不會在此階段被覆寫或自動替換。沒有可信新版 Catalog 時禁止使用舊 NPC／商店／製作／場景資料放行登入。
- **資源安全**：官方原始檔、帶 AssetPath 的完整索引與衍生資料只留玩家私人快取。公開 GitHub 只提交解析器、schema 定義、測試和文件。

下一步為通用 `OfficialCatalogBuilder`／`CatalogRuntime` 建立功能 adapter 與原子切換。必須先解決各項實際來源資料的可驗證解碼，再接入圖一的更新進度與登入檢測。
