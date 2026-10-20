# v0.5.2 官方右側功能圖示（原始 PNG 待提供）

使用者截圖右側由上至下的圖示：**任務、副本、活動、協力、公會委託**。

目前 GitHub 現有 `assets/function-icons/MainIcon_*.png` 是另一組功能導航素材，
**無法證明其與此五枚遊戲右側圖示是同一張 Sprite**。使用者提供的
`resources_1262.zip` 僅含 `resources.assets` 與 `resources.resource`，
尚未核實可以抽取右側五枚透明 UI 圖示。

若取得原始遊戲貼圖，請解包 1262 的 `MainPackage` UI 圖集
（例如 `mainpackage_atlas.bundle`、其他 SpriteAtlas 的 Unity Bundle），
提供含透明通道的 PNG 或完整原始 Bundle，保留原檔名稱與圖集來源。

放在此目錄的檔名：
- `Menu_Dungeon.png`：副本（主頁入口 + 副本視窗「主要」）
- `Menu_Cooperate.png`：協力（副本視窗「協力」）
- `Menu_Tasks.png`：任務（備用，目前無對應功能入口）
- `Menu_Events.png`：活動（備用）
- `Menu_GuildCommission.png`：公會委託（備用）

副本與協力的 PNG 只要加入本目錄，下一次啟動 LaLa 會自動載入對應透明
原圖；未提供時仍保留文字按鈕，避免誤用相似但不相同的圖。

此資料夾不包含從螢幕截圖擷取、去背的假原始圖示。
