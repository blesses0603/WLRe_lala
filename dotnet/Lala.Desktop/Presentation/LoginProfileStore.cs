using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Lala.Desktop;

internal sealed record LoginProfile(Guid Id, string Account, string Group, int LineId, string? ProtectedPassword)
{
    public override string ToString() => $"{Account} · {Group} / {LineId % 100}線";
}

/// <summary>Local account preferences. Imported preferences never supply endpoints or credentials.</summary>
internal sealed class LoginProfileStore
{
    internal const int MaximumBytes = 131072;
    private sealed record LocalFile(int Version, LoginProfile[] Accounts);
    private sealed record PortableAccount(string Account, string Group, int LineId);
    private sealed record PortableFile(int Version, PortableAccount[] Accounts);
    private static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };
    private readonly string? file;
    private LoginProfile[] accounts = [];
    internal IReadOnlyList<LoginProfile> Accounts => accounts;
    internal bool CanRememberPassword => OperatingSystem.IsWindows();
    internal LoginProfileStore(string? directory = null, bool inMemory = false)
    {
        if (inMemory) return;
        directory ??= Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LaLa", "Desktop", "Login");
        if (!Path.IsPathFullyQualified(directory)) throw new IOException("Invalid login preferences directory.");
        file = Path.Combine(directory, "accounts.json");
    }
    internal void Load()
    {
        if (file is null || !File.Exists(file)) return;
        if (new FileInfo(file).Length > MaximumBytes) throw new InvalidDataException("Account preferences too large.");
        var value = JsonSerializer.Deserialize<LocalFile>(File.ReadAllBytes(file), Options);
        if (value is null || value.Version != 1 || value.Accounts is null) throw new InvalidDataException("Invalid account preferences.");
        Validate(value.Accounts);
        accounts = value.Accounts;
    }
    private static void Validate(LoginProfile[] rows)
    {
        if (rows.Length > 100 || rows.Any(p => p is null || p.Id == Guid.Empty || string.IsNullOrWhiteSpace(p.Account) ||
            p.Account.Length > 255 || p.Account.Any(char.IsControl) || string.IsNullOrWhiteSpace(p.Group) ||
            p.Group.Length > 80 || p.Group.Any(char.IsControl) || p.LineId is <= 0 or > 65535 || p.ProtectedPassword?.Length > 8192) ||
            rows.Select(p => p.Id).Distinct().Count() != rows.Length ||
            rows.Select(p => (p.Account, p.Group)).Distinct().Count() != rows.Length)
            throw new InvalidDataException("Invalid account preferences.");
    }
    private void Commit(LoginProfile[] rows)
    {
        Validate(rows);
        var bytes = JsonSerializer.SerializeToUtf8Bytes(new LocalFile(1, rows), Options);
        if (bytes.Length > MaximumBytes) throw new InvalidDataException("Account preferences too large.");
        if (file is not null)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(file)!);
            var temporary = file + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try { File.WriteAllBytes(temporary, bytes); File.Move(temporary, file, overwrite: true); }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        accounts = rows;
    }
    internal LoginProfile Save(string account, string group, int lineId, string password, bool rememberPassword)
    {
        if (password.Length > 255) throw new InvalidDataException("Password is too long.");
        var old = accounts.FirstOrDefault(p => p.Account == account && p.Group == group);
        string? encrypted = null;
        if (rememberPassword)
        {
            if (!CanRememberPassword) throw new PlatformNotSupportedException();
            if (password.Length == 0) encrypted = old?.ProtectedPassword ?? throw new InvalidDataException("Password is empty.");
            else
            {
                var bytes = Encoding.UTF8.GetBytes(password);
                try { encrypted = Convert.ToBase64String(WindowsLoginProtection.Transform(bytes, protect: true)); }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
        }
        var row = new LoginProfile(old?.Id ?? Guid.NewGuid(), account, group, lineId, encrypted);
        Commit(accounts.Where(p => p.Id != row.Id).Append(row).ToArray());
        return row;
    }
    internal string ReadPassword(LoginProfile profile)
    {
        if (profile.ProtectedPassword is null) return "";
        var bytes = WindowsLoginProtection.Transform(Convert.FromBase64String(profile.ProtectedPassword), protect: false);
        try { return Encoding.UTF8.GetString(bytes); }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }
    internal void Delete(Guid id) => Commit(accounts.Where(p => p.Id != id).ToArray());
    internal void ForgetPassword(Guid id) => Commit(accounts.Select(p => p.Id == id ? p with { ProtectedPassword = null } : p).ToArray());
    internal byte[] Export() => JsonSerializer.SerializeToUtf8Bytes(new PortableFile(1,
        accounts.Select(p => new PortableAccount(p.Account, p.Group, p.LineId)).ToArray()), Options);
    internal int Import(byte[] bytes)
    {
        if (bytes.Length > MaximumBytes) throw new InvalidDataException("Account preferences too large.");
        var value = JsonSerializer.Deserialize<PortableFile>(bytes, Options);
        if (value is null || value.Version != 1 || value.Accounts is null || value.Accounts.Length > 100) throw new InvalidDataException("Invalid account preferences.");
        var imported = value.Accounts.Select(p => p is null ? throw new InvalidDataException() : new LoginProfile(Guid.NewGuid(), p.Account, p.Group, p.LineId, null)).ToArray();
        Validate(imported);
        var merged = accounts.ToList();
        foreach (var p in imported)
        {
            var index = merged.FindIndex(existing => existing.Account == p.Account && existing.Group == p.Group);
            if (index < 0) merged.Add(p);
            else merged[index] = merged[index] with { LineId = p.LineId };
        }
        Commit(merged.ToArray());
        return imported.Length;
    }
}

internal static class WindowsLoginProtection
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Blob { public int Size; public IntPtr Data; }
    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string? description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref Blob input, IntPtr description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    internal static byte[] Transform(byte[] bytes, bool protect)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var input = new Blob { Size = bytes.Length, Data = Marshal.AllocHGlobal(bytes.Length) };
        Blob output = default;
        try
        {
            Marshal.Copy(bytes, 0, input.Data, bytes.Length);
            bool ok = protect ? CryptProtectData(ref input, "LaLa Desktop login", IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output)
                : CryptUnprotectData(ref input, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error());
            if (output.Size is < 0 or > 16384) throw new CryptographicException();
            var result = new byte[output.Size]; Marshal.Copy(output.Data, result, 0, result.Length); return result;
        }
        finally
        {
            for (int i = 0; i < input.Size; i++) Marshal.WriteByte(input.Data, i, 0);
            Marshal.FreeHGlobal(input.Data);
            if (output.Data != IntPtr.Zero)
            {
                for (int i = 0; i < output.Size; i++) Marshal.WriteByte(output.Data, i, 0);
                LocalFree(output.Data);
            }
        }
    }
}
