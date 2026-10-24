# LaLa 官方 YooAsset 增量更新（安全預覽／明確下載）

## 已實作流程

1. `ResourcePath_PC.dat` → 遊戲 DataVer → 完整 `DataPackage.version`、`MainPackage.version`。
2. 從**官方 HTTPS** 讀取 `{Package}.hash`、`{Package}.bytes`，驗證 CRC32 little-endian、YooAsset 2.2.5 格式及內嵌修訂版號；私有快取保存 SHA-256 驗證收據。
3. 若存在前一次驗證過的私有收據，選出比當前版號舊的最新 Manifest，完整比對 Bundle 新增／修改／移除；BundleID 重排不會誤判內容變動。
4. 呼叫方用**確切 AssetPath 或 BundleName** 指定真正需要的資源；自動求出跨 Bundle 的遞迴依賴閉包，依賴先列入，路徑遺失或循環就停止。
5. 對每個必要 Bundle 決定：`cached`（新版快取已驗證）、`reuse_previous`（舊版相同檔案經 MD5/CRC32/長度驗證）、`download`（需向官方取得）。
6. **預設只產生計畫**；只有顯式 `--download` 才會在總檔案數／總下載量配額允許下循序抓取。成功不會將遊戲相容性 `assets_ready` 設為 true。

每次官方更新**只下載所選業務功能需要而未快取的 Bundle**。這不是無條件下載整個官方遊戲；沒有選擇器或找不到必要 Asset 時，會安全停止。

## 私有需求清單

要讓 LaLa 自動知道哪些 Bundle 是必要的，首先需要由 NPC、商店、製作、場景等功能的解析模組定義確切 AssetPath／BundleName。不要僅靠資源檔名包含 `npc`、`shop`、`scene` 等文字來決定，也不要把私有完整索引提交 GitHub。

在玩家個人資料夾（**Git 工作樹以外**）建立 JSON。例如以下是目前已由官方實際驗證、可用於第一輪通路測試的**單一** DataPackage Bundle；不代表 NPC／導航等資料已可用：

```json
{
  "schema_version": 1,
  "packages": {
    "DataPackage": {
      "asset_paths": [],
      "bundle_names": ["datapackage_data_v.bundle"]
    }
  }
}
```

檔案可放在 Windows `%LOCALAPPDATA%\\WLRE_LaLa\\official_sync\\required_assets.json`；Linux/macOS 可使用個人私有設定目錄。只以**精確名稱**選取，不接受 `*` 萬用字元；未驗證的新版目標資源缺失時，不沿用 1262 索引。

## 執行（從專案根目錄）

```powershell
# 預覽：讀取兩包版本／Manifest，找出本機可重用與需要下載的檔案；不下載 Bundle
python -m tools.plan_official_incremental --requirements "$env:LOCALAPPDATA\WLRE_LaLa\official_sync\required_assets.json"

# 明確同意後才下載；本例總量最多 64 MiB、最多 32 個 Bundle
python -m tools.plan_official_incremental --requirements "$env:LOCALAPPDATA\WLRE_LaLa\official_sync\required_assets.json" --download --max-mib 64 --max-files 32
```

若要輸出完整必要 Bundle 名稱／依賴清單，加上 `--report` 及一個**不存在的**私有 JSON 路徑。工具會以原子方式建立，不覆蓋舊報告，並拒絕寫入 Git 工作樹。一般 CLI 輸出只有資產數、Bundle 數、差異與大小摘要。

## 1275 私有驗證與未完成事項

- 用使用者私有 1262／1275 DataPackage Manifest 驗證：15 個 Bundle 有內容／相依異動；選取 `datapackage_data_v.bundle` 後，實際必要下載為 **1 個／4,695 bytes**（沒有舊版快取時）。
- 官方真實的同名 1275 Bundle 已通過大小、MD5 及 little-endian CRC32 網路端到端驗證；但尚未啟用整包自動下載。
- 尚缺**經 LaLa 業務模組審核的確切必要資產需求表**、從 Unity Bundle 解析出 NPC/商店/製作/場景資料並建立 1275 資源包、`12910` 缺失 Mesh 的合法來源及遊戲功能回歸。下載一份 Bundle **不能**自動解除圖一的登入阻擋。
- 首次使用、缺乏歷史驗證收據時只能形成 `first_baseline` 計畫；不能假稱已比較過舊版。即使 Manifest 比對成功，遊戲封包／導航相容性仍須另外驗收。
- 對同版號重新發布內容的歷史保存、斷點續傳、週四自動觸發排程、GUI 背景進度顯示、細緻頻寬限速與大於 256 MiB 的必要檔案支援仍待後續實作。目前單檔上限 256 MiB、預設總下載 64 MiB／32 個檔案，採循序下載和校驗後原子快取。

## 安全性

禁止將官方原始 `.bytes`、`.bundle`、含遊戲 AssetPath 的完整索引或玩家私人需求清單提交公開 GitHub。工具僅使用玩家本機快取，來源限定已確認的官方 HTTPS 主機，拒絕轉址、路徑穿越、不符雜湊及配額超標。
