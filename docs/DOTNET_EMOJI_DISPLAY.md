> v8.0.71 最新接線與驗證界線見 [正式表情工廠](DOTNET_EMOJI_PRODUCTION.md)。以下保留各批實作與當時驗證紀錄。

# ver 8.0.70 表情必要物件投影與小數裁切

Core `EmojiGalleryRequest` 綁定目前帳號快照、owner publication 與精確 activation。只提供可見 token 的不可變顯示 metadata 與私有 PNG 複本；每次讀取前後重查，不能據此取得聊天或遊戲指令權限。hidden token 不列入網格，列序號與共享首幀保留。

Desktop 登入橋接、表情入口與網格已接上此介面。圖片背景解碼，逐圖 1 MiB／整批獨立 PNG 8 MiB／最多 255 個 token，核對 SHA、PNG header 與 native 尺寸。相同輸入重用 Bitmap／按鈕；不同輸入先清除，撤銷有 200 ms 檢查與每次點擊檢查，任何晚到結果不得復活。關閉取消且等待在途工作；沒有新的遊戲 socket 或發送路徑。

版面對照 `wlre/ui/emoji_picker.py` 的偏好比例 1.35、可容納格數排序與 24–40 圖示大小；Avalonia 最小 cell 採 52×58，並非 Tk 原生字型的逐像素尺寸。空間不足顯示提示。選取只插入 `[EmojiN]` 到當前帳號的本機聊天草稿選取位置，遵守 512 字上限；不會自行送出。

## 已測量與界線

24 項新增原生 UI 檢查涵蓋共享 token、原生繪製、相同刷新／縮放重用、撤銷點擊、失敗不反覆解碼、關閉等待非合作讀取、晚到結果、格數／容量及草稿隔離。兩個共享首幀 token 初次只解碼一次，再執行 10 次相同更新與縮放新增零次解碼；這是自有小圖的呼叫計數，不是正式圖集耗時或 FPS。

Core 既有 owner／帳號測試擴充 gallery 可見索引、hidden 拒絕、私有副本與帳號快照撤銷；公開未綁定 runtime 不能取得 gallery。正式工廠沒有註冊，production 沒有表情圖片，仍顯示未就緒空狀態。

## 受限正式來源實測

本批官方服務恢復回應，經既有禁止 redirect 的下載器取得 Data EmojiData Bundle 與六個 Main 圖集依賴，總額仍受精確 manifest closure 與 32 MiB 家族上限約束。逐檔大小／MD5／CRC／SHA 與既有審查紀錄一致；版本與 Manifest 前後再查一致。檔案僅保存雲端私有快取，未提交官方 payload。

UnityPy 查明圖集 246 個 packed Sprite 全部位於 `CAB-cea8ff565680c1d33e8f134c42bb48fe`，因此六個來源 Bundle 不代表像素選取必須跨六個物件檔案。主檔含 1,946 個 Sprite，其中名稱符合 Emoji 首幀樣式的 87 個（不等於映射所需 62 個）。這些首幀的 physics shape 最多 6 組／49 點。

v8.0.69 的全檔解析在無關 `Icon_Grid01` 的 65 組／260 點 physics shape 被上限 64 阻擋。v8.0.70 保留此一般解析行為，新增專用 `ReadEmojiAtlasProjection`：仍完整驗證 header、所有 type tree、物件索引／span／重疊、外部清單與全部 container；只接受唯一精確表情 AssetPath、本檔 atlas／packed Sprite／Texture 指標。必要 Sprite 仍須通過原 physics 上限、backlink 與 render key；只有此圖集的必要物件會交給後續解碼。外部指標、缺失、錯誤類別與重複根路徑均拒絕，沒有將 64 提升至 65。

官方 SpriteAtlas 確實含小數 textureRect。UnityPy 1.25.4 `SpriteHelper.py` 將 Float32 欄位轉為 Python double，計算右／下端點後交給 Pillow 13.0.0 `Image._crop`；Pillow 對每個端點使用 ties-to-even round。C# 因此採 double 相加與端點取整後相減，不是截斷或單獨取整寬高。仍要求有限、正尺寸、原始及取整後範圍均在 Texture 內，Sprite 512／Texture 2048、格式／色域與 physics 上限均保留。

同一份已驗證私有官方快取，經 C# 原生 metadata／物件解析的 **62** 首幀，完整 RGBA SHA、尺寸與 token／可見性皆與 UnityPy 對照一致；PNG 合計 **279,975 bytes**。再執行 SQLite 寫入與全新讀回，兩次獨立原生重建及 **62** 個 PNG/token 全數一致。這是快取來源正向像素／資料庫驗證，未重新聲稱端點目前版本，也不是 production 工廠或可撤銷發布驗收；正式工廠仍未註冊。測試程式與官方 payload 留在工作區私有目錄，repo 僅提交自有合成 fixture 與非 payload 紀錄。證據見 [來源與指標紀錄](emoji_source_1296_projection_audit.json)。

新增 40 個完整 SerializedFile 經 UnityPy/Pillow 解碼的自有小數／五種旋轉／alpha RGBA oracle，以及 6 個必要物件投影正反例。一般讀取仍拒絕無關 65 shape，專用入口只返回 atlas／sprite／texture；將超限 Sprite 放入必要清單則仍拒絕。原始越界、非有限、零／取整後空尺寸與取消仍拒絕。

## 小地圖剩餘工作

已核對 Python `world/smallmaps.py`：目前圖片必須與 active runtime 的 catalog identity 相同，場景透過 model_id 映射 SmallMap2D 圖片，並核對 map_width／map_height／small_offset_x／small_offset_y 與版本。Core 尚未建立對應圖片來源／PNG／SQLite、場景投影與撤銷顯示；不得沿用歷史 1262 ZIP 或假設同名圖片可用。此批尚未實作小地圖。

`HasVisualAssets=false`、一般操作 Held，無真實帳密或正式遊戲 TCP。來源下載成功與合成網格成功，都不是正式完整圖資、登入或遊戲操作驗收。

v8.0.69 本機驗證：Core.Tests 強制重建零警告／錯誤，完整 **45,767** 通過；公開 consumer、Python **18**、Desktop Release 零警告／錯誤及離線 **81** 通過。原生 UI **262**／32 張既有截圖，加頭像 **13**、表情 **24**、catalog **10**／資源確認 **6**／登入 loopback **11**；另產生 2 張自有表情截圖，已目視檢查 62 格實際視窗。視窗測試曾抓出固定畫布及預設 button padding 造成的空間問題，已修正並完整重跑；精確提交 CI 另列 PR。


v8.0.69 精確提交 `7c21bcd5877d91ed5f5064ae965d326c9cb42552` 的 .NET 與 Python（含 macOS）CI 已全數成功。v8.0.70 本機與 CI 結果另列 PR。
