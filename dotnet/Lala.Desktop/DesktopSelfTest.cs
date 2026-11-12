using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.State;
using Lala.Core.Catalogs;

using System.Collections.Immutable;

namespace Lala.Desktop;

/// <summary>Deterministic presentation-boundary tests. No UI platform, network, or real user data.</summary>
internal static partial class DesktopSelfTest
{
    public static void Run()
    {
        var directory = Path.Combine(Path.GetTempPath(), "lala-desktop-selftest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var suite = new Checks();
        try
        {
            var stages = new ResourceStageProgress();
            suite.True(stages.Value == 0, "preparation stage bar begins at zero");
            stages.Observe(new("取得並驗證必要資源（含快取）", 1, 4));
            double before = stages.Value;
            stages.Observe(new("取得並驗證必要資源（含快取）", 3, 4));
            suite.True(stages.Value > before && stages.Value < 100, "observed file counts advance the active stage without completing the whole pipeline");
            stages.Observe(new("寫入小地圖快取")); before = stages.Value;
            stages.Observe(new("查詢官方版本與下載清單"));
            suite.True(stages.Value == before, "repeated early observations never move the stage bar backwards");
            stages.Observe(new("資源取得或驗證失敗", IsFinished: true));
            suite.True(stages.Value == before && stages.Value < 100, "failed completion never fills the stage bar");
            stages.Observe(new("必要資源驗證完成", IsFinished: true));
            stages.Observe(new("重新核對登入清單"));
            suite.True(stages.Value < 100, "resource completion still reserves progress for final catalog admission");
            stages.Complete(); suite.True(stages.Value == 100, "successful host admission completes the stage bar");
            var cacheStages = new ResourceStageProgress();
            cacheStages.Observe(new("驗證既有小地圖快取", 0, 2)); double cacheBefore = cacheStages.Value;
            cacheStages.Observe(new("驗證既有小地圖快取", 1, 2));
            suite.True(cacheStages.Value > cacheBefore && cacheStages.Value < 100, "warm small-map validation counts advance the actual resource stage");
            cacheBefore = cacheStages.Value; cacheStages.Observe(new("建立小地圖快取", 2, 2));
            suite.True(cacheStages.Value > cacheBefore && cacheStages.Value < 100, "cold small-map rebuilding advances without claiming login admission");
            var resourceRoot = DesktopResourceDirectory.FromLocalApplicationData(directory);
            suite.True(resourceRoot == Path.Combine(directory, "LaLa", "Resources"), "resources use a fixed per-user application-data subdirectory");
            suite.True(!Directory.Exists(resourceRoot), "resource path resolution does not create files");
            foreach (var invalid in new[] { "", " ", "relative" })
            {
                bool rejected = false;
                try { DesktopResourceDirectory.FromLocalApplicationData(invalid); }
                catch (IOException) { rejected = true; }
                suite.True(rejected, "missing or relative app-data location never falls back to cwd");
            }
            TestSession(suite, directory);
            TestCharacterLog(suite);
            TestImageReader(suite);
            TestDraft(suite);
            suite.True(SettingsActions.TargetOptions(-3, 2, "lowSpAction").Labels.SequenceEqual(new[] { "最低SP", "座標順序", "最高SP" }), "SP item priorities");
            suite.True(SettingsActions.TargetOptions(-2, 2, "lowHpAction").Labels[0] == "最低HP", "HP item priorities");
            suite.True(!SettingsActions.TargetOptions(60021, 1, "lowSpAction").Enabled, "defense needs no target");
            suite.True(!SettingsActions.TargetOptions(60041, 1, "lowSpAction").Enabled, "escape needs no target");
            suite.True(SettingsActions.TargetOptions(10001, 1, "lowSpAction").Labels[2] == "最高HP", "enemy HP priority retained");
            suite.True(SettingsActions.TargetOptions(1001, 1, "lowSpAction").Labels[0].Contains("友方最低SP"), "unknown skill effect is not inferred");
            TestPreferences(suite, directory);
            TestFeaturePreferences(suite, directory);
            TestIndependentResourceRules(suite, directory);
            TestSkillEffects(suite);
            Console.WriteLine($"Desktop presentation self-test: {suite.Count} checks passed. Offline only; no UI/native or server acceptance.");
        }
        finally { Directory.Delete(directory, true); }
    }

    private static void TestCharacterLog(Checks check)
    {
        using var session=new DesktopSession();long generation=session.Generation;
        System.Collections.Immutable.ImmutableArray<Lala.Core.Gameplay.GameServerEvent> events=[
            new(1,26,4,"gold_snapshot","角色金幣",OwnerRoleId:17),
            new(2,22,2,"scene_npc_move","場景 NPC"),
            new(3,12,1,"position_snapshot","其他角色",Role:18,OwnerRoleId:18),
            new(4,90,1,"unimplemented","未確認歸屬")];
        session.SetServerEvents(generation,events,17);
        check.True(session.ServerEvents.Length==1&&session.ServerEvents[0].Sequence==1,"character log excludes NPCs, unknown ownership and other roles");
        session.SetServerEvents(generation,events,18);
        check.True(session.ServerEvents.Length==1&&session.ServerEvents[0].Sequence==3,"switching character replaces previous character history");
        session.SetServerEvents(generation,events,null);
        check.True(session.ServerEvents.IsEmpty,"no selected character means no character history");
        session.SetServerEvents(generation,events,17);session.Reset();
        session.SetServerEvents(generation,events,17);
        check.True(session.ServerEvents.IsEmpty,"account reset clears history and rejects delayed old publications");
        var controls=Enumerable.Range(1,80).Select(i=>new Lala.Core.Gameplay.GameServerEvent(i,20,10,"event_continue_permission","許可",OwnerRoleId:17))
            .Append(new(81,20,8,"event_end","結束",OwnerRoleId:17))
            .Append(new(82,20,74,"event_rejected","伺服器拒絕事件",OwnerRoleId:17)).ToImmutableArray();
        var summaries=CharacterEventSummary.Lines(controls);
        check.True(summaries.Length==2&&summaries[0].Contains("80 次接續通知")&&summaries[0].Contains("已結束"),"ordinary control receipts form one display summary");
        check.True(summaries[1].Contains("[接收 20-74]")&&summaries[1].Contains("拒絕"),"server rejection stays separately visible after summarized traffic");
    }

    private static void TestSkillEffects(Checks check)
    {
        var (state,labels) = DesktopTestData.Create();
        labels = labels with { SkillDetails = labels.SkillDetails.SetItem(2101,new(3,17,1,SkillRecoveryKind.Sp)) };
        var row = SkillPresentation.All(state,labels).First(row => row.Player && row.Id == 2101);
        check.True(row.RecoveryText == "恢復 SP（恢復量未知）" && row.Cells[5] == "17", "SP cost is separate from recovery category and unknown amount");
        check.True(row.MetadataText.Contains("友方") && row.MetadataText.Contains("消耗 SP 17"), "reviewed target and cost are display facts");
        check.True(SettingsActions.Choices(new(1,1,"合成",state,labels),"player",false).Single(choice => choice.Id == 2101).Label.Contains("恢復 SP"), "observed skill picker includes recovery category");
        var withdrawn = SkillPresentation.All(state,new DesktopLabels()).First(row => row.Player && row.Id == 2101);
        check.True(withdrawn.RecoveryText == "恢復效果未驗證" && withdrawn.Cells[5] == "待核對", "withdrawn metadata never retains recovery or cost");
        check.True(SkillPresentation.All(state,labels).Where(row => row.Id != 2101).All(row => row.Details is null), "known recovery cannot spread to another skill ID");
    }

    private static void TestIndependentResourceRules(Checks check, string root)
    {
        var draft = new BattleSettingsDraft();
        var player = BattleSettingsDraft.Profile(draft.Value, "player");
        var partner = BattleSettingsDraft.Profile(draft.Value, "partner");
        player["lowHpAction"]!["id"] = 1001; player["lowHpAction"]!["kind"] = 1; player["lowHpAction"]!["value"] = 123;
        player["lowSpAction"]!["id"] = 1002; player["lowSpAction"]!["value"] = 45; player["bLowSpAction"] = true;
        partner["lowHpAction"]!["id"] = 2001; partner["lowHpAction"]!["kind"] = 1; partner["lowHpAction"]!["value"] = 234;
        partner["lowSpAction"]!["id"] = 2002; partner["lowSpAction"]!["value"] = 67; partner["bLowSpAction"] = true;
        var store = new DesktopPreferencesStore(Path.Combine(root,"independent-rules"));
        store.WriteBattle("合成條件角色",draft);
        var reopened = new DesktopPreferencesStore(Path.Combine(root,"independent-rules")).ReadBattle("合成條件角色");
        check.True(reopened.ToJson() == draft.ToJson(), "HP A/B and SP C/D for both actors survive store reopen independently");
        BattleSettingsDraft.Profile(reopened.Value,"player")["lowHpAction"]!["value"] = 999;
        check.True(BattleSettingsDraft.Int(BattleSettingsDraft.Profile(reopened.Value,"player")["lowSpAction"]!["value"]) == 45 &&
            BattleSettingsDraft.Int(BattleSettingsDraft.Profile(reopened.Value,"partner")["lowHpAction"]!["value"]) == 234,
            "changing player HP never changes SP or companion rules");
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
