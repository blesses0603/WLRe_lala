using System.Collections.Immutable;
using System.Globalization;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Desktop;

/// <summary>
/// Explicit native UI acceptance using synthetic "介面測試" data. The caller supplies a
/// temporary preference store. Screenshots render actual Avalonia windows after layout.
/// </summary>
internal static class DesktopUiSmokeTest
{
    public static Task RunAsync(DesktopSession session, DashboardWindow dashboard, string? screenshotDirectory) =>
        new Run(session, dashboard, screenshotDirectory).ExecuteAsync();

    private sealed class Run(DesktopSession session, DashboardWindow dashboard, string? screenshotDirectory)
    {
        private readonly List<Window> opened = [];
        private int checks;
        private int screenshots;
        private long sequence;
        private readonly (ServiceStateSnapshot State, DesktopLabels Labels) fixture = DesktopTestData.Create();

        public async Task ExecuteAsync()
        {
            if (!Dispatcher.UIThread.CheckAccess()) throw new InvalidOperationException("UI smoke test must run on the Avalonia UI thread.");
            if (screenshotDirectory is not null) Directory.CreateDirectory(screenshotDirectory);
            session.Reset(DesktopTestData.Identity);
            try
            {
                await EmptyAndLoginAsync();
                Publish(fixture.State, fixture.Labels);
                await Settle(dashboard);
                await Capture(dashboard, "02-dashboard-observed");
                await BattleAndMapAsync();
                await InventoryAndSkillsAsync();
                await NavigationAsync();
                await ExpeditionAsync();
                await SettingsAsync();
                await ScopeAndLifecycleAsync();
                Console.WriteLine($"Desktop native UI smoke test: {checks} checks passed; {screenshots} rendered screenshots. Synthetic data only; no live login, game commands, installer or production-server acceptance.");
            }
            finally
            {
                foreach (var window in opened.AsEnumerable().Reverse()) if (window.IsVisible) window.Close();
                session.Reset();
                dashboard.SelectEventTab();
            }
        }

        private async Task EmptyAndLoginAsync()
        {
            dashboard.SelectBattleTab();
            await Settle(dashboard);
            var battle = Find<BattleView>(dashboard, "BattleView");
            Check(Descendants<Button>(battle).Count(b => b.Name?.StartsWith("BattleSlot_", StringComparison.Ordinal) == true) == 16,
                "empty battle keeps exactly sixteen packet-position cells");
            Check(Descendants<Button>(battle).Where(b => b.Name?.StartsWith("BattleSlot_", StringComparison.Ordinal) == true)
                .All(b => !b.IsEnabled), "empty battle has no selectable invented occupants");
            Disabled(dashboard, "DashboardDisconnect", "ChatSend", "MapSyncNavigation", "MapCancelSync", "MapPortalGo");
            Check(Find<TextBlock>(dashboard, "MapPosition").Text!.Contains("等待", StringComparison.Ordinal),
                "empty map does not display guessed coordinates");
            foreach (var name in new[] { "OpenInventory", "OpenSkills", "OpenSettings", "OpenExpedition", "OpenLogin" })
                Check(Find<Button>(dashboard, name).IsEnabled, "dashboard feature launcher exists: " + name);
            await Capture(dashboard, "01-dashboard-empty");

            int previews = 0;
            var login = Show(new LoginWindow(session, () => previews++, () => { }));
            await Settle(login);
            Disabled(login, "LoginSubmit", "LoginDisconnect", "LoginEnterRole", "LoginSaveIdentity", "LoginDeleteIdentity",
                "LoginLoadProfile", "LoginSaveProfile", "LoginVersionCheck");
            Check(!Find<ComboBox>(login, "LoginServer").IsEnabled && !Find<ComboBox>(login, "LoginLine").IsEnabled,
                "login cannot select fabricated server endpoints");
            Check(!Find<CheckBox>(login, "LoginRememberPassword").IsEnabled, "unimplemented credential persistence is unavailable");
            var account = Find<TextBox>(login, "LoginAccount");
            var password = Find<TextBox>(login, "LoginPassword");
            account.Text = "介面測試帳號";
            await Settle(login);
            password.Text = "介面測試-非真密碼";
            Check(password.PasswordChar != '\0', "login password is masked");
            await Capture(login, "03-login");
            Click(login, "LoginPreview");
            Check(previews == 1 && string.IsNullOrEmpty(password.Text), "preview handoff clears the password without logging in");
            password.Text = "介面測試-非真密碼";
            account.Text = "介面測試另一帳號";
            await Settle(login);
            Check(string.IsNullOrEmpty(password.Text), "changing the account clears the previous password");
            password.Text = "介面測試-非真密碼";
            login.Close();
            Check(string.IsNullOrEmpty(password.Text) && string.IsNullOrEmpty(account.Text), "closing login clears account and password edits");
            Progress("登入、主畫面空狀態");
        }

