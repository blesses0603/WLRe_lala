using Lala.Core.Sessions;
namespace Lala.Desktop;

internal static class DesktopLoginTarget
{
    internal static bool Matches(DesktopServerCatalogSnapshot expected, DesktopServerCatalogSnapshot observed, int lineId)
    {
        if (!observed.IsFresh) return false;
        var before = expected.Lines.Where(x=>x.Id==lineId).Take(2).ToArray();
        var after = observed.Lines.Where(x=>x.Id==lineId).Take(2).ToArray();
        if (before.Length!=1 || after.Length!=1 || before[0].Group!=after[0].Group ||
            before[0].Profile is not {} a || after[0].Profile is not {} b) return false;
        if (!a.VerificationEndpoint.Equals(b.VerificationEndpoint) || !a.FormalEndpoint.Equals(b.FormalEndpoint) ||
            a.TransmitXor!=b.TransmitXor || a.ReceiveXor!=b.ReceiveXor || a.Platform!=b.Platform || a.Language!=b.Language) return false;
        var old=expected.Version;var next=observed.Version;
        // Null versions are possible only in explicit offline UI fixtures.
        return old is null ? next is null : next is not null && old.ExeVersion==next.ExeVersion && old.DataVersion==next.DataVersion &&
            old.Packages.Count==next.Packages.Count && old.Packages.All(p=>next.Packages.TryGetValue(p.Key,out var version)&&version==p.Value);
    }
    internal static string DescribeEnd(AccountConnectionStatus status)
    {
        if (status.EndReason is AccountConnectionEndReason.Cancelled or AccountConnectionEndReason.Stopped or AccountConnectionEndReason.Disposed)
            return "登入或連線已停止";
        return status.History.LastOrDefault()?.Failure switch
        {
            AccountConnectionFailure.ConnectFailed => "TCP 連接失敗；請檢查網路與所選分流狀態",
            AccountConnectionFailure.ConnectTimedOut => "TCP 連接逾時；尚未確認登入成功",
            AccountConnectionFailure.ReadTimedOut or AccountConnectionFailure.LoginDeadline => "等待伺服器回覆或使用者確認逾時",
            AccountConnectionFailure.LoginProtocolFailed or AccountConnectionFailure.InvalidProtocol => "登入協定遭拒或回覆格式不符；請重新查詢官方版本",
            AccountConnectionFailure.RemoteEof => "伺服器已關閉連線",
            AccountConnectionFailure.WriteUncertain => "傳送結果不明；已停止且不會自動重送",
            AccountConnectionFailure.CleanupFailed => "連線資源清理未完成，請關閉程式",
            _ => "登入或連線未完成；請重新查詢分流及資源狀態"
        };
    }
    internal static string Describe(AccountLoginStage? stage) => stage switch
    {
        AccountLoginStage.ConnectingVerification => "正在連接驗證伺服器 TCP",
        AccountLoginStage.SendingVerification => "驗證 TCP 已連接；等待確認或傳送驗證登入",
        AccountLoginStage.AwaitingVerification => "驗證登入已送出；等待伺服器回覆",
        AccountLoginStage.ConnectingFormal => "帳號驗證通過；正在連接所選分流 TCP",
        AccountLoginStage.SendingFormal => "分流 TCP 已連接；等待確認或傳送分流登入",
        AccountLoginStage.AwaitingFormal => "分流登入已送出；等待伺服器回覆",
        AccountLoginStage.AwaitingRoles => "分流登入通過；等待角色清單",
        AccountLoginStage.SelectingRole => "請選擇角色並確認進入",
        AccountLoginStage.SendingRole => "正在傳送已確認的角色選擇",
        AccountLoginStage.AwaitingWorld => "角色選擇已送出；等待世界資料",
        AccountLoginStage.AcknowledgingWorld => "已收到世界資料；完成登入確認中",
        AccountLoginStage.ProtocolComplete => "登入協定完成；一般遊戲操作仍停用",
        AccountLoginStage.Cancelled => "登入已取消",
        AccountLoginStage.Failed => "登入握手未完成",
        AccountLoginStage.Held => "登入已停止",
        _ => "準備本次登入"
    };
}
