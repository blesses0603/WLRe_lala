using System.Collections.Immutable;
using Lala.Core.State;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

/// <summary>
/// Desktop presentation boundary for immutable Core publications. Publications remain
/// observations: neither a world_ready string nor a resource gate grants transport authority.
/// A future host supplies a generation and monotonically increasing publication number.
/// </summary>
public sealed partial class DesktopSession : IDisposable
{
    private readonly object gate = new();
    private ServiceStateSnapshot snapshot = new();
    private long generation = 1;
    private long publication = -1;
    private bool disposed;
    private string identityKey = "desktop-preview";
    private DesktopLabels labels = new();
    private Func<ushort, byte[]?>? itemImageReader;
    private Func<ServiceStateSnapshot,bool,PortraitRenderRequest?>? portraitReader;

    private Func<EmojiGalleryRequest?>? emojiReader;
    private Func<ushort,SmallMapRenderRequest?>? smallMapReader;
    private Func<ushort,SceneNpcRosterRequest?>? npcReader;
    private bool connected;
    private Func<string, string, uint?, Task>? chatSender;
    private Func<GameAction, Task>? gameSender;
    private Func<string, bool, GameAutomationSettings?, Task>? automationSender;
    private Func<string, GameAutomationSettings, Task<bool>>? automationUpdater;
    private Func<Task>? efficiencyResetter;
    internal void AttachEfficiencyResetter(long expectedGeneration, Func<Task> reset)
    { lock (gate) { if (disposed || generation != expectedGeneration) return; efficiencyResetter = reset; } }
    internal bool CanResetEfficiency { get { lock (gate) return !disposed && connected && efficiencyResetter is not null; } }
    internal Task ResetEfficiencyAsync(long expectedGeneration)
    {
        Func<Task> reset; lock (gate) { RequireCurrentDraft(expectedGeneration); reset = !disposed && connected && efficiencyResetter is { } current ? current : throw new InvalidOperationException("請先完成登入。"); }
        return reset();
    }
    private ImmutableDictionary<string, GameAutomationStatus> automations = ImmutableDictionary<string, GameAutomationStatus>.Empty;
    private GameNavigationStatus navigationStatus = new(false, "尚未啟動導航");
    internal GameNavigationStatus NavigationStatus { get { lock (gate) return navigationStatus; } }
    private Func<GameNavigationTarget, CancellationToken, Task<GameNavigationRoute>>? navigationPreview;
    private Func<GameNavigationTarget, CancellationToken, Task>? navigationStart;
    private Func<Task>? navigationCancel;
    internal void AttachNavigation(long expectedGeneration, Func<GameNavigationTarget, CancellationToken, Task<GameNavigationRoute>> preview,
        Func<GameNavigationTarget, CancellationToken, Task> start, Func<Task> cancel)
    { lock (gate) { if (disposed || generation != expectedGeneration) return; navigationPreview = preview; navigationStart = start; navigationCancel = cancel; } }
    internal Task<GameNavigationRoute> PreviewNavigationAsync(GameNavigationTarget target, CancellationToken token = default)
    {
        Func<GameNavigationTarget, CancellationToken, Task<GameNavigationRoute>> sender;
        lock (gate) { if (disposed || !gameReady || navigationPreview is null) throw new InvalidOperationException("請先完成登入與資源準備。"); sender = navigationPreview; }
        return sender(target, token);
    }
    internal Task NavigateAsync(GameNavigationTarget target, CancellationToken token = default)
    {
        Func<GameNavigationTarget, CancellationToken, Task> sender;
        lock (gate) { if (disposed || !gameReady || navigationStart is null) throw new InvalidOperationException("請先完成登入與資源準備。"); sender = navigationStart; }
        return sender(target, token);
    }
    internal Task StopNavigationAsync()
    { Func<Task>? stop; lock (gate) stop = navigationCancel; return stop?.Invoke() ?? Task.CompletedTask; }
    internal ImmutableDictionary<string, GameAutomationStatus> Automations { get { lock (gate) return automations; } }
    internal void AttachAutomationSender(long expectedGeneration, Func<string, bool, GameAutomationSettings?, Task> sender,
        Func<string, GameAutomationSettings, Task<bool>>? updater = null)
    { lock (gate) { if (disposed || generation != expectedGeneration) return; automationSender = sender; automationUpdater = updater; } }
    internal Task SetAutomationAsync(string kind, bool enabled, GameAutomationSettings? settings = null)
    {
        Func<string, bool, GameAutomationSettings?, Task> sender;
        lock (gate)
        {
            if (disposed || automationSender is null || enabled && (!connected || !gameReady)) throw new InvalidOperationException("請先完成登入與資源準備。");
            sender = automationSender;
        }
        return sender(kind, enabled, settings);
    }
    private bool gameReady;
    private OfflineRuntimeCandidate? catalogs;
    internal OfflineRuntimeCandidate? Catalogs { get { lock (gate) return catalogs; } }
    internal void SetCatalogs(long expectedGeneration, OfflineRuntimeCandidate? value)
    { lock (gate) { if (disposed || generation != expectedGeneration || ReferenceEquals(catalogs, value)) return; catalogs = value; } Changed?.Invoke(); }
    private GameActionStatus? actionStatus;
    private ImmutableArray<string> actionLog = [];
    private ImmutableArray<GameServerEvent> serverEvents = [];
    internal ImmutableArray<GameServerEvent> ServerEvents { get { lock (gate) return serverEvents; } }
    internal void SetServerEvents(long expectedGeneration, ImmutableArray<GameServerEvent> value, uint? currentRole)
    {
        lock (gate)
        {
            if (disposed || generation != expectedGeneration) return;
            if (serverEvents == value && (value.IsEmpty || value[0].OwnerRoleId == currentRole)) return;
            // Defense at the presentation boundary too: unknown or other-role receipts never appear.
            var own = currentRole is null ? [] : value.All(e => e.OwnerRoleId == currentRole)
                ? value : value.Where(e => e.OwnerRoleId == currentRole).ToImmutableArray();
            if (serverEvents.SequenceEqual(own)) return;
            serverEvents = own;
        }
        Changed?.Invoke();
    }
    public GameActionStatus? ActionStatus { get { lock (gate) return actionStatus; } }
    public ImmutableArray<string> ActionLog { get { lock (gate) return actionLog; } }
    internal void AttachGameSender(long expectedGeneration, Func<GameAction, Task> sender)
    { lock (gate) { if (disposed || generation != expectedGeneration) return; gameSender = sender; } }
    internal void SetGameplayState(long expectedGeneration, bool ready, GameActionStatus? status, ImmutableArray<string> log, ImmutableDictionary<string, GameAutomationStatus> automatic, GameNavigationStatus navigation)
    {
        lock (gate)
        {
            if (disposed || generation != expectedGeneration || gameReady == ready && actionStatus == status && actionLog == log && ReferenceEquals(automations, automatic) && navigationStatus == navigation) return;
            gameReady = ready; actionStatus = status; actionLog = log; automations = automatic; navigationStatus = navigation;
        }
        Changed?.Invoke();
    }
    internal Task ExecuteGameActionAsync(GameAction action)
    {
        Func<GameAction, Task> sender;
        lock (gate)
        {
            if (disposed || !connected || !gameReady || gameSender is null) throw new InvalidOperationException("請先完成登入與資源準備。");
            sender = gameSender;
        }
        return sender(action);
    }
    public bool IsConnected { get { lock (gate) return connected && !disposed; } }
    public bool CanSendChat { get { lock (gate) return connected && !disposed && chatSender is not null; } }
    internal void AttachChatSender(long expectedGeneration, Func<string, string, uint?, Task>? sender)
    {
        lock (gate) { if (disposed || generation != expectedGeneration) return; chatSender = sender; }
        Changed?.Invoke();
    }
    internal void SetConnected(long expectedGeneration, bool value)
    {
        lock (gate) { if (disposed || generation != expectedGeneration || connected == value) return; connected = value; }
        Changed?.Invoke();
    }
    internal Task SendChatAsync(string channel, string text, uint? target)
    {
        Func<string, string, uint?, Task> sender;
        lock (gate)
        {
            if (disposed || !connected || chatSender is null) throw new InvalidOperationException("請先完成登入。");
            sender = chatSender;
        }
        return sender(channel, text, target);
    }