        private async Task BattleAndMapAsync()
        {
            dashboard.SelectBattleTab();
            await Settle(dashboard);
            var battle = Find<BattleView>(dashboard, "BattleView");
            var before = session.ReadView();
            battle.SelectSlot(new(1, 1));
            battle.SelectSlot(new(3, 2));
            Check(battle.SelectedActorKey == "1:1" && battle.SelectedTargetKey == "3:2", "battle selection preserves original server slots");
            Check(ReferenceEquals(before.Snapshot, session.Snapshot) && !session.CanSendGameCommands &&
                session.Snapshot.Local.Battle.Commands.Length == 0, "selecting actor and target sends no command and does not mutate Core");
            battle.SelectSlot(new(4, 4));
            battle.SelectSlot(new(1, 4));
            Check(battle.SelectedTargetKey == "3:2", "dead and empty cells do not replace the target");
            Check(Find<TextBlock>(dashboard, "MapPosition").Text!.Contains("120, 240", StringComparison.Ordinal),
                "map shows only current confirmed textual coordinates");
            Check(!Descendants<Image>(Find<Border>(dashboard, "MapSurface")).Any(),
                "missing official map remains an empty-state surface");
            await Capture(dashboard, "04-battle-map");

            var replacementBattle = BattleEventReducer.Apply(fixture.State.Local.Battle,
                new BattleUnitsEvent([DesktopTestData.Unit(3, 2, 8899, 0, 0, 400, "介面測試替換目標")]));
            Publish(With(local: new(fixture.State.Local.Session, fixture.State.Local.World, replacementBattle)), fixture.Labels);
            await Settle(dashboard);
            Check(battle.SelectedTargetKey is null && battle.SelectedActorKey == "1:1",
                "reusing a battle slot invalidates only the replaced occupant selection");
            var staleWorld = fixture.State.Local.World with
            {
                Location = fixture.State.Local.World.Location with { ConfirmedIsCurrent = false }
            };
            Publish(With(local: new(fixture.State.Local.Session, staleWorld, fixture.State.Local.Battle)), fixture.Labels);
            await Settle(dashboard);
            Check(Find<TextBlock>(dashboard, "MapPosition").Text!.Contains("等待", StringComparison.Ordinal),
                "stale confirmed coordinates are not shown as current map position");
            Publish(fixture.State, fixture.Labels);
            await Settle(dashboard);
            Progress("戰場選取、地圖座標守衛");
        }

