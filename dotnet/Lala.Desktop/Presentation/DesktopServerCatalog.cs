using System.Diagnostics;
using System.Net;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Discovery;

namespace Lala.Desktop;

internal sealed record DesktopServerLine(int Id, string Group, string Label, AccountConnectionProfile? Profile);
internal sealed record DesktopServerCatalogSnapshot(IReadOnlyList<DesktopServerLine> Lines, string Status, long ObservedAt)
{
    internal Lala.Core.Resources.OfficialVersionSnapshot? Version { get; init; }
    internal bool IsFresh => Stopwatch.GetElapsedTime(ObservedAt) < TimeSpan.FromMinutes(5);
}
internal interface IDesktopServerCatalog
{
    Task<DesktopServerCatalogSnapshot> LoadAsync(CancellationToken token);
}

/// <summary>Release-owned Python protocol profile; never sourced from downloaded server rows.
/// Source: wlre/configuration.py DEFAULT_PROFILE and SUPPORTED_RESOURCES. Capture:
/// 2dd969e7d4e85556bc526db42632521e5c7d7c5ac7201f0aaf559da87dce2322.
/// This is reviewed historical evidence, not live-server or TLS authentication.</summary>
internal sealed class OfficialDesktopServerCatalog : IDesktopServerCatalog
{
    internal static AccountConnectionProfile? ProfileFor(OfficialServerCandidateSnapshot snapshot, OfficialServerLineCandidate line)
    {
        if (!snapshot.TlsOriginObserved || snapshot.Version.ExeVersion != "1.3.0" ||
            line.GroupId is not (1 or 2) || !snapshot.Lines.Contains(line)) return null;
        return new(new(IPAddress.Parse("34.81.10.22"), 16988), new(IPAddress.Parse(line.Host), line.Port),
            173, 173, 1, 3, 0); // Interactive role selector always overrides fixed RoleIndex.
    }
    public async Task<DesktopServerCatalogSnapshot> LoadAsync(CancellationToken token)
    {
        using var discovery = OfficialServerDiscovery.Create();
        var snapshot = await discovery.RefreshAsync(token).ConfigureAwait(false);
        var lines = snapshot.Lines.Select(line => new DesktopServerLine(line.Id,
            line.GroupId switch { 1 => "地球", 2 => "水星", _ => "未支援伺服器" },
            $"{line.Id % 100}線", ProfileFor(snapshot, line))).ToArray();
        return new(lines, $"官方伺服器清單 · {new Uri(snapshot.ExactUrl).Host} · {snapshot.Version.DataVersion}｜" +
            (snapshot.Version.ExeVersion == "1.3.0" ? "協定沿用 Python 版已觀測設定；資源仍 Held" : "官方執行版本未知，登入已阻擋"), Stopwatch.GetTimestamp()) { Version = snapshot.Version };
    }
}

/// <summary>Offline UI fixtures only. Never constructs a production source or fetches URLs.</summary>
internal sealed class OfflineDesktopServerCatalog : IDesktopServerCatalog
{
    private readonly DesktopServerCatalogSnapshot snapshot;
    internal OfflineDesktopServerCatalog(params DesktopServerLine[] lines)
        => snapshot = new(lines, "離線合成伺服器清單（不代表官方驗證）", Stopwatch.GetTimestamp());
    public Task<DesktopServerCatalogSnapshot> LoadAsync(CancellationToken token)
    { token.ThrowIfCancellationRequested(); return Task.FromResult(snapshot); }
}
