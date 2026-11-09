# Core 頭像合成前置層（PR #79 ver 8.0.54）

本批把 Python `portrait_render.py` 的已審查 CPU 配色投影移植為內部純函式 `PortraitRenderer`。
來源 SHA256：`bb46c4e85a409ce346e9c861615e34b8c6224244432bcbd6961efcfa8361b6ed`。來源證據與限制見 [Python 官方頭像紀錄](OFFICIAL_CHARACTER_PORTRAITS.md)。
本次沒有重新取得官方 Bundle、Shader 或手機畫面；不把歷史 Python 實檔驗收轉算成 C# 驗收。

- 固定 256×256 RGBA base／mask，保留 straight alpha；支援五組十進位配色、材質預設色、眼睛混色與圓形遮罩。
- 必須明示 `official-mobile-gamma-1296` 與 `UI_ProfilePhotoWithMask`，拒絕 keyword／shape mask、未知 profile、無效幾何、非有限參數與運算溢位。
- 輸入像素與顏色向量均複製，取消不回傳部分結果。輸出只是呼叫者擁有的 RGBA，沒有來源、版本、當前性、publication 或遊戲操作權限。
- 圓形 mask 的有限數值範圍沿用 Python renderer；它不是 production 材質白名單，未來來源層仍須核對固定 Shader、精確 Material／Texture PPtr、UV、兩個已審查 clip 值與 edge=0。
- 十張完整自有合成圖由實際 Python 函式產生 SHA256 對照，覆蓋全部像素、配色／預設色、透明度與圓形邊界；另測未知變體、錯誤輸入、複製及取消。沒有官方圖像進入 Git。

## 尚未接線的相依

| 圖資 | 已有基礎 | 尚缺 |
| --- | --- | --- |
| 頭像 | 四種未壓縮格式、DXT1／DXT5、CPU 配色投影 | 精確 Material／Shader／外部 Texture 指標解析與來源鎖定、base/mask 庫、角色映射、背景工作及可撤銷 UI publication |
| 表情 | 像素與 PNG／SQLite 基礎 | EmojiData 固定來源、SpriteAtlas 指標／首幀解析及整批驗證 |
| 小地圖 | 有界 Texture2D 欄位／像素基礎 | 精確獨立 Texture 路徑、1024×1024 專用限制、場景映射、快取與 UI 座標綁定 |

目前不呼叫此 renderer 進行 production 頭像載入，不讓 UI 執行完整著色，也不設定圖資就緒。
HasVisualAssets=false；正式來源、GPU／手機畫面及實機驗收仍未完成。恢復量仍未知。

## 同批介面重繪優化

v8.0.53 已重用相同 Bitmap，但每次 Paint 仍建立所有可見格位的 Grid、TextBlock、Image。
現在每格比較完整物品顯示資料、選取狀態與目前 admitted Bitmap；只有改變的格位重建。
每次仍逐格取得／驗證目前 PNG，結束後淘汰不再使用的圖片，不能略過撤銷檢查。

以原生 UI 的 tile 建立計數回歸驗證：24 格連續 10 次相同刷新從原路徑 240 次重建降至 0；
首次選取更新一格，切換選取更新前後兩格。來源、圖片、數量、搜尋、換頁、換帳仍沿用原有驗證。
這不是 FPS 或整體載入秒數測量；資料投影、PNG 複製／雜湊仍在 UI 刷新路徑，後續需繼續量測。

本機專項驗證：Core 頭像 13 項、Python 頭像＋倉庫／發行 21 項、公開 consumer、Desktop Release 零警告／錯誤、離線 81 項、原生 UI 257 項／32 張截圖通過。完整 Core 與精確提交 CI 另於 PR #79 記錄。
