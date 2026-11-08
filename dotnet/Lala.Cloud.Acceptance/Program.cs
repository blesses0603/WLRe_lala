namespace Lala.Cloud.Acceptance;

internal static class Program
{
    internal const string Help = """
        Lala.Cloud.Acceptance
        Usage: dotnet run --project dotnet/Lala.Cloud.Acceptance -c Release -- --self-test

        --self-test runs synthetic, loopback-only login/held-receive checks with fake credentials.
        This is not official-server or live-account validation. No gameplay or resource bootstrap runs.

        There is deliberately no live CLI mode, default target, profile discovery, or credential input
        through arguments, environment variables, files, stdin, or logs. A future authorized secure host
        must supply an explicit AccountConnectionProfile and its own IAccountCredentialSource directly
        to CloudAcceptanceRunner. That secure credential adapter is not included here. The host must
        authorize the endpoints/account and arrange a trusted network: raw TCP/XOR is not encryption.

        Every runner is one-shot with one attempt. Observation/overall limits request Stop; cleanup
        joins admitted work and may exceed those limits if a credential callback ignores cancellation.
        Results contain only enums/counts. Receive revision advancement is not heartbeat proof.
        """;

    private static async Task<int> Main(string[] args)
    {
        if (args.Length == 0 || args is ["--help"] or ["-h"])
        {
            Console.WriteLine(Help);
            return 0;
        }
        if (args is not ["--self-test"])
        {
            // Never echo unknown arguments: an operator might accidentally pass a secret.
            Console.Error.WriteLine("Unsupported arguments. Only --self-test and help are available.");
            return 2;
        }
        return await SyntheticSelfTests.RunAsync().ConfigureAwait(false);
    }
}
