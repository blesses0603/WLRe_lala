using System.Collections.Immutable;
using Lala.Core.State;
using Lala.Core.Catalogs;

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
    private Func<ushort, byte[]?>? itemImageReader;

    public DesktopSession(DesktopPreferencesStore? preferences = null) =>
        Preferences = preferences ?? new DesktopPreferencesStore();

    public DesktopPreferencesStore Preferences { get; }
    public event Action? Changed;
    public ServiceStateSnapshot Snapshot { get { lock (gate) return snapshot; } }
    public long Generation { get { lock (gate) return generation; } }
    public string IdentityKey { get { lock (gate) return identityKey; } }
    public bool CanSendGameCommands => false;
    public const string ConnectionUnavailable = "一般遊戲操作尚未接入；資源保持 Held。";
    private string connectionText = "尚未連線";
    public string ConnectionText { get { lock (gate) return connectionText; } }
    internal void SetConnectionText(string value)
    {
        lock (gate) { if (disposed || connectionText == value) return; connectionText = value; }
        Changed?.Invoke();
    }
    internal void SetItemImageReader(long expectedGeneration, Func<ushort, byte[]?>? reader)
    {
        lock (gate) { if (disposed || generation != expectedGeneration) return; itemImageReader = reader; }
        Changed?.Invoke();
    }
    internal byte[]? ReadItemImage(ushort itemId)
    {
        Func<ushort, byte[]?>? reader; long expected;
        lock (gate) { if (disposed) return null; reader = itemImageReader; expected = generation; }
        var png = reader?.Invoke(itemId); // Core rechecks owner/account; no callback under presentation gate.
        lock (gate) return !disposed && generation == expected && ReferenceEquals(reader, itemImageReader) ? png : null;
    }
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
            connectionText = "尚未連線";
            snapshot = new();
            labels = new(); itemImageReader = null;
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
        Action? changed;
        lock (gate)
        {
            disposed = true;
            generation = checked(generation + 1);
            snapshot = new();
            labels = new(); itemImageReader = null;
            changed = Changed; Changed = null;
        }
        changed?.Invoke();
    }
}

public sealed record DesktopPublication(long Generation, long Sequence, string IdentityKey,
    ServiceStateSnapshot Snapshot, DesktopLabels Labels);

/// <summary>Display labels supplied alongside the same publication; never action metadata.</summary>
public sealed record DesktopLabels
{
    public ImmutableDictionary<ushort, string> Items { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public ImmutableDictionary<uint, string> Skills { get; init; } = ImmutableDictionary<uint, string>.Empty;
    public ImmutableDictionary<uint, DesktopSkillDetails> SkillDetails { get; init; } = ImmutableDictionary<uint, DesktopSkillDetails>.Empty;
    public ImmutableDictionary<ushort, string> Scenes { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public ImmutableDictionary<ushort, string> Npcs { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public ImmutableDictionary<ushort, string> ExpeditionTasks { get; init; } = ImmutableDictionary<ushort, string>.Empty;
    public string Item(ushort id) => Items.GetValueOrDefault(id) ?? $"物品 {id}（名稱待同步）";
    public string Skill(uint id) => Skills.GetValueOrDefault(id) ?? $"特技 {id}（名稱待同步）";
    public string Scene(ushort id) => Scenes.GetValueOrDefault(id) ?? $"地圖 {id}";
    public string Npc(ushort id) => Npcs.GetValueOrDefault(id) ?? $"夥伴 {id}（名稱待同步）";
    public string ExpeditionTask(ushort id) => ExpeditionTasks.GetValueOrDefault(id) ?? $"任務 {id}（資料待同步）";
}

/// <summary>Display-only catalog facts. Neither learning nor casting is inferred.</summary>
public sealed record DesktopSkillDetails(uint KindSort, uint SpCost, uint TargetKind, SkillRecoveryKind Recovery)
{
    public string Category => KindSort switch { 1 => "物理", 2 => "魔法", 3 => "輔助", 4 => "被動", _ => "其他／未驗證" };
    public string Target => TargetKind switch { 0 => "敵方", 1 => "友方", 2 => "任意目標", 3 => "自身", 4 => "其他目標", 5 => "隊友", _ => "目標未驗證" };
    public string RecoveryText => Recovery switch
    {
        SkillRecoveryKind.Hp => "恢復 HP（恢復量未知）",
        SkillRecoveryKind.Sp => "恢復 SP（恢復量未知）",
        SkillRecoveryKind.HpAndSp => "恢復 HP／SP（恢復量未知）",
        _ => "恢復效果未驗證"
    };
}
