# 當前場景商店目錄與預覽（ver 8.0.80）

Python 依據：`wlre/services/world/npc_shop.py` 的 `shop_catalog`、`draft_purchase`，以及 `npc_item_data.py` 的 `sellable`。既有 Core 已有 Eve 互動索引、ItemData 基礎價格及 S23/S26/S27 回覆觀測，但缺少可撤銷的當前場景商品目錄。

`AccountRuntime.TryGetSceneShopPreview(scene, interactionIndex, ...)` 僅從當前同版資源查詢明確互動索引；沒有使用 NPC index、名字或商品列序猜測。資料限定 form 2/3、kind 3/database 2，退出 kind 4 跳過；保留原始商品索引與順序。缺少價格仍是 null，不以零補值；官方零價格保留。restrict & 16 表示目錄禁售，不是實際可賣權限。

購買預覽核對數量 1–9999、商品索引及 uint 基礎金額溢位，返回實際成交金額 null、Enabled false。沒有封包建構或送出。預覽數量範圍沿用 Python，不能據此宣稱實際協定或背包支持該數量。

資源及帳號／接收 attempt／目前場景撤銷後，不再交付目錄或預覽。公開產品及預覽是不可變歷史資料，保留它們不能授權交易。單目錄最多 255 列（含退出列），超額安全拒絕；未知名稱使用中性物品 ID 文字，不查歷史全域目錄。

尚未接桌面商店視窗或 live S20 手動開店上下文，折扣、目前金幣、庫存與結算仍未知。測試涵蓋型別、重複、退出、禁售、缺價、零價、數量、溢位及撤銷競態，交 GitHub CI 執行；正向帳號 fixture 仍屬合成驗證，沒有真實遊戲命令。
