using System.Collections.Immutable;
using System.Numerics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Protocol;
using Lala.Core.Social.Ark;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Social.Ark;

public sealed class ArkReceiveParityTests
{
    internal static readonly JsonSerializerOptions Options = CreateOptions();
    private static JsonSerializerOptions CreateOptions()
    {
        var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
        options.Converters.Add(new IntegerConverter());
        options.Converters.Add(new ValueConverter());
        return options;
    }

    [Theory]
    [MemberData(nameof(ArkReceivePythonVectors.Sequences), MemberType = typeof(ArkReceivePythonVectors))]
    public void ActualPythonReceiveSnapshotsAndMemoryBoundaryIntentsMatch(string name, string json)
    {
        var scenario = JsonNode.Parse(json)!;
        var state = ReadState(scenario["initial"]!);
        var history = new List<(ArkReceiveSnapshot State, JsonNode Expected)> { (state, scenario["initial"]!) };
        Check(scenario["initial"]!, Project(state), name + " initial");
        var number = 0;
        foreach (var step in scenario["steps"]!.AsArray())
        {
            var operation = step!["operation"]!;
            var ctx = ReadContext(step["context"]!);
            ServerEvent observation;
            if (operation["direct"] is { } direct)
            {
                if (direct["type"]!.GetValue<string>() == "world_player")
                {
                    var role = direct["player"]!["role_id"]!.GetValue<uint>();
                    observation = World(role);
                    ctx = ctx with { PlayerRoleId = role };
                }
                else observation = new NamedEvent(direct["type"]!.GetValue<string>());
            }
            else
            {
                var packet = new Packet(operation["main"]!.GetValue<byte>(), operation["sub"]!.GetValue<byte>(),
                    Convert.FromHexString(operation["hex"]!.GetValue<string>()));
                if (step["error"] is { } error)
                {
                    Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() => ArkDecoder.Decode(packet)).Message);
                    Check(step["expected"]!, Project(state), $"{name}, malformed {number++}");
                    history.Add((state, step["expected"]!));
                    continue;
                }
                observation = (ServerEvent?)ArkDecoder.Decode(packet) ?? new NamedEvent("unimplemented");
            }
            var result = ArkReceiveReducer.Apply(state, observation, ctx);
            state = result.State;
            Check(step["expected"]!, Project(state), $"{name}, step {number++}");
            var intents = step["intents"]!.AsArray();
            if (intents.Count == 0) Assert.Null(result.MemoryIntent);
            else
            {
                Assert.Single(intents);
                Assert.NotNull(result.MemoryIntent);
                Check(intents[0]!, ProjectIntent(result.MemoryIntent), name + " intent");
            }
            history.Add((state, step["expected"]!));
        }
        foreach (var previous in history) Check(previous.Expected, Project(previous.State), name + " historical");
    }

    [Fact]
    public void OracleSourceHashesUseByteOnlyCrLfNormalization()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "wlre", "services", "star_ark.py"))) root = root.Parent;
        Assert.NotNull(root);
        foreach (var (path, hash) in JsonNode.Parse(ArkReceivePythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), Convert.ToHexString(SHA256.HashData(CanonicalSourceBytes(
                File.ReadAllBytes(Path.Combine(root.FullName, path))))).ToLowerInvariant());
    }

    [Fact]
    public void NormalizationDoesNotDecodeOrChangeBareCr()
    {
        Assert.Equal(new byte[] { 255, 10, 254, 13, 0, 10, 13 }, CanonicalSourceBytes([255, 13, 10, 254, 13, 0, 10, 13]));
    }

    private static byte[] CanonicalSourceBytes(byte[] bytes)
    {
        using var output = new MemoryStream(bytes.Length);
        for (var i = 0; i < bytes.Length; i++)
        {
            if (bytes[i] == 13 && i + 1 < bytes.Length && bytes[i + 1] == 10) continue;
            output.WriteByte(bytes[i]);
        }
        return output.ToArray();
    }

    internal static ServerEvent World(uint role) => new ServerLayoutEvent(new WorldPlayerEvent(
        new WorldPlayer(role, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, false, [], "", 0)));
    private sealed record NamedEvent(string Name) : ServerEvent(0, 0) { public override string Type => Name; }
    private static T Read<T>(JsonNode node) => node.Deserialize<T>(Options)!;
    private static JsonNode? Node<T>(T value) => JsonSerializer.SerializeToNode(value, Options);
    private static ArkCatalogToken? ReadToken(JsonNode? token) => token is null ? null : new(token[0]!.GetValue<bool>(), token[1]?.GetValue<string>());
    private static JsonNode? Token(ArkCatalogToken? token) => token is null ? null : new JsonArray(token.Attempted, token.IdentityKey);

    internal static ArkReceiveSnapshot ReadState(JsonNode source)
    {
        var clone = source.DeepClone();
        var pending = clone["pending"]?.DeepClone(); clone["pending"] = null;
        var token = ReadToken(clone["catalog_token"]); clone["catalog_token"] = null;
        if (clone["ship"]!.AsObject().Count == 0) clone["ship"] = null;
        var added = clone["main_events"]!.AsObject().Where(p => p.Value!["type"] is not null)
            .Select(p => byte.Parse(p.Key)).ToImmutableHashSet();
        return Read<ArkReceiveSnapshot>(clone) with { Pending = pending is null ? null : ReadPending(pending), CatalogToken = token, AddedMainEvents = added };
    }

    private static ArkPendingObservation ReadPending(JsonNode source)
    {
        var clone = source.DeepClone().AsObject();
        var token = ReadToken(clone["token"]); clone["token"] = null;
        var quote = clone["quote"]?.DeepClone(); clone["quote"] = null;
        var known = new HashSet<string> { "kind", "role", "token", "daily_generation", "due", "quote", "balance", "paid", "ship_ack", "event", "complete", "result", "awards" };
        var other = new JsonObject();
        foreach (var (key, value) in clone) if (!known.Contains(key)) other[key] = value?.DeepClone();
        ArkDispatchQuote? parsedQuote = null;
        if (quote is not null)
        {
            var extra = quote.DeepClone().AsObject();
            foreach (var key in new[] { "planet", "agent", "duration", "price" }) extra.Remove(key);
            parsedQuote = Read<ArkDispatchQuote>(quote) with { OtherFields = Read<StateValue>(extra) };
        }
        return Read<ArkPendingObservation>(clone) with { Token = token, Quote = parsedQuote, OtherFields = Read<StateValue>(other) };
    }

    private static ArkReceiveContext ReadContext(JsonNode context) => new(context["role"]?.GetValue<uint>(),
        Read<BigInteger>(context["daily_generation"]!), ReadRuntime(context["current"]!))
    { QuestionRuntime = context["second"] is { } second ? ReadRuntime(second) : null, MemoryAvailability = ArkQuestionMemoryAvailability.Unavailable };

    private static ArkRuntimeObservation ReadRuntime(JsonNode runtime) => new(runtime["available"]!.GetValue<bool>(),
        ReadToken(runtime["token"]), Read<ImmutableDictionary<uint, string>>(runtime["texts"]!));

    internal static JsonNode Project(ArkReceiveSnapshot state)
    {
        var node = Node(state)!;
        node.AsObject().Remove("added_main_events");
        node["catalog_token"] = Token(state.CatalogToken);
        node["pending"] = state.Pending is { } pending ? ProjectPending(pending) : null;
        node["question"] = state.Question is { } question ? ProjectQuestion(question) : null;
        node["ship"] ??= new JsonObject();
        foreach (var index in state.AddedMainEvents) node["main_events"]![index.ToString()]!["type"] = "ark_main_added";
        return node;
    }

    private static JsonNode ProjectPending(ArkPendingObservation pending)
    {
        var node = Node(pending)!.AsObject();
        node.Remove("other_fields");
        node["token"] = Token(pending.Token);
        if (pending.Kind != "dispatch") foreach (var key in new[] { "quote", "balance", "paid", "ship_ack" }) node.Remove(key);
        else
        {
            var quote = Node(pending.Quote)!.AsObject();
            quote.Remove("other_fields");
            foreach (var (key, value) in Node(pending.Quote!.OtherFields)!.AsObject()) quote[key] = value?.DeepClone();
            node["quote"] = quote;
        }
        if (pending.Kind is not ("fight" or "question")) foreach (var key in new[] { "event", "complete", "result" }) node.Remove(key);
        if (pending.Kind != "fight") node.Remove("awards");
        foreach (var (key, value) in Node(pending.OtherFields)!.AsObject()) node[key] = value?.DeepClone();
        return node;
    }

    private static JsonNode ProjectQuestion(ArkQuestionSnapshot question)
    {
        var node = Node(question)!.AsObject();
        node["type"] = "ark_question";
        foreach (var key in new[] { "answer_source", "answer_kind", "candidate_reason", "candidate_revision", "candidate_source", "selected_candidate" })
            if (node[key] is null) node.Remove(key);
        if (question.AnswerSource is null && question.AnswerKind is null && question.KnownAnswer is null) node.Remove("known_answer");
        return node;
    }

    internal static JsonNode ProjectIntent(ArkQuestionMemoryIntent intent)
    {
        var node = Node(intent)!;
        node["token"] = Token(intent.Token);
        node["operation"] = intent.Operation.ToString();
        node["question"] = ProjectQuestion(intent.Question);
        return node;
    }

    private static void Check(JsonNode expected, JsonNode actual, string description) =>
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{description}\nExpected: {expected}\nActual: {actual}");

    private sealed class IntegerConverter : JsonConverter<BigInteger>
    {
        public override BigInteger Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        { using var doc = JsonDocument.ParseValue(ref reader); return BigInteger.Parse(doc.RootElement.GetRawText()); }
        public override void Write(Utf8JsonWriter writer, BigInteger value, JsonSerializerOptions options) => writer.WriteRawValue(value.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    private sealed class ValueConverter : JsonConverter<StateValue>
    {
        public override StateValue Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        { using var doc = JsonDocument.ParseValue(ref reader); return ReadValue(doc.RootElement); }
        private static StateValue ReadValue(JsonElement value) => value.ValueKind switch
        {
            JsonValueKind.Object => StateValue.Map(value.EnumerateObject().Select(p => KeyValuePair.Create(p.Name, ReadValue(p.Value)))),
            JsonValueKind.Array => StateValue.List(value.EnumerateArray().Select(ReadValue)),
            JsonValueKind.String => StateValue.Scalar(value.GetString()),
            JsonValueKind.True => StateValue.Scalar(true), JsonValueKind.False => StateValue.Scalar(false),
            JsonValueKind.Number => StateValue.Scalar(BigInteger.Parse(value.GetRawText())),
            _ => StateValue.Null
        };
        public override void Write(Utf8JsonWriter writer, StateValue value, JsonSerializerOptions options)
        {
            if (value.Kind == StateValueKind.Map)
            {
                writer.WriteStartObject();
                foreach (var (key, item) in value.MapValue) { writer.WritePropertyName(key); Write(writer, item, options); }
                writer.WriteEndObject();
            }
            else if (value.Kind is StateValueKind.List or StateValueKind.Tuple)
            {
                writer.WriteStartArray(); foreach (var item in value.SequenceValue) Write(writer, item, options); writer.WriteEndArray();
            }
            else JsonSerializer.Serialize(writer, value.ScalarValue, options);
        }
    }
}
