using System.Text.Json;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class InventoryPersistenceParityTests
{
    [Theory]
    [MemberData(nameof(InventoryPythonVectors.Cases), MemberType = typeof(InventoryPythonVectors))]
    public async Task Complete_retained_python_transactions_match_reports_and_all_six_tables(string id)
    {
        var fixture = InventoryPythonVectors.Case(id);
        // These Python-only invalid values have no legal value in the typed Core API.
        // Verify the exclusion explicitly rather than substituting an unrelated parser branch.
        if (id == "identity-wrong-type")
        {
            Assert.Equal(typeof(ManifestIdentity), typeof(ResourceInventoryInput).GetMethod("Capture", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!.GetParameters()[2].ParameterType);
            Assert.Equal("ValueError", fixture.GetProperty("calls")[0].GetProperty("expected").GetProperty("error").GetProperty("type").GetString());
            return;
        }
        if (id is "selected-data-not-bytes-string" or "selected-data-not-bytes-bytearray")
        {
            Assert.Equal(typeof(ReadOnlyMemory<byte>?), typeof(ResourceInventoryMember).GetProperty("Data")!.PropertyType);
            Assert.Equal("ValueError", fixture.GetProperty("calls")[0].GetProperty("expected").GetProperty("error").GetProperty("type").GetString());
            return;
        }
        using var db = new InventoryTestDatabase(); db.Operations(fixture.GetProperty("initialSetup"));
        var calls = fixture.GetProperty("calls"); int index = 0;
        foreach (var call in calls.EnumerateArray())
        {
            db.Operations(call.GetProperty("preCallSQL")); var before = db.Snapshot();
            bool strict = fixture.GetProperty("policy").GetString() == "source_accepts_strict_rejects" && index == calls.GetArrayLength() - 1;
            var expected = call.GetProperty("expected"); ResourceInventoryReceipt? result = null;
            var failure = await Record.ExceptionAsync(async () =>
            {
                var input = InventoryTestDatabase.Input(call);
                result = await ResourceInventoryStore.RecordAsync(db.Connection(), input);
            });
            if (strict || expected.GetProperty("error").ValueKind != JsonValueKind.Null)
            {
                if (failure is null) Assert.Fail($"{id} call {index}: expected rejection");
                Assert.Null(result);
                if (!strict)
                {
                    string message = expected.GetProperty("error").GetProperty("message").GetString()!;
                    Assert.StartsWith(message, failure.Message, StringComparison.Ordinal);
                    if (message is "No resource tables to record" or "Ambiguous or invalid resource table" or "Catalog identity does not match inventory")
                        Assert.IsType<ArgumentException>(failure);
                    else Assert.IsType<InvalidDataException>(failure);
                }
                if (strict) Equal(before, db.Snapshot(), id + " strict atomic rollback");
                else Equal(expected.GetProperty("snapshot"), db.Snapshot(), id + " rejected source snapshot");
            }
            else
            {
                if (failure is not null) Assert.Fail($"{id} call {index}: {failure}");
                Assert.NotNull(result);
                using var report = JsonDocument.Parse(result.Report.ToJson());
                Equal(expected.GetProperty("report"), report.RootElement, id + " report");
                Equal(expected.GetProperty("snapshot"), db.Snapshot(), id + " snapshot");
                Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.Outcome);
                Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted);
                Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
            }
            index++;
        }
    }

    [Fact]
    public void Retained_source_hashes_are_crlf_only_pinned_and_fixture_ids_are_unique()
    {
        string root = RepositoryRoot();
        foreach (var source in InventoryPythonVectors.Root.GetProperty("source_sha256").EnumerateObject())
        {
            byte[] raw = File.ReadAllBytes(Path.Combine(root, source.Name)); using var normalized = new MemoryStream(raw.Length);
            for (int i = 0; i < raw.Length; i++) { if (raw[i] == 13 && i + 1 < raw.Length && raw[i + 1] == 10) continue; normalized.WriteByte(raw[i]); }
            Assert.Equal(source.Value.GetString(), InventoryTestDatabase.Sha(normalized.ToArray()));
        }
        Assert.Equal(InventoryPythonVectors.CaseCount, InventoryPythonVectors.Cases().Select(row => (string)row[0]).Distinct().Count());
        foreach (var item in InventoryPythonVectors.Root.GetProperty("identities").EnumerateObject())
        {
            var identity = InventoryTestDatabase.Identity(item.Name);
            Assert.Equal(item.Value.GetProperty("catalog_key").GetString(), identity.Key);
            Assert.Equal(item.Value.GetProperty("canonical_json").GetString(), identity.CanonicalJson);
        }
    }
    internal static void Equal(JsonElement expected, JsonElement actual, string context)
    {
        if (!JsonElement.DeepEquals(expected, actual)) Assert.Fail(context + "\nExpected: " + expected + "\nActual: " + actual);
    }
    private static string RepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "wlre/services/world/resource_database.py"))) return directory.FullName;
        throw new InvalidOperationException("Retained source checkout unavailable");
    }
}