        private async Task InventoryAndSkillsAsync()
        {
            var inventory = Show(new InventoryWindow(session));
            var skills = Show(new SkillsWindow(session));
            await Settle(inventory);
            await Settle(skills);
            Check(inventory.VisibleBagItemCount == 30, "backpack uses all thirty observed fixture records");
            Check(skills.SkillRowCount == 4, "skill view excludes zero-level and removed skills while preserving both actors");
            Check(!ReferenceEquals(inventory.Content, skills.Content), "backpack and skills are separate window content trees");
            Disabled(inventory, "InventoryBagHealHp", "InventoryBagHealSp", "InventoryBagDepositGarage", "InventoryBagDepositMaterials");
            Disabled(skills, "SkillsCast");
            inventory.SelectBagItem(1);
            Check(inventory.SelectedBagIndex == 1 && inventory.BagDetailsText.Contains("可用 18", StringComparison.Ordinal),
                "backpack details retain actual slot and subtract observed reservations");
            skills.SelectSkillRow(0);
            Check(skills.SelectedSkillKey == "player:2101", "skill selection includes actor identity");
            inventory.SearchText = "1002";
            await Settle(inventory);
            Check(inventory.VisibleBagItemCount == 1 && inventory.SelectedBagIndex is null && skills.SelectedSkillKey == "player:2101",
                "backpack search clears hidden item selection without changing skill selection");
            skills.SearchText = "2101";
            await Settle(skills);
            Check(skills.SkillRowCount == 2 && inventory.SearchText == "1002", "skill search independently retains two actors with the same skill ID");
            inventory.SearchText = "";
            await Settle(inventory);
            inventory.SelectBagItem(30);
            Check(inventory.BagPageIndex == 1 && inventory.SelectedBagIndex == 30,
                "selecting an observed item changes to its page without changing its ID");
            inventory.ChangeBagPage(int.MaxValue);
            Check(inventory.BagPageIndex == 1, "backpack pagination clamps at its final observed page");
            await Capture(inventory, "05-backpack");
            inventory.SearchText = "介面測試找不到的道具";
            await Settle(inventory);
            Check(inventory.VisibleBagItemCount == 0 && inventory.SelectedBagIndex is null && inventory.BagPageIndex == 0,
                "empty search has no invented selection and returns to page zero");
            inventory.SearchText = "";
            inventory.SelectTab(1);
            await Settle(inventory);
            Disabled(inventory, "InventoryGarageWithdraw");
            await Capture(inventory, "06-backpack-storage");
            Find<TabControl>(inventory, "InventoryStorageTabs").SelectedIndex = 1;
            await Settle(inventory);
            Disabled(inventory, "InventoryMaterialsWithdraw");
            Check(Descendants<TextBlock>(inventory).Any(t => t.Text?.Contains("90000", StringComparison.Ordinal) == true),
                "storage displays a count wider than the original byte record");
            await Capture(inventory, "07-backpack-materials");
            inventory.SelectTab(0);
            skills.SearchText = "";
            await Settle(skills);
            skills.SelectSkillRow(0);
            await Capture(skills, "08-skills");

            var removed = fixture.State.PlayerKnowledge with { RemovedSkillIds = [2101, 2199] };
            Publish(With(knowledge: removed), fixture.Labels);
            await Settle(skills);
            Check(skills.SkillRowCount == 3 && skills.SelectedSkillKey is null,
                "removing a selected player skill cannot silently select the companion's matching ID");
            Publish(fixture.State, fixture.Labels);
            await Settle(inventory);
            inventory.SelectBagItem(1);
            var oldItem = fixture.State.Bag.Items[1];
            var newItem = oldItem with { OriginalRecord = oldItem.OriginalRecord with { ItemId = 2001 } };
            Publish(With(bag: fixture.State.Bag with { Items = fixture.State.Bag.Items.SetItem(1, newItem) }), fixture.Labels);
            await Settle(inventory);
            Check(inventory.SelectedBagIndex is null, "reusing a backpack slot clears the old item selection");
            Publish(fixture.State, fixture.Labels);
            await Settle(inventory);
            inventory.Close(); skills.Close();
            Progress("背包、獨立特技、搜尋及槽位變更");
        }

