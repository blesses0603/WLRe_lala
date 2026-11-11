using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.Gameplay;

public sealed record GameNpcChoice(int Index, ushort TextId, string Text);
public sealed record GameNpcChoiceMenu(ushort Scene, ushort Interaction, string Title, ImmutableArray<GameNpcChoice> Options);

/// <summary>Display-only menu from supplied catalog rows. The account core rechecks all input at sending.</summary>
public static class GameNpcChoices
{
    public static GameNpcChoiceMenu? Read(EveV115Indexes indexes, IReadOnlyDictionary<ushort, TalkDataRow> talks, ushort scene, ushort interaction)
    {
        if (indexes.Scenes.IsDefault) return null;
        var scenes = indexes.Scenes.Where(s => s.SceneId == scene).Take(2).ToArray();
        if (!indexes.IncludesInteractions || scenes.Length != 1) return null;
        var rows = scenes[0].Interactions.Where(r => r.Index == interaction).Take(2).ToArray();
        if (rows.Length != 1 || rows[0].FormKind != 1 || rows[0].Items.IsDefault) return null;
        var items = rows[0].Items; var headers = items.Where(i => i.Kind == 1).ToArray(); var options = items.Where(i => i.Kind == 3).ToArray();
        if (headers.Length != 1 || options.Length is < 1 or > 10 || items.Any(i => i.Kind is not (1 or 3 or 4)) ||
            headers.Concat(options).Any(i => i.DatabaseKind != 1) || !talks.TryGetValue(headers[0].TextId, out var heading)) return null;
        var result = ImmutableArray.CreateBuilder<GameNpcChoice>();
        foreach (var item in options)
        {
            if (!talks.TryGetValue(item.TextId, out var text) || string.IsNullOrWhiteSpace(text.Text)) return null;
            result.Add(new(result.Count, item.TextId, text.Text));
        }
        return new(scene, interaction, heading.Text, result.ToImmutable());
    }
}
