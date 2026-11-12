using System.Collections.Immutable;
using Avalonia.Controls;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private sealed record AlchemyChoice(byte Index, ushort ItemId, uint Serial, byte SerialVersion, string Label)
    { public override string ToString() => Label; }
    private readonly List<(ComboBox Item, NumericUpDown Count)> alchemyRows = [];
    private ComboBox? alchemyMode;
    private NumericUpDown? alchemyRuns;
    private TextBlock? alchemyStatus;
    private Control AlchemyControls()
    {
        alchemyRows.Clear();
        alchemyMode = Ui.Combo(["無技能", "初級煉金", "中級煉金", "高級煉金"], 0);
        alchemyRuns = new() { Minimum = 1, Maximum = 999, Value = 1, Width = 100 };
        var body = new StackPanel { Spacing = 10 };
        body.Children.Add(Ui.Row(Ui.Text("煉金術"), alchemyMode, Ui.Text("執行次數"), alchemyRuns));
        for (int i = 0; i < 5; i++)
        {
            var choice = Ui.Combo([], -1); choice.MinWidth = 340;
            var count = new NumericUpDown { Minimum = 1, Maximum = 50, Value = 1, Width = 95 };
            alchemyRows.Add((choice, count));
            body.Children.Add(Ui.Row(Ui.Text($"材料 {i + 1}"), choice, count, Ui.Button("清除", () => choice.SelectedIndex = -1)));
        }
        alchemyStatus = Ui.Text("開始前會核對完整材料消耗；每次等伺服器確認後才接續。", color: Ui.Muted);
        body.Children.Add(alchemyStatus);
        body.Children.Add(Ui.Row(Ui.Button("開始煉金", async () =>
        {
            try
            {
                var materials = alchemyRows.Where(row => row.Item.SelectedItem is AlchemyChoice).Select(row =>
                {
                    var selected = (AlchemyChoice)row.Item.SelectedItem!;
                    return new AlchemyIngredient(selected.Index, selected.ItemId, checked((byte)(row.Count.Value ?? 1)), selected.Serial, selected.SerialVersion);
                }).ToImmutableArray();
                await session.SetAutomationAsync("alchemy", true, new() { AlchemyMaterials = materials,
                    AlchemyRuns = checked((int)(alchemyRuns.Value ?? 1)), AlchemyMode = new[] { "none", "basic", "intermediate", "advanced" }[alchemyMode.SelectedIndex] });
            }
            catch (Exception error) when (error is InvalidOperationException or Lala.Core.Protocol.ProtocolException) { actionNote.Text = error.Message; }
        }), Ui.Button("停止後續煉金", async () => await session.SetAutomationAsync("alchemy", false))));
        return Page("煉金", body);
    }
    private void RefreshAlchemyControls()
    {
        if (key != "alchemy") return;
        bool running = session.Automations.GetValueOrDefault("alchemy")?.Enabled == true;
        var s = session.Snapshot; var labels = session.ReadView().Labels;
        var choices = s.Bag.Items.Values.Where(row => row.Index <= 255).OrderBy(row => row.Index)
            .Select(row => new AlchemyChoice((byte)row.Index, row.ItemId, row.OriginalRecord.Serial, row.OriginalRecord.SerialVersion, $"{row.Index} · {labels.Item(row.ItemId)} × {row.Count}")).ToArray();
        foreach (var row in alchemyRows)
        {
            var selected = row.Item.SelectedItem as AlchemyChoice;
            row.Item.ItemsSource = choices;
            row.Item.SelectedItem = selected is null ? null : choices.FirstOrDefault(choice => choice.Index == selected.Index && choice.ItemId == selected.ItemId && choice.Serial == selected.Serial && choice.SerialVersion == selected.SerialVersion);
            row.Item.IsEnabled = row.Count.IsEnabled = !running;
        }
        if (alchemyMode is not null) alchemyMode.IsEnabled = !running;
        if (alchemyRuns is not null) alchemyRuns.IsEnabled = !running;
        if (alchemyStatus is not null && session.Automations.TryGetValue("alchemy", out var status)) alchemyStatus.Text = status.Message;
    }
}