        private async Task NavigationAsync()
        {
            var navigation = Show(new NavigationWindow(session));
            await Settle(navigation);
            Disabled(navigation, "NavigationSyncPreview");
            var scene = Find<TextBox>(navigation, "NavigationSceneId");
            var x = Find<TextBox>(navigation, "NavigationStartX");
            var output = Find<TextBox>(navigation, "NavigationOutput");
            Check(scene.Text == DesktopTestData.SceneId.ToString(CultureInfo.InvariantCulture) && x.Text == "120",
                "navigation defaults use the same confirmed current scene");
            scene.Text = "";
            Click(navigation, "NavigationPreview");
            Check(Find<TextBlock>(navigation, "NavigationStatus").Text!.Contains("地圖 ID", StringComparison.Ordinal) &&
                string.IsNullOrEmpty(output.Text), "navigation rejects a missing map ID without output");
            scene.Text = DesktopTestData.SceneId.ToString(CultureInfo.InvariantCulture);
            x.Text = "NaN";
            Click(navigation, "NavigationPreview");
            Check(Find<TextBlock>(navigation, "NavigationStatus").Text!.Contains("有限數值", StringComparison.Ordinal),
                "navigation refuses non-finite coordinates");
            x.Text = "150.5";
            Find<TextBox>(navigation, "NavigationEndX").Text = "350";
            Click(navigation, "NavigationPreview");
            Check(Find<TextBlock>(navigation, "NavigationStatus").Text!.Contains("無法產生路線", StringComparison.Ordinal) &&
                string.IsNullOrEmpty(output.Text), "valid input cannot fabricate a route without official navigation data");
            await Capture(navigation, "09-navigation");
            x.Text = "170.5";
            Publish(fixture.State, fixture.Labels);
            await Settle(navigation);
            Check(x.Text == "170.5", "unrelated publication preserves coordinates being edited");
            var changedWorld = fixture.State.Local.World with { Player = fixture.State.Player! with { Scene = 54322 } };
            Publish(With(local: new(fixture.State.Local.Session, changedWorld, fixture.State.Local.Battle)), fixture.Labels);
            await Settle(navigation);
            Check(scene.Text == "54322" && string.IsNullOrEmpty(x.Text), "new scene never inherits coordinates from the previous scene");
            Publish(fixture.State, fixture.Labels);
            navigation.Close();
            Progress("導航表單驗證及換圖失效");
        }

        private async Task ExpeditionAsync()
        {
            var scope = session.ReadView();
            session.SaveExpedition(scope.Generation, scope.IdentityKey, new(RestoreItemId: 1001));
            var expedition = Show(new ExpeditionWindow(session));
            await Settle(expedition);
            Disabled(expedition, "ExpeditionStart", "ExpeditionStop");
            foreach (var name in new[] { "ExpeditionMinHours", "ExpeditionMinFaith", "ExpeditionMinSuccess" })
            {
                var number = Find<NumericUpDown>(expedition, name);
                var editor = Descendants<TextBox>(number).Single();
                Check(editor.Bounds.Width >= 36 && !string.IsNullOrWhiteSpace(editor.Text),
                    "expedition numeric value remains visible beside spinner controls: " + name);
            }
            var tasks = Find<TextTable>(expedition, "ExpeditionTasks");
            var roles = Find<TextTable>(expedition, "ExpeditionRoles");
            Check(tasks.RowCount == 3 && roles.RowCount == 2, "expedition lists preserve received task and outpost rows");
            tasks.SelectIndex(0);
            Check(Find<TextBox>(expedition, "ExpeditionTaskDetail").Text!.Contains("任務 ID：410", StringComparison.Ordinal),
                "expedition task selection retains its real received ID");
            tasks.SelectIndex(2);
            Check(Find<TextBox>(expedition, "ExpeditionTaskDetail").Text!.Contains("499", StringComparison.Ordinal) &&
                Find<TextBox>(expedition, "ExpeditionTaskDetail").Text!.Contains("資料待同步", StringComparison.Ordinal),
                "unknown task names are marked as missing catalog data");
            tasks.SelectIndex(0);
            Find<NumericUpDown>(expedition, "ExpeditionMinHours").Value = 2.5m;
            Find<NumericUpDown>(expedition, "ExpeditionMinFaith").Value = 85;
            Find<NumericUpDown>(expedition, "ExpeditionMinSuccess").Value = 90;
            var restore = Find<ComboBox>(expedition, "ExpeditionRestoreItem");
            restore.SelectedIndex = 0;
            restore.SelectedIndex = 1;
            var before = session.ReadView().Snapshot;
            Click(expedition, "ExpeditionSave");
            Check(session.Preferences.ReadExpedition(scope.IdentityKey) == new ExpeditionPreferences(2.5m, 85, 90, true, 1001),
                "expedition save retains the selected restoration item and all local draft fields");
            Check(ReferenceEquals(before, session.Snapshot) && !session.Snapshot.Expedition.Enabled && !session.CanSendGameCommands,
                "saving expedition preferences never dispatches or changes Core state");
            await Capture(expedition, "10-expedition");
            expedition.Close();
            Progress("遠征三欄與本機草稿保存");
        }

