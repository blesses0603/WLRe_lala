using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Lala.Desktop;

/// <summary>Detached editor for the existing Python preference shape. Validation here is
/// structural only; it neither verifies an item/skill catalog nor starts an automation.</summary>
public sealed class BattleSettingsDraft
{
    public JsonObject Value { get; }
    public BattleSettingsDraft() => Value = Defaults();
    private BattleSettingsDraft(JsonObject value) => Value = value;
    public BattleSettingsDraft Copy() => new((JsonObject)Value.DeepClone());
    public string ToJson()
    {
        Validate(Value);
        return Value.ToJsonString(DesktopPreferencesStore.JsonOptions);
    }
    public static BattleSettingsDraft Parse(string text)
    {
        if (Encoding.UTF8.GetByteCount(text) > DesktopPreferencesStore.MaximumBytes)
            throw new InvalidDataException("設定檔超過 128 KiB，未載入。");
        using var document = JsonDocument.Parse(text.TrimStart('\ufeff'), new JsonDocumentOptions { MaxDepth = 20 });
        CheckDuplicates(document.RootElement);
        var incoming = JsonNode.Parse(document.RootElement.GetRawText()) as JsonObject
            ?? throw new InvalidDataException("AI 設定必須為 JSON 物件。");
        var result = Defaults();
        Merge(result, incoming);
        // Legacy JSON without recovery derives both actors' percentages from the old fields.
        if (!incoming.ContainsKey("recovery"))
            foreach (var resource in new[] { "hp", "sp" })
                foreach (var who in new[] { "player", "partner" })
                    result["recovery"]![resource]![who + "_percent"] = result["field_" + resource + "_percent"]!.DeepClone();
        Validate(result);
        return new(result);
    }

    public static int Int(JsonNode? node) => node is JsonValue value && value.TryGetValue<int>(out var number)
        ? number : throw new InvalidDataException("設定欄位必須為整數。");
    public static bool Bool(JsonNode? node) => node is JsonValue value && value.TryGetValue<bool>(out var flag)
        ? flag : throw new InvalidDataException("設定開關必須為布林值。");
    public static decimal Number(JsonNode? node) => node is JsonValue && decimal.TryParse(node.ToJsonString(),
        NumberStyles.Float, CultureInfo.InvariantCulture, out var number) ? number : throw new InvalidDataException("設定數值無效。");
    public static JsonObject Profile(JsonObject value, string who) => (JsonObject)value["profiles"]![who]!;

