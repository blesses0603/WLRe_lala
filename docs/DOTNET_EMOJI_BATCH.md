# ver 8.0.67 表情首幀與 PNG 批次候選

`EmojiPixelBatch` 是完整像素／PNG 的觀察結果，`HasVerifiedProvenance=false`。不寫 SQLite、不建立目前帳號 publication、不啟用 UI 或聊天發送。正式來源驗證、exact container／全部外部指標組合尚未接到這個入口。

## 對照 Python

依 `wlre/services/world/emoji_database.py::build_catalog`：每個資料列 token 對應 `Emoji_<icon:03>_1`。hidden 只控制列表顯示，資料仍需有圖；重複 icon 共用一張 PNG，但資料列不合併。未知 token 缺席。只保留需要的首幀，其他名稱忽略；缺圖或重複需要的首幀拒絕。

`FromAtlas` 對已選定快照的明示 Sprite 指標逐個解析，使用既有 `AtlasSpritePixels.Extract` 檢查 membership、render key、反向指標及 Texture／archive 身份；不從名字尋找其他圖集。這個候選 API 的 atlasFile／atlasId 仍必須由之後的正式來源組合層依精確 container 取得，不能把呼叫者提供的指標當成正式來源證明。

## 完成與限制

- 最多檢視 2048 張候選；單圖 1..512 尺寸、單 PNG 最多 1 MiB，全部獨立首幀 PNG 合計最多 8 MiB，沿用 Python 額度。
- 獨立 `EncodeEmoji` 使用完整 RGBA 與 PNG 壓縮；不假造物品 Sprite context，不變更物品或頭像 PNG 編碼。
- PNG／像素副本及固定尺寸、SHA 均保留；批次 fingerprint 綁定 EmojiData 原文 SHA、排序後全部首幀名稱、尺寸、來源輸入指紋、完整像素與 PNG SHA。列順序、hidden、輸入 bytes 或像素改變會改變摘要，解碼列舉順序不影響摘要。
- 僅完整列舉及集合驗證後返回批次；中途錯誤或取消不交付部分結果。回傳圖片保持私有 bytes，只提供複本。沒有來源准入、儲存提交或撤銷能力。

## 驗證與剩餘工作

自有 fixture 透過 Python 真實 `build_catalog`，只在測試作用域替換 EmojiData raw digest；C# 使用明示 offline layout parser，正式固定 raw pin 未修改。對照 token／hidden／重複 icon、每張 PNG 解壓後完整 RGBA 與像素 SHA，另覆蓋缺圖、重複、晚到失敗、取消、列舉上限、單圖／總額與來源指紋。這些不是正式 62 首幀驗收。

上一批雲端環境重啟後，原本 `/tmp` 官方快取遺失。本批同一已審查 `wlreftpsrc.chinesegamer.net` HTTPS 版本端點兩次都在代理 CONNECT 階段逾時（先預設 timeout，再 20 秒有界重試），尚未取得新版本或 Bundle；未切換 host、未繞過 TLS／代理／版本／雜湊檢查，沒有猜測正式物件 ID。原有公開來源 audit 與 v8.0.66 三段 slice 證據保留。

下一步需取得並核對同版來源，完成 exact container／全部選定指標及 62 首幀的官方正向批次，綁定完整來源閉包指紋，再接 SQLite 原子寫入、新連線獨立重建回讀、來源重查與可撤銷發布，最後接 UI。小地圖仍未完成。未使用真帳密或正式遊戲 TCP，`HasVisualAssets=false`，一般操作 Held。