        private async Task SettingsAsync()
        {
            var scope = session.ReadView();
            var savedBefore = session.Preferences.ReadBattle(scope.IdentityKey).ToJson();
            var settings = Show(new SettingsWindow(session));
            await Settle(settings);
            Check(Find<TabControl>(settings, "SettingsTabs").ItemCount == 5, "settings preserves all five legacy tabs");
            settings.SetAction("player", "orderAction", 0, BattleSettingsDraft.Action(60021));
            settings.SetAction("player", "orderAction", 1, BattleSettingsDraft.Action(10001));
            Check(settings.MoveAction("player", "orderAction", 0, 1), "ordered battle actions can be reordered locally");
            Check(BattleSettingsDraft.Int(settings.DraftSnapshot.Value["profiles"]!["player"]!["orderAction"]![1]!["id"]) == 60021,
                "action reorder preserves the selected action ID");
            Check(!settings.MoveAction("player", "orderAction", 0, -1), "action reorder rejects movement outside its list");
            var export = settings.ExportDraftJson();
            settings.ImportJson(export);
            Check(session.Preferences.ReadBattle(scope.IdentityKey).ToJson() == savedBefore,
                "editing, export and import do not implicitly save settings");
            var beforeInvalid = settings.ExportDraftJson();
            Reject<InvalidDataException>(() => settings.ImportJson("{\"field_heal\":false,\"field_heal\":true}"),
                "settings rejects duplicate-key imports");
            Check(settings.ExportDraftJson() == beforeInvalid, "failed import keeps the preceding draft");
            settings.SelectTab(0);
            await Capture(settings, "11-settings-player");
            settings.SelectRuleGroup("player", "misc");
            await Capture(settings, "12-settings-player-conditions");
            settings.SelectTab(1);
            await Capture(settings, "13-settings-companion");
            settings.SelectTab(2);
            await Settle(settings);
            Find<Slider>(settings, "SettingsThreshold_hp_player").Value = 67;
            Check(BattleSettingsDraft.Int(settings.DraftSnapshot.Value["recovery"]!["hp"]!["player_percent"]) == 67,
                "HP recovery slider writes only the detached draft");
            await Capture(settings, "14-settings-recovery");
            settings.SelectTab(3);
            await Capture(settings, "15-settings-maintenance");
            settings.SelectTab(4);
            await Settle(settings);
            Find<CheckBox>(settings, "SettingsPlayerDeath").IsChecked = true;
            await Capture(settings, "16-settings-stop");
            Click(settings, "SettingsCancel");
            Check(session.Preferences.ReadBattle(scope.IdentityKey).ToJson() == savedBefore,
                "cancelling settings discards the entire unsaved draft");

            settings = Show(new SettingsWindow(session));
            await Settle(settings);
            settings.SetRuleEnabled("player", "repeatAction", true);
            var observedBefore = session.Snapshot;
            Check(settings.ApplyDraft(), "applying a current draft succeeds in the temporary settings store");
            Check(BattleSettingsDraft.Bool(session.Preferences.ReadBattle(scope.IdentityKey).Value["profiles"]!["player"]!["bRepeatAction"]),
                "applied rule preference survives reopening");
            Check(ReferenceEquals(observedBefore, session.Snapshot) && !session.CanSendGameCommands,
                "applying battle settings never starts AI or mutates Core");
            settings.Close();
            Progress("設定五頁、草稿匯入取消與套用");
        }

