using System.Globalization;
using Avalonia.Controls;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

internal sealed class NpcInteractionWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly TextBlock title = Ui.Text("尚未開始 NPC 對話", 18, bold: true), dialogue = Ui.Text("請先在小地圖選擇 NPC 並按互動。"), status = Ui.Text("", 12, Ui.Muted);
    private readonly StackPanel choices = Ui.Column();
    private readonly Button next, closeMenu;
    private readonly List<Button> choiceButtons = [];
    private long generation;
    private string menuKey = "";
    private bool closed, sending;
    internal NpcInteractionWindow(DesktopSession session) : base("NPC 對話與選項", 620, 550)
    {
        this.session = session; generation = session.Generation;
        next = Ui.Button("接續對話", async () => await SendAsync(new("npc", "next")), "NpcContinue");
        closeMenu = Ui.Button("關閉伺服器選單", async () =>
        {
            var state = session.Snapshot; var current = state.Local.Session.NpcDialogue;
            var rows = session.Catalogs?.EveIndexes.Scenes.Where(s => s.SceneId == current.Scene).SelectMany(s => s.Interactions).Where(r => r.Index == current.OptionIndex).ToArray() ?? [];
            if (current.Scene is not { } scene || current.OptionIndex is not { } interaction || rows.Length != 1) return;
            await SendAsync(new("npc", rows[0].FormKind is 2 or 3 ? "close_shop" : "close_choice", Count: interaction, Scene: scene,
                Key: current.EffectPacket?.ToString(CultureInfo.InvariantCulture)));
        }, "NpcCloseMenu");
        SetBody(Ui.Column(title, new ScrollViewer { Content = Ui.Column(dialogue, choices), Height = 310 }, Ui.Row(next, closeMenu), status,
            Ui.Text("選項以目前官方對話資料為準；關閉此視窗不會自動替你選擇或關閉伺服器選單。", 12, Ui.Muted)));
        session.Changed += Changed; Closed += (_, _) => { closed = true; session.Changed -= Changed; }; Refresh();
    }
    private void Changed() => Ui.OnUi(() => { if (!closed) Refresh(); });
    private async Task SendAsync(GameAction action)
    {
        if (sending) return; long expectedGeneration = generation;
        try
        {
            sending = true; Refresh(); session.RequireCurrentDraft(expectedGeneration);
            await session.ExecuteGameActionAsync(action);
            if (!closed && generation == expectedGeneration) status.Text = session.ActionStatus?.Message ?? "已送出，等待伺服器回覆。";
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException) { if (!closed) status.Text = error.Message; }
        finally { sending = false; if (!closed) Refresh(); }
    }
    private void Refresh()
    {
        if (session.Generation != generation) { choices.Children.Clear(); choiceButtons.Clear(); next.IsEnabled = closeMenu.IsEnabled = false; title.Text = "帳號或連線已變更，請重新開啟。"; return; }
        var view = session.ReadView(); var state = view.Snapshot; var info = state.Local.Session.NpcDialogue; var catalog = session.Catalogs;
        bool ready = !sending && session.CanSendGameCommands && state.Local.Battle.Active != true && !state.Local.Session.EventFlow.AwaitingResponse;
        title.Text = info.Active ? "NPC · " + (info.NpcId is > 0 and <= ushort.MaxValue ? view.Labels.Npc((ushort)info.NpcId.Value) : "目前互動") : "尚未開始 NPC 對話";
        dialogue.Text = info.Phase != "requesting" && info.TextId is { } textId && catalog?.Talks.GetValueOrDefault(textId) is { } line ? line.Text
            : info.Active ? "正在等待對話文字或可用選項。" : "請先在小地圖選擇 NPC 並按互動。";
        next.IsEnabled = ready && info.Active && info.Phase is "talk" or "continue";
        var interactions = catalog?.EveIndexes.Scenes.Where(s => s.SceneId == info.Scene).SelectMany(s => s.Interactions).Where(r => r.Index == info.OptionIndex).ToArray() ?? [];
        closeMenu.IsEnabled = ready && info.Active && info.Phase == "choice_unavailable" && interactions.Length == 1 && interactions[0].FormKind is 1 or 2 or 3;
        string currentKey = $"{info.Scene}:{info.EffectPacket}:{info.Phase}:{info.OptionIndex}:{info.Active}:{catalog?.GetHashCode()}";
        if (currentKey != menuKey)
        {
            menuKey = currentKey; choices.Children.Clear(); choiceButtons.Clear();
            if (info.Active && info.Phase == "choice_unavailable" && info.Scene is { } scene && info.OptionIndex is { } index && catalog is not null)
            {
                var menu = GameNpcChoices.Read(catalog.EveIndexes, catalog.Talks, scene, index);
                if (menu is not null)
                {
                    choices.Children.Add(Ui.Text(menu.Title, 15, bold: true));
                    string? receipt = info.EffectPacket?.ToString(CultureInfo.InvariantCulture);
                    foreach (var option in menu.Options)
                    {
                        var button = Ui.Button((option.Index + 1) + ". " + option.Text,
                            async () => await SendAsync(new("npc", "choose", option.TextId, option.Index, Count: index, Scene: scene, Key: receipt)), "NpcChoice" + option.Index);
                        choiceButtons.Add(button); choices.Children.Add(button);
                    }
                }
                else choices.Children.Add(Ui.Text(interactions.Length == 1 && interactions[0].FormKind is 2 or 3 ? "目前為商店選單，可使用專屬關閉操作。" : "此選單資料尚未核對，不會猜測選項。", 12, Ui.Muted));
            }
        }
        foreach (var button in choiceButtons) button.IsEnabled = ready;
    }
}
