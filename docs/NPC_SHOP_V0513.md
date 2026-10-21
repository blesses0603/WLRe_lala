# NPC 第三階段：武器／道具商店與交易安全（v0.5.13 開發版）

## 官方 1262 資料證據（已逐檔核對）

- Lua/Logic/EventManager.lua：EventInteractList 依 Eve 的 formKind 開啟普通選項（1）、武器商店（2）、道具商店（3）；SendCloseShop 使用 C20-9 **零位元組 payload**，不同於普通選項 C20-9 40。
- Lua/Logic/Shop.lua：ShopCommodityData.SetDataFromEvent 僅接受 subItem.kind=3，商品索引是 subItem.id，物品 ID 是 subItem.dataBaseId。價格取 itemData[itemId].price、幣種 Gold，不是 TalkData 字串。
- Lua/Logic/Shop.lua：SendPurchaseItem(index,buyingCount) 發 C27-1，欄位為 u8 商品索引 + u32 數量（Little Endian）。
- Lua/Logic/Bag.lua：SendSellItem(index,count) 發 C27-3，欄位為 u8 背包格位 + u8 數量。
- Lua/Logic/Protocols/Protocols_027.lua：S27-1 購買結果 1 byte，0 伺服器回覆成功、1 金幣不足、2 背包空間不足、3 超數量、4 其他失敗；S27-6 為販售後背包/金幣資料；S27-8 為販售結果通知（1 成功）。
- Lua/Data/ItemData.lua：ItemData.New 的 price 和 sellPrice 是 u32；restrict 的 bit 16 表示不可賣給 NPC。
- 官方 Eve 1262 資源：共 65 組 formKind 2/3 商店（19 武器、46 道具）。目前 65 組商品的 kind=3 / database_kind=2 都通過來源核對。

## 已完成

1. 新增 wlre/services/world/npc_shop.py：只接受已驗證 Eve 真實場景及 formKind=2/3，按官方 id 列出商品，已知名稱取現有戰鬥道具清單；未知名稱顯示 ID。不把商品 id 當作一般 NPC 對話或 TextData。
2. 小地圖 NPC 分頁在已接收到該場景的 S20 type 6 商店事件時開啟唯讀商品／背包視窗；尚未同步的背包不顯示推測存貨。買入／賣出金額一律顯示「待官方 ItemData_C」。
3. 獨立的 close_npc_shop 只在商店真實事件啟動、場景一致、手動確認時送一次官方 C20-9 空內容，等待 S20-8。普通對話關閉不再適用於已核對的商店。
4. 補上 S27-1 官方 1-byte 回覆解析，S27-8 既有訊息沿用。伺服器回覆成功**不等於**價格已扣除或物品已入背包，必須重新核對實際同步。
5. purchase_wire_layout / sell_wire_layout 僅用於單元測試及未來協定驗證。命令路由明確拒絕 npc_shop_buy / npc_shop_sell；現階段任何交易都不會送到伺服器。

## 尚缺與後續必要條件

- 完整官方 ItemData_C TextAsset（不是 TextData_C 或 TalkData_C），用於確認商品 name、price、sellPrice、restrict、可堆疊狀態。
- 角色 Gold 的真實 S 封包載入、持有金額與修訂版次。沒有權威同步不允許付款。
- 購買前必須確認背包空格與容量、數量上限、價格×數量溢位保護、交易前金額、交易唯一識別，以及購買結果和背包變化一致性。
- 販售前必須先查 restrict bit 16、已同步可售格位與實際數量；不得賣任務物品、綁定或未核對物品。
- 交易須人工二次確認；送出後不重送，直到權威 Gold 與背包資料對帳完成，遇不一致則標記 uncertain 並要求重新登入。
- 正式遊戲伺服器真實 NPC 買賣、關閉商店與伺服器重試情境仍未 E2E 驗收，不能宣稱真實購物功能可用。

## 下一階段所需的來源

可沿用以前的 AssetStudioMod 或 UnityPy 搜尋器，從 DataPackage/MainPackage 的 BundleFiles 掃描 TextAsset 名稱 ItemData_C，保留原始 bytes 與掃描報告。不要從資料庫或一般文字 ID 推算價格。完成可靠 ItemData_C 解碼並擷取金幣同步封包後，才能啟用真正的購買與販售。
