using System.Text;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class InventoryPersistenceBoundsTests
{
    [Theory]
    [InlineData("UTF-8")]
    [InlineData("UTF-16le")]
    [InlineData("UTF-16be")]
    public async Task Encodings_preserve_embedded_nul_unicode_identity_and_derived_json(string encoding)
    {
        using var db = new InventoryTestDatabase();
        db.Execute("PRAGMA encoding='" + encoding + "'; CREATE TABLE unrelated_marker(id INTEGER)");
        var call = InventoryPythonVectors.Case("all-ten-seven-derived-views").GetProperty("calls")[0];
        var first = await ResourceInventoryStore.RecordAsync(db.Connection(), InventoryTestDatabase.Input(call));
        InventoryPersistenceParityTests.Equal(call.GetProperty("expected").GetProperty("snapshot"), db.Snapshot(), encoding);
        var owned = ResourceInventoryInput.Capture("nul\0😀", [new("tables/A\0雪😀.bytes", new byte[] { 0, 1, 255 })]);
        var second = await ResourceInventoryStore.RecordAsync(db.Connection(), owned);
        var repeated = await ResourceInventoryStore.RecordAsync(db.Connection(), owned);
        Assert.Equal(second.Report.ToJson(), repeated.Report.ToJson()); Assert.Equal(2, second.VersionId);
        Assert.False(first.RuntimeAdmitted); Assert.False(second.RuntimeAdmitted);
        Assert.Equal("nul\0😀", db.Snapshot().GetProperty("tables").GetProperty("versions")[1].GetProperty("catalog_key").GetString());
        Assert.Contains(db.Snapshot().GetProperty("tables").GetProperty("resources").EnumerateArray(), row => row.GetProperty("name").GetString() == "A\0雪😀.bytes");
    }

    [Fact]
    public async Task Mutable_input_and_provider_aliases_cannot_mutate_owned_input_or_report()
    {
        byte[] bytes = [1, 2, 3]; var members = new List<ResourceInventoryMember> { new("tables/Opaque.bytes", bytes) };
        var input = ResourceInventoryInput.Capture("synthetic", members); byte[] returned = input.Tables[0].CopyBytes();
        bytes[0] = 9; returned[1] = 9; members.Clear(); Assert.Equal(new byte[] { 1, 2, 3 }, input.Tables[0].CopyBytes());
        using var db = new InventoryTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        byte[]? providerAlias = null;
        connection.TransformValue = (_, _, value) => { if (value is byte[] raw) providerAlias = raw; return value; };
        var receipt = await ResourceInventoryStore.RecordAsync(connection, input);
        Assert.NotNull(providerAlias); Array.Fill(providerAlias, (byte)99);
        Assert.Equal(new byte[] { 1, 2, 3 }, input.Tables[0].CopyBytes());
        Assert.Equal(input.Tables[0].Sha256, db.Snapshot().GetProperty("tables").GetProperty("resources")[0].GetProperty("data_sha256").GetString());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, InventoryRowChanges>)receipt.Report.OtherRows).Add("bad", InventoryRowChanges.ParseFailed()));
    }

    [Theory]
    [InlineData("members")]
    [InlineData("tables")]
    [InlineData("name")]
    [InlineData("key")]
    [InlineData("unicode")]
    [InlineData("bytes")]
    [InlineData("total-bytes")]
    public void Capture_rejects_stricter_quotas_without_io(string kind)
    {
        List<ResourceInventoryMember> members = [new("tables/Opaque.bytes", new byte[] { 1 })]; string key = "synthetic";
        switch (kind)
        {
            case "members": members = Enumerable.Range(0, 513).Select(i => new ResourceInventoryMember("ignored" + i, null)).ToList(); break;
            case "tables": members = Enumerable.Range(0, 257).Select(i => new ResourceInventoryMember("tables/" + i + ".bytes", ReadOnlyMemory<byte>.Empty)).ToList(); break;
            case "name": members = [new("tables/" + new string('a', 121) + ".bytes", ReadOnlyMemory<byte>.Empty)]; break;
            case "key": key = new string('k', 129); break;
            case "unicode": key = "invalid\ud800"; break;
            case "bytes": members = [new("tables/Opaque.bytes", new byte[ResourceInventoryInput.MaximumTableBytes + 1])]; break;
            case "total-bytes":
                var chunk = new byte[ResourceInventoryInput.MaximumTableBytes];
                members = Enumerable.Range(0, 9).Select(i => new ResourceInventoryMember("tables/" + i + ".bytes", chunk)).ToList(); break;
        }
        Assert.ThrowsAny<Exception>(() => ResourceInventoryInput.Capture(key, members));
    }

    [Theory]
    [InlineData("view")]
    [InlineData("collation")]
    [InlineData("foreign-key")]
    [InlineData("generated")]
    [InlineData("trigger")]
    [InlineData("huge-trigger-name")]
    [InlineData("huge-index-name")]
    public async Task Unknown_schema_rejects_without_schema_reset_or_partial_writes(string shape)
    {
        using var db = new InventoryTestDatabase();
        switch (shape)
        {
            case "view": db.Execute("CREATE VIEW versions AS SELECT 1 AS id,'synthetic' AS catalog_key"); break;
            case "collation": db.Execute("CREATE TABLE versions(id INTEGER PRIMARY KEY,catalog_key TEXT COLLATE NOCASE UNIQUE NOT NULL)"); break;
            case "foreign-key": db.Execute("CREATE TABLE versions(id INTEGER PRIMARY KEY REFERENCES arbitrary(id),catalog_key TEXT UNIQUE NOT NULL)"); break;
            case "generated": db.Execute("CREATE TABLE versions(id INTEGER PRIMARY KEY,catalog_key TEXT UNIQUE NOT NULL,extra TEXT GENERATED ALWAYS AS(catalog_key))"); break;
            default:
                await ResourceInventoryStore.RecordAsync(db.Connection(), InventoryTestDatabase.Simple());
                string name = shape == "trigger" ? "unexpected" : new string('x', 600_000);
                db.Execute(shape == "huge-index-name" ? "CREATE INDEX \"" + name + "\" ON resources(name)" :
                    "CREATE TRIGGER \"" + name + "\" AFTER INSERT ON resources BEGIN SELECT 1; END");
                break;
        }
        var before = db.Snapshot();
        var connection = new ScriptedReadConnection(db.Connection());
        connection.TransformValue = (_, _, value) => { if (value is string text) Assert.True(text.Length <= 32768); return value; };
        var error = await Record.ExceptionAsync(() => ResourceInventoryStore.RecordAsync(connection, InventoryTestDatabase.Simple()));
        Assert.IsType<InvalidDataException>(error); Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, error.Data[ResourceInventoryDatabase.OutcomeKey]);
        InventoryPersistenceParityTests.Equal(before, db.Snapshot(), shape);
    }

    [Theory]
    [InlineData("active")]
    [InlineData("previous")]
    [InlineData("parent")]
    public async Task Integer_affinity_does_not_allow_unbounded_descriptor_materialization(string field)
    {
        using var db = new InventoryTestDatabase(); await ResourceInventoryStore.RecordAsync(db.Connection(), InventoryTestDatabase.Simple());
        if (field == "active") db.Execute("UPDATE sync_state SET active_id=zeroblob(16777217)");
        else if (field == "previous") db.Execute("UPDATE sync_state SET previous_id=zeroblob(16777217)");
        else db.Execute("INSERT INTO version_parents VALUES(1,zeroblob(16777217))");
        var connection = new ScriptedReadConnection(db.Connection());
        connection.TransformValue = (_, _, value) => { Assert.False(value is byte[]); return value; };
        var error = await Record.ExceptionAsync(() => ResourceInventoryStore.RecordAsync(connection, InventoryTestDatabase.Simple()));
        Assert.IsType<InvalidDataException>(error); Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, error.Data[ResourceInventoryDatabase.OutcomeKey]);
    }

    [Fact]
    public void Python_lexical_order_is_scalar_not_utf16_or_numeric_and_input_order_is_retained()
    {
        var input = ResourceInventoryInput.Capture("", [new("tables/😀.bytes", ReadOnlyMemory<byte>.Empty), new("tables/\ue000.bytes", ReadOnlyMemory<byte>.Empty), new("tables/10.bytes", ReadOnlyMemory<byte>.Empty), new("tables/2.bytes", ReadOnlyMemory<byte>.Empty)]);
        Assert.Equal(new[] { "😀.bytes", "\ue000.bytes", "10.bytes", "2.bytes" }, input.Tables.Select(table => table.Name));
        Assert.Equal(new[] { "10", "2", "\ue000", "😀" }, InventoryRowChanges.Sorted(["😀", "2", "\ue000", "10"]));
    }
}
