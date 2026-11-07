# 官方角色與夥伴頭像（桌面）

## 顯示與資料來源

首頁「角色與夥伴」卡分為兩列，各在文字左側放置 40px 官方頭像。角色選擇遵循官方 `UIPlayerInfo`／`GetCharacterId` 的 sex + headStyle 對應；它是官方二維角色肖像，不是目前穿戴裝備的三維人物截圖。顏色取最近一次已收到的 palette1 / palette5。夥伴以出戰資料的 modeling（大於零時）或 npc_id，查同版 NpcData 的 iconId、modelKind、palettes。重複／缺少角色識別、未知頭像、未出戰、版本不符時不借用別人的圖。

顯示以 LaLa 已收到的角色／夥伴快照為準；此功能沒有新增封包、操作角色或放寬登入權限。離線資料標為最後同步。尚未觀察到的新造型／配色需等待原有角色資料同步，不宣稱未收到的更新已生效。

## 精確來源契約

已審核 Data 1.3.23，DataPackage `1296_2026_11_04_13_34_19_13`，MainPackage `1296_2026_11_04_13_36_07_72`。NpcData payload 沿用已審核 SHA256。角色對應來自同版 Define 的十五組 CHARACTER_DATAS；NPC 欄位與官方 NpcData.lua、FollowNpcData.GetModelId 逐項核對。

頭像採獨立 **data-only projection**。不是啟動 Unity，也不宣稱已滿足 material Bundle 的 103 個 Unity 執行依賴。只讀取三個 SHA 鎖定的原始 Bundle 中指定 Material 的 Texture、local mask 與 Shader PPtr：

- mainpackage_material.bundle：1,903,222 bytes。
- mainpackage_texture_a.bundle：21,442,774 bytes。
- mainpackage_unityshaders.bundle：1,226,061 bytes。

總計 24,572,057 bytes。啟動同步有獨立 32 MiB／3 檔上限，不提高導航或核心資料預算。下載前用已驗證官方 Manifest 決定 URL／size／MD5／CRC，解析時另驗證已審核 SHA256、UnityFS header、serialized file/path ID、精確 container、Texture 類型與尺寸、材質參數、UV、shader 指紋及 keyword。

同版有 15 個角色、763 個夥伴材質，共 778 個頭像。153 個材質的 mask 為 null；只因已核對同一 shader 的正式預設值為 white 才使用全白遮罩，不是猜圖。不同 NPC 可以依官方 PPtr 共用同一貼圖，不以檔名相似自行推論。未知來源或 shader 變體保留原檔並安全顯示待同步。

## 色域與參考畫面

使用者提供的 UgPhone 畫面屬官方手機客戶端。以既有 SHA／ETag 鎖定 APK 的有上限 range read 取得 globalgamemanagers，檔案 SHA256 為 `ac933dbdb8407c4b0ca540c16356cc80675b8a262cc90095e7f1513c4f8ead31`，PlayerSettings 的 m_ActiveColorSpace=0（Gamma）、m_ColorGamuts=[0]。本功能明確實作 `official-mobile-gamma-1296` 配色投影；renderer 拒絕缺少或不同 profile。PC 資源中的頭像貼圖、材質與 shader 使用上述精確指紋，未推論 Windows 遊戲的 PlayerSettings 等同手機。

正式 PNG 保留 straight alpha，依已核對 shader 的 SrcAlpha／OneMinusSrcAlpha 混合語意交由 UI 合成。CPU 數學對照可證明此 Gamma 投影的公式，不能據此宣稱跨平台 Unity GPU、畫面縮放／取樣、壓縮格式或手機截圖逐像素等價。

## 快取與執行緒

官方 Bundle 留在使用者私人同步目錄，不隨 Git 或安裝包發佈。SQLite 只存同版衍生 base/mask PNG、像素與檔案 SHA、材質 metadata SHA、官方來源索引。整批 778 個頭像在來源前後重驗後才原子發布；損壞衍生資料從同版 Bundle 重建，新版失敗不覆蓋舊版、不混用版本。

每窗口 provider 最多兩個待處理工作、單一背景執行緒、32 個 Pillow 結果。Tk thread 不下載、不解包 Unity、不做完整像素著色；它只輪詢既有 refresh 並維護自己的兩張 PhotoImage。換來源或關窗取消待執行工作、丟棄過期結果，釋放圖片。暫時本地讀取錯誤採有上限退避，不能永久鎖在待同步，也不每秒忙重試。

## 驗證界線

已以官方 DXBC 指令建立獨立數學對照，不執行下載的遊戲程式。CPU 公式測試不能替代 GPU 的色域、取樣、混合或正式遊戲截圖驗收。實檔提取、資料庫來源核對與像素驗證結果由測試／研究回執另行記錄。

本功能只改桌面。沒有登入正式角色、修改 Android、合併 PR、發佈或部署。

## 本次實檔與回歸

官方來源前後版本核對相同，實際完成 778 個頭像提取與原子建庫；研究快取 SQLite 為 41,775,104 bytes（含已驗證 profile metadata）。當版有圖示的 7,586 個 NPC 記錄中 6,464 個指向此圖像集合，其餘沒有確認素材時顯示待同步，不從其他圖像補齊。確認角色及夥伴樣本能實際渲染，單個 256px 肖像約一秒，故只在背景執行緒處理。

本地 cloud 完整回歸與來源測試另列於 PR；因本地 Xvfb 無法建立 listening socket，GUI 測試本地略過，交由既有 Linux Xvfb／Windows CI 實跑。不在使用者桌面彈出測試視窗。沒有正式遊戲 GPU、帳號登入或手機實機驗收。
