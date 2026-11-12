namespace Lala.Desktop;

/// <summary>Stable per-user resource storage; resolution performs no filesystem writes.</summary>
internal static class DesktopResourceDirectory
{
    internal static string Resolve() => FromLocalApplicationData(Environment.GetFolderPath(
        Environment.SpecialFolder.LocalApplicationData, Environment.SpecialFolderOption.DoNotVerify));

    internal static string FromLocalApplicationData(string directory)
    {
        // Never fall back to the working directory, installation folder or a shared temp folder.
        if (string.IsNullOrWhiteSpace(directory) || !Path.IsPathFullyQualified(directory))
            throw new IOException("The operating system did not provide a user application-data directory.");
        return Path.GetFullPath(Path.Combine(directory, "LaLa", "Resources"));
    }
}
