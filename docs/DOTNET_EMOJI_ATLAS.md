# ver 8.0.63 SpriteAtlas 結構解析前置層

本批只新增內部、離線的 SpriteAtlas class 687078895 結構投影，不是正式表情圖集取得或像素驗收。沒有新的 public API、下載、資料庫、publication 或桌面圖片入口。既有物品圖與 TextAsset 入口不自動接納圖集。

## 格式及限制

固定 SerializedFile22／Windows64／2021.3.45f2、UnityPy 1.25.4 所附 release TPK 的 70-node schema 指紋。新增獨立 allowAtlases opt-in，只有這個 class 的深度上限為 10；其他 class 不變。每個物件上限 2 MiB、packed sprites／names／render data 各最多 2048；字串最多 1024 bytes。取消、截斷、尾隨資料、重複指標／名稱／render key、非有限浮點、無效指標與尺寸均拒絕。

保留完整 GUID＋64-bit render key、Sprite PPtr、Texture／alpha PPtr、裁切、兩組 offset、UV、downscale 與 settingsRaw，並以獨立不可變集合交付。外部指標只是保留 file index；尚未證明其對應來源。Variant／secondary textures 未支援。非零 alpha 和 packed settings 可作為結構資料保留，**不代表已有解碼或繪製支援**；不得直接餵入現有非圖集 Sprite 像素路徑。

## 獨立證據

`dotnet/Lala.Core.Tests/Resources/Atlases/generate_atlases.py` 使用固定 UnityPy 真實 write_typetree、SerializedFile.save、read_typetree 完整回讀比對自有物件，包括兩個不同 render keys／外部指標和非零 offsets／UV。輸出有 TPK SHA256、schema SHA256、自有 SerializedFile 與正反案例。Fixture 不是官方 Bundle，也不替換任何正式來源 pin。UnityPy 使用與既有圖資 fixture 相同的 MIT 授權參考，見 `dotnet/Lala.Core.Tests/Resources/UnityImages/UNITYPY-LICENSE.txt` 及 UnityTextAssets 的第三方說明。

## Python 行為與下一步

- `wlre/services/world/emoji_database.py`：EmojiData_C 要求既有固定原始 SHA；聊天 token 是資料列的 1-based 序號，不是 id／mark_id。每列選 `Emoji_{icon:03}_1` 首幀；hidden 控制列表顯示。須從精確 SpriteAtlas 資產路徑取得全部需要的首幀。
- 仍需圖集 Sprite 的 renderDataKey／atlas PPtr 解析、來源身份與外部指標配對、packed texture rect／rotation／alpha／UV 的可靠像素規則及獨立像素對照；不能將結構解析成功當成可顯示。
- 之後才是同版 EmojiData 映射、整批來源與 PNG／SQLite 獨立回讀、可撤銷發布、聊天／表情選單顯示。未知 token 保留原文字，不自動發送聊天。
- `smallmap_database.py`／`smallmaps.py`：小地圖使用精確 SmallMap2D 路徑的 1024×1024 Texture2D；最多 2048 圖，模型 ID 唯一且 1..65535。場景 ID 需經當前 StageData 模型映射，不能視為圖片 ID。小地圖的來源計畫、PNG／SQLite、撤銷及桌面顯示仍未完成，顯示投影不授權導航發送。

本批不改 HasVisualAssets=false／一般遊戲操作 Held，也不宣稱完整 Python UI、正式圖資、GPU 或正式服驗收。
