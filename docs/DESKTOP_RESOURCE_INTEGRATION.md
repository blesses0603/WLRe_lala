# Desktop 資源準備接線 — PR #79 ver 8.0.47

本批在登入前接入必要資料的真實下載、驗證及 SQLite 啟用流程；圖資尚未啟用，
不是 Python 完整資源流程或正式服驗收。

## 登入前流程

1. 版本視窗取得官方 metadata。只有清單、已知協定或本機 SQLite 自洽均不能進入登入。
2. 使用者選擇資料根目錄，先進行不建立／修復檔案的唯讀檢查。
3. 「登入前下載、驗證與準備」顯示獨立確認框，列出官方 HTTPS、Bundle 快取、SQLite
   路徑及目錄／暫存檔／journal 寫入範圍。拒絕時不執行 HTTP 或寫入。
4. 新增公開 `PreloginResourcePreparation`，由私有 production `ResourceRuntimeOwner`
   執行既有官方來源、Manifest／Bundle 驗證、必要十表解析、SQLite bootstrap、獨立回讀
   及來源重查。建構不執行 I/O；沒有帳號、帳密或遊戲 socket，也不接收任意來源／URL。
5. `Ready` 只表示當前必要資料目錄通過既有准入。視窗重新取得官方清單，再精確比對
   exe／data／完整 Package 名稱及版本；不符、過期、未知協定均不放行。
6. 正式桌面路由在登入按鈕、啟動登入及每次確認返回時再次檢查當前資源。登入後仍使用
   `AccountRuntime.CreatePrepared` 獨立重查及綁定，登入前的歷史結果不能授權帳號資料。
   登入後資源寫入與驗證／正式 TCP 帳密傳送各自確認。官方 TCP 沒有 TLS，XOR 可逆。
7. 刷新、改目錄、取消、停止／關閉立即撤銷資源准入，並等待背景工作及 owner 釋放；
   已完成或結果不明的磁碟寫入不回復、不自動重試。根目錄只留在本次程式記憶體。
8. 同一次帳號 publication 提供接收狀態與物品／場景名稱；撤銷時清除。一般遊戲操作
   仍 Held。`PreloginResourceResult`、候選目錄都不提供登入或封包發送權限。

## Python 對照與圖資阻礙

已核對 `game_version_gate.py`、`dynamic_bundle_runtime.py`、`bundle_runtime_1275.py`。
Python 在登入前比較官方 exe／data／兩個 Package，再驗證來源與 SQLite；可選圖片各自
有同版來源與快取驗證，不是找到舊 PNG 或資料庫就啟用。本批補上必要資料的登入前順序。

尚缺以下真實圖資鏈，`HasVisualAssets` 明確保持 false：

| Python 來源 | C# 尚缺的相依與驗證 |
| --- | --- |
| `item_image_database.py` | Unity Sprite→同 asset Texture2D 解析、有限尺寸／數量解碼、PNG 與 RGBA 雜湊、精確 inputs/catalog key、commit 前來源重查 |
| `portrait_database.py` | 頭像映射、圖集裁切、同版來源／像素與快取驗證 |
| `emoji_database.py` | EmojiData 與圖片來源相依、同版 catalog 及快取驗證 |
| `smallmap_database.py` | 小地圖 Sprite／Texture2D、場景映射、同版來源與像素驗證 |

目前 Core 的受限 Unity 解碼器只處理 TextAsset，未具備 Sprite／Texture2D 圖像解碼與
上述圖片 SQLite／publication 橋接。不能將未驗證舊圖資顯示為就緒；不猜格式或降低驗證。
背景版本 observer、Python ZIP 重建、程式更新器與全介面一致也仍未完成。

路徑正規化及固定子路徑沿用 Core；這不是防禦惡意 symlink／外部替換的檔案系統 sandbox。

## 驗證方式

- 資源 Core 測試使用合成來源；正向 current identity 案例沿用明示 white-box `_production`
  seam，只證明生命週期／精確比對接線，不證明官方 provenance 或真實資料成功啟用。
- 新增建構／關閉無 I/O、離線來源不能准入、精確版本不符阻擋、停止撤銷及等待晚到來源測試。
- 原生 UI 驗證 metadata 不能放行、準備確認取消不建目錄、登入的資源 gate、清理與既有路由。
- 既有 public runtime loopback 驗證資源與帳密確認分離；不走 production HTTP。
- 全部測試只用合成／loopback／臨時檔案；未連官方 HTTP、正式服或讀取真帳密。

- 本機驗證：Release build 0 警告／錯誤；Core 資源 204、原生 UI 226（29 張圖）、catalog UI 10、登入 loopback 11、資源確認 loopback 6、離線 Desktop 63、公開 consumer 與 Python 倉庫／發行 15 通過。

## 8.0.46 圖像像素基礎批次

已完成四種未壓縮 Texture2D 格式及未打包矩形 Sprite 的純像素解碼、完整來源／像素雜湊與記憶體快取比對。尚未解析 class 28／213 或從官方 Bundle 建立圖片；context 是觀測主張，不能授予 provenance。PNG／SQLite、實際來源解析及圖資 publication 仍未完成，登入前流程與 HasVisualAssets=false 不變。詳見 [範圍、參照與相依](../dotnet/Lala.Core/Resources/UnityImages/README.md)。

## 8.0.47 圖片 SerializedFile 接線

內部 UnitySpriteExtractor 已可從有限且 checksum 驗證的 Bundle 集合，按固定 2021.3.45f2 release type tree 解析 class 28／213，精確核對同檔容器配對與 Sprite→Texture 指標，再建立像素候選。原 TextAsset 路徑不自動接受圖片。獨立 UnityPy writer／SpriteHelper 與 AssetsTools 驗證使用自有合成檔，不能代表官方圖資驗收；正式圖片取得／publication、PNG／SQLite 與 UI 仍未接入。詳見圖資 README。
