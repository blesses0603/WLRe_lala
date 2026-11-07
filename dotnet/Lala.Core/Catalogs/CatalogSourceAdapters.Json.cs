using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;
using Lala.Core.World.Eve;

namespace Lala.Core.Catalogs;

public static partial class CatalogSourceAdapters
{
    public const int MaxJsonDepth = 64;
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    private static EveIndexSourceRecords JsonScenes(ReadOnlySpan<byte> raw, bool npcs, CancellationToken token)
    {
        using var document = ReadJson(raw, token);
        var doc = document.RootElement;
        string source = npcs ? EveV115Parser.NpcSource : EveV115Parser.InteractionSource;
        var scenes = Property(doc, "scenes");
        if (doc.ValueKind != JsonValueKind.Object || !EqualsOne(Property(doc, "schema_version")) ||
            Property(doc, "source").ValueKind != JsonValueKind.String || Property(doc, "source").GetString() != source ||
            scenes.ValueKind != JsonValueKind.Object || !Integer(Property(doc, "record_count"), out var declared))
            throw new CatalogAdapterException("Derived index schema/source mismatch");
        var result = new Dictionary<string, ImmutableArray<JsonElement>>(StringComparer.Ordinal);
        var order = new List<string>();
        int total = 0;
        foreach (var (key, rows) in UniqueProperties(scenes))
        {
            token.ThrowIfCancellationRequested();
            // Python isdecimal plus str(int(key)) == key permits only canonical ASCII forms.
            if (!ushort.TryParse(key, NumberStyles.None, CultureInfo.InvariantCulture, out ushort scene) ||
                scene.ToString(CultureInfo.InvariantCulture) != key || rows.ValueKind != JsonValueKind.Array ||
                rows.GetArrayLength() > 4096)
                throw new CatalogAdapterException("Invalid scene ID or list");
            var parsed = ImmutableArray.CreateBuilder<JsonElement>(rows.GetArrayLength());
            var indices = new HashSet<BigInteger>();
            foreach (var row in rows.EnumerateArray())
            {
                token.ThrowIfCancellationRequested();
                bool fields = Integer(Property(row, "index"), out var index);
                if (npcs)
                    fields &= Integer(Property(row, "npc_id"), out _) && Integer(Property(row, "x"), out _) && Integer(Property(row, "y"), out _);
                else fields &= Integer(Property(row, "form_kind"), out _);
                if (row.ValueKind != JsonValueKind.Object || !fields || index < 0 || index > 65535 || !indices.Add(index))
                    throw new CatalogAdapterException("Invalid/duplicate event index");
                if (npcs)
                {
                    if (!Range(row, "npc_id", 1, uint.MaxValue) || !Range(row, "x", 0, uint.MaxValue) || !Range(row, "y", 0, uint.MaxValue))
                        throw new CatalogAdapterException("Invalid NPC source field");
                }
                else
                {
                    var items = Property(row, "items");
                    if (!Range(row, "form_kind", 1, 3) || items.ValueKind != JsonValueKind.Array || items.GetArrayLength() > 255)
                        throw new CatalogAdapterException("Invalid shop interaction type");
                    foreach (var item in items.EnumerateArray())
                    {
                        token.ThrowIfCancellationRequested();
                        if (item.ValueKind != JsonValueKind.Object || !Range(item, "id", 0, 255) ||
                            !Range(item, "text_id", 0, 65535) || !Range(item, "database_kind", 0, 255) || !Range(item, "kind", 0, 255))
                            throw new CatalogAdapterException("Invalid interaction item");
                    }
                }
                parsed.Add(row.Clone()); // Already normalized; rows outlive the disposed document.
            }
            result.Add(key, parsed.MoveToImmutable()); order.Add(key);
            total += rows.GetArrayLength();
            if (total > MaxRows) throw new CatalogAdapterException("Index exceeds maximum record count");
        }
        if (total != declared) throw new CatalogAdapterException("Index record count mismatch");
        token.ThrowIfCancellationRequested();
        return new(new OrderedCatalog<string, ImmutableArray<JsonElement>>(result, order), total);
    }

