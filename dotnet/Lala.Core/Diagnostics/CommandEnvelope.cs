using System.Collections;
using Lala.Core.Protocol;

namespace Lala.Core.Diagnostics;

/// <summary>Ingress shape checks only. Each command still needs its game-specific validator.</summary>
public static class CommandEnvelope
{
    public static string Validate(object? command)
    {
        if (!TryType(command, out var value))
            throw new ProtocolException("指令格式錯誤：預期含有 type 的資料物件");
        if (value is not string name || name.Length == 0 || CodePointCount(name) > 64)
            throw new ProtocolException("指令格式錯誤：type 必須是有效的指令名稱");
        return name;
    }

    /// <summary>Never formats arbitrary envelope values, payloads, or credentials for diagnostics.</summary>
    public static string RejectedType(object? command)
    {
        if (!TryType(command, out var value) || value is not string name || name.Length > 64)
            return "invalid";
        bool hasAlphanumeric = false;
        foreach (char c in name)
        {
            if (c == '_') continue;
            if (c is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9')
                hasAlphanumeric = true;
            else return "invalid";
        }
        return hasAlphanumeric ? name : "invalid";
    }

    private static bool TryType(object? command, out object? value)
    {
        // Accept typed read-only snapshots and legacy dictionary envelopes, not arbitrary objects.
        if (command is IReadOnlyDictionary<string, object?> snapshot)
        { snapshot.TryGetValue("type", out value); return true; }
        if (command is IDictionary mapping)
        { value = mapping.Contains("type") ? mapping["type"] : null; return true; }
        value = null;
        return false;
    }

    private static int CodePointCount(string value)
    {
        // Python len(str) counts Unicode code points, not UTF-16 code units.
        int count = 0;
        for (int i = 0; i < value.Length; i++, count++)
            if (char.IsHighSurrogate(value[i]) && i + 1 < value.Length && char.IsLowSurrogate(value[i + 1])) i++;
        return count;
    }
}
