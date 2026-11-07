namespace Lala.Core.Catalogs;

/// <summary>Explicit reviewed field inputs, not an assertion of source provenance.</summary>
public sealed record ItemStackInput(
    int FitType, int Kind, int Special, int AvailableTime, int LimitedTime,
    int UseCount, int Flags2, int FirstAttributeKind, int SecondAttributeKind);

/// <summary>Pure ItemData.CanOverlap parity. Does not authorize inventory operations.</summary>
public static class ItemStackRules
{
    public static bool CanOverlap(int itemId, ItemStackInput row)
    {
        ArgumentNullException.ThrowIfNull(row);
        if (itemId is < 1 or > ushort.MaxValue)
            throw new ArgumentOutOfRangeException(nameof(itemId), "Invalid stack rule item identity");
        if (!Valid(row.FitType) || !Valid(row.Kind) || !Valid(row.Special)
            || !Valid(row.AvailableTime) || !Valid(row.LimitedTime) || !Valid(row.UseCount)
            || !Valid(row.Flags2) || !Valid(row.FirstAttributeKind) || !Valid(row.SecondAttributeKind))
            throw new ArgumentOutOfRangeException(nameof(row), "Missing reviewed stack rule fields");

        int fit = row.FitType;
        if (fit == 10 || itemId is 34106 or 34152 or 34163 or 34164 or 34168 or 34180) return false;
        if (fit is > 0 and < 7 or 11) return false;
        if (row.Kind is 39 or 58) return false;
        if (fit == 9) return false;
        if ((fit is > 0 and < 8 or 10 or 11) && row.AvailableTime > 0) return false;
        if ((fit is > 0 and < 9 or 10 or 11) && (row.LimitedTime > 0 || (row.Flags2 & 1) != 0)) return false;
        if (row.Special == 151 && (row.FirstAttributeKind is 25 or 26 || itemId is 34298 or 34299)) return false;
        if (row.Special == 130 && row.UseCount > 1) return false;
        return row.Kind != 76;
    }

    private static bool Valid(int value) => value is >= 0 and <= ushort.MaxValue;
}
