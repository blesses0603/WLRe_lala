using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Social.Ark;
using Lala.Core.Storage;
using Xunit;
using static Lala.Core.Tests.Storage.ArkQuestionStorageTestDatabase;

namespace Lala.Core.Tests.Storage;

public sealed class ArkQuestionStorageParityTests
{
    private static readonly JsonDocument Vectors = JsonDocument.Parse(ArkQuestionStorageVectors.Json);
    public static IEnumerable<object[]> Identities => Vectors.RootElement.GetProperty("identities").EnumerateArray().Select((v, i) => new object[] { i });
    public static IEnumerable<object[]> Scenarios => Vectors.RootElement.GetProperty("scenarios").EnumerateArray().Select((v, i) => new object[] { v.GetProperty("name").GetString()!, i });

    [Theory][InlineData(0)][InlineData(1)][InlineData(2)]
    public void Actual_python_database_is_read_and_migrated_without_relearning(int version)
    {
        var legacy = Vectors.RootElement.GetProperty("legacyDatabases")[version];
        using var db = new ArkQuestionStorageTestDatabase();
        File.WriteAllBytes(db.PathName, Convert.FromBase64String(legacy.GetProperty("bytes").GetString()!));
        var role = BigInteger.Parse(legacy.GetProperty("role").GetString()!);
        Assert.Equal(new ArkQuestionObservation(22, ArkQuestionEvidenceStatus.Confirmed), db.Store().Observe(Token, role, Question));
        Assert.Equal(2L, db.Scalar("PRAGMA user_version"));
        Assert.Equal(ArkQuestionEvidenceStatus.Confirmed, db.Store().RecordCandidate(Token, role, Question, 22, "reviewed-local", "r1"));
        Assert.True(db.Store().ClaimCandidate(Token, role, Question, 22));
    }

    [Theory, MemberData(nameof(Identities))]
    public void Canonical_identity_matches_retained_python(int index)
    {
        var data = Vectors.RootElement.GetProperty("identities")[index];
        var question = QuestionFrom(data.GetProperty("question"));
        var role = BigInteger.Parse(data.GetProperty("role").GetString()!);
        var result = ArkQuestionIdentity.Create(Token, role, question);
        Assert.Equal(data.GetProperty("catalog").GetString(), result.Catalog);
        Assert.Equal(data.GetProperty("roleHash").GetString(), result.Role);
        Assert.Equal(data.GetProperty("fingerprint").GetString(), result.Fingerprint);
        Assert.Equal(data.GetProperty("payload").GetString(), result.CanonicalPayload);
        Assert.Equal(result, ArkQuestionIdentity.Create(Token, role, question with
        { Options = [.. question.Options.Reverse()], Labels = [.. question.Labels.Reverse()], KnownAnswer = 123, AnswerKind = "confirmed" }));
    }

    [Theory, MemberData(nameof(Scenarios))]
    public void Durable_operations_and_tables_match_retained_python(string name, int scenarioIndex)
    {
        var data = Vectors.RootElement.GetProperty("scenarios")[scenarioIndex];
        using var db = new ArkQuestionStorageTestDatabase();
        int index = 0;
        foreach (var step in data.GetProperty("steps").EnumerateArray())
        {
            var store = db.Store();
            var token = new ArkCatalogToken(true, step.GetProperty("catalog").GetString());
            var role = BigInteger.Parse(step.GetProperty("role").GetString()!);
            var question = QuestionFrom(step.GetProperty("question"));
            uint answer = step.GetProperty("answer").GetUInt32();
            bool flag = step.GetProperty("flag").GetBoolean();
            string op = step.GetProperty("operation").GetString()!;
            object? result;
            switch (op)
            {
                case "observe":
                    var observed = store.Observe(token, role, question);
                    result = new object?[] { observed.Answer, Status(observed.Status) }; break;
                case "confirm": result = Status(store.Confirm(token, role, question, answer)); break;
                case "quarantine": result = Status(store.Quarantine(token, role, question)); break;
                case "record_candidate": result = Status(store.RecordCandidate(token, role, question, answer, "reviewed-local", "r1")); break;
                case "claim_candidate": result = store.ClaimCandidate(token, role, question, answer); break;
                case "record_candidate_attempt": result = store.RecordCandidateAttempt(token, role, question, answer, flag); break;
                case "reject": store.Reject(token, role, question, answer, flag); result = null; break;
                default: throw new InvalidDataException(op);
            }
            Assert.True(JsonNode.DeepEquals(JsonNode.Parse(step.GetProperty("result").GetRawText()), JsonSerializer.SerializeToNode(result)), $"{name} step {index} {op} result");
            Assert.True(JsonNode.DeepEquals(JsonNode.Parse(step.GetProperty("state").GetRawText()), db.Snapshot()), $"{name} step {index} {op} tables");
            index++;
        }
    }
    private static string Status(ArkQuestionEvidenceStatus status) => status.ToString().ToLowerInvariant();
}