        private async Task ScopeAndLifecycleAsync()
        {
            var inventory = Show(new InventoryWindow(session));
            var skills = Show(new SkillsWindow(session));
            var expedition = Show(new ExpeditionWindow(session));
            var settings = Show(new SettingsWindow(session));
            await Settle(inventory); await Settle(skills); await Settle(expedition); await Settle(settings);
            inventory.SearchText = "1001";
            inventory.SelectBagItem(1);
            skills.SearchText = "2101";
            skills.SelectSkillRow(0);
            var oldScope = session.ReadView();
            var oldExpedition = session.Preferences.ReadExpedition(oldScope.IdentityKey);
            var oldBattle = session.Preferences.ReadBattle(oldScope.IdentityKey).ToJson();
            session.Reset("介面測試換帳");
            await Settle(inventory); await Settle(skills); await Settle(expedition); await Settle(settings);
            Check(inventory.SearchText == "" && inventory.VisibleBagItemCount == 0 && inventory.SelectedBagIndex is null,
                "account generation reset clears backpack filter and selection");
            Check(skills.SearchText == "" && skills.SkillRowCount == 0 && skills.SelectedSkillKey is null,
                "account generation reset clears skill filter and selection");
            Check(!Find<Button>(settings, "SettingsApply").IsEnabled && !settings.ApplyDraft(),
                "stale settings cannot apply after account change");
            Check(!Find<Button>(expedition, "ExpeditionSave").IsEnabled, "stale expedition save button is disabled");
            // Exercise the handler as well as the disabled widget: UI gating alone is not an account boundary.
            Find<Button>(expedition, "ExpeditionSave").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Check(session.Preferences.ReadExpedition(oldScope.IdentityKey) == oldExpedition &&
                session.Preferences.ReadExpedition(session.IdentityKey) == new ExpeditionPreferences(),
                "forced stale expedition handler cannot write either identity's settings");
            Check(session.Preferences.ReadBattle(oldScope.IdentityKey).ToJson() == oldBattle,
                "rejected stale battle apply preserves the original identity's settings");
            Check(!session.Publish(oldScope.Generation, long.MaxValue, fixture.State, fixture.Labels),
                "late publication from the previous account is rejected by the UI host");
            inventory.Close(); skills.Close(); expedition.Close(); settings.Close();

            // A detached child must not retain a session subscription; reattachment reads the fresh publication.
            Publish(fixture.State, fixture.Labels);
            var detached = new BattleView(session);
            var host = Show(new Window { Width = 480, Height = 340, Content = detached, Title = "介面測試生命週期" });
            await Settle(host);
            detached.SelectSlot(new(3, 2));
            Check(detached.SelectedTargetKey == "3:2", "attached battle child observes the current fixture");
            host.Content = null;
            session.Reset("介面測試卸載");
            await Settle(host);
            Check(detached.SelectedTargetKey == "3:2", "detached battle child receives no later session callbacks");
            host.Content = detached;
            await Settle(host);
            Check(detached.SelectedTargetKey is null, "reattached battle child refreshes generation and clears old selection");
            host.Close();

            using (var manager = new DesktopWindows(session, () => { }))
            {
                manager.OpenMain();
                var managed = manager.OpenExpedition();
                await Settle(managed);
                var managedScope = session.ReadView();
                var managedBefore = session.Preferences.ReadExpedition(managedScope.IdentityKey);
                managed.Close();
                Check(!managed.IsVisible, "closing a current managed expedition hides its retained local draft");
                Check(ReferenceEquals(managed, manager.OpenExpedition()),
                    "reopening the same expedition generation preserves its local draft instance");
                managed.Close();
                session.Reset("介面測試遠征換帳");
                await Settle(manager.Dashboard);
                var fresh = manager.OpenExpedition();
                await Settle(fresh);
                Check(!ReferenceEquals(managed, fresh) && Find<Button>(fresh, "ExpeditionSave").IsEnabled,
                    "reopening a hidden expedition after account change creates a writable current draft");
                Find<NumericUpDown>(fresh, "ExpeditionMinHours").Value = 1.5m;
                Click(fresh, "ExpeditionSave");
                Check(session.Preferences.ReadExpedition(session.IdentityKey).MinHours == 1.5m,
                    "the reopened expedition saves to the new identity scope");
                Check(session.Preferences.ReadExpedition(managedScope.IdentityKey) == managedBefore,
                    "recreating a hidden expedition never overwrites the preceding identity scope");
            }
            Check(!session.CanSendGameCommands, "all UI exercises retain the no-transport boundary");
            Progress("換帳失效與視窗訂閱生命週期");
        }

