using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Lala.Desktop;

/// <summary>Local, identity-scoped UI preferences only. No account credentials, game data,
/// runtime readiness or enabled service state is persisted.</summary>
public sealed class DesktopPreferencesStore
{
    public const int MaximumBytes = 131072;
    private readonly string directory;
    internal static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow, MaxDepth = 20
    };

    public DesktopPreferencesStore(string? directory = null) => this.directory = directory ?? Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LaLa", "DesktopPreview");

    public BattleSettingsDraft ReadBattle(string identity)
    {
        var text = Read(identity, "battle");
        return text is null ? new BattleSettingsDraft() : BattleSettingsDraft.Parse(text);
    }
    public void WriteBattle(string identity, BattleSettingsDraft value) => Write(identity, "battle", value.ToJson());
    public ExpeditionPreferences ReadExpedition(string identity)
    {
        var text = Read(identity, "expedition");
        if (text is not null)
        {
            using var document = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 20 });
            BattleSettingsDraft.CheckDuplicates(document.RootElement);
        }
        var value = text is null ? new ExpeditionPreferences() : JsonSerializer.Deserialize<ExpeditionPreferences>(text, JsonOptions)
            ?? throw new InvalidDataException("遠征設定必須為物件。");
        value.Validate(); return value;
    }
    public void WriteExpedition(string identity, ExpeditionPreferences value)
    {
        value.Validate(); Write(identity, "expedition", JsonSerializer.Serialize(value, JsonOptions));
    }

    private string? Read(string identity, string kind)
    {
        var path = FilePath(identity, kind);
        try
        {
            using var stream = File.OpenRead(path);
            return ReadBounded(stream);
        }
        catch (FileNotFoundException) { return null; }
        catch (DirectoryNotFoundException) { return null; }
    }

    public static string ReadBounded(Stream stream)
    {
        using var bytes = new MemoryStream();
        var buffer = new byte[4096];
        int count;
        while ((count = stream.Read(buffer, 0, buffer.Length)) != 0)
        {
            if (bytes.Length + count > MaximumBytes) throw new InvalidDataException("設定檔超過 128 KiB，未載入。");
            bytes.Write(buffer, 0, count);
        }
        return new UTF8Encoding(false, true).GetString(bytes.ToArray()).TrimStart('\ufeff');
    }

    private string FilePath(string identity, string kind)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(identity);
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity)));
        return Path.Combine(directory, key + "." + kind + ".json");
    }

    private void Write(string identity, string kind, string json)
    {
        var path = FilePath(identity, kind);
        var bytes = Encoding.UTF8.GetBytes(json);
        if (bytes.Length > MaximumBytes) throw new InvalidDataException("設定檔超過大小限制。");
        Directory.CreateDirectory(directory);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(temporary, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                stream.Write(bytes); stream.Flush(true);
            }
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}

public sealed record ExpeditionPreferences(decimal MinHours = 0, int MinFaith = 80,
    int MinSuccess = 75, bool AutoClaim = true, ushort? RestoreItemId = null)
{
    public void Validate()
    {
        if (MinHours is < 0 or > 24 || MinFaith is < 1 or > 100 || MinSuccess is < 0 or > 100)
            throw new InvalidDataException("遠征設定超出範圍：時間 0～24 小時、好友度 1～100、成功率 0～100%。");
        if (RestoreItemId == 0) throw new InvalidDataException("恢復物品 ID 必須大於零，或選擇自動。");
    }
}
