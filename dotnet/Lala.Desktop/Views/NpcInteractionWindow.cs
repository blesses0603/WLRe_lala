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
    private readonly ListBox products = new() { Name = "NpcShopProducts", Height = 180, Background = Ui.Panel };
    private readonly TextBox quantity = new() { Name = "NpcShopQuantity", Text = "1", Width = 70, MaxLength = 4 };
    private readonly TextBlock total = Ui.Text("請選擇商品", 12, Ui.Muted);
    private readonly StackPanel shopPanel;
    private readonly Button buy, sell;
    private GameShopMenu? shopMenu;
    private sealed record Product(Lala.Core.Resources.SceneShopProduct Row)
    {
        public override string ToString() => $"{Row.Name}　{Row.BasePriceGold?.ToString(CultureInfo.InvariantCulture) ?? "?"} 金幣";
    }
    private long generation;
    private string menuKey = "";
    private bool closed, sending;
    internal NpcInteractionWindow(DesktopSession session) : base("NPC 對話與選項", 620, 550)
    {
        this.session = session; generation = session.Generation;
        buy = Ui.Button("購買", async () => await BuyAsync(), "NpcShopBuy");
        sell = Ui.Button("販售背包物品", () => new InventoryWindow(session).Show(), "NpcShopSell");
        shopPanel = Ui.Column(products, Ui.Row(Ui.Text("數量"), quantity, buy, sell), total);
        shopPanel.IsVisible = false;
        products.SelectionChanged += (_, _) => RefreshTotal();
        quantity.TextChanged += (_, _) => RefreshTotal();
        next = Ui.Button("接續對話", async () => await SendAsync(new("npc", "next")), "NpcContinue");
        closeMenu = Ui.Button("關閉伺服器選單", async () =>
        {
            var state = session.Snapshot; var current = state.Local.Session.NpcDialogue;
            var rows = session.Catalogs?.EveIndexes.Scenes.Where(s => s.SceneId == current.Scene).SelectMany(s => s.Interactions).Where(r => r.Index == current.OptionIndex).ToArray() ?? [];
            if (current.Scene is not { } scene || current.OptionIndex is not { } interaction || rows.Length != 1) return;
            await SendAsync(new("npc", rows[0].FormKind is 2 or 3 ? "close_shop" : "close_choice", Count: interaction, Scene: scene,
                Key: current.EffectPacket?.ToString(CultureInfo.InvariantCulture)));
        }, "NpcCloseMenu");
        SetBody(Ui.Column(title, new ScrollViewer { Content = Ui.Column(dialogue, choices, shopPanel), Height = 350 }, Ui.Row(next, closeMenu), status,
            Ui.Text("選項以目前官方對話資料為準；關閉此視窗不會自動替你選擇或關閉伺服器選單。", 12, Ui.Muted)));
        session.Changed += Changed; Closed += (_, _) => { closed = true; session.Changed -= Changed; }; Refresh();
    }
    private void Changed() => Ui.OnUi(() => { if (!closed) Refresh(); });
    private void RefreshTotal()
    {
        var row = (products.SelectedItem as Product)?.Row;
        total.Text = row?.BasePriceGold is {} price && int.TryParse(quantity.Text, out int count) && count is > 0 and <= 9999
            ? $"合計 {(ulong)price * (uint)count} 金幣" : "請選擇商品並輸入 1～9999 的數量。";
    }
    private async Task BuyAsync()
    {
        if (sending || shopMenu is not {} menu || products.SelectedItem is not Product product || product.Row.BasePriceGold is not {} price) return;
        if (!int.TryParse(quantity.Text, out int count) || count is < 1 or > 9999) { RefreshTotal(); return; }
        var action = new GameAction("shop", "buy", product.Row.ItemId, product.Row.OfferIndex, count, X: menu.Interaction, Scene: menu.Scene,
            Key: menu.EffectKey, ExpectedPrice: price);
        bool confirmed;
        try
        {
            sending = true; Refresh();
            confirmed = await new ItemActionConfirmationWindow("確認購買", $"{product.Row.Name} × {count}", $"合計 {(ulong)price * (uint)count} 金幣").ShowDialog<bool>(this);
        }
        finally { sending = false; if (!closed) Refresh(); }
        if (confirmed && !closed) await SendAsync(action);
    }
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
        if (session.Generation != generation)
        {
            choices.Children.Clear(); choiceButtons.Clear(); products.ItemsSource = null; shopMenu = null; shopPanel.IsVisible = false;
            next.IsEnabled = closeMenu.IsEnabled = buy.IsEnabled = sell.IsEnabled = false;
            title.Text = "帳號或連線已變更，請重新開啟。"; return;
        }
        var view = session.ReadView(); var state = view.Snapshot; var info = state.Local.Session.NpcDialogue; var catalog = session.Catalogs;
        var replacement = catalog is null ? null : GameInventoryOperations.Shop(state, catalog);
        if (replacement?.EffectKey != shopMenu?.EffectKey || replacement?.Scene != shopMenu?.Scene || replacement?.Interaction != shopMenu?.Interaction || replacement is null)
        {
            var selected = (products.SelectedItem as Product)?.Row.OfferIndex;
            products.ItemsSource = replacement?.Products.Select(p => new Product(p)).ToArray() ?? [];
            products.SelectedItem = (products.ItemsSource as Product[])?.FirstOrDefault(p => p.Row.OfferIndex == selected);
        }
        shopMenu = replacement; shopPanel.IsVisible = replacement is not null;
        bool ready = !sending && session.CanSendGameCommands && state.Local.Battle.Active != true && !state.Local.Session.EventFlow.AwaitingResponse;
        buy.IsEnabled = sell.IsEnabled = ready && replacement is not null && session.ActionStatus?.Pending != true;
        title.Text = info.Active ? "NPC · " + (info.NpcId is > 0 and <= ushort.MaxValue ? view.Labels.Npc((ushort)info.NpcId.Value) : "目前互動") : "尚未開始 NPC 對話";
        dialogue.Text = replacement is not null ? "選擇商品與數量，確認後購買。" : info.Phase != "requesting" && info.TextId is { } textId && catalog?.Talks.GetValueOrDefault(textId) is { } line ? line.Text
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
                else if (replacement is not null) choices.Children.Add(Ui.Text(replacement.Title, 15, bold: true));
                else choices.Children.Add(Ui.Text("此選單資料尚未核對，不會猜測選項。", 12, Ui.Muted));
            }
        }
        foreach (var button in choiceButtons) button.IsEnabled = ready;
    }
}
