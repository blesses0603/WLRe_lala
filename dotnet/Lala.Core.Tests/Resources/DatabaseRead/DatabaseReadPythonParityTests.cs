using System.Data.Common;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class DatabaseReadPythonParityTests
{
    [Theory]
    [MemberData(nameof(DatabaseReadPythonVectors.Cases), MemberType = typeof(DatabaseReadPythonVectors))]
    public async Task Real_sqlite_capture_and_separate_match_preserve_retained_expectations(string id)
    {
        var fixture = DatabaseReadPythonVectors.Case(id);
        using var db = new DatabaseReadTestDatabase(fixture.TryGetProperty("database_encoding", out var encoding) ? encoding.GetString() : null);
        foreach (var operation in fixture.GetProperty("operations").EnumerateArray())
            db.ExecuteParameters(operation.GetProperty("sql").GetString()!, "$p", operation.GetProperty("parameters").EnumerateArray().Select(Materialize).ToArray());
        var expected = fixture.GetProperty("expected");
        var connection = new ScriptedReadConnection(db.Connection());
        RuntimeDatabaseReadObservation? observation = null;
        Exception? failure = await Record.ExceptionAsync(async () => observation = await RuntimeDatabaseSnapshotReader.ReadAsync(connection));
        if (!expected.GetProperty("reader_capture").GetBoolean())
        {
            if (failure is not (InvalidDataException or DbException)) Assert.Fail(failure?.ToString() ?? "Unexpected successful capture");
            Assert.Null(observation);
        }
        else
        {
            if (failure is not null) Assert.Fail(failure.ToString());
            Assert.NotNull(observation); Assert.True(observation.CompletedSingleReadTransaction);
            Assert.False(observation.HasVerifiedProvenance); Assert.False(observation.RuntimeAdmitted);
            Assert.False(observation.AssetsReady); Assert.False(observation.CanSendPackets);
            var digests = DatabaseReadTestDatabase.Digests();
            foreach (var item in fixture.GetProperty("expected_digest_overrides").EnumerateObject()) digests[item.Name] = item.Value.GetString();
            var result = RuntimeDatabaseStructuralMatcher.Match(observation.Snapshot, DatabaseReadTestDatabase.Identity(), digests);
            Assert.Equal(expected.GetProperty("reader_matches").GetBoolean(), result.MatchesSuppliedRuntime);
            Assert.False(result.ProvesDatabaseTransaction); Assert.False(result.RuntimeAdmitted);
            Assert.Equal(expected.GetProperty("python_matches").GetBoolean(), result.MatchesSuppliedRuntime);
        }
        Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
        Assert.All(connection.CreatedCommands, command => Assert.True(command.WasDisposed));
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed));
    }

    [Fact]
    public void Retained_original_python_source_and_shared_synthetic_identity_are_pinned()
    {
        Assert.True(JsonElement.DeepEquals(DatabaseMatchPythonVectors.Root.GetProperty("identity_inputs"), DatabaseReadPythonVectors.Root.GetProperty("identity_inputs")));
        string root = RepositoryRoot();
        foreach (var source in DatabaseReadPythonVectors.Root.GetProperty("source_sha256").EnumerateObject())
        {
            byte[] raw = File.ReadAllBytes(Path.Combine(root, source.Name)); using var normalized = new MemoryStream(raw.Length);
            for (int i = 0; i < raw.Length; i++) { if (raw[i] == 13 && i + 1 < raw.Length && raw[i + 1] == 10) continue; normalized.WriteByte(raw[i]); }
            Assert.Equal(source.Value.GetString(), DatabaseReadTestDatabase.Sha(normalized.ToArray()));
        }
    }

    private static object? Materialize(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Null) return null;
        if (value.ValueKind == JsonValueKind.String) return value.GetString();
        if (value.ValueKind == JsonValueKind.Number) return value.TryGetInt64(out long integer) ? (object)integer : value.GetDouble();
        string kind = value.GetProperty("kind").GetString()!;
        if (kind == "repeat_text") return string.Concat(Enumerable.Repeat(value.GetProperty("value").GetString()!, value.GetProperty("length").GetInt32()));
        byte[] bytes;
        if (kind == "base64") bytes = Convert.FromBase64String(value.GetProperty("value").GetString()!);
        else if (kind == "repeat") { bytes = new byte[value.GetProperty("length").GetInt32()]; Array.Fill(bytes, value.GetProperty("byte").GetByte()); }
        else throw new InvalidOperationException("Unknown retained recipe");
        Assert.Equal(value.GetProperty("size").GetInt32(), bytes.Length); Assert.Equal(value.GetProperty("sha256").GetString(), DatabaseReadTestDatabase.Sha(bytes));
        return bytes;
    }
    private static string RepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "wlre/services/world/resource_database.py"))) return directory.FullName;
        throw new InvalidOperationException("Retained source checkout unavailable");
    }
}
