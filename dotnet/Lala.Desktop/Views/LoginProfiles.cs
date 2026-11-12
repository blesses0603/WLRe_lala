using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Platform.Storage;

namespace Lala.Desktop;

public sealed partial class LoginWindow
{
    private readonly LoginProfileStore profileStore;
    private readonly ComboBox saved = new() { Name = "LoginSavedAccounts", PlaceholderText = "選擇已記住的帳號", MinHeight = 30,
        HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Stretch };
    private readonly CheckBox rememberAccount = new() { Name = "LoginRememberAccount", Content = "記住帳號" };
    private readonly CheckBox rememberPassword = new() { Name = "LoginRememberPassword", Content = "記住密碼" };
    private readonly List<Control> managementControls = [];
    private bool applyingProfile, profileOperation;
    internal Task Pending => operation ?? Task.CompletedTask;

    private void InitializeProfiles()
    {
        saved.SelectionChanged += (_, _) => { if (!applyingProfile && saved.SelectedItem is LoginProfile profile) ApplyProfile(profile); };
        rememberAccount.IsCheckedChanged += (_, _) => RememberChanged(passwordChanged: false);
        rememberPassword.IsCheckedChanged += (_, _) => RememberChanged(passwordChanged: true);
        KeyDown += (_, e) =>
        {
            if (e.Key != Key.Enter || e.KeyModifiers != KeyModifiers.None) return;
            if (roleRequest is not null && enter.IsEnabled) { SelectRole(); e.Handled = true; }
            else if (submit.IsEnabled) { BeginLogin(); e.Handled = true; }
        };
        try { profileStore.Load(); ReloadProfiles(); }
        catch (Exception) { status.Text = "帳號設定無法讀取；原檔保留，可重新載入設定或手動輸入登入。"; }
        SetManagementEnabled(true);
    }
    private void SetManagementEnabled(bool enabled)
    {
        foreach (var control in managementControls) control.IsEnabled = enabled;
        rememberPassword.IsEnabled = enabled && profileStore.CanRememberPassword;
        if (!profileStore.CanRememberPassword) ToolTip.SetTip(rememberPassword, "此平台尚未提供密碼加密儲存；可記住帳號。 ");
    }
    private void ReloadProfiles(Guid? selected = null)
    {
        var previous = applyingProfile; applyingProfile = true;
        try
        {
            saved.ItemsSource = profileStore.Accounts.ToArray();
            saved.SelectedItem = selected is {} id ? profileStore.Accounts.FirstOrDefault(p => p.Id == id) : null;
        }
        finally { applyingProfile = previous; }
    }
    private void NewProfile()
    {
        if (operation is not null || profileOperation) return;
        applyingProfile = true;
        try { saved.SelectedIndex = -1; account.Text = ""; password.Text = ""; rememberAccount.IsChecked = rememberPassword.IsChecked = false; }
        finally { applyingProfile = false; }
        status.Text = "請選擇伺服器與分流，再輸入新帳號。";
        account.Focus(); UpdateAdmission();
    }
    private void ApplyProfile(LoginProfile profile)
    {
        if (operation is not null) return;
        applyingProfile = true;
        try
        {
            var groups = catalog?.Lines.Select(p => p.Group).Distinct().ToArray() ?? [];
            servers.SelectedIndex = Array.IndexOf(groups, profile.Group);
            // Explicitly rebuild even if the same server remained selected.
            SelectServer();
            lines.SelectedIndex = Array.FindIndex(groupLines, p => p.Id == profile.LineId);
            account.Text = profile.Account;
            password.Text = "";
            rememberAccount.IsChecked = true;
            rememberPassword.IsChecked = profile.ProtectedPassword is not null && profileStore.CanRememberPassword;
            status.Text = lines.SelectedIndex < 0 ? "已填入帳號；儲存的分流目前不可用，請選擇官方分流。" : "已載入帳號設定，按登入後自動連線。";
            try { if (profileStore.CanRememberPassword) password.Text = profileStore.ReadPassword(profile); }
            catch (Exception) { status.Text = "已載入帳號，儲存的密碼無法解密，請重新輸入密碼。"; }
        }
        finally { applyingProfile = false; UpdateAdmission(); }
    }
    private bool SaveCurrentProfile(bool implicitSave = false)
    {
        if (profileOperation || operation is not null) return false;
        if (implicitSave && rememberAccount.IsChecked != true) return true;
        if (string.IsNullOrWhiteSpace(account.Text) || servers.SelectedItem is not string group ||
            lines.SelectedIndex < 0 || lines.SelectedIndex >= groupLines.Length || groupLines[lines.SelectedIndex].Profile is null)
        { status.Text = "請先填寫帳號並選擇可用的官方伺服器與分流。"; return false; }
        try
        {
            var row = profileStore.Save(account.Text, group, groupLines[lines.SelectedIndex].Id, password.Text ?? "", rememberPassword.IsChecked == true);
            applyingProfile = true;
            try { rememberAccount.IsChecked = true; ReloadProfiles(row.Id); }
            finally { applyingProfile = false; }
            status.Text = row.ProtectedPassword is null ? "已儲存帳號與分流；沒有儲存密碼。" : "已儲存帳號與分流，密碼已由 Windows 加密保護。";
            return true;
        }
        catch (Exception) { status.Text = "帳號設定無法儲存，請檢查存取權限；記住密碼時須先輸入密碼。"; return false; }
    }
    private void DeleteProfile()
    {
        if (operation is not null || profileOperation) return;
        if (saved.SelectedItem is not LoginProfile selected) { status.Text = "請先從帳號清單選擇要刪除的帳號。"; return; }
        try { profileStore.Delete(selected.Id); ReloadProfiles(); NewProfile(); status.Text = "已刪除這組帳號及儲存的密碼。"; }
        catch (Exception) { status.Text = "帳號設定無法刪除，請檢查存取權限。"; }
    }
    private void RememberChanged(bool passwordChanged)
    {
        if (applyingProfile || operation is not null) return;
        applyingProfile = true;
        try
        {
            if (passwordChanged && rememberPassword.IsChecked == true) rememberAccount.IsChecked = true;
            if (rememberAccount.IsChecked != true) rememberPassword.IsChecked = false;
            if (saved.SelectedItem is LoginProfile profile && profile.Account == account.Text)
            {
                if (rememberAccount.IsChecked != true) { profileStore.Delete(profile.Id); ReloadProfiles(); }
                else if (rememberPassword.IsChecked != true) { profileStore.ForgetPassword(profile.Id); ReloadProfiles(profile.Id); }
            }
        }
        catch (Exception) { status.Text = "無法更新帳號記憶設定，請檢查存取權限。"; }
        finally { applyingProfile = false; }
    }
    private void BeginLogin()
    {
        if (operation is not null || profileOperation) return;
        UpdateAdmission();
        if (!submit.IsEnabled) { status.Text = "請填寫帳號密碼並選擇可用分流，且先完成版本與資料庫檢查。"; return; }
        if (!SaveCurrentProfile(implicitSave: true)) return;
        stopping = false; operation = LoginAsync();
    }
    private async Task TransferProfilesAsync(bool import)
    {
        if (profileOperation || operation is not null) return;
        profileOperation = true; SetManagementEnabled(false); UpdateAdmission();
        try
        {
            var type = new FilePickerFileType("LaLa 帳號設定") { Patterns = ["*.json"] };
            if (import)
            {
                var files = await StorageProvider.OpenFilePickerAsync(new() { Title = "載入 LaLa 帳號設定", AllowMultiple = false, FileTypeFilter = [type] });
                if (files.Count == 0 || closed) return;
                using var selected = files[0];
                await using var stream = await selected.OpenReadAsync();
                var buffer = new byte[LoginProfileStore.MaximumBytes + 1]; int used = 0;
                while (used < buffer.Length)
                {
                    int count = await stream.ReadAsync(buffer.AsMemory(used));
                    if (count == 0) break;
                    used += count;
                }
                int imported = profileStore.Import(buffer.AsSpan(0, used).ToArray());
                ReloadProfiles(); account.Text = ""; ClearSecrets();
                status.Text = $"已載入 {imported} 組帳號設定，請從帳號清單選擇；匯入不包含密碼。";
            }
            else
            {
                if (profileStore.Accounts.Count == 0) { status.Text = "請先使用「儲存此組」建立帳號，再匯出設定。"; return; }
                using var selected = await StorageProvider.SaveFilePickerAsync(new() { Title = "儲存 LaLa 帳號設定（不含密碼）", SuggestedFileName = "lala-accounts.json", DefaultExtension = "json", FileTypeChoices = [type] });
                if (selected is null || closed) return;
                await using var stream = await selected.OpenWriteAsync();
                if (stream.CanSeek) stream.SetLength(0);
                await stream.WriteAsync(profileStore.Export());
                status.Text = "已匯出帳號與分流設定；檔案不包含密碼。";
            }
        }
        catch (Exception) { status.Text = "設定檔無法讀寫或格式不符，原有帳號設定已保留。"; }
        finally { profileOperation = false; SetManagementEnabled(!closed); UpdateAdmission(); }
    }
}
