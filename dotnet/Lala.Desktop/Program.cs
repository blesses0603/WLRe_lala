using Avalonia;

namespace Lala.Desktop;

internal static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        if (args.Contains("--self-test", StringComparer.Ordinal))
        {
            InspectorSelfTest.Run();
            return;
        }
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<Lala.Presentation.App>()
        .UsePlatformDetect().WithInterFont().LogToTrace();
}
