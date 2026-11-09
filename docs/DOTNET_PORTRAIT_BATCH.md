# 獨立 Texture 與頭像批次（PR #79 ver 8.0.58）

## 已實作

新增 `BoundedTexturePixels`／`TexturePixelCandidate`，完整 Texture2D 不需要 Sprite ID、裁切或圖集語意。保留 serialized `m_ColorSpace`，只接受目前已審查的 color space 1、RGBA32／DXT1／DXT5、單 mip／單 image、inline Windows64 資料；色域 0 不會默默改標或轉換。完整 Texture 最大 1024×1024，原 Sprite 512 上限不變。輸出獨立持有、由下向上翻成 top-down RGBA，記錄來源與像素 SHA；候選不具 publication 權限。

`PortraitBatchLayout` 依 Python `portrait_assets.py` 核對三個固定 CAB、778 個精確材質 container、Shader file／path ID、base Texture container 與 local mask 指標。外部名稱按固定 UnityPy `FileIdentifier.name` 的 basename 語意，只比對已驗證來源中的三個精確 CAB；不搜尋磁碟、不擴充相依來源。不同材質共用貼圖時保留 PPtr，不以材質圖號猜貼圖圖號。結構檢查本身不證明官方來源或 Shader 內容。

`PortraitBatch.Process` 只接受既有三檔 pins 已通過的 `VerifiedPortraitSources`，受限讀取／解包與固定 SerializedFile 格式檢查後，先驗證正式 Shader 指紋及 white 預設，再檢查完整結構。逐張驗證 256×256 base／mask 的格式與色域，產生持有獨立像素、配色設定與每圖指紋的候選，交給呼叫端處理；不把 778 張 RGBA 全留在結果陣列。只有通過 Shader 驗證後，null mask 才產生 white。

完整走完 778 筆、callback 成功且沒有取消後才回傳整批 fingerprint／count。**callback 不是發布，失敗前可能已交付部分候選**：未來儲存端必須暫存、驗證整批 receipt、獨立回讀並重查來源／currentness，再決定發布。本批尚未接入 production 自動準備、資料庫、撤銷綁定或頭像顯示。候選可離線著色，不能據此解除任何資源或遊戲限制。

TextureColorSpace 的 0=Linear、1=sRGB 已對照 [Unity 2021.3 官方定義](https://github.com/Unity-Technologies/UnityCsReference/blob/2021.3/Runtime/Export/Graphics/GraphicsEnums.cs#L432-L437)；它與同檔的 PlayerSettings／ColorSpace 列舉不是同一套數值，不能混用。

## 證據與限制

- 固定 UnityPy 1.25.4 實際 Texture2D reader 產生 12 組獨立整圖 SHA，涵蓋 RGBA32／DXT1／DXT5、非 block 整數尺寸、256 與 1024；沒有用 Sprite 冒充 Texture。
- 自有 writer Texture 驗證色域欄位保留及 0 的拒絕；測試格式／尺寸／mip／stream／payload／取消與輸入、輸出所有權。
- 778 筆自有材質結構測試涵蓋共享貼圖、local／null mask、缺失／重複 container、錯誤 class、錯誤外部引用與不完整集合。其 Shader 僅為結構宣告，**不能通過正式 Shader pin，也沒有拿它當完整 Process 正向測試**。
- 正式三檔已驗證來源的 Process 完整正向驗收尚未進行；不提供替換 pins 的測試後門，不放寬來源／版本或解包總量限制。

剩餘：正式來源整批驗證、PNG／SQLite 整批讀回與撤銷發布、角色／夥伴映射、背景 UI 載入；表情 SpriteAtlas、小地圖專用來源／儲存／顯示與完整 Python 介面也未完成。1024 純像素測試不代表小地圖功能已完成。沒有新增 FPS／載入速度宣告；既有 UI 繪製計數回歸保留。HasVisualAssets=false，未連正式服／使用真帳密。

## v8.0.57 CI 歷史核查

.NET 全平台及 Python Windows／Linux 成功。macOS Python job 129223973164 在 2026-11-09 14:49 UTC 被取消，runner_id=0、無測試步驟與日誌；GitHub annotation 指出 hosted runner 多次未能取得，並註記 macOS arm64 容量不足。整組 Main and PR tests 結論 failure，不能記為 macOS 通過。本輪未取消或重跑該流程。
