using System.Collections.Immutable;
using System.Text.Json.Nodes;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

internal static partial class DesktopSelfTest
{
    private static void TestFeaturePreferences(Checks check, string directory)
    {
        string a = AccountPreferenceIdentity.For("synthetic-account-a", "地球"), b = AccountPreferenceIdentity.For("synthetic-account-b", "地球");
        check.True(a == AccountPreferenceIdentity.For("synthetic-account-a", "地球") && a != b && a != AccountPreferenceIdentity.For("synthetic-account-a", "水星"), "settings identity is stable and isolates account and server");
        check.True(!a.Contains("synthetic-account-a", StringComparison.Ordinal), "preference identity contains no plaintext account name");
        using var session = new DesktopSession(new(Path.Combine(directory, "features")));
        session.Reset(a); long generation = session.Generation;
        session.SaveAssistant(generation, a, new(GuildSign: true, GoldBudget: 123));
        session.SaveCraftPlan(generation, a, new() { Entries = [new(101, 2), new(102, 4)] });
        session.Reset(a);
        check.True(session.Preferences.ReadAssistant(a).GuildSign && session.Preferences.ReadAssistant(a).GoldBudget == 123, "assistant preferences survive another login for the same account");
        check.True(session.Preferences.ReadCraftPlan(a).Entries.SequenceEqual(new CraftPlanEntry[] { new(101, 2), new(102, 4) }), "craft plan preserves recipe order and batches");
        check.True(!session.Preferences.ReadAssistant(b).GuildSign && session.Preferences.ReadCraftPlan(b).Entries.Length == 0, "different accounts do not share assistant flags or craft plans");
        check.Reject<InvalidOperationException>(() => session.SaveAssistant(generation, a, new()), "old account generation cannot save assistant preferences");
        check.Reject<InvalidOperationException>(() => session.SaveCraftPlan(generation, a, new()), "old account generation cannot save craft plan");
        check.Reject<InvalidDataException>(() => session.SaveAssistant(session.Generation, a, new(GoldBudget: -1)), "negative spending budget is rejected");
        check.True(session.Preferences.ReadAssistant(a).GoldBudget == 123, "invalid assistant settings never replace saved settings");
        check.Reject<InvalidDataException>(() => session.SaveCraftPlan(session.Generation, a, new() { Entries = [new(101, 256)] }), "craft batches outside protocol range cannot be saved");
        check.True(session.Preferences.ReadCraftPlan(a).Entries.Length == 2, "invalid craft plan preserves previous saved plan");
        var battle = session.Preferences.ReadBattle(a);
        battle.Value["party_guard"] = new JsonObject { ["enabled"] = true, ["members"] = new JsonArray(new JsonObject { ["role_id"] = 42u, ["name"] = "介面測試隊員" }) };
        session.SaveBattle(session.Generation, a, battle);
        check.True(GameplayPreferences.Read(session).RequiredParty.SequenceEqual(new uint[] { 42 }), "saved required party list reaches core settings");
        battle.Value["field_heal"] = true;
        battle.Value["recovery"]!["hp"]!["storage"] = "first";
        battle.Value["recovery"]!["hp"]!["items"]![0] = 20;
        battle.Value["recovery"]!["hp"]!["player_percent"] = 67;
        battle.Value["recovery"]!["sp"]!["partner_percent"] = 22;
        session.SaveBattle(session.Generation, a, battle);
        var supply = GameplayPreferences.Read(session);
        check.True(supply.FieldHeal && supply.HpRecovery.Storage == "first" && supply.HpRecovery.Items[0] == 20 && supply.HpRecovery.PlayerPercent == 67 && supply.SpRecovery.PartnerPercent == 22,
            "saved field recovery priorities, storage order and per-recipient thresholds reach the core");
        int starts = 0, updates = 0;
        generation = session.Generation;
        session.SetConnected(generation, true);
        session.AttachAutomationSender(generation, (_, _, _) => { starts++; return Task.CompletedTask; }, (kind, settings) =>
        {
            updates++; check.True(kind == "battle" && settings.RequiredParty.SequenceEqual(new uint[] { 42 }), "active AI update uses newly saved settings");
            return Task.FromResult(true);
        });
        session.SetGameplayState(generation, true, null, [], ImmutableDictionary<string, GameAutomationStatus>.Empty.Add("battle", new("battle", true, "fixture")), new(false, "fixture"));
        session.ReapplyActiveSettingsAsync(generation, a, "battle", "daily").GetAwaiter().GetResult();
        check.True(starts == 0 && updates == 1, "applying settings updates only active AI and never calls the start entry");
        session.Reset(b);
        check.Reject<InvalidOperationException>(() => session.ReapplyActiveSettingsAsync(generation, a, "battle").GetAwaiter().GetResult(), "switching accounts rejects a delayed settings application");
        check.True(updates == 1, "stale settings cannot reach another account sender");
    }
}
