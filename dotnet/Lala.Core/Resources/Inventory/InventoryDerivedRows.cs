using System.Collections;
using System.Collections.Immutable;
using System.Globalization;
using System.Text;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.Resources.Inventory;

/// <summary>Pure resource_database.record_inventory row projections. These descriptive rows
/// neither establish provenance nor authorize a runtime, resource activation, or packets.</summary>
internal static class InventoryDerivedRows
{
    internal const int MaximumRowJsonBytes = 256 * 1024;
    internal const int MaximumViewJsonBytes = 64 * 1024 * 1024;
    internal const int MaximumRows = 1_000_000;
    private static readonly IComparer<string> PythonStringOrder = Comparer<string>.Create(CompareCodePoints);

    internal static ImmutableArray<KeyValuePair<string, string>> Parse(string source,
        ReadOnlySpan<byte> raw, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        return source switch
        {
            // No package-version input or caller-controlled hash acceptance. The parser retains
            // its independent fixed 1296 SHA pin and original source insertion order.
            "items_v1" => Project(ItemDataParser.ParseForSourceAdapter(raw, token)
                .Select(pair => Row(Number(pair.Key), ItemFields(pair.Value))), token),
            "smith_v1" => Project(SmithDataParser.ParseRecords(raw, token)
                .Select(row => Row(Number(row.RecipeId ?? row.CandidateRowKey ?? row.ItemId), SmithFields(row))), token),
            "talk_v1" => Project(TalkDataParser.Parse(raw, token)
                .Select(pair => Row(Number(pair.Key), new Dictionary<string, object?>
                {
                    ["text"] = pair.Value.Text, ["voice_id"] = pair.Value.VoiceId
                })), token),
            "text_v1" => Project(TextDataParser.Parse(raw, token)
                .Select(pair => Row(Number(pair.Key), pair.Value)), token),
            "scenes_v1" => Project(StageDataParser.Parse(raw, token)
                .Select(pair => Row(Number(pair.Key), StageFields(pair.Value))), token),
            // Separate source calls retain the source parser's selection and diagnostics.
            "eve_npc_v1" => ParseEve(raw, EveV115Parser.NpcSource, token),
            "eve_interact_v1" => ParseEve(raw, EveV115Parser.InteractionSource, token),
            _ => throw new ArgumentException("Unknown inventory derived-row source", nameof(source))
        };
    }

    private static ImmutableArray<KeyValuePair<string, string>> ParseEve(ReadOnlySpan<byte> raw,
        string source, CancellationToken token)
    {
        var bytes = EveV115Parser.DeriveIndex(raw, source, token);
        token.ThrowIfCancellationRequested();
        using var document = JsonDocument.Parse(bytes.AsMemory());
        // DeriveIndex sorts numeric scene properties lexicographically, as Python's JSON does.
        // Enumerate that document rather than the typed parser's numeric scene ordering.
        return Project(EveRows(document.RootElement.GetProperty("scenes"), token), token);
    }

    private static IEnumerable<KeyValuePair<string, object?>> EveRows(JsonElement scenes,
        CancellationToken token)
    {
        var keys = new HashSet<string>(StringComparer.Ordinal);
        foreach (var scene in scenes.EnumerateObject())
        {
            token.ThrowIfCancellationRequested();
            foreach (var row in scene.Value.EnumerateArray())
            {
                token.ThrowIfCancellationRequested();
                string key = scene.Name + ":" + Number(row.GetProperty("index").GetUInt16());
                if (!keys.Add(key)) throw new EveDecodeException("Duplicate Eve scene/index");
                yield return Row(key, row);
            }
        }
    }

    // Internal projection/serialization helpers permit synthetic quota and reviewed-field tests
    // without introducing an input-byte digest override or bypassing the parser's source pin.
    internal static ImmutableArray<KeyValuePair<string, string>> Project(
        IEnumerable<KeyValuePair<string, object?>> rows, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        var result = ImmutableArray.CreateBuilder<KeyValuePair<string, string>>();
        long viewBytes = 2; // Canonical {"row_key":row_json,...}, including all key/punctuation bytes.
        foreach (var row in rows)
        {
            token.ThrowIfCancellationRequested();
            ValidateViewLimits(result.Count + 1, viewBytes);
            string json = Serialize(row.Value, token);
            viewBytes += Quote(row.Key, token).Length + 1L + json.Length + (result.Count == 0 ? 0 : 1);
            ValidateViewLimits(result.Count + 1, viewBytes);
            result.Add(KeyValuePair.Create(row.Key, json));
        }
        token.ThrowIfCancellationRequested();
        return result.ToImmutable();
    }

    internal static string SerializeItemRow(ItemDataRow row, CancellationToken token = default) =>
        Serialize(ItemFields(row), token);

