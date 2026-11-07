using Lala.Android.Lifecycle;

namespace Lala.Android.Platform;

internal static class ConnectionStatusText
{
    internal static string Describe(ConnectionSnapshot state) => state.Phase switch
    {
        ConnectionPhase.Unavailable => "共用連線核心尚未接入；未連線遊戲。",
        ConnectionPhase.WaitingForNetwork => "等待已驗證的網路；尚未確認伺服器連線。",
        ConnectionPhase.Connecting => "正在建立會話，等待核心確認。",
        ConnectionPhase.Active => "連線核心已確認會話啟用。",
        ConnectionPhase.RetryWaiting when state.Reason == ConnectionEndReason.ConnectTimedOut => "建立會話逾時，等待重試。",
        ConnectionPhase.RetryWaiting => $"連線中斷，等待第 {state.RetryCount + 1} 次重試。",
        ConnectionPhase.Stopping => "正在取消工作並釋放連線。",
        ConnectionPhase.CleanupBlocked => "連線尚未完全釋放，暫停新的連線。",
        ConnectionPhase.Failed => state.Reason switch
        {
            ConnectionEndReason.AuthenticationRejected => "登入被拒絕，請重新確認帳號。",
            ConnectionEndReason.ResourceHeld => "資源檢查未通過，請完成檢查後手動開始。",
            ConnectionEndReason.RetryLimitReached => "已達重試上限，請返回 App 手動開始。",
            _ => "連線已停止，請返回 App 檢查。"
        },
        _ => "連線已停止。"
    };
}
