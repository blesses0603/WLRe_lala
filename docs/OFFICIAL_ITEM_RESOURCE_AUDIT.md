# 第十三階段：Android 完整複驗與物品來源盤點

## 表情最終版本的完整回歸

對 Android 第十二階段提交 `8b7e06c57e4982057a4f0e1b0d57cc591e76d918` 重新逐檔執行完整回歸，180 個測試檔全部退出碼 0，無失敗。可從 unittest 輸出計數 1,400 項、略過 4；部分 Kivy 日誌接管 stderr，該計數不是所有實際案例的總數。這次包含先前失敗的聊天 UI、功能及獨立表情 UI 測試，不以局部複驗代替全套結果。

工作區記錄 `/tmp/phase13-android-full.log` 及 `/tmp/normalized-android-isolated/summary.json`。未執行遠端 CI、APK、手機或正式服驗收。

## 移除不需隨附的舊覆蓋報告

兩端全庫搜尋確認 `item_icon_coverage.json` 沒有 runtime／UI 消費者，只有來源／打包清單與 release 測試讀取。它是舊資料的衍生稽核報告，不是官方原始表。

release 測試現在直接開啟剩餘已釘選的 `item_icon_map.json` 與 `item_icons.zip`，逐筆核對 `original_available`，並從真正存在的 PNG 重算覆蓋筆數；保留既有 9,855／1,432 的歷史版本檢查。沒有拿新圖像配舊映射，也沒有改變物品 UI 或猜測新版 icon 欄位。

已刪除 seed active／BLOB 的舊 coverage 報告、VACUUM、移除來源與打包需求並列為 retired。種子由 10 項減為 9 項，大小 68,395,008 bytes。這是取消不需要隨附的稽核檔案，不是宣稱新版物品圖示遷移完成。

這項清理後兩端 release／seed／資源安全相關測試各 39 項通過。Android 完整 180 檔結果對應清理前的最終表情版本；清理後只重跑適當範圍。

## 官方物品圖像實檔證據

官方 1.3.23，MainPackage `1296_2026_11_04_13_36_07_72`：Manifest 的 `Assets/ResourcesBuild/Sprite/Sprite_Item/*.png` 共 4,352 個資產，完整計畫是一個 25,402,412-byte Bundle，在 32 MiB／4 檔查證額度內取得。下載 checksum、UnityFS header、前後官方版本檢查均通過。

原先 TextAsset 精確選取器拒絕同路徑兩物件，並非資源損壞。逐路徑檢查後確認全部 4,352 個資產各自包含恰好一個 Texture2D 及一個 Sprite；每個 Sprite 的 m_RD.texture PathID 與同路徑 Texture2D 相同，且解參照後的 assets_file 也是同一個。以這項實際引用證據選擇 Sprite，未更動產品的 TextAsset 安全選取器、未任選同名第一個物件。

4,352 張 Sprite 全部成功解碼成 RGBA，寬高最大各 128，包含 s1000。逐張精確 AssetPath、Sprite／Texture PathID、尺寸及像素 SHA-256 保存在 `validation/remaining-resources-1296/item-sprites-decoded.json`；重現腳本 `verify-item-sprites.py` 同置工作區。官方圖像、完整清單及原始 Bundle 不加入 Git 或安裝包。

圖像可解碼不等於物品映射已驗證：當次已釘選的 ItemData_C 有 11,366 個 item ID，舊圖像 mapping 只有 11,287 個；有 79 個當次 ID 沒有舊映射，舊 ID 不在當次資料的數量為 0。這項集合比對不能證明重疊 ID 的 icon 語意仍相同。證據記錄 `item-mapping-gap.json`。

## 剩餘 9 項的具體下一步

| 項目 | 還需要的可靠資料／驗證 |
| --- | --- |
| item_icon_map.json | 同版 ItemData.lua 的可讀來源或經獨立驗證的欄位說明，涵蓋 iconId、尺寸、fallback 規則；必須完整處理 11,366 筆及 79 個新增 ID，不以檔名／舊 mapping 猜測。 |
| item_icons.zip | 圖像已完成完整解碼證據，但需以上同版映射，再實作版本化 DB、兩端消費者及 cache 更新／冷啟動驗證。 |
| item_stackable.json | 同版 CanOverlap 欄位與測試向量；現有 parser 跳過未知欄位，不能以位置推論布林。 |
| alchemy_catalog.json | 同版 spares、材料分類、kind/special/restrict 等欄位及跨表驗證；舊來源標記為 1248 matched to 1262，不能視為 1296 語意。 |
| combat_catalog.json | Skill、SkillMotion、Npc、Item 的完整角色／技能／元素權重 adapter 與可靠語意。 |
| normal_attack_data.json | 同版武器、NPC、捕捉網欄位與公式證據；不能從已知價格／名稱推測戰鬥值。 |
| stage_coordinates.json | 同版場景與導航 geometry 的對照，以及 offset_y／sentinel 特例的完整驗證；保留現有相容性閘門。 |
| graph_origins.json | 同版 Scene/NavMesh bounds 與 vertex→packet 轉換的可重現證據。 |
| navigation_data.zip | M10001 樣本完整相依為 88 Bundle、830,825,656 bytes，仍超過現行安全額度；不提高限制、不跳過依賴，也尚無可靠 geometry 解碼。 |

已取得的六份官方 Lua 實檔仍是未識別封裝；目前沒有相符的可靠解碼器或可讀欄位來源。未使用其他遊戲解碼器、猜金鑰或猜二進位欄位。其餘資料保留；下一項物品遷移的關鍵缺口已縮小為同版 ItemData 欄位語意與映射，不能因 Sprite 解碼成功就宣稱完成。

全部變更僅在本機，兩端同步，未推送、合併或建立 Release。官方 UI PNG／程式圖示仍需另行分類，不計入上述 9 項。