    // Reports share the canonical spelling but apply their own persistence budget. Derived rows
    // still use the stricter row cap through Serialize; none of these limits is a parser verdict.
    internal static string CanonicalJson(JsonElement value, CancellationToken token = default,
        int maximumBytes = MaximumViewJsonBytes)
    {
        token.ThrowIfCancellationRequested();
        var writer = new CanonicalWriter(token, maximumBytes);
        writer.Write(value);
        token.ThrowIfCancellationRequested();
        return writer.ToString();
    }

    internal static void ValidateViewLimits(int rowCount, long jsonBytes)
    {
        if (rowCount > MaximumRows)
            throw new InvalidDataException("Inventory derived view exceeds row count limit");
        if (jsonBytes > MaximumViewJsonBytes)
            throw new InvalidDataException("Inventory derived view exceeds JSON size limit");
    }

    private static Dictionary<string, object?> ItemFields(ItemDataRow row)
    {
        var fields = new Dictionary<string, object?>
        {
            ["name"] = row.Name, ["price"] = row.Price, ["sell_price"] = row.SellPrice,
            ["restrict"] = row.Restrict, ["open_used"] = row.OpenUsed, ["need_level"] = row.NeedLevel
        };
        if (row.ReviewedDetails is not { } details) return fields;
        fields["unknown_tail_1296_hex"] = details.UnknownTail1296Hex;
        fields["kind"] = details.Kind;
        fields["order"] = details.Order;
        fields["icon_id"] = details.IconId;
        fields["attributes"] = details.Attributes.Select(attribute => new Dictionary<string, object?>
        {
            ["kind"] = attribute.Kind, ["effect"] = attribute.Effect, ["value"] = attribute.Value
        });
        fields["flags2"] = details.Flags2;
        fields["is_pvp_time_over"] = details.IsPvpTimeOver;
        fields["shop_icon_id"] = details.ShopIconId;
        fields["material"] = details.Material;
        fields["level"] = details.Level;
        fields["fit_type"] = details.FitType;
        fields["special"] = details.Special;
        fields["spares"] = details.Spares;
        fields["size_l"] = details.SizeL;
        fields["size_w"] = details.SizeW;
        fields["size_h"] = details.SizeH;
        fields["item_w"] = details.ItemW;
        fields["item_h"] = details.ItemH;
        fields["available_time"] = details.AvailableTime;
        fields["limited_time"] = details.LimitedTime;
        fields["use_count"] = details.UseCount;
        fields["style_bank_set_sort_id"] = details.StyleBankSetSortId;
        fields["stackable"] = details.Stackable;
        if (details.SkillLink is { } skillLink) fields["skill_link"] = skillLink;
        return fields;
    }

    private static Dictionary<string, object?> SmithFields(SmithRecipe row)
    {
        var fields = new Dictionary<string, object?>
        {
            ["item_id"] = row.ItemId, ["design_id"] = row.DesignId, ["skill"] = row.Skill,
            ["tool_id"] = row.ToolId, ["output"] = row.Output,
            ["materials"] = row.Materials.Select(material => new Dictionary<string, object?>
            {
                ["item_id"] = material.ItemId, ["count"] = material.Count
            }),
            ["seconds"] = row.Seconds, ["skill_level"] = row.SkillLevel, ["suggest"] = row.Suggest,
            ["time_id"] = row.TimeId, ["limit_kind"] = row.LimitKind, ["mark_id"] = row.MarkId,
            ["limit_times"] = row.LimitTimes, ["order"] = row.Order
        };
        if (row.RecipeId is { } recipeId) fields["recipe_id"] = recipeId;
        if (row.CandidateRowKey is { } candidateKey) fields["candidate_row_key"] = candidateKey;
        if (row.ReadOnly is { } readOnly) fields["read_only"] = readOnly;
        return fields;
    }

    private static Dictionary<string, object?> StageFields(StageDataRow row) => new()
    {
        ["id"] = row.Id, ["name_id"] = row.NameId, ["model_id"] = row.ModelId,
        ["max_members"] = row.MaxMembers, ["min_members"] = row.MinMembers, ["min_level"] = row.MinLevel,
        ["time_minutes"] = row.TimeMinutes, ["tag"] = row.Tag, ["room_capacity"] = row.RoomCapacity,
        ["group"] = row.Group, ["flag"] = row.Flag, ["pos_x_ratio"] = row.PosXRatio,
        ["pos_y_ratio"] = row.PosYRatio, ["map_width"] = row.MapWidth, ["map_height"] = row.MapHeight,
        ["small_offset_x"] = row.SmallOffsetX, ["small_offset_y"] = row.SmallOffsetY
    };

    private static KeyValuePair<string, object?> Row(string key, object? value) => new(key, value);
    private static string Number(IFormattable value) => value.ToString(null, CultureInfo.InvariantCulture);

