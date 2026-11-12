using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Controls.Presenters;
using Avalonia.Controls.Templates;
using Avalonia.Media;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Resources;

namespace Lala.Desktop;

public sealed partial class LoginWindow
{
    private readonly Func<AccountRoleSelectionRequest, byte, PortraitRenderRequest?>? rolePortrait;
    private readonly List<PortraitView> rolePortraitViews = [];
    private ListBoxItem CreateRoleCardWithPortrait(AccountRoleSelectionRequest request, RoleSnapshot role)
    {
        var view = new PortraitView(64);
        rolePortraitViews.Add(view);
        PortraitRenderRequest? source = null;
        try { source = rolePortrait?.Invoke(request, role.Index); } catch { }
        if (source is not null)
        {
            view.Update(source.Identity, () => ReferenceEquals(roleRequest, request) && source.IsCurrent, source.RenderAsync);
            ToolTip.SetTip(view, "官方角色頭像");
        }
        else { view.Update(null, absent: true); ToolTip.SetTip(view, "官方頭像尚未就緒"); }
        return CreateRoleCard(role, view);
    }
    internal static ListBoxItem CreateRoleCard(RoleSnapshot role, Control? portrait = null)
    {
        string element = role.Element switch { 0 => "無屬性", 1 => "地屬性", 2 => "水屬性", 3 => "火屬性", 4 => "風屬性", _ => "屬性未知" };
        var name = Ui.Text(role.Name, 17, bold: true);
        name.TextWrapping = TextWrapping.NoWrap; name.TextTrimming = TextTrimming.CharacterEllipsis;
        var availability = Ui.Text(role.Locked ? "角色已鎖定" : "點選角色", 12, role.Locked ? Ui.Muted : Ui.Accent);
        string Stat(string label, long current, long maximum) => maximum > 0 ? $"{label}  {current:N0} / {maximum:N0}" : $"{label}  —";
        var header = new Grid { ColumnDefinitions = new("*,Auto"), ColumnSpacing = 8 };
        Ui.At(header, Ui.Text($"角色 {role.Index} · Lv.{role.Level}", 12, Ui.Muted), 0);
        var attribute = Ui.Row(Ui.Text(element, 12, Ui.Muted));
        if (role.Element <= 4)
        {
            var icon = Ui.Icon($"elements/Icon_Element{role.Element + 1:000}.png", 22);
            icon.Name = $"LoginRoleElement{role.Index}";
            ToolTip.SetTip(icon, element);
            attribute.Children.Insert(0, icon);
        }
        Ui.At(header, attribute, 1);
        var details = Ui.Column(name, Ui.Text(Stat("HP", role.Hp, role.MaxHp), 12),
            Ui.Text(Stat("SP", role.Sp, role.MaxSp), 12), availability);
        details.Spacing = 5;
        var content = new Grid { ColumnDefinitions = new(portrait is null ? "*" : "64,*"), ColumnSpacing = 12 };
        if (portrait is not null) Ui.At(content, portrait, 0);
        Ui.At(content, details, portrait is null ? 0 : 1);
        var body = Ui.Column(header, content);
        body.Spacing = 5;
        var frame = new Border
        {
            Width = 332, Padding = new Thickness(12, 10), CornerRadius = new CornerRadius(9),
            Background = Brush.Parse("#e51b3448"), BorderBrush = Ui.BorderBrush, BorderThickness = new Thickness(1), Child = body
        };
        var item = new ListBoxItem
        {
            Name = $"LoginRoleCard{role.Index}", Content = frame, IsEnabled = !role.Locked,
            Padding = new Thickness(0), Margin = new Thickness(0, 0, 8, 6),
            Template = new FuncControlTemplate<ListBoxItem>((_, _) => new ContentPresenter { Content = frame })
        };
        item.PropertyChanged += (_, change) =>
        {
            if (change.Property != ListBoxItem.IsSelectedProperty) return;
            frame.BorderBrush = item.IsSelected ? Ui.Accent : Ui.BorderBrush;
            frame.Background = Brush.Parse(item.IsSelected ? "#f12a5068" : "#e51b3448");
            availability.Text = role.Locked ? "角色已鎖定" : item.IsSelected ? "✓ 已選取" : "點選角色";
        };
        item.Opacity = role.Locked ? .55 : 1;
        AutomationProperties.SetName(item, $"角色 {role.Index}，{role.Name}，等級 {role.Level}，{element}，{(role.Locked ? "已鎖定" : "可選取")}");
        ToolTip.SetTip(item, role.Name);
        return item;
    }
}