    private static JsonDocument ReadJson(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        try
        {
            token.ThrowIfCancellationRequested();
            StrictUtf8.GetCharCount(raw);
            using var source = JsonDocument.Parse(raw.ToArray(), new JsonDocumentOptions { MaxDepth = MaxJsonDepth });
            ValidateJson(source.RootElement, token);
            // Python keeps the last duplicate value in the first occurrence's position. Normalize
            // recursively before taking owned row snapshots, including all unknown extra fields.
            using var stream = new MemoryStream();
            using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { MaxDepth = MaxJsonDepth }))
                Normalize(source.RootElement, writer, token);
            token.ThrowIfCancellationRequested();
            return JsonDocument.Parse(stream.ToArray(), new JsonDocumentOptions { MaxDepth = MaxJsonDepth });
        }
        catch (JsonException) { throw new CatalogAdapterException("Invalid UTF-8/JSON index"); }
        catch (DecoderFallbackException) { throw new CatalogAdapterException("Invalid UTF-8/JSON index"); }
        catch (InvalidOperationException) { throw new CatalogAdapterException("Invalid UTF-8/JSON index"); }
    }

    private static void ValidateJson(JsonElement value, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (value.ValueKind == JsonValueKind.Object)
            foreach (var property in value.EnumerateObject())
            {
                _ = property.Name; ValidateJson(property.Value, token);
            }
        else if (value.ValueKind == JsonValueKind.Array)
            foreach (var item in value.EnumerateArray()) ValidateJson(item, token);
        else if (value.ValueKind == JsonValueKind.String) _ = value.GetString();
        else if (value.ValueKind == JsonValueKind.Number)
        {
            string number = value.GetRawText();
            if (IsIntegerText(number) && number.TrimStart('-').Length > 4300 ||
                !IsIntegerText(number) && !double.IsFinite(value.GetDouble()))
                throw new CatalogAdapterException("Invalid UTF-8/JSON index");
        }
    }

    private static void Normalize(JsonElement value, Utf8JsonWriter writer, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                writer.WriteStartObject();
                foreach (var (key, item) in UniqueProperties(value))
                {
                    token.ThrowIfCancellationRequested();
                    writer.WritePropertyName(key); Normalize(item, writer, token);
                }
                writer.WriteEndObject(); break;
            case JsonValueKind.Array:
                writer.WriteStartArray();
                foreach (var item in value.EnumerateArray()) Normalize(item, writer, token);
                writer.WriteEndArray(); break;
            case JsonValueKind.String: writer.WriteStringValue(value.GetString()); break;
            case JsonValueKind.Number:
                string number = value.GetRawText();
                // Python's normal JSON decoder rejects integer literals over 4,300 decimal digits.
                if (IsIntegerText(number) && number.TrimStart('-').Length > 4300 ||
                    !IsIntegerText(number) && !double.IsFinite(value.GetDouble()))
                    throw new CatalogAdapterException("Invalid UTF-8/JSON index");
                writer.WriteRawValue(number); break;
            default: value.WriteTo(writer); break;
        }
    }

    private static IEnumerable<KeyValuePair<string, JsonElement>> UniqueProperties(JsonElement value)
    {
        var rows = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
        var order = new List<string>();
        foreach (var property in value.EnumerateObject())
        {
            if (!rows.ContainsKey(property.Name)) order.Add(property.Name);
            rows[property.Name] = property.Value;
        }
        foreach (string key in order) yield return KeyValuePair.Create(key, rows[key]);
    }
    private static JsonElement Property(JsonElement value, string name) =>
        value.ValueKind == JsonValueKind.Object && value.TryGetProperty(name, out var item) ? item : default;
    private static bool IsIntegerText(string value) => value.IndexOfAny(['.', 'e', 'E']) < 0;
    private static bool Integer(JsonElement value, out BigInteger result)
    {
        result = default;
        if (value.ValueKind != JsonValueKind.Number) return false;
        string text = value.GetRawText();
        return IsIntegerText(text) && BigInteger.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out result);
    }
    private static bool Range(JsonElement row, string name, long min, long max) =>
        Integer(Property(row, name), out var value) && value >= min && value <= max;
    private static bool EqualsOne(JsonElement value) => value.ValueKind == JsonValueKind.True ||
        value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number) && number == 1;
}