        private ServiceStateSnapshot With(LocalStateSnapshot? local = null, BagReceiveSnapshot? bag = null,
            PlayerKnowledgeSnapshot? knowledge = null) => new(local ?? fixture.State.Local,
                storage: fixture.State.Storage, bag: bag ?? fixture.State.Bag, companions: fixture.State.Companions,
                playerKnowledge: knowledge ?? fixture.State.PlayerKnowledge, expedition: fixture.State.Expedition);

        private void Publish(ServiceStateSnapshot state, DesktopLabels labels)
        {
            if (!session.Publish(session.ReadView().Generation, ++sequence, state, labels))
                throw new InvalidOperationException("UI smoke fixture publication was unexpectedly rejected.");
        }

        private T Show<T>(T window) where T : Window
        {
            opened.Add(window);
            window.Show(dashboard);
            return window;
        }

        private void Check(bool condition, string description)
        {
            if (!condition) throw new InvalidOperationException("Desktop UI smoke failed: " + description);
            checks++;
        }

        private void Reject<T>(Action action, string description) where T : Exception
        {
            try { action(); }
            catch (T) { checks++; return; }
            throw new InvalidOperationException("Desktop UI smoke failed: " + description + $" (expected {typeof(T).Name})");
        }

        private void Disabled(Visual root, params string[] names)
        {
            foreach (var name in names) Check(!Find<Button>(root, name).IsEnabled, "live action remains disabled: " + name);
        }

        private static void Click(Visual root, string name)
        {
            var button = Find<Button>(root, name);
            if (!button.IsEnabled) throw new InvalidOperationException("UI smoke attempted disabled local action: " + name);
            button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        }

        private static IEnumerable<T> Descendants<T>(Visual root) where T : Visual => root.GetSelfAndVisualDescendants().OfType<T>();
        private static T Find<T>(Visual root, string name) where T : Control => Descendants<T>(root).FirstOrDefault(c => c.Name == name)
            ?? throw new InvalidOperationException($"Desktop UI smoke cannot find {typeof(T).Name} '{name}'.");

        private static async Task Settle(Window window)
        {
            await Task.Delay(80);
            await Dispatcher.UIThread.InvokeAsync(window.UpdateLayout, DispatcherPriority.Render);
        }

        private async Task Capture(Window window, string name)
        {
            await Settle(window);
            Check(window.Bounds.Width > 0 && window.Bounds.Height > 0 && window.IsVisible, "native window rendered: " + name);
            if (screenshotDirectory is null) return;
            var size = new PixelSize(checked((int)Math.Ceiling(window.Bounds.Width)), checked((int)Math.Ceiling(window.Bounds.Height)));
            using var bitmap = new RenderTargetBitmap(size, new Vector(96, 96));
            bitmap.Render(window);
            using var encoded = new MemoryStream();
            bitmap.Save(encoded, PngBitmapEncoderOptions.Default);
            Check(encoded.Length > 8, "screenshot encoder produced nonempty PNG data: " + name);
            encoded.Position = 0;
            using var decoded = new Bitmap(encoded);
            Check(decoded.PixelSize == size, "screenshot PNG decodes at the rendered window size: " + name);
            File.WriteAllBytes(Path.Combine(screenshotDirectory, name + ".png"), encoded.ToArray());
            screenshots++;
        }

        private void Progress(string stage) => Console.WriteLine($"Desktop UI: {stage}通過（累計 {checks} 項）。");
    }
}
