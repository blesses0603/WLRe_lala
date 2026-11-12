using Avalonia;

namespace Lala.Desktop;

internal static class Program
{
    internal static bool UiSmokeTest { get; private set; }
    internal static string? ScreenshotDirectory { get; private set; }
    [STAThread]
    public static void Main(string[] args)
    {
        if (args.Contains("--self-test", StringComparer.Ordinal))
        {
            InspectorSelfTest.Run();
            DesktopSelfTest.Run();
            return;
        }
        UiSmokeTest = args.Contains("--ui-self-test", StringComparer.Ordinal);
        var screenshotIndex = Array.IndexOf(args, "--screenshots");
        if (screenshotIndex >= 0)
        {
            if (!UiSmokeTest || screenshotIndex + 1 >= args.Length)
                throw new ArgumentException("--screenshots requires --ui-self-test and a directory.");
            ScreenshotDirectory = Path.GetFullPath(args[screenshotIndex + 1]);
        }
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<DesktopApplication>()
        .UsePlatformDetect().WithInterFont().LogToTrace();
}
