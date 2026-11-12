using System.Collections.Immutable;
using System.Globalization;
using System.Text;
using System.Text.Json;
using Lala.Core.Resources;

namespace Lala.Core.Sessions.Discovery;

/// <summary>Conservative Python server-list subset. IPv6 and ambiguous IPv4 spellings are unsupported.</summary>
internal static class OfficialServerListParser
{
    internal const int MaximumBytes = 64 * 1024;
    internal const int MaximumRows = 256;
    private static OfficialServerDiscoveryException Invalid() => new(OfficialServerDiscoveryFailure.InvalidDocument);

    internal static ImmutableArray<OfficialServerLineCandidate> Parse(byte[] raw, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (raw.Length is < 1 or > MaximumBytes) throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.Size);
        try
        {
            using var document = ResourceValidation.Parse(raw, MaximumBytes, allowBom: true, cancellationToken: token);
            var array = document.RootElement;
            if (array.ValueKind != JsonValueKind.Array || array.GetArrayLength() is < 1 or > MaximumRows) throw Invalid();
            var ids = new HashSet<int>();
            var groups = new Dictionary<int, string>();
            var pending = new List<(int Id, string Host, int Port)>();
            foreach (var row in array.EnumerateArray())
            {
                token.ThrowIfCancellationRequested();
                if (row.ValueKind != JsonValueKind.Object) throw Invalid();
                var fields = new HashSet<string>(StringComparer.Ordinal);
                foreach (var field in row.EnumerateObject())
                    if (!fields.Add(field.Name)) throw Invalid();
                if (!ResourceValidation.Integer(ResourceValidation.Property(row, "id"), out int id) ||
                    id is < 1 or > 65535 || !ids.Add(id)) throw Invalid();
                string? name = ResourceValidation.String(row, "name");
                if (name is null || ResourceValidation.TextLength(name) is < 1 or > 120) throw Invalid();
                // Python treats ids below 100 as groups and skips id 100. Reject the
                // ambiguous sentinel rather than letting it masquerade as a group.
                if (id == 100) throw Invalid();
                if (id < 100) { groups.Add(id, name); continue; }
                string? host = ResourceValidation.String(row, "address");
                if (host is null || !IsSupportedPublicAddress(host))
                    throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.InvalidEndpoint);
                if (!ResourceValidation.Integer(ResourceValidation.Property(row, "port"), out int port) || port is < 1 or > 65535)
                    throw Invalid();
                pending.Add((id, host, port));
            }
            if (pending.Count == 0) throw Invalid();
            var result = ImmutableArray.CreateBuilder<OfficialServerLineCandidate>(pending.Count);
            foreach (var row in pending.OrderBy(row => row.Id))
            {
                token.ThrowIfCancellationRequested();
                // A referenced id must be a real group (1..99), never another line.
                if (!groups.TryGetValue(row.Id / 100, out string? title)) throw Invalid();
                title = string.Concat(title.EnumerateRunes().Where(r => r.Value >= 32 && r.Value != 127).Take(60));
                string label = title + "｜" + (row.Id % 100).ToString(CultureInfo.InvariantCulture) +
                    "線 (" + row.Id.ToString(CultureInfo.InvariantCulture) + ")";
                result.Add(new(row.Id, label, row.Host, row.Port));
            }
            return result.MoveToImmutable();
        }
        catch (ResourceValidationException) { throw Invalid(); }
        catch (InvalidOperationException) { throw Invalid(); }
    }

    internal static bool IsSupportedPublicAddress(string value)
    {
        // IPAddress.TryParse accepts octal, hex, packed integers and shortened forms.
        // Parse all four decimal octets ourselves before considering routability.
        string[] parts = value.Split('.');
        if (parts.Length != 4) return false;
        Span<byte> octets = stackalloc byte[4];
        for (int i = 0; i < parts.Length; i++)
        {
            string part = parts[i];
            if (part.Length is < 1 or > 3 || part.Length > 1 && part[0] == '0' ||
                part.Any(c => c is < '0' or > '9') ||
                !byte.TryParse(part, NumberStyles.None, CultureInfo.InvariantCulture, out octets[i])) return false;
        }
        int a = octets[0], b = octets[1], c = octets[2];
        return !(a is 0 or 10 or 127 or >= 224 ||
            a == 100 && b is >= 64 and <= 127 || a == 169 && b == 254 ||
            a == 172 && b is >= 16 and <= 31 || a == 192 && b == 168 ||
            a == 192 && b == 0 && c is 0 or 2 || a == 192 && b == 88 && c == 99 ||
            a == 198 && b is 18 or 19 || a == 198 && b == 51 && c == 100 ||
            a == 203 && b == 0 && c == 113);
    }
}
