using System.Collections.Immutable;

namespace Lala.Core.Inventory;

/// <summary>Immutable receive-only observations. Formatting is metadata-only and no event
/// authorizes inventory, storage, recovery, crafting or movement actions.</summary>
public abstract record InventoryEvent(byte Main, byte Sub)
{
    public abstract string Type { get; }
    public sealed override string ToString() => $"{Type} (S{Main}-{Sub})";
}

public sealed record StorageGarageInitialEvent(ImmutableArray<Protocol.ItemSave> Items) : InventoryEvent(62, 7)
{
    public override string Type => "storage_garage_initial";
}
public sealed record StorageGarageAddEvent(Protocol.ItemSave Item) : InventoryEvent(62, 11)
{
    public override string Type => "storage_garage_add";
}
public sealed record StorageGarageDeleteEvent(byte Index, byte Count) : InventoryEvent(62, 13)
{
    public override string Type => "storage_garage_delete";
}
public sealed record StorageMaterial(ushort Index, ushort ItemId, ushort Count)
{
    public override string ToString() => nameof(StorageMaterial);
}
public abstract record StorageMaterialsEvent(ImmutableArray<StorageMaterial> Items) : InventoryEvent(62, 57);
public sealed record StorageMaterialsInitialEvent(ImmutableArray<StorageMaterial> Items) : StorageMaterialsEvent(Items)
{
    public override string Type => "storage_materials_initial";
}
public sealed record StorageMaterialsAddEvent(ImmutableArray<StorageMaterial> Items) : StorageMaterialsEvent(Items)
{
    public override string Type => "storage_materials_add";
}
public sealed record StorageMaterialsDeleteEvent(ushort Index, ushort Count) : InventoryEvent(62, 57)
{
    public override string Type => "storage_materials_delete";
}
public sealed record StorageMoveResultEvent(byte Result) : InventoryEvent(62, 71)
{
    public override string Type => "storage_move_result";
}
public sealed record StorageParametersEvent(byte GarageSpace, ushort MaterialSpace, ushort MaterialStackLimit) : InventoryEvent(62, 72)
{
    public override string Type => "storage_parameters";
}
public sealed record StorageExpandedEvent(byte Sub, string Target, ushort Value) : InventoryEvent(62, Sub)
{
    public override string Type => "storage_expanded";
}
public sealed record StorageErrorEvent(byte Kind, byte ErrorCode) : InventoryEvent(62, 25)
{
    public override string Type => "storage_error";
}

public sealed record PotionBalanceEvent(string Resource, int Value) : InventoryEvent(23, 208)
{
    public override string Type => "potion_balance";
}
public sealed record PotionBalanceAddEvent(string Resource, int Value) : InventoryEvent(23, 208)
{
    public override string Type => "potion_balance_add";
}
public sealed record PotionUsedEvent(string Resource, ImmutableArray<byte> Targets) : InventoryEvent(23, 208)
{
    public override string Type => "potion_used";
}
public sealed record PotionItemUpdateEvent(byte Index, int Durable, byte? BottleKind = null, byte? NpcIndex = null) : InventoryEvent(23, 208)
{
    public override string Type => "potion_item_update";
}

public sealed record CraftScheduleRow(byte Index, ushort ItemId, double Elapsed, byte Count,
    uint BaseTime, ushort? RecipeId = null)
{
    public override string ToString() => nameof(CraftScheduleRow);
}
public sealed record CraftSnapshotEvent(ImmutableArray<CraftScheduleRow> Rows, byte Active) : InventoryEvent(64, 1)
{
    public override string Type => "craft_snapshot";
}
public sealed record CraftAddedEvent(CraftScheduleRow Row) : InventoryEvent(64, 16)
{
    public override string Type => "craft_added";
}
public sealed record CraftStartedEvent(byte Index) : InventoryEvent(64, 2)
{
    public override string Type => "craft_started";
}
public sealed record CraftPausedEvent(byte Index) : InventoryEvent(64, 3)
{
    public override string Type => "craft_paused";
}
public sealed record CraftDeletedEvent(byte Index) : InventoryEvent(64, 5)
{
    public override string Type => "craft_deleted";
}
public sealed record CraftCompletedEvent(byte Index, ushort Points) : InventoryEvent(64, 4)
{
    public override string Type => "craft_completed";
    public string Reason => "製作完成";
}
public sealed record CraftFailedEvent(byte Sub, byte Index, ushort Points, string Reason) : InventoryEvent(64, Sub)
{
    public override string Type => "craft_failed";
}
public sealed record CraftHumanEvent(byte Index, uint NpcId) : InventoryEvent(64, 10)
{
    public override string Type => "craft_human";
}
public sealed record CraftSwappedEvent(bool Success, byte? First = null, byte? Second = null) : InventoryEvent(64, 25)
{
    public override string Type => "craft_swapped";
}
public sealed record FurnitureRecord(ushort Index, ushort ItemId, ushort X, ushort Y, ushort Z,
    byte Direction, ushort Workbench, ImmutableArray<ushort> Contents, byte Floor, byte Status)
{
    public override string ToString() => nameof(FurnitureRecord);
}
public abstract record CraftFurnitureEvent(byte Sub, string Reason, string RoomAction) : InventoryEvent(62, Sub)
{
    public sealed override string Type => "navigation_geometry_change";
    public string GeometryScope => "house";
    public virtual bool AffectsGeometry => true;
    public bool GeometryRebuilt => false;
    public bool DetailsParsed => true;
}
public sealed record FurnitureSnapshotEvent(uint Owner, ImmutableArray<FurnitureRecord> Furniture)
    : CraftFurnitureEvent(4, "furniture_snapshot", "snapshot")
{
    public override bool AffectsGeometry => !Furniture.IsEmpty;
}
public sealed record FurnitureAddedEvent(byte Kind, FurnitureRecord Furniture)
    : CraftFurnitureEvent(1, "furniture_added", "add");
public sealed record FurnitureRemovedEvent(ushort Index)
    : CraftFurnitureEvent(2, "furniture_removed", "remove");
public sealed record FurnitureRetainedEvent(ushort Index)
    : CraftFurnitureEvent(76, "furniture_retained", "retain");
public sealed record FurnitureToolEvent(byte Kind, ushort Index, ushort ItemId, ushort Workbench)
    : CraftFurnitureEvent(5, "furniture_added", "tool");