    public static readonly (string Key, string Flag, string Title, int Count)[] Groups =
    [
        ("orderAction", "bOrderAction", "順序行動", 2), ("repeatAction", "bRepeatAction", "循環行動", 5),
        ("roundAction", "bRoundAction", "指定回合", 3), ("lowHpAction", "bLowHpAction", "低HP條件", 1),
        ("lowSpAction", "bLowSpAction", "低SP條件", 1), ("enemyHpAction", "bEnemyHPAction", "敵HP條件", 1),
        ("deadAction", "bDeadAction", "同方陣亡", 1)
    ];
    public static JsonObject Action(int id = 0, int kind = 1) => new() { ["id"] = id, ["kind"] = kind, ["target"] = 1, ["bUseNextSkill"] = false };
    private static JsonArray Actions(int count) => new(Enumerable.Range(0, count).Select(_ => (JsonNode)Action()).ToArray());
    private static JsonArray Slots(int count) => new(Enumerable.Range(0, count).Select(_ => (JsonNode)JsonValue.Create(0)!).ToArray());
    private static JsonObject DefaultProfile(bool partner)
    {
        var lowHp = Action(-2, 2); lowHp["notice"] = partner ? 3 : 2; lowHp["value"] = 100;
        var lowSp = Action(60021); lowSp["notice"] = partner ? 3 : 2; lowSp["value"] = 20;
        var enemy = Action(10008); enemy["compareKind"] = 2; enemy["value"] = 100;
        return new()
        {
            ["bDeadAction"] = false, ["deadAction"] = Action(60021), ["bEnemyHPAction"] = false, ["enemyHpAction"] = enemy,
            ["bLowHpAction"] = true, ["lowHpAction"] = lowHp, ["bLowSpAction"] = false, ["lowSpAction"] = lowSp,
            ["bRoundAction"] = false, ["roundAction"] = Actions(3), ["bRepeatAction"] = false, ["repeatAction"] = Actions(5),
            ["bOrderAction"] = true, ["orderAction"] = new JsonArray(Action(10001), Action())
        };
    }
    private static JsonObject Recovery(int percent) => new()
    {
        ["enabled"] = true, ["items"] = Slots(10), ["storage"] = "off", ["other_items"] = true,
        ["player_percent"] = percent, ["partner_percent"] = percent
    };
    private static JsonObject Defaults() => new()
    {
        ["bPlayerDieCloseAI"] = false, ["bNPCDieCloseAI"] = false, ["field_heal"] = false,
        ["field_hp_percent"] = 60, ["field_sp_percent"] = 30,
        ["profiles"] = new JsonObject { ["player"] = DefaultProfile(false), ["partner"] = DefaultProfile(true) },
        ["recovery"] = new JsonObject { ["hp"] = Recovery(60), ["sp"] = Recovery(30) },
        ["party_guard"] = new JsonObject { ["enabled"] = false, ["members"] = new JsonArray() },
        ["maintenance"] = new JsonObject { ["repair_enabled"] = false, ["repair_below"] = 50,
            ["repair_items"] = Slots(2), ["cleanup_enabled"] = false, ["cleanup_items"] = Slots(15) }
    };

    private static void Merge(JsonObject target, JsonObject input)
    {
        foreach (var pair in input)
        {
            if (!target.ContainsKey(pair.Key)) throw new InvalidDataException("設定含未支援欄位。");
            if (target[pair.Key] is JsonObject nested)
            {
                if (pair.Value is not JsonObject values) throw new InvalidDataException("設定區段必須為物件。");
                Merge(nested, values);
            }
            else if (pair.Key is "orderAction" or "repeatAction" or "roundAction")
            {
                if (pair.Value is not JsonArray source || target[pair.Key] is not JsonArray rows || source.Count > rows.Count)
                    throw new InvalidDataException("AI 行動數量錯誤。");
                var prototype = (JsonObject)rows[0]!.DeepClone();
                for (var i = 0; i < source.Count; i++)
                {
                    if (source[i] is not JsonObject action) throw new InvalidDataException("AI 行動格式錯誤。");
                    var candidate = (JsonObject)prototype.DeepClone();
                    Merge(candidate, action);
                    rows[i] = candidate;
                }
                // Python fills omitted array slots with skip, not with the first default action.
                for (var i = source.Count; i < rows.Count; i++) rows[i] = Action();
            }
            else target[pair.Key] = pair.Value?.DeepClone();
        }
    }

