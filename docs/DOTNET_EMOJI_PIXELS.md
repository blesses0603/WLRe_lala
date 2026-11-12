# ver 8.0.64 圖集指標及首幀像素前置層

新增選定 SerializedFile 範圍內的 Sprite→SpriteAtlas→Texture／alpha 精確配對與受限像素解碼。這仍是內部離線候選，不取得官方表情資料、不寫圖片資料庫、不發布桌面圖片或啟用遊戲操作。所有候選 `HasVerifiedProvenance=false`。

## 指標及像素

- 只有 `allowImages` 與 `allowAtlases` 同時明示開啟時，Sprite 才可含非空圖集指標及有界 tags。原來物品圖路徑仍拒絕圖集。無圖集指標時不依 tag 名稱尋找 fallback。
- 由選定範圍的不可變快照重新解析物件，核對目標 Sprite 名稱、圖集 packed membership、Sprite 反向圖集指標和完整 GUID＋64-bit render key。Texture／alpha 從圖集所屬檔案解引用；外部 file index 須有精確 ExternalPath→檔案身份綁定。不同檔案相同 PathId 不會混用。
- 保留來源物件完整 bytes／檔案身份／PathId 指紋；不是只雜湊裁切結果。返回像素獨立擁有，呼叫者修改副本不能改變候選。
- 像素僅接受色域 1、RGBA32／DXT1／DXT5、單 mip／inline／Windows64、貼圖最多 2048、首幀最多 512。矩形裁切須有限整數且完整在圖內；alpha 要求同尺寸，取其紅色通道。
- 明示接受 settingsRaw 3／7／11／15／19：矩形 packed、無旋轉／水平翻轉／垂直翻轉／180／90。依 Python 真實 SpriteHelper 順序裁切、packing transform、最後垂直翻轉。只接受 downscale=1，且轉換後尺寸等於 Sprite 邏輯尺寸。
- tight mesh、trimmed logical size、其他 packing bits、secondary textures、variant、未知色域／格式或缺少任何指標均拒絕。不推測 GPU 顯示、動畫或未支援的 mesh 行為。Sprite 自身 m_RD 在圖集路徑只做有界讀取，不替代圖集 render data。

## 獨立驗證

`generate_pixels.py` 以固定 UnityPy 1.25.4 release TPK 和真實 SerializedFile writer 建立完整自有 SpriteAtlas／Sprite／Texture2D 檔案，實際呼叫 `Sprite.image`，產生 30 組非正方形首幀的完整 RGBA 對照（3 種格式 × 5 種 packing transform × 有／無 alpha）。另有嵌入 schema、外部同號 PathId、反向指標／render key／membership、來源 bytes 指紋與副本、拒絕條件和取消測試。

本批仍逐張解析，不含跨圖快取或效能量測，未宣稱載入秒數或 FPS 改善；整批接線時需量測並避免重複解析。

這些資料沒有官方來源身份；即使像素完全一致，也不代表正式 SpriteAtlas、EmojiData、整批 PNG／SQLite 或桌面表情已驗收。UnityPy MIT 授權見 `dotnet/Lala.Core.Tests/Resources/UnityImages/UNITYPY-LICENSE.txt`。

## 尚待完成

1. 固定可信官方來源計畫、精確表情圖集入口及完整依賴，按原始 EmojiData SHA／資料列序號對應 `Emoji_{icon:03}_1`。不能以顯示名稱或場景編號猜測映射。
2. 完整首幀集合、每圖來源與整批指紋、PNG／SQLite 獨立重建回讀及來源重查、帳號／版本撤銷發布。
3. 聊天／表情選單的背景解碼、快取失效與顯示。未知 token 保留原文字，顯示不授權聊天傳送。
4. 小地圖的官方 Texture2D 來源、StageData→模型 ID 映射、1024-square PNG／SQLite 及桌面顯示；其他 Python 介面差距仍按原盤點推進。

維持 `HasVisualAssets=false` 及一般操作 Held；未使用真實帳密或連正式服。
