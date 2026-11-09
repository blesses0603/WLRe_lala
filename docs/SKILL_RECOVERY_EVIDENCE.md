# 已審查技能恢復種類（PR #79 ver 8.0.52）

## 可重現來源與範圍

2026-11-09 重新讀取使用者提供的 `WLRE_Lua_1262_Decoded_Analysis.zip`，整包 SHA256
`3e53db47ea22294207bfbc230322dbcc0429e4a4c94c7f67aacc924e18d77fce`。
其中 `Lua/Data/SkillData.lua` 是 24,000 bytes，SHA256
`962e95717ddce2c8d56da622df0e578afbf7bd6c63a19e53a809fb4a283f3228`，
與 `official_lua_codec.KNOWN_FILES` 先前審查的官方 1.3.23 解碼輸出逐 byte 同指紋。
這是檔案身分比對，不是只看壓縮檔的版本名稱。原始 Lua、壓縮檔與內容金鑰不納入 PR。

公開來源為 [SkillData.lua](https://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.23/LuaScripts/Lua/Data/SkillData.lua)，
先前審查的加密輸入 SHA256 為
`1304e566b6f33e23d4cdc569e35b350a4c5eaa438c8942f126f4f96af000cb3c`。
本次有界讀取官方清單時 HTTPS 連線逾時，因此**沒有取得新的線上驗收證據**；
並未更換來源、更新 pin、執行 Lua 或連線遊戲 TCP。既有解碼證據見
[官方 Lua 解碼紀錄](OFFICIAL_CLIENT_LUA_DECODING.md)。

## 已確認的語意

| FightWay | 恢復種類 | 官方檔案中的依據 |
| --- | --- | --- |
| 6 | SP | `IsAddSPSkill`，以及 `GetSkillEffect` 的文字 ID 31435 |
| 7 | HP | `IsAddHPSkill`，以及 `GetSkillEffect` 的文字 ID 31425 |
| 14 | HP 與 SP | `GetSkillEffect` 的文字 ID 31436；不是 `IsAddSPSkill` 的 true 分支 |
| 其餘／缺失 | 未知 | 不把未分類當成「一定不會恢復」 |

研究時另外核對 `Lua/Logic/FightManager.lua`（SHA256
`6b40ba250a2406193fc022a536c95addcb9034a899304a9d0f24d98c46c50004`，
也與先前官方解碼指紋相同）：其技能選擇路徑對 `IsAddSPSkill` 呼叫 `GetAllyLowSP`。
這補強 6 的 SP 語意，但本批不移植該路徑、不新增自動選技或發送。

整包靜態搜尋中的 VariableA-D 只有 SkillData 讀入位置，未找到恢復量計算；
被動 RoundAddSP 的顯示使用收到的 value，不能當作量值公式。
`ReduceSP` 繼續表示施放消耗，`TargetKind` 只表示目標類型。
吸取 SP、被動每回合恢復、恢復公式／上下限、實際成功量均未加入分類或估算。

## 實作與資料邊界

- `SkillRecoveryEffects.FromFightWay` 是純分類器，`SkillDataRow.RecoveryKind` 以不可變欄位取值。
  它不證明來源、不估算量、不保證有可用目標或 SP 足夠，也不授權施放。
- production `SkillDataParser.Parse` 仍只接受原固定二進位 SHA256
  `ed6383251b4f0fb9f7d9eb85c99346a268b99bdded839f6957f083c4b7f0545c`。
  未知版本仍拒絕；沒有為測試或本次研究放寬 pin。
- Avalonia 從目前 `PublicationSnapshot` 的可選已驗證技能目錄投影名稱、種類、消耗與目標；
  缺少目錄時顯示未驗證。技能視窗與動態行動清單顯示恢復種類及「恢復量未知」。
  目錄撤銷後清除舊效果與消耗；只有已觀察到學會的技能才進入行動選單。
- Python 使用同一有限分類，呈現在特技資訊與動態行動清單；不改自動戰鬥規則或指令發送。
- HP < A → B、SP < C → D 仍由使用者獨立選擇。顯示的是選定技能的資料；若允許次階技能，
  最後實際選技仍沿用既有已學與升階規則，不保證次階與原技能效果相同。

## 驗證限制

測試使用自有合成欄位，覆蓋全部 byte 值與未知／缺失、消耗與恢復分離、不可變資料、
正式 parser pin 拒絕、目錄撤銷及選單顯示；另外以已核對原檔靜態檢查三個 effect text ID。
沒有把合成 UI 或參考檔比對稱為目前官方 SkillData 整批下載／回讀成功；也沒有正式服施放驗收。