    private static void Validate(JsonObject value)
    {
        CheckShape(value, Defaults());
        foreach (var flag in new[] { "bPlayerDieCloseAI", "bNPCDieCloseAI", "field_heal" }) Bool(value[flag]);
        foreach (var key in new[] { "field_hp_percent", "field_sp_percent" }) InRange(value[key], 0, 100);
        foreach (var who in new[] { "player", "partner" })
        {
            var profile = Profile(value, who);
            foreach (var (key, flag, _, count) in Groups)
            {
                Bool(profile[flag]);
                var rows = count == 1 ? new[] { profile[key] } :
                    profile[key] is JsonArray array && array.Count == count ? array.ToArray() : throw new InvalidDataException("AI 行動數量錯誤。");
                foreach (var row in rows)
                {
                    if (row is not JsonObject action) throw new InvalidDataException("AI 行動格式錯誤。");
                    InRange(action["id"], -3, 65535); InRange(action["kind"], 1, 2); InRange(action["target"], 1, 3);
                    if (Int(action["id"]) is -2 or -3) action["kind"] = 2;
                    if (Bool(action["bUseNextSkill"]) && Int(action["kind"]) == 2) throw new InvalidDataException("道具沒有次階特技。");
                    if (action.ContainsKey("notice")) InRange(action["notice"], 1, 3);
                    if (action.ContainsKey("compareKind")) InRange(action["compareKind"], 1, 2);
                    if (action.ContainsKey("value") && Number(action["value"]) < 0) throw new InvalidDataException("HP／SP 門檻不可為負數。");
                }
            }
        }
        foreach (var resource in new[] { "hp", "sp" })
        {
            var config = value["recovery"]![resource]!;
            Bool(config["enabled"]); Bool(config["other_items"]);
            if (config["storage"]?.GetValue<string>() is not ("off" or "first" or "after")) throw new InvalidDataException("儲存槽順序無效。");
            InRange(config["player_percent"], 0, 100); InRange(config["partner_percent"], 0, 100); ValidateSlots(config["items"], 10);
        }
        var maintenance = value["maintenance"]!;
        Bool(maintenance["repair_enabled"]); Bool(maintenance["cleanup_enabled"]); InRange(maintenance["repair_below"], 0, 249);
        ValidateSlots(maintenance["repair_items"], 2); ValidateSlots(maintenance["cleanup_items"], 15);
        var party = value["party_guard"]!;
        bool enabled = Bool(party["enabled"]);
        if (party["members"] is not JsonArray members || members.Count > 4 || enabled && members.Count == 0)
            throw new InvalidDataException("必要隊員設定無效。");
        var seen = new HashSet<decimal>();
        foreach (var member in members)
        {
            if (member is not JsonObject record || record.Any(p => p.Key is not ("role_id" or "name"))) throw new InvalidDataException("必要隊員資料無效。");
            decimal id = Number(record["role_id"]);
            if (id is <= 0 or > uint.MaxValue || id != decimal.Truncate(id) || !seen.Add(id)) throw new InvalidDataException("必要隊員 ID 無效或重複。");
            var name = record["name"]?.GetValue<string>() ?? "";
            if (name.Length > 128 || name.Any(char.IsControl)) throw new InvalidDataException("必要隊員名稱無效。");
        }
    }
    private static void InRange(JsonNode? node, int low, int high)
    {
        int value = Int(node);
        if (value < low || value > high) throw new InvalidDataException("設定數值超出允許範圍。");
    }
    private static void ValidateSlots(JsonNode? value, int count)
    {
        if (value is not JsonArray array || array.Count != count) throw new InvalidDataException("補給／整理格數錯誤。");
        foreach (var id in array) InRange(id, 0, 65535);
    }
    private static void CheckShape(JsonNode? value, JsonNode expected)
    {
        if (expected is JsonObject fields)
        {
            if (value is not JsonObject supplied || supplied.Count != fields.Count || supplied.Any(pair => !fields.ContainsKey(pair.Key)))
                throw new InvalidDataException("設定欄位缺漏或含未支援欄位。");
            foreach (var pair in fields) CheckShape(supplied[pair.Key], pair.Value!);
        }
        else if (expected is JsonArray array)
        {
            if (value is not JsonArray supplied) throw new InvalidDataException("設定清單格式錯誤。");
            // The variable-length party member list is validated separately below.
            if (array.Count == 0) return;
            if (supplied.Count != array.Count) throw new InvalidDataException("設定清單格數錯誤。");
            for (var i = 0; i < array.Count; i++) CheckShape(supplied[i], array[i]!);
        }
        else if (value is not JsonValue) throw new InvalidDataException("設定值不可為空或複合物件。");
    }
    internal static void CheckDuplicates(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var keys = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in element.EnumerateObject())
            {
                if (!keys.Add(property.Name)) throw new InvalidDataException("JSON 含重複欄位，未載入。");
                CheckDuplicates(property.Value);
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
            foreach (var child in element.EnumerateArray()) CheckDuplicates(child);
    }
}
