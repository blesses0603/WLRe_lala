# 官方普攻與捕捉資料

普攻與捕捉不再讀取 normal_attack_data.json 種子。桌面與 Android 從當次官方 Runtime 的 SQLite 正規化快照讀取同版 ItemData_C、NpcData_C，剩餘種子為 stage_coordinates.json、graph_origins.json、navigation_data.zip、combat_catalog.json。

## 可重現證據

官方 Data 1.3.23、DataPackage 1296_2026_11_04_13_34_19_13 的 NpcData_C SHA256 為 edd827d228cbd5306dfcfbda150f5194406b87b45481fb930544218057aca31c。ItemData_C 使用既有已審核 1296 指紋。官方 Lua 清單 MD5、加密來源及解碼結果 SHA256、重新加密一致性均已核對；工具另登錄 NpcData、NpcCareerData、CreateRoleData、Skill、FightManager、UIBattle 的來源指紋。Lua 原文與 codec 參數均不隨程式發佈，也未執行官方 Lua。

NpcData.New 的兩個 UTF-16 名稱後有 203 bytes 固定欄位。ID 位於偏移 1 的 UInt16；可捕捉欄位位於 26，零代表 true；bodyType 27、kind 106、normalAttackKind 114。驗證記錄數上限、唯一非零 ID、文字長度、完整消耗與已審核實檔 SHA，未知格式不得套用此布局。

Skill.GetNormalSkill 使用物品 kind、NPC kind/bodyType/normalAttackKind；既有損壞裝備與火箭筒分支已核對 ItemData.lua。FightManager.SendAttack 明確以 specialAbility=140 判定捕捉網，直接取第一個 attributes.value 減 100；不額外推測屬性種類。角色轉生等級乘 100，加等級與捕捉網加成，再容許目標高 5 級；跟隨 NPC 採主人等級。

實檔包含 11,366 筆物品、7,586 筆 NPC、兩種捕捉網。舊物品 kind 全部一致；NPC 60619 的 kind 從 2 改為 1，60633–60636 從 5 改為 0，沿用官方新版值。捕捉網 25218、25225 均加 10。

## 更新與失敗

normalized_resources 保存兩份原始輸入、來源雜湊、版本化 normal_attacks 快照及匯入結果，沿用交易發布、衍生資料驗證／修復與原始資料保留機制。該可選資料匯入失敗時保留既有資料庫歷史，但不將舊版資料混入新 Runtime，狀態記錄原因。

每次普攻或捕捉判斷只取一次目前 Runtime 快照。未同步時武器及 NPC 普攻明確拒絕，捕捉不會自動選取；角色空手普攻仍依已知協定算法運作。既有使用者的舊本機種子副本不再作為消費來源。

合成測試覆蓋 Unicode／欄位布局、未知指紋、截斷、重複／零 ID、尾端資料、冷啟動、版本切換、捕捉網公式及等級邊界；實檔在兩端透過完整官方 Runtime 驗證。GUI 驗證僅限 Linux 虛擬顯示，未做正式服送包或 Android 實機驗收。

## 尚未完成

combat_catalog 還包含技能、角色起始技能與屬性權重。技能讀取布局已取得官方 Lua，但角色常數尚需正式的官方 Lua 擷取／資料轉換流程；後續已在官方 FightUnit.lua 找到完全對應的屬性權重矩陣及 GetElementAttackTimes 消費邏輯，仍須將來源擷取、驗證及受限資料抽取接入執行流程，不能將矩陣直接內嵌程式便宣稱移除離線資料。三項導航／投影資料仍缺少完整幾何與座標語意驗證；現有下載額度不變。