    public DesktopSession(DesktopPreferencesStore? preferences = null) =>
        Preferences = preferences ?? new DesktopPreferencesStore();

    public DesktopPreferencesStore Preferences { get; }
    public event Action? Changed;
    public ServiceStateSnapshot Snapshot { get { lock (gate) return snapshot; } }
    public long Generation { get { lock (gate) return generation; } }
    public string IdentityKey { get { lock (gate) return identityKey; } }
    public bool CanSendGameCommands { get { lock (gate) return !disposed && connected && gameReady && gameSender is not null; } }
    public const string ConnectionUnavailable = "請先完成登入與資源準備，並等待所需遊戲資料同步。";
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
    internal void SetPortraitReader(long expectedGeneration,Func<ServiceStateSnapshot,bool,PortraitRenderRequest?>? reader)
    {
        lock(gate){if(disposed||generation!=expectedGeneration)return;portraitReader=reader;}Changed?.Invoke();
    }
    internal PortraitRenderRequest? ReadPortrait(ServiceStateSnapshot expected,bool companion)
    {
        Func<ServiceStateSnapshot,bool,PortraitRenderRequest?>? reader;long captured;
        lock(gate){if(disposed||!ReferenceEquals(expected,snapshot))return null;reader=portraitReader;captured=generation;}
        var request=reader?.Invoke(expected,companion);
        lock(gate)return !disposed&&generation==captured&&ReferenceEquals(reader,portraitReader)&&ReferenceEquals(expected,snapshot)?request:null;
    }
    internal void SetNpcReader(long expectedGeneration,Func<ushort,SceneNpcRosterRequest?>? reader)
    {lock(gate){if(disposed||generation!=expectedGeneration)return;npcReader=reader;}Changed?.Invoke();}
    internal SceneNpcRosterRequest? ReadNpcRoster(ServiceStateSnapshot observed,ushort scene)
    {
        Func<ushort,SceneNpcRosterRequest?>? reader;long expected;
        lock(gate){if(disposed||!ReferenceEquals(snapshot,observed))return null;reader=npcReader;expected=generation;}
        var result=reader?.Invoke(scene);if(result?.IsCurrent!=true)return null;
        lock(gate)return !disposed&&generation==expected&&ReferenceEquals(snapshot,observed)&&ReferenceEquals(reader,npcReader)?result:null;
    }
    internal void SetSmallMapReader(long expectedGeneration,Func<ushort,SmallMapRenderRequest?>? reader)
    {lock(gate){if(disposed||generation!=expectedGeneration)return;smallMapReader=reader;}Changed?.Invoke();}
    internal SmallMapRenderRequest? ReadSmallMap(ServiceStateSnapshot observed,ushort scene)
    {
        Func<ushort,SmallMapRenderRequest?>? reader;long expected;
        lock(gate){if(disposed||!ReferenceEquals(snapshot,observed))return null;reader=smallMapReader;expected=generation;}
        var result=reader?.Invoke(scene);if(result?.IsCurrent!=true)return null;
        lock(gate)return !disposed&&generation==expected&&ReferenceEquals(snapshot,observed)&&ReferenceEquals(reader,smallMapReader)?result:null;
    }
    internal void SetEmojiReader(long expectedGeneration,Func<EmojiGalleryRequest?>? reader)
    {lock(gate){if(disposed||generation!=expectedGeneration)return;emojiReader=reader;}Changed?.Invoke();}
    internal EmojiGalleryRequest? ReadEmojiGallery()
    {
        Func<EmojiGalleryRequest?>? reader;long expected;
        lock(gate){if(disposed)return null;reader=emojiReader;expected=generation;}
        var result=reader?.Invoke();if(result?.IsCurrent!=true)return null;
        lock(gate)return !disposed&&generation==expected&&ReferenceEquals(reader,emojiReader)?result:null;
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
            connectionText = "尚未連線"; connected = false; chatSender = null;
            gameReady = false; gameSender = null; actionStatus = null; actionLog = []; catalogs = null;
            serverEvents = [];
            automationSender = null; automationUpdater = null; efficiencyResetter = null; automations = ImmutableDictionary<string, GameAutomationStatus>.Empty;
            navigationPreview = null; navigationStart = null; navigationCancel = null; navigationStatus = new(false, "尚未啟動導航");
            snapshot = new();
            labels = new(); itemImageReader = null; portraitReader = null; emojiReader = null; smallMapReader = null; npcReader = null;
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
            connected = false; chatSender = null;
            gameReady = false; gameSender = null; actionStatus = null; actionLog = []; catalogs = null;
            serverEvents = [];
            automationSender = null; automationUpdater = null; efficiencyResetter = null; automations = ImmutableDictionary<string, GameAutomationStatus>.Empty;
            navigationPreview = null; navigationStart = null; navigationCancel = null; navigationStatus = new(false, "尚未啟動導航");
            generation = checked(generation + 1);
            snapshot = new();
            labels = new(); itemImageReader = null; portraitReader = null; emojiReader = null; smallMapReader = null; npcReader = null;
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
