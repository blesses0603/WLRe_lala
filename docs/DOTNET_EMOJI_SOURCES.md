# ver 8.0.65 表情資料映射與受限來源準備

本批新增內部 `PrepareEmojiSourcesAsync` 入口及 `EmojiMapping`。尚未掛入 production 自動準備／啟用流程，沒有表情圖片資料庫、publication、桌面顯示或聊天發送。本批不代表正式表情取得已正向驗收。

## Python 映射

沿用 `wlre/services/world/emoji_database.py` 的固定 EmojiData_C 原始 SHA256：`b21c48d487d83463332157e1d56af0a258f26cecf2e906ca518526badcd5a75b`。先限制最多 2044 bytes，再檢查 hash、1..255 筆及精確長度。每筆是 id／mark／icon／uint32 text／hidden 的 8 bytes；id、icon、text 不可零，hidden 必須 0 或 1。

Token 使用 **1-based 列序號**；不以 id 或 mark_id 查找。相同 id／icon 不會刪掉資料列，首幀名稱 `Emoji_{icon:03}_1` 則以集合去重，hidden 只控制列表顯示。資料及返回列不可變，未知 token 回傳缺席。

明示的離線 layout parser 只給自有 fixture 使用，標記 Reviewed=false；來源捕捉會拒絕這種映射。正式 API 不接受可替換 hash 或「來源可信」旗標。

## 精確來源及順序

- 僅接受已知 DataVersion 1.3.23、DataPackage `1296_2026_11_04_13_34_19_13` 與 MainPackage `1296_2026_11_04_13_36_07_72`。未知版本不套用既有格式。
- DataPackage 精確路徑 `Assets/ResourcesBuild/Data/EmojiData_C.bytes`；MainPackage 精確路徑 `Assets/ResourcesBuild/Sprite/Atlas/SpriteAtlas_Emoji/SpriteAtlas_Emoji.spriteatlasv2`。
- 依 Manifest 為各根列出的完整 dependency set 加 root，不遞迴 dependency 的 dependencies。保留完整 manifest SHA、Bundle spec、每資產閉包與取得的 SHA256。
- 預先檢查兩份計畫。資料閉包最多 24 檔／32 MiB；圖集閉包依 Python 限 **8 檔／32 MiB**；此來源數量限制不擴大既有選定解碼範圍。後續實際解碼還必須檢查 SerializedFile 數量、格式和指標。
- 重用既有 required attempt、官方 HTTPS URL 組合、cache 檢查、共同下載數／bytes 與停止／撤銷守衛。取得資料 Bundle、精確 TextAsset 解碼、固定 raw SHA／映射通過後才取得圖集。未知 EmojiData 不產生圖集請求。
- 捕捉來源時再次由已擁有的 Data Bundle 獨立解出 mapping，不信任呼叫者列資料。最終重查兩份完整 Manifest、版本及當前 attempt，才回傳不可變準備結果。

Bundle checksums 與這個準備結果仍是 byte/source observations；圖集沒有憑空加入官方 SHA pin。只有 EmojiData raw pin 是 Python 已審查常數。這個入口不能自行建立官方 provenance、目前帳號 publication 或 UI readiness；正式宿主來源准入仍是必要條件。

## 公開來源核對（2026-11-09 UTC）

只讀官方 HTTPS `.version`、Manifest `.bytes`／`.hash`，沿用 Python 同來源、版本、CRC 與完整索引驗證，確認版本仍與上述常數一致。表情資料根為 `datapackage_data_e.bundle`（1,822,959 bytes）；圖集精確閉包為六檔合計 26,541,041 bytes：

- `mainpackage_share_assets_resourcesbuild_sprite_sprite_bricktreasure.bundle`：241,598
- `mainpackage_share_assets_resourcesbuild_sprite_sprite_emoji_sc.bundle`：787,748
- `mainpackage_share_assets_resourcesbuild_sprite_sprite_gamewhackmole.bundle`：686,253
- `mainpackage_share_assets_resourcesbuild_sprite_sprite_monopoly.bundle`：616,676
- `mainpackage_share_assets_resourcesbuild_sprite_sprite_resonance.bundle`：493,351
- `mainpackage_atlas.bundle`：23,715,415

這項觀察修正了原先四檔來源限制，沒有省略 Manifest 依賴或遞迴加檔。隨後依這份精確計畫取得並驗證全部六檔圖集 Bundle 的 size／MD5／CRC，只在雲端 `/tmp/lala-v65-public-reference` 檢查，不提交原始資料到 repo。Python 實際核對 Data Bundle 的 EmojiData 原文為 **500 bytes、62 列／62 首幀**，raw SHA 與固定值完全一致；這是公開來源檢查，不是 C# runtime 或桌面正向驗收。

Python 圖集元資料檢查得到 **246 packed Sprite／246 render entries，settingsRaw 全為 67**。三張貼圖為色域 1、單 mip、DXT5，兩張 1024×1024、一張 512×512；inline bytes 為零，資料位於同 Bundle 的 `CAB-cea8ff565680c1d33e8f134c42bb48fe.resS`，完整 archive 路徑必須精確配對。三段 (offset,size) 分別為 (54400192,1048576)、(10739280,1048576)、(4147136,262144)。圖集 owner 是 `CAB-cea8ff565680c1d33e8f134c42bb48fe`。

全部 62 個首幀具有明示本檔 atlas PPtr、非空 physics shapes，至少一維邏輯尺寸不同於 atlas crop；圖集全體 physics shape 的最大單形點數為 38。這些是目前 Core **settingsRaw 67／physics shape／trim／.resS** 尚未支援的實際缺口，不是下載或登入問題。現有 C# 解析器保持拒絕，未擅自放寬；下一批必須用獨立向量完整驗證這些路徑後才能組合整批。沒有正式登入或遊戲 TCP，也未宣稱官方首幀像素已通過 C#。

完整 Manifest／Bundle SHA256 與範圍紀錄見 [公開來源 audit](emoji_source_1296_audit.json)；這些紀錄尚未自動成為 Core 的准入 pin。

## 測試與尚待接線

Python 真實 `parse_entries` 以明示的自有 fixture digest seam 產生獨立對照；C# 正式 parser 必須拒絕所有這些合成 bytes。另以 UnityPy 真實 writer 建立精確 EmojiData TextAsset／UnityFS，驗證取得與解碼確實到達 raw SHA gate，再拒絕圖集下載。包含額度、重用、不遞迴閉包、版本／路徑、取消及退役。**C# 完整準備／圖集／發布的正式來源正向驗收尚未完成**；上述 Python 公開資料 raw SHA 已另行核對，沒有改寫正式 pin 來讓測試通過。

仍需官方完整圖集的精確容器／CAB 外部引用證據、首幀整批驗證、PNG／SQLite 新連線獨立回讀、來源重查與可撤銷發布，再接 production 與表情 UI。小地圖來源、模型映射及顯示仍未完成；未宣稱完整 Python UI 或效能提升。`HasVisualAssets=false`、一般操作 Held；未連正式服、未使用真帳密。
