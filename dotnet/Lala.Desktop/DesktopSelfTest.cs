using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.State;

namespace Lala.Desktop;

/// <summary>Deterministic presentation-boundary tests. No UI platform, network, or real user data.</summary>
internal static class DesktopSelfTest
{
    public static void Run()
    {
        var directory = Path.Combine(Path.GetTempPath(), "lala-desktop-selftest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var suite = new Checks();
        try
        {
            TestSession(suite, directory);
            TestImageReader(suite);
            TestDraft(suite);
            TestPreferences(suite, directory);
            Console.WriteLine($"Desktop presentation self-test: {suite.Count} checks passed. Offline only; no UI/native or server acceptance.");
        }
        finally { Directory.Delete(directory, true); }
    }

    private static void TestImageReader(Checks check)
    {
        using var images = new DesktopSession(); long generation = images.Generation;
        images.SetItemImageReader(generation, _ => new byte[] { 1 });
        check.True(images.ReadItemImage(1) is { Length: 1 }, "image reader available only in its presentation generation");
        images.Reset();
        check.True(images.ReadItemImage(1) is null, "account reset removes image provider");
        images.SetItemImageReader(generation, _ => new byte[] { 2 });
        check.True(images.ReadItemImage(1) is null, "stale image provider cannot attach to replacement account");
        images.SetItemImageReader(images.Generation, _ => { images.Reset(); return new byte[] { 3 }; });
        check.True(images.ReadItemImage(1) is null, "generation change during image copy discards the result");
        int changed = 0; images.Changed += () => changed++;
        images.Dispose();
        check.True(changed == 1 && images.ReadItemImage(1) is null, "disposal notifies views to clear image buffers");
    }

    private static void TestSession(Checks check, string directory)
    {
        using var session = new DesktopSession(new DesktopPreferencesStore(Path.Combine(directory, "session")));
        var (fixture, labels) = DesktopTestData.Create();
        var generation = session.Generation;
        int notifications = 0;
        session.Changed += () => notifications++;
        check.True(session.Snapshot.Player is null && !session.CanSendGameCommands, "fresh session is empty and cannot send");
        check.True(session.Publish(generation, 10, fixture, labels), "current generation publication accepted");
        check.True(ReferenceEquals(session.Snapshot, fixture) && ReferenceEquals(session.Labels, labels) && notifications == 1,
            "publication preserves immutable snapshot and matching labels");
        var view = session.ReadView();
        check.True(view.Generation == generation && view.Sequence == 10 && view.IdentityKey == session.IdentityKey &&
            ReferenceEquals(view.Snapshot, fixture) && ReferenceEquals(view.Labels, labels), "atomic view carries one generation, sequence, identity, snapshot and label set");
        check.True(!session.Publish(generation, 10, new()) && !session.Publish(generation, 9, new()) && notifications == 1,
            "duplicate and out-of-order publications rejected without notification");
        check.True(!session.CanSendGameCommands && session.ConnectionText == "尚未連線",
            "world-ready observation does not grant transport authority");
        check.NoThrow(() => session.RequireCurrentDraft(generation), "current settings draft accepted");
        session.Reset("介面測試帳號乙");
        check.True(session.Generation > generation && session.Snapshot.Player is null && session.Labels.Items.Count == 0,
            "reset clears state and display labels");
        check.True(!session.Publish(generation, long.MaxValue, fixture, labels), "old generation cannot overwrite reset state");
        check.Reject<InvalidOperationException>(() => session.RequireCurrentDraft(generation), "old settings draft rejected");
        check.Reject<InvalidOperationException>(() => session.SaveBattle(generation, session.IdentityKey, new()),
            "stale battle save rejected");
        check.Reject<InvalidOperationException>(() => session.SaveExpedition(generation, session.IdentityKey, new()),
            "stale expedition save rejected");
        check.Reject<InvalidOperationException>(() => session.SaveBattle(session.Generation, "介面測試另一帳號", new()),
            "battle save checks identity as well as generation");
        check.Reject<InvalidOperationException>(() => session.SaveExpedition(session.Generation, "介面測試另一帳號", new()),
            "expedition save checks identity as well as generation");
        check.True(session.Publish(session.Generation, 0, fixture, labels), "new generation restarts publication sequence");
        var before = session.Snapshot;
        var draft = new BattleSettingsDraft();
        draft.Value["field_heal"] = true;
        session.SaveBattle(session.Generation, session.IdentityKey, draft);
        session.SaveExpedition(session.Generation, session.IdentityKey, new(2.5m, 85, 90, true));
        check.True(ReferenceEquals(before, session.Snapshot) && !session.CanSendGameCommands && !session.Snapshot.Expedition.Enabled,
            "saving UI settings never mutates Core or starts services");
        check.True(session.Preferences.ReadExpedition(session.IdentityKey).MinHours == 2.5m,
            "atomic session save persists current identity preferences");
        generation = session.Generation;
        session.Dispose();
        check.True(!session.Publish(generation, long.MaxValue, fixture) && session.Snapshot.Player is null,
            "disposed session rejects publications and drops state");
        check.Reject<ObjectDisposedException>(() => session.Reset(), "disposed session cannot reset");
        check.Reject<ObjectDisposedException>(() => session.SaveExpedition(session.Generation, session.IdentityKey, new()),
            "disposed session cannot save a draft");
    }

    private static void TestDraft(Checks check)
    {
        var original = new BattleSettingsDraft();
        var copy = original.Copy();
        copy.Value["profiles"]!["player"]!["orderAction"]![0]!["id"] = 60021;
        copy.Value["recovery"]!["hp"]!["items"]![0] = 1001;
        check.True(BattleSettingsDraft.Int(original.Value["profiles"]!["player"]!["orderAction"]![0]!["id"]) == 10001 &&
            BattleSettingsDraft.Int(original.Value["recovery"]!["hp"]!["items"]![0]) == 0, "draft copy owns nested objects and slot arrays");
        check.True(BattleSettingsDraft.Parse(copy.ToJson()).ToJson() == copy.ToJson(), "draft JSON round-trip preserves unsaved choices");
        var legacy = BattleSettingsDraft.Parse("\ufeff{\"field_hp_percent\":44,\"profiles\":{\"player\":{\"orderAction\":[{\"id\":60021,\"kind\":1,\"target\":2}]}}}");
        check.True(BattleSettingsDraft.Int(legacy.Value["recovery"]!["hp"]!["partner_percent"]) == 44 &&
            BattleSettingsDraft.Int(legacy.Value["profiles"]!["player"]!["orderAction"]![1]!["id"]) == 0,
            "legacy import derives supply threshold and fills omitted action slots with skip");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"password\":\"介面測試非真密碼\"}"),
            "import refuses credential or unknown fields");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"profiles\":null}"), "null rule section rejected");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"field_hp_percent\":101}"), "out-of-range supply threshold rejected");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"profiles\":{\"player\":{\"orderAction\":[{\"target\":4}]}}}"),
            "unknown action target rejected");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"profiles\":{\"player\":{\"orderAction\":[{\"id\":65536}]}}}"),
            "out-of-range action ID rejected");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"profiles\":{\"player\":{\"orderAction\":[{\"kind\":2,\"bUseNextSkill\":true}]}}}"),
            "items cannot carry next-tier skill flag");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"recovery\":{\"hp\":{\"items\":[0,0]}}}"),
            "supply slot shape cannot be truncated");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"field_heal\":false,\"field_heal\":true}"),
            "duplicate top-level JSON keys rejected");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse("{\"profiles\":{\"player\":{\"orderAction\":[{\"id\":0,\"id\":60021}]}}}"),
            "duplicate nested action keys rejected");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse(new string(' ', DesktopPreferencesStore.MaximumBytes) + "{}"),
            "oversized JSON rejected before parsing");
        check.Reject<InvalidDataException>(() => BattleSettingsDraft.Parse(new string('測', DesktopPreferencesStore.MaximumBytes / 3 + 1)),
            "JSON size bound counts UTF-8 bytes");
        var injected = new BattleSettingsDraft();
        injected.Value["password"] = "介面測試非真密碼";
        check.Reject<InvalidDataException>(() => injected.ToJson(), "directly edited draft cannot export unknown credential fields");
        injected = new BattleSettingsDraft();
        injected.Value["profiles"]!["player"]!["orderAction"]![0]!["endpoint"] = "介面測試非連線位置";
        check.Reject<InvalidDataException>(() => injected.ToJson(), "directly edited action cannot export unknown fields");
        injected = new BattleSettingsDraft();
        ((JsonObject)injected.Value["maintenance"]!).Remove("repair_items");
        check.Reject<InvalidDataException>(() => injected.ToJson(), "directly edited draft cannot omit required sections");
        using var malformed = new MemoryStream([0xc3, 0x28]);
        check.Reject<DecoderFallbackException>(() => DesktopPreferencesStore.ReadBounded(malformed), "malformed UTF-8 settings rejected");
        using var oversized = new MemoryStream(new byte[DesktopPreferencesStore.MaximumBytes + 1]);
        check.Reject<InvalidDataException>(() => DesktopPreferencesStore.ReadBounded(oversized), "stream reader has a hard capacity bound");
        using var bom = new MemoryStream(Encoding.UTF8.GetBytes("\ufeff{}"));
        check.True(DesktopPreferencesStore.ReadBounded(bom) == "{}", "stream reader accepts UTF-8 BOM");
    }

    private static void TestPreferences(Checks check, string root)
    {
        var directory = Path.Combine(root, "preferences");
        var store = new DesktopPreferencesStore(directory);
        check.True(store.ReadExpedition("介面測試帳號甲") == new ExpeditionPreferences() && !Directory.Exists(directory),
            "missing preferences read defaults without creating files");
        var first = new BattleSettingsDraft();
        first.Value["field_hp_percent"] = 42;
        var second = new BattleSettingsDraft();
        second.Value["field_hp_percent"] = 71;
        store.WriteBattle("介面測試帳號甲", first);
        store.WriteBattle("../介面測試帳號乙", second);
        check.True(BattleSettingsDraft.Int(store.ReadBattle("介面測試帳號甲").Value["field_hp_percent"]) == 42 &&
            BattleSettingsDraft.Int(store.ReadBattle("../介面測試帳號乙").Value["field_hp_percent"]) == 71,
            "battle preferences remain isolated per identity");
        store.WriteExpedition("介面測試帳號甲", new(4.5m, 88, 95, false, 1001));
        store.WriteExpedition("../介面測試帳號乙", new(0, 80, 75, true));
        check.True(store.ReadExpedition("介面測試帳號甲") == new ExpeditionPreferences(4.5m, 88, 95, false, 1001) &&
            store.ReadExpedition("../介面測試帳號乙").RestoreItemId is null, "expedition preferences preserve type and identity isolation");
        var files = Directory.GetFiles(directory);
        check.True(files.Length == 4 && files.All(path => Path.GetDirectoryName(path) == directory &&
            !Path.GetFileName(path).Contains("介面測試", StringComparison.Ordinal)) && Directory.GetFiles(directory, "*.tmp").Length == 0,
            "identity paths are hashed and successful atomic writes leave no temporary files");
        check.True(files.All(path => !File.ReadAllText(path).Contains("password", StringComparison.OrdinalIgnoreCase) &&
            !File.ReadAllText(path).Contains("credential", StringComparison.OrdinalIgnoreCase) &&
            !File.ReadAllText(path).Contains("介面測試帳號", StringComparison.Ordinal)), "saved preferences contain no account identity or credentials");
        var changed = store.ReadBattle("介面測試帳號甲");
        changed.Value["field_hp_percent"] = 99;
        check.True(BattleSettingsDraft.Int(store.ReadBattle("介面測試帳號甲").Value["field_hp_percent"]) == 42,
            "editing loaded draft does not persist until save");
        changed.Value["field_hp_percent"] = 101;
        check.Reject<InvalidDataException>(() => store.WriteBattle("介面測試帳號甲", changed), "invalid battle save rejected before overwrite");
        check.True(BattleSettingsDraft.Int(store.ReadBattle("介面測試帳號甲").Value["field_hp_percent"]) == 42,
            "failed save preserves existing valid preferences");
        check.Reject<InvalidDataException>(() => store.WriteExpedition("介面測試帳號甲", new(-1)), "negative expedition time rejected");
        check.Reject<InvalidDataException>(() => store.WriteExpedition("介面測試帳號甲", new(MinFaith: 101)), "invalid expedition faith rejected");
        check.Reject<InvalidDataException>(() => store.WriteExpedition("介面測試帳號甲", new(MinSuccess: 101)), "invalid expedition success threshold rejected");
        check.Reject<InvalidDataException>(() => store.WriteExpedition("介面測試帳號甲", new(RestoreItemId: 0)), "zero restoration item ID rejected");

        var malformedDirectory = Path.Combine(root, "malformed");
        var malformedStore = new DesktopPreferencesStore(malformedDirectory);
        malformedStore.WriteExpedition("介面測試", new());
        var path = Directory.GetFiles(malformedDirectory).Single();
        File.WriteAllText(path, "{\"MinHours\":0,\"MinHours\":1}");
        check.Reject<InvalidDataException>(() => malformedStore.ReadExpedition("介面測試"), "duplicate expedition JSON keys rejected");
        File.WriteAllText(path, "{\"Password\":\"介面測試非真密碼\"}");
        check.Reject<JsonException>(() => malformedStore.ReadExpedition("介面測試"), "expedition JSON refuses credential fields");
    }

    private sealed class Checks
    {
        public int Count { get; private set; }
        public void True(bool condition, string name)
        {
            if (!condition) throw new InvalidOperationException("Desktop self-test failed: " + name);
            Count++;
        }
        public void NoThrow(Action action, string name)
        {
            try { action(); }
            catch (Exception error) { throw new InvalidOperationException("Desktop self-test failed: " + name, error); }
            Count++;
        }
        public void Reject<T>(Action action, string name) where T : Exception
        {
            try { action(); }
            catch (T) { Count++; return; }
            catch (Exception error) { throw new InvalidOperationException("Desktop self-test failed: " + name + " (wrong exception)", error); }
            throw new InvalidOperationException("Desktop self-test failed: " + name + $" (expected {typeof(T).Name})");
        }
    }
}
