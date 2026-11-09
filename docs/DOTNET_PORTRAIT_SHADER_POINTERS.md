# Shader 驗證與選定檔案指標解析（PR #79 ver 8.0.57）

本批新增內部 Shader class 48 解析與精確選定範圍的 PPtr resolver。**仍未將完整頭像管線接入 production／UI**，也未完成表情與小地圖。

## 固定 Shader 結構

根據 UnityPy 1.25.4 TPK 的 2021.3.45f2 release 結構：2,304 nodes、最大深度 22，正規化 SHA256 `f3ed8d034e403d3917510a21390e073793d851a96523aa8fd51e756b9888b6fb`。只有獨立 `allowShaders` 入口接受此 class；其他類別的節點／深度限制不放寬。

只從精確驗證的嵌入 tree 建立不可變、重用的欄位布局；每個 object 都檢查完整序列化結構。單物件 8 MiB、一般陣列 16,384、字串 4,096 bytes、總遍歷 2,000,000 步；取消、非法 bool／非有限浮點、重複 property、截斷與尾隨資料拒絕。不執行、不解壓縮 Shader 程式，也不載入外部 class database。

頭像驗證重新從 bytes 讀取 `m_ParsedForm.m_Name`、`_ColorMask1` 的預設名稱與 `compressedBlob` SHA256，核對 Python 已審查的 `UI_ProfilePhotoWithMask`、`white` 及固定 blob 指紋。不能用呼叫者提供的 observation／hash 取代 bytes。自有 Shader 雖具相同名稱與 white 預設，仍被正式 blob pin 拒絕；沒有可替換 pin 的測試入口。

## 外部指標

`UnitySelectedObjects` 僅使用已提供的 ParsedFile、完整 `UnityFileIdentity`、精確 ExternalPath 與明示 binding。最多 4 檔、128 bindings、16,384 objects、32 MiB bytes；快照複製索引、外部清單與物件 bytes。共享貼圖保留原 PathId，不依材質名稱推算；缺檔、越界、重複／未綁定、錯誤 class 或缺少物件即拒絕。不讀硬碟、不搜尋 basename、不擴充相依來源。

只有 `FileId=0, PathId=0` 且明示允許 null 才回傳 null；這不生成白色遮罩或授權 renderer。bindings 本身是呼叫者提供的投影設定，尚需 production 組合層以已審查來源身份建立，不單靠 resolver 證明官方 provenance。

## 證據與剩餘工作

固定 UnityPy 真實 writer／SerializedFile.save 產生自有 Shader，含每一層巢狀陣列的非空分支、材質預設、指紋拒絕、schema 改寫、完整截斷測試及容量／取消；沒有官方 Shader bytes。另測精確外部 binding、共享貼圖、原輸入改寫後保持快照、null mask 與錯誤類別。

仍需把三檔已驗證來源、完整 container／材質 PPtr、精確 Shader file/path ID、貼圖與 mask 的格式／像素驗證組合成完整頭像批次，再接資料庫、可撤銷發布、背景著色與 UI。沒有宣稱正式來源正向驗收、GPU 等價或新的繪製速度改善。既有表格與圖片快取回歸保留；HasVisualAssets=false、遊戲操作 Held，未連正式服／使用真帳密。
