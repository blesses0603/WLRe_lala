using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
using System.Net;
using System.Text;
using System.Text.Json;
using Lala.Core.Sessions;

namespace Lala.Desktop;

/// <summary>Real UI and persisted preferences with synthetic accounts, never production credentials.</summary>
internal static class DesktopLoginProfilesTest
{
    internal static async Task RunAsync()
    {
        string directory = Path.Combine(Path.GetTempPath(), "lala-login-profiles-" + Guid.NewGuid().ToString("N"));
        LoginWindow? login = null; int checks = 0;
        using var session = new DesktopSession();
        void Check(bool condition, string name) { if (!condition) throw new InvalidOperationException("Login profiles: " + name); checks++; }
        try
        {
            var store = new LoginProfileStore(directory);
            store.Load(); Check(store.Accounts.Count == 0 && !Directory.Exists(directory), "empty store reads without creating files");
            var one = store.Save("synthetic-one", "地球", 101, "", false);
            store.Save("synthetic-two", "水星", 201, "", false);
            var reloaded = new LoginProfileStore(directory); reloaded.Load();
            Check(reloaded.Accounts.Count == 2, "accounts survive a new store instance");
            if (OperatingSystem.IsWindows())
            {
                one = store.Save("synthetic-one", "地球", 102, "synthetic-password-密碼", true);
                reloaded.Load();
                Check(reloaded.ReadPassword(reloaded.Accounts.Single(p => p.Id == one.Id)) == "synthetic-password-密碼", "Windows user protection round-trips Unicode passwords");
                var local = File.ReadAllText(Path.Combine(directory, "accounts.json"));
                Check(!local.Contains("synthetic-password") && one.ProtectedPassword is not null, "local JSON contains encrypted password only");
                var damaged = one with { ProtectedPassword = Convert.ToBase64String([1, 2, 3]) };
                bool rejected = false; try { store.ReadPassword(damaged); } catch { rejected = true; }
                Check(rejected, "damaged protected passwords fail without a plaintext fallback");
            }
            var portable = store.Export();
            Check(!Encoding.UTF8.GetString(portable).Contains("Password"), "portable settings contain no encrypted or plaintext password fields");
            var imported = new LoginProfileStore(inMemory: true); imported.Import(portable); imported.Import(portable);
            Check(imported.Accounts.Count == 2 && imported.Accounts.All(p => p.ProtectedPassword is null), "portable imports merge accounts without duplicating rows or importing passwords");
            foreach (var invalid in new[] { Encoding.UTF8.GetBytes("{}"), new byte[LoginProfileStore.MaximumBytes + 1],
                Encoding.UTF8.GetBytes("{\"Version\":1,\"Accounts\":[{\"Account\":\"x\",\"Group\":\"地球\",\"LineId\":101,\"Password\":\"bad\"}]}") })
            {
                bool rejected = false; try { imported.Import(invalid); } catch { rejected = true; }
                Check(rejected && imported.Accounts.Count == 2, "malformed, oversized or credential-bearing imports preserve existing settings");
            }
            var profile = new AccountConnectionProfile(new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 2), 173, 173, 1, 3, 0);
            var source = new OfflineDesktopServerCatalog(new(101, "地球", "1線", profile), new(102, "地球", "2線", profile), new(201, "水星", "1線", profile));
            login = new LoginWindow(session, () => { }, () => { }, source, profileStore: store);
            login.Show(); await Task.Delay(80);
            T Find<T>(string name) where T : Control => login.GetVisualDescendants().OfType<T>().Single(p => p.Name == name);
            void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            var saved = Find<ComboBox>("LoginSavedAccounts");
            saved.SelectedItem = store.Accounts.Single(p => p.Id == one.Id);
            Check(Find<TextBox>("LoginAccount").Text == "synthetic-one" && Find<ComboBox>("LoginLine").SelectedIndex == (OperatingSystem.IsWindows() ? 1 : 0), "saved account restores official server and exact line");
            if (OperatingSystem.IsWindows())
            {
                Check(Find<TextBox>("LoginPassword").Text == "synthetic-password-密碼" && Find<Button>("LoginSubmit").IsEnabled, "saved protected password enables explicit login without connecting automatically");
                Find<CheckBox>("LoginRememberPassword").IsChecked = false;
                Check(store.Accounts.Single(p => p.Id == one.Id).ProtectedPassword is null, "unchecking remember password deletes the saved encrypted password");
            }
            Find<TextBox>("LoginPassword").Text = "fake";
            saved.SelectedItem = store.Accounts.Single(p => p.Account == "synthetic-two");
            Check(Find<TextBox>("LoginAccount").Text == "synthetic-two" && string.IsNullOrEmpty(Find<TextBox>("LoginPassword").Text), "switching saved accounts never keeps another account password");
            Click("LoginNewDraft");
            Check(saved.SelectedIndex == -1 && string.IsNullOrEmpty(Find<TextBox>("LoginAccount").Text) && !Find<Button>("LoginSubmit").IsEnabled, "new draft clears account selection and requires credentials");
            Find<ComboBox>("LoginServer").SelectedIndex = 0;
            Find<TextBox>("LoginAccount").Text = "synthetic-three";
            Find<TextBox>("LoginPassword").Text = "fake-three";
            Click("LoginSaveIdentity");
            Check(store.Accounts.Any(p => p.Account == "synthetic-three") && Find<CheckBox>("LoginRememberAccount").IsChecked == true, "save identity creates remembered account preferences");
            Click("LoginSaveIdentity"); Check(store.Accounts.Count == 3, "saving again updates without duplicate accounts");
            Click("LoginDeleteIdentity");
            Check(store.Accounts.Count == 2 && saved.SelectedIndex == -1 && string.IsNullOrEmpty(Find<TextBox>("LoginPassword").Text), "delete identity removes saved account and clears the draft");
            store.Save("synthetic-missing-line", "地球", 199, "", false);
            await login.ShutdownAsync(); login.Close();
            login = new LoginWindow(session, () => { }, () => { }, source, profileStore: store);
            login.Show(); await Task.Delay(80);
            Find<ComboBox>("LoginSavedAccounts").SelectedItem = store.Accounts.Single(p => p.LineId == 199);
            Check(Find<ComboBox>("LoginLine").SelectedIndex == -1 && !Find<Button>("LoginSubmit").IsEnabled, "stale saved lines never fall back silently or bypass official admission");
            Console.WriteLine($"Desktop login profiles: {checks} assertions passed; synthetic accounts and temporary local files only.");
        }
        finally
        {
            if (login is not null) { await login.ShutdownAsync(); login.Close(); }
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }
}
