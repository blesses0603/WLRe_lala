using System.Collections.Immutable;
using Lala.Core.State;

namespace Lala.Desktop;

/// <summary>
/// Desktop presentation boundary for immutable Core publications. Publications remain
/// observations: neither a world_ready string nor a resource gate grants transport authority.
/// A future host supplies a generation and monotonically increasing publication number.
/// </summary>
public sealed class DesktopSession : IDisposable
{
    private readonly object gate = new();
    private ServiceStateSnapshot snapshot = new();
    private long generation = 1;
    private long publication = -1;
    private bool disposed;
    private string identityKey = "desktop-preview";
    private DesktopLabels labels = new();

    public DesktopSession(DesktopPreferencesStore? preferences = null) =>
        Preferences = preferences ?? new DesktopPreferencesStore();

    public DesktopPreferencesStore Preferences { get; }
    public event Action? Changed;
    public ServiceStateSnapshot Snapshot { get { lock (gate) return snapshot; } }
    public long Generation { get { lock (gate) return generation; } }
    public string IdentityKey { get { lock (gate) return identityKey; } }
    public bool CanSendGameCommands => false;
    public const string ConnectionUnavailable = "尚未接通遊戲連線；等待登入與資料同步。";
    public string ConnectionText => "尚未連線";
    public DesktopLabels Labels { get { lock (gate) return labels; } }
    public DesktopPublication ReadView()
    {
        lock (gate) return new(generation, publication, identityKey, snapshot, labels);
    }

    public bool Publish(long expectedGeneration, long sequence, ServiceStateSnapshot value,
        DesktopLabels? labels = null)
    {
        ArgumentNullException.ThrowIfNull(value);
        lock (gate)
        {
            if (disposed || expectedGeneration != generation || sequence <= publication) return false;
            snapshot = value;
            publication = sequence;
            this.labels = labels ?? new();
        }
        Changed?.Invoke();
        return true;
    }

    /// <summary>Invalidates queued publications and every open account-bound settings draft.</summary>
    public void Reset(string presentationIdentity = "desktop-preview")
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(presentationIdentity);
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            generation = checked(generation + 1);
            publication = -1;
            snapshot = new();
            labels = new();
            identityKey = presentationIdentity;
        }
        Changed?.Invoke();
    }

    public void RequireCurrentDraft(long expectedGeneration)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (expectedGeneration != generation)
                throw new InvalidOperationException("帳號或連線已變更，請重新開啟設定。此次草稿未套用。");
        }
    }

    public void SaveBattle(long expectedGeneration, string expectedIdentity, BattleSettingsDraft draft)
    {
        lock (gate)
        {
            RequireCurrentDraft(expectedGeneration);
            if (!string.Equals(identityKey, expectedIdentity, StringComparison.Ordinal))
                throw new InvalidOperationException("帳號已變更，請重新開啟設定。");
            Preferences.WriteBattle(identityKey, draft);
        }
    }

    public void SaveExpedition(long expectedGeneration, string expectedIdentity, ExpeditionPreferences draft)
    {
        lock (gate)
        {
            RequireCurrentDraft(expectedGeneration);
            if (!string.Equals(identityKey, expectedIdentity, StringComparison.Ordinal))
                throw new InvalidOperationException("帳號已變更，請重新開啟設定。");
            Preferences.WriteExpedition(identityKey, draft);
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            disposed = true;
            generation = checked(generation + 1);
            snapshot = new();
            labels = new();
            Changed = null;
        }
    }
}

public sealed record DesktopPublication(long Generation, long Sequence, string IdentityKey,
    ServiceStateSnapshot Snapshot, DesktopLabels Labels);

/// <summary>Display labels supplied alongside the same publication; never action metadata.</summary>
public sealed record DesktopLabels
{
    public ImmutableDictionary<ushort, string> Items { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public ImmutableDictionary<uint, string> Skills { get; init; } = ImmutableDictionary<uint, string>.Empty;
    public ImmutableDictionary<ushort, string> Scenes { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public ImmutableDictionary<ushort, string> Npcs { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public ImmutableDictionary<ushort, string> ExpeditionTasks { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public string Item(ushort id) => Items.GetValueOrDefault(id) ?? $"物品 {id}（名稱待同步）";
    public string Skill(uint id) => Skills.GetValueOrDefault(id) ?? $"特技 {id}（名稱待同步）";
    public string Scene(ushort id) => Scenes.GetValueOrDefault(id) ?? $"地圖 {id}";
    public string Npc(ushort id) => Npcs.GetValueOrDefault(id) ?? $"夥伴 {id}（名稱待同步）";
    public string ExpeditionTask(ushort id) => ExpeditionTasks.GetValueOrDefault(id) ?? $"任務 {id}（資料待同步）";
}
