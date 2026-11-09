# ver 8.0.69 表情網格與正式來源查核

Core `EmojiGalleryRequest` 綁定目前帳號快照、owner publication 與精確 activation。只提供可見 token 的不可變顯示 metadata 與私有 PNG 複本；每次讀取前後重查，不能據此取得聊天或遊戲指令權限。hidden token 不列入網格，列序號與共享首幀保留。

Desktop 登入橋接、表情入口與網格已接上此介面。圖片背景解碼，逐圖 1 MiB／整批獨立 PNG 8 MiB／最多 255 個 token，核對 SHA、PNG header 與 native 尺寸。相同輸入重用 Bitmap／按鈕；不同輸入先清除，撤銷有 200 ms 檢查與每次點擊檢查，任何晚到結果不得復活。關閉取消且等待在途工作；沒有新的遊戲 socket 或發送路徑。

版面對照 `wlre/ui/emoji_picker.py` 的偏好比例 1.35、可容納格數排序與 24–40 圖示大小；Avalonia 最小 cell 採 52×58，並非 Tk 原生字型的逐像素尺寸。空間不足顯示提示。選取只插入 `[EmojiN]` 到當前帳號的本機聊天草稿選取位置，遵守 512 字上限；不會自行送出。

## 已測量與界線

24 項新增原生 UI 檢查涵蓋共享 token、原生繪製、相同刷新／縮放重用、撤銷點擊、失敗不反覆解碼、關閉等待非合作讀取、晚到結果、格數／容量及草稿隔離。兩個共享首幀 token 初次只解碼一次，再執行 10 次相同更新與縮放新增零次解碼；這是自有小圖的呼叫計數，不是正式圖集耗時或 FPS。

Core 既有 owner／帳號測試擴充 gallery 可見索引、hidden 拒絕、私有副本與帳號快照撤銷；公開未綁定 runtime 不能取得 gallery。正式工廠沒有註冊，production 沒有表情圖片，仍顯示未就緒空狀態。

## 受限正式來源實測

本批官方服務恢復回應，經既有禁止 redirect 的下載器取得 Data EmojiData Bundle 與六個 Main 圖集依賴，總額仍受精確 manifest closure 與 32 MiB 家族上限約束。逐檔大小／MD5／CRC／SHA 與既有審查紀錄一致；版本與 Manifest 前後再查一致。檔案僅保存雲端私有快取，未提交官方 payload。

UnityPy 查明圖集 246 個 packed Sprite 全部位於 `CAB-cea8ff565680c1d33e8f134c42bb48fe`，因此六個來源 Bundle 不代表像素選取必須跨六個物件檔案。主檔含 1,946 個 Sprite，其中名稱符合 Emoji 首幀樣式的 87 個（不等於映射所需 62 個）。這些首幀的 physics shape 最多 6 組／49 點。

**C# 正向驗收仍失敗：** 既有 `BoundedSerializedFile.Read` 驗證所有 Sprite，遇無關 `Icon_Grid01` 的 65 組／260 點 physics shape，在既有 64 組上限阻擋。沒有升高上限、跳過失敗後宣稱成功或啟用 production 工廠。下一步需設計來源綁定、完整索引／span／schema 驗證後的精確必要物件投影，仍須逐圖像素對照及整批回讀驗證。證據見 [來源與指標紀錄](emoji_source_1296_projection_audit.json)。

## 小地圖剩餘工作

已核對 Python `world/smallmaps.py`：目前圖片必須與 active runtime 的 catalog identity 相同，場景透過 model_id 映射 SmallMap2D 圖片，並核對 map_width／map_height／small_offset_x／small_offset_y 與版本。Core 尚未建立對應圖片來源／PNG／SQLite、場景投影與撤銷顯示；不得沿用歷史 1262 ZIP 或假設同名圖片可用。此批尚未實作小地圖。

`HasVisualAssets=false`、一般操作 Held，無真實帳密或正式遊戲 TCP。來源下載成功與合成網格成功，都不是正式完整圖資、登入或遊戲操作驗收。

本機最終驗證：Core.Tests 強制重建零警告／錯誤，完整 **45,767** 通過；公開 consumer、Python **18**、Desktop Release 零警告／錯誤及離線 **81** 通過。原生 UI **262**／32 張既有截圖，加頭像 **13**、表情 **24**、catalog **10**／資源確認 **6**／登入 loopback **11**；另產生 2 張自有表情截圖，已目視檢查 62 格實際視窗。視窗測試曾抓出固定畫布及預設 button padding 造成的空間問題，已修正並完整重跑；精確提交 CI 另列 PR。