    private static string Quote(string value, CancellationToken token, int maximumBytes = MaximumRowJsonBytes)
    {
        token.ThrowIfCancellationRequested();
        // Bound before the escaping allocation, including ensure_ascii expansion.
        if (value.Length > maximumBytes)
            throw new InvalidDataException("Inventory derived row exceeds JSON size limit");
        long length = 2;
        for (int index = 0; index < value.Length; index++)
        {
            if ((index & 1023) == 0) token.ThrowIfCancellationRequested();
            length += value[index] switch
            {
                '"' or '\\' or '\b' or '\f' or '\n' or '\r' or '\t' => 2,
                < ' ' or >= '\x7f' => 6,
                _ => 1
            };
            if (length > maximumBytes)
                throw new InvalidDataException("Inventory derived row exceeds JSON size limit");
        }
        string quoted = ResourceValidation.Quote(value);
        token.ThrowIfCancellationRequested();
        return quoted;
    }

    private static string Serialize(object? value, CancellationToken token)
    {
        var writer = new CanonicalWriter(token, MaximumRowJsonBytes);
        writer.Write(value);
        token.ThrowIfCancellationRequested();
        return writer.ToString();
    }

    // Every source field is integer, boolean, string, array or object. Do not serialize CLR model
    // property names, absent nullable fields, floating-point conversions, or locale-specific text.
    private sealed class CanonicalWriter(CancellationToken token, int maximumBytes)
    {
        private readonly StringBuilder buffer = new();

        public override string ToString() => buffer.ToString();

        private void Append(string text)
        {
            token.ThrowIfCancellationRequested();
            if (text.Length > maximumBytes - buffer.Length)
                throw new InvalidDataException("Inventory derived row exceeds JSON size limit");
            buffer.Append(text);
        }

        internal void Write(object? value)
        {
            token.ThrowIfCancellationRequested();
            switch (value)
            {
                case null: Append("null"); break;
                case string text: Append(Quote(text, token, maximumBytes)); break;
                case bool flag: Append(flag ? "true" : "false"); break;
                case byte or sbyte or short or ushort or int or uint or long or ulong:
                    Append(Number((IFormattable)value)); break;
                case IReadOnlyDictionary<string, object?> fields:
                    WriteObject(fields); break;
                case JsonElement element: WriteElement(element); break;
                case IEnumerable items:
                    Append("[");
                    bool first = true;
                    foreach (object? item in items)
                    {
                        if (!first) Append(",");
                        first = false;
                        Write(item);
                    }
                    Append("]"); break;
                default: throw new InvalidDataException("Unsupported inventory derived-row value");
            }
        }

        private void WriteObject(IEnumerable<KeyValuePair<string, object?>> fields)
        {
            Append("{");
            bool first = true;
            foreach (var field in fields.OrderBy(pair => pair.Key, PythonStringOrder))
            {
                if (!first) Append(",");
                first = false;
                Append(Quote(field.Key, token, maximumBytes)); Append(":"); Write(field.Value);
            }
            Append("}");
        }

        private void WriteElement(JsonElement value)
        {
            switch (value.ValueKind)
            {
                case JsonValueKind.Object:
                    WriteObject(value.EnumerateObject().Select(property => Row(property.Name, property.Value))); break;
                case JsonValueKind.Array:
                    Append("[");
                    bool first = true;
                    foreach (var item in value.EnumerateArray())
                    {
                        if (!first) Append(",");
                        first = false;
                        Write(item);
                    }
                    Append("]"); break;
                case JsonValueKind.String: Append(Quote(value.GetString()!, token, maximumBytes)); break;
                case JsonValueKind.Number when value.TryGetInt64(out long number): Append(Number(number)); break;
                case JsonValueKind.Number when value.TryGetUInt64(out ulong unsignedNumber): Append(Number(unsignedNumber)); break;
                case JsonValueKind.True: Append("true"); break;
                case JsonValueKind.False: Append("false"); break;
                case JsonValueKind.Null: Append("null"); break;
                default: throw new InvalidDataException("Unsupported inventory derived-row JSON value");
            }
        }
    }

    // Python sorts Unicode scalar values, whereas .NET Ordinal sorts UTF-16 code units.
    // Source field names are ASCII, but the shared report helper also handles Unicode keys.
    private static int CompareCodePoints(string? left, string? right)
    {
        if (ReferenceEquals(left, right)) return 0;
        if (left is null) return -1;
        if (right is null) return 1;
        int a = 0, b = 0;
        while (a < left.Length && b < right.Length)
        {
            int comparison = Next(left, ref a).CompareTo(Next(right, ref b));
            if (comparison != 0) return comparison;
        }
        return (left.Length - a).CompareTo(right.Length - b);

        static int Next(string text, ref int index)
        {
            char first = text[index++];
            return char.IsHighSurrogate(first) && index < text.Length && char.IsLowSurrogate(text[index])
                ? char.ConvertToUtf32(first, text[index++]) : first;
        }
    }
}
