using System.Collections.Immutable;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace Lala.Core.World.Eve;

public sealed record EveNpcRow(ushort Index, uint NpcId, uint X, uint Y, ImmutableArray<byte> EventIds)
{
    public int EventCount => EventIds.Length;
}
public readonly record struct EveInteractionItem(byte Id, ushort TextId, byte DatabaseKind, byte Kind);
public sealed record EveInteractionRow(ushort Index, byte FormKind, ushort LinkNumber, ImmutableArray<EveInteractionItem> Items);
public sealed record EveSceneIndexes(ushort SceneId, ImmutableArray<EveNpcRow> Npcs, ImmutableArray<EveInteractionRow> Interactions);

/// <summary>Immutable, untrusted layout observations only. They do not authorize event execution,
/// packets, resource activation, NPC availability, or shop actions. No input bytes are retained.</summary>
public sealed class EveV115Indexes
{
    public ImmutableArray<EveSceneIndexes> Scenes { get; }
    public bool IncludesNpcs { get; }
    public bool IncludesInteractions { get; }
    public int NpcRecordCount { get; }
    public int InteractionRecordCount { get; }

    internal EveV115Indexes(ImmutableArray<EveSceneIndexes> scenes, bool npcs, bool interactions,
        int npcCount, int interactionCount) =>
        (Scenes, IncludesNpcs, IncludesInteractions, NpcRecordCount, InteractionRecordCount) =
        (scenes, npcs, interactions, npcCount, interactionCount);

    /// <summary>Exact schema-v1 JSON bytes emitted by the retained Python parser. The returned
    /// bytes are immutable; numeric scene properties follow Python sort_keys lexicographic order.</summary>
    public ImmutableArray<byte> ToJsonUtf8(string source, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        bool npcs = source == EveV115Parser.NpcSource;
        if (!(npcs ? IncludesNpcs : source == EveV115Parser.InteractionSource && IncludesInteractions))
            throw new EveDecodeException("Unknown requested Eve index");
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream))
        {
            writer.WriteStartObject();
            writer.WriteNumber("record_count", npcs ? NpcRecordCount : InteractionRecordCount);
            writer.WriteStartObject("scenes");
            foreach (var scene in Scenes.OrderBy(s => s.SceneId.ToString(CultureInfo.InvariantCulture), StringComparer.Ordinal))
            {
                cancellationToken.ThrowIfCancellationRequested();
                writer.WriteStartArray(scene.SceneId.ToString(CultureInfo.InvariantCulture));
                if (npcs)
                    foreach (var row in scene.Npcs)
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        writer.WriteStartObject();
                        writer.WriteNumber("event_count", row.EventCount);
                        writer.WriteStartArray("event_ids");
                        foreach (byte id in row.EventIds) writer.WriteNumberValue(id);
                        writer.WriteEndArray();
                        writer.WriteNumber("index", row.Index);
                        writer.WriteNumber("npc_id", row.NpcId);
                        writer.WriteNumber("x", row.X);
                        writer.WriteNumber("y", row.Y);
                        writer.WriteEndObject();
                    }
                else
                    foreach (var row in scene.Interactions)
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        writer.WriteStartObject();
                        writer.WriteNumber("form_kind", row.FormKind);
                        writer.WriteNumber("index", row.Index);
                        writer.WriteStartArray("items");
                        foreach (var item in row.Items)
                        {
                            cancellationToken.ThrowIfCancellationRequested();
                            writer.WriteStartObject();
                            writer.WriteNumber("database_kind", item.DatabaseKind);
                            writer.WriteNumber("id", item.Id);
                            writer.WriteNumber("kind", item.Kind);
                            writer.WriteNumber("text_id", item.TextId);
                            writer.WriteEndObject();
                        }
                        writer.WriteEndArray();
                        writer.WriteNumber("link_number", row.LinkNumber);
                        writer.WriteEndObject();
                    }
                writer.WriteEndArray();
            }
            writer.WriteEndObject();
            writer.WriteNumber("schema_version", 1);
            writer.WriteString("source", source);
            writer.WriteEndObject();
        }
        cancellationToken.ThrowIfCancellationRequested();
        // Transfer only this newly owned array, never caller memory, without a second output copy.
        var result = ImmutableCollectionsMarshal.AsImmutableArray(stream.ToArray());
        cancellationToken.ThrowIfCancellationRequested();
        return result;
    }
}
