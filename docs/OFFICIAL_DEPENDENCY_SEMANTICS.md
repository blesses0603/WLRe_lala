# 第十一階段：驗證並修正 YooAsset 相依規劃

本機修改，尚未推送。剩餘種子仍為 12 項；本階段消除圖集取得的實際阻擋並保存格式證據，沒有把未接入資料庫／UI 的資源稱為已遷移。

## 對應版本的原始碼證據

Manifest parser 的格式版本為 2.2.5，對應 YooAsset tag 2.2.10。已直接取得以下上游原始碼核對：

- [PackageManifest.GetAllDependencies](https://github.com/tuyoogame/YooAsset/blob/2.2.10/Assets/YooAsset/Runtime/ResourcePackage/PackageManifest.cs)：取得資產主 Bundle 後，直接枚舉該 Bundle 的 DependIDs 並檢查索引範圍，不遞迴展開每個依賴。
- [DeserializeManifestOperation](https://github.com/tuyoogame/YooAsset/blob/2.2.10/Assets/YooAsset/Runtime/ResourcePackage/Operation/Internal/DeserializeManifestOperation.cs)：Bundle 欄位順序與 LaLa parser 一致，DependIDs 是最後的 Int32 array。
- [TaskCreateManifest](https://github.com/tuyoogame/YooAsset/blob/2.2.10/Assets/YooAsset/Editor/AssetBundleBuilder/BuildPipeline/BaseTasks/TaskCreateManifest.cs)：將引擎產生的相依名稱轉成 ID，排除主 Bundle 自身。
- [ScriptableBuildPipeline](https://github.com/tuyoogame/YooAsset/blob/2.2.10/Assets/YooAsset/Editor/AssetBundleBuilder/BuildPipeline/ScriptableBuildPipeline/BuildTasks/TaskCreateManifest_SBP.cs)：從 BundleInfos.Dependencies 取得列表。當次官方 Main Manifest 明確標記使用 ScriptableBuildPipeline。

因此 LaLa 原本把每份 DependIDs 當成 DAG 邊再遞迴並拒絕 cycle，與上游 runtime 的讀取方式不符。本次兩端改成「所選 root 加上每個 root 明列的完整相依集合」，合併去重、固定排序；沒有下載依賴以外的未知資源。所有 Manifest 身分、缺少依賴、Bundle 大小／指紋／checksum、下載數及總額度限制照常執行。這是下載規劃，不是在 Python 中執行 Unity 載入順序。

## 官方實檔結果

官方 1.3.23、MainPackage `1296_2026_11_04_13_36_07_72`：

| 精確資產 | 相依計畫 | 結果 |
| --- | --- | --- |
| Sprite/Atlas/SpriteAtlas_Emoji/SpriteAtlas_Emoji.spriteatlasv2 | 6 Bundles，共 26,541,041 bytes | 32 MiB／8 檔的獨立查證額度內，全部下載、checksum、UnityFS header 校驗通過；精確 container 物件為 SpriteAtlas，246 張 packed Sprite 全部解碼並保存尺寸與 RGBA SHA-256。未替換成 SC 圖集。 |
| Sprite/Sprite_Item/s1000.png | 1 Bundle，25,402,412 bytes | 已驗證計畫；本階段未下載／解碼該 Bundle，Item ID→sprite 欄位仍缺獨立證據。 |
| Scenes/BaseScenes/M10001/M10001.unity | 88 Bundles，830,825,656 bytes | 計畫不再錯誤拒絕 cycle，但超過現有安全下載額度。沒有提高額度、刪除依賴或假稱完成導航幾何驗證。 |

三組計畫中，root 的明列相依集合都已包含其各依賴的相依：額外遞迴增加數為 0。這是當次 Manifest 的獨立核對結果，不把它強加為所有未來 Manifest 的格式規則。

桌面及 Android 查證腳本均完整解出 Emoji 圖集 246 張 Sprite。使用 UnityPy 的 Sprite 圖像解碼處理裁切／旋轉及外部貼圖引用；不是將 atlas 原圖當成每個表情。原圖、Bundle、完整資產清單及 Sprite 像素指紋僅存工作區，不納入 Git／安裝包。圖像語意仍需與 token、第一幀命名、UI 生命週期一起驗證。

## 表情表的進一步證據

既有經審核的 62 筆 catalog 欄位，依數字 token 順序，以 count u32 + 每筆 `(id u8, mark_id u8, icon_id u8, text_id u32, hidden u8)` 重新編碼，其中 hidden 為既有 show_in_list 的反值，icon_id 取既有明確 sprite ID。產生的完整 500 bytes 與當次官方 EmojiData_C **完全相同**，SHA-256：`b21c48d487d83463332157e1d56af0a258f26cecf2e906ca518526badcd5a75b`。

這是完整 round-trip 證據，能支持下一階段只接受此已知原檔指紋的嚴格解析器；不能據此接受任意新版 layout 或一般化 Lua 解碼。下一步仍需規範 catalog DB、變尺寸 Sprite 圖像 DB、62 個 token 與第一幀完整 join、桌面和 Android 消費者更新、冷啟動與失敗回滾測試。完成前保留 emoji_catalog.json 及 emoji_images.zip。

## 測試與限制

- 桌面官方同步／動態 Runtime／圖像 DB 等相關測試 197 項，略過 1，無失敗。
- Android 同範圍 138 項，無失敗。
- 新增兩端共用 6 項測試：互相依賴可形成有限唯一集合、不遞迴重新解釋完整集合、多 root 合併、重複項去重、缺少依賴拒絕、asset/root 等價、循環不能繞過預算（部分在同一案例中驗證）。
- 實檔下載前後官方版本一致。未執行遊戲、正式服封包、APK、手機或遠端 CI。本階段未重跑全套回歸。
- 其餘導航幾何、物品語意、鍊金／戰鬥欄位缺口沿用第十階段逐項盤點；沒有聲稱所有剩餘項目不可做。

私有證據：`validation/remaining-resources-1296/yooasset-direct-dependencies.json`、`emoji-atlas-decoded.json`、`emoji-roundtrip.json`。上游查核檔案另存 `/tmp/yoo-*.cs`。
