# 官方登入接線核查（ver 8.0.81）

已存在的真實接線：OfficialDesktopServerCatalog 透過 OfficialServerDiscovery 取得官方 HTTPS 清單；驗證端點與 XOR／平台／語言取自 wlre/configuration.py 已審查的 DEFAULT_PROFILE，未知 exe 版本拒絕。LoginWindow 使用 AccountRuntime.CreatePrepared 或 AccountLoginPreparation，最後由 HeldLoginTransport 連接驗證及所選分流 TCP。驗證成功後釋放第一條連線，再登入分流；角色選擇不預設，世界資料與初始化完成後才完成登入確認。

本批補強：在啟動 TCP 前、每次使用者確認帳密傳送後重新取得清單，核對指定 line ID 唯一、分組、兩端點、XOR、平台／語言、exe/data 與完整 package 版本一致。未知、變更、來源錯誤或取消拒絕繼續，不替換為新端點。HTTPS 重查沒有攜帶遊戲帳密。正式來源必須具備 Version；null Version 只在明示離線 UI fixture 出現。

新增 AccountLoginProgress，直接映射目前 attempt 的握手狀態；選角等待能持續收 heartbeat，UI 不把 TCP 連接當認證完成、不把認證成功當世界初始化完成。停止／替換後不再提供活動階段，保留的一次快照僅是歷史觀測。

驗證交 CI：既有 UI loopback 走完整兩次帳密確認、手動選角、世界資料、ack 與停止釋放；新增清單消失／重複／協定改變的檢查與 TCP 啟動前阻擋測試。帳號密碼僅合成值。沒有官方遊戲 TCP 或正式帳號成功證據，不宣稱正式服驗收；真帳密由使用者在桌面自行輸入且每次傳送確認。TCP 無 TLS，XOR 可逆，不提供安全加密。一般遊戲指令仍停用。
