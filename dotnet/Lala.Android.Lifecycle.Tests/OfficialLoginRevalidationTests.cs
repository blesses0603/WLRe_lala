using System.Diagnostics;
using System.Net;
using System.Text.Json;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Lala.Desktop;
using Xunit;

namespace Lala.Android.Lifecycle.Tests;

public sealed class OfficialLoginRevalidationTests
{
    private static DesktopServerCatalogSnapshot Catalog(bool old = false, int port = 16989, string data = "1.3.23")
    {
        var profile = new AccountConnectionProfile(new(IPAddress.Loopback, 16988), new(IPAddress.Loopback, port), 173, 173, 1, 3, 0);
        var version = OfficialVersionSnapshot.Parse(JsonSerializer.SerializeToUtf8Bytes(new
        {
            schema_version = 1, origin = "official_pc_version_endpoint", data_ver = data, exe_version = "1.3.0",
            packages = new { DataPackage = "1296_2026_11_04_13_34_19_13", MainPackage = "1296_2026_11_04_13_36_07_72" },
            checked_at_utc = "2026-11-10T00:00:00+00:00", assets_ready = false
        }));
        return new([new(103, "地球", "3線", profile)], "offline fixture", Stopwatch.GetTimestamp() - (old ? Stopwatch.Frequency * 600 : 0)) { Version = version };
    }

    [Fact]
    public void Aged_ui_selection_can_be_revalidated_without_rebuilding_resources()
    {
        var selected = Catalog(old: true);
        Assert.False(selected.IsFresh);
        Assert.True(DesktopLoginTarget.Matches(selected, Catalog(), 103));
    }

    [Fact]
    public void Revalidation_requires_a_fresh_observation()
        => Assert.False(DesktopLoginTarget.Matches(Catalog(old: true), Catalog(old: true), 103));

    [Fact]
    public void Revalidation_rejects_changed_server_or_version_or_missing_line()
    {
        Assert.False(DesktopLoginTarget.Matches(Catalog(old: true), Catalog(port: 16990), 103));
        Assert.False(DesktopLoginTarget.Matches(Catalog(old: true), Catalog(data: "1.3.24"), 103));
        Assert.False(DesktopLoginTarget.Matches(Catalog(old: true), Catalog(), 104));
    }
}
