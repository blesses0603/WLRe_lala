# 副本／協力圖示來源（PR #57，2026-10-26）

已加入使用者提供的兩張 PNG：
- `Menu_Dungeon.png`：副本主程式導覽入口、房間管理「主要」子分頁。
- `Menu_Cooperate.png`：房間管理「協力」子分頁。

本次上傳已比對 Git blob SHA，與使用者給定的檔案 **完全一致**；
**原始官方 1275 Bundle 路徑、Sprite / Texture2D 的 path_id
尚未驗證**。因此不宣稱兩張檔案已從官方 1275 Bundle
重新提取，不會自行把截圖加工冒充原始素材。

UI 載入沿用 `instance_menu_icons.py` 與 `RoundedNotebook`；
找不到圖示或圖片無法開啟時，安全退回原有文字分頁，
不影響「副本／協力」功能。

如需重取官方原始素材，請用另附的
`WLRE_1275_Official_UI_Extractor.zip`，指定遊戲客戶端的
`_Data/yoo/MainPackage/BundleFiles` 掃描；
僅有 `.bytes`、`.hash` 的 1275 Manifest 壓縮包不含圖片。
提取結果含 CSV 原始 bundle/path_id 資訊，可對比上述檔案是否相同。

未提供的 `Menu_Tasks.png`、`Menu_Events.png` 和
`Menu_GuildCommission.png` 仍不會以不相關圖示替代。
