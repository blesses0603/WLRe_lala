using Lala.Core.Gameplay;

namespace Lala.Desktop;

public sealed partial class DesktopSession
{
    private void RequirePreferenceScope(long expectedGeneration, string expectedIdentity)
    {
        RequireCurrentDraft(expectedGeneration);
        if (identityKey != expectedIdentity) throw new InvalidOperationException("帳號已變更，設定未套用。");
    }
    public void SaveAssistant(long expectedGeneration, string expectedIdentity, AssistantPreferences draft)
    { lock (gate) { RequirePreferenceScope(expectedGeneration, expectedIdentity); Preferences.WriteAssistant(identityKey, draft); } }
    public void SaveCraftPlan(long expectedGeneration, string expectedIdentity, CraftPlanPreferences draft)
    { lock (gate) { RequirePreferenceScope(expectedGeneration, expectedIdentity); Preferences.WriteCraftPlan(identityKey, draft); } }
    internal async Task ReapplyActiveSettingsAsync(long expectedGeneration, string expectedIdentity, params string[] kinds)
    {
        Func<string, GameAutomationSettings, Task<bool>>? updater; GameAutomationSettings settings; string[] enabled;
        lock (gate)
        {
            RequirePreferenceScope(expectedGeneration, expectedIdentity);
            enabled = kinds.Where(k => automations.GetValueOrDefault(k)?.Enabled == true).Distinct().ToArray();
            if (enabled.Length == 0) return;
            if (!connected || !gameReady || automationUpdater is null) throw new InvalidOperationException("設定已儲存，連線尚未就緒，未更新執行中的功能。");
            updater = automationUpdater; settings = GameplayPreferences.Read(this);
        }
        foreach (var kind in enabled)
        {
            lock (gate) RequirePreferenceScope(expectedGeneration, expectedIdentity);
            await updater(kind, settings);
        }
    }
}
