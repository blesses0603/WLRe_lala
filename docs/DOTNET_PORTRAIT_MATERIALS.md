# 頭像材質解碼前置層（PR #79 ver 8.0.56）

本批將 Unity 2021.3.45f2 的 Material（class 21）接入受限 SerializedFile22 讀取器，使用獨立 `allowMaterials` 開關；既有 TextAsset 與物品圖片讀取入口仍不接納材質。這是內部資料解碼，**尚未接入正式頭像下載／顯示**。

## 來源與格式

- 依 repo `wlre/services/world/portrait_assets.py` 已審查的材質欄位與條件，讀取 shader／texture／mask PPtr、keywords、UV、浮點值與 RGBA 色彩。共享貼圖依 PPtr 保留，例如自有測試中的材質 7214 引用貼圖 7213，不用檔名猜引用。
- Material 嵌入 type tree 必須精確符合 UnityPy 1.25.4 TPK 中的 2021.3.45f2 release shape：107 nodes，正規化 SHA256 `a9e27e0128a6337ddea3c51592bb90e48b2203fd87a3e5ce7f395d0a8e830ad7`。不增加泛用、不受限的 type tree interpreter。
- 單一材質最多 128 KiB；字串、每種 map／vector 與 PPtr 索引有獨立上限。拒絕重複 key、非有限浮點、無效 bool、截斷、尾隨資料及 virtual texture stacks；使用不可變映射與純量記錄，輸入 bytes 修改不影響已解碼值。
- 頭像候選投影只接受已審查的 keywords／shape／edge／clip／UV 條件與完整 14 色欄位。候選保留原始 shader 與貼圖 PPtr，沒有升格為已驗證 Shader、renderer settings 或 publication。Null mask **不**自動替換白色：須先驗證 Shader 的預設值。

## 測試與尚缺工作

`Resources/Portraits/generate_materials.py` 以固定 UnityPy 的真實 type-tree writer 和 SerializedFile.save 建立自有樣本，記錄 TPK、shape 與 serialized asset 雜湊。測試包含 18 組材質變體、獨立 opt-in、type tree 改寫、每一個截斷位置、容量、取消及輸入所有權。樣本不含官方材質 bytes，不代表官方 Bundle 整批正向驗收。

下一步仍須 Shader class 48 解碼／compressedBlob 指紋及預設遮罩驗證、精確外部檔案綁定與 PPtr 解析、每圖來源、base／mask 儲存、可撤銷發布及 UI 背景載入。表情 SpriteAtlas 和小地圖 1024 Texture 獨立路徑也尚未完成。本批沒有新增繪製效能數字；保留前批表格列重用及圖片／格位快取回歸。

來源三檔 pins、總額度與版本限制見 [來源計畫](DOTNET_PORTRAIT_SOURCES.md)。HasVisualAssets=false，遊戲操作仍 Held；未連正式服、未使用真帳密，未宣稱完整 Python 介面一致或實機驗收。
