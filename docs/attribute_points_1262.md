# 1262 角色配點協定（LaLa）

依據已上傳 1262 Lua：
- `Lua/Common/Define.lua`：EAttribute Int=27 Str=28 Con=29 Agi=30 Wis=33 AttrPot=38，MaxLimitAttrPot=602。
- `Lua/Logic/Attribute.lua`：`Send_AddPlayerAttribute` 寫入 C8-1，資料是 `u8(0)` + `u8(count)` + count 組 `u8(attribute_kind) + u32(points)`（小端序）。
- `Lua/Logic/Protocols/Protocols_008.lua`：S8-1 是能力值更新、S8-4 無負載成功提示。
- `Lua/UI/Logic/UIAttributesPoint.lua`：五項能力先本地暫存、確認後才送出。戰鬥中拒絕配點。

LaLa 以 S5-3 的五項基礎能力與 `attribute_potential` 作為權威基準；S8-1 的 Int/Str/Con/Agi/Wis/AttrPot 需反映到玩家統計。
為避免未驗證的潛能加成超額配點，暫時僅允許原始屬性小於 602 的增點（比原版限制更保守）。
傳送期間不能重複提交，需同時收到 S8-4 成功與對應的能力/點數權威更新才解除鎖定。
逾時會標示結果未確認，必須重新登入同步才能再配點。這不是伺服器失敗的證明。
未在實際伺服器進行配點測試；切勿以合成測試推論真人帳號一定成功。
