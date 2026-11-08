using System.Security.Cryptography;
using System.Runtime.InteropServices;
using Lala.Core.Sessions;

namespace Lala.Cloud.Acceptance;

/// <summary>Interactive synthetic fixture, never a real-account or secure OS input host.</summary>
internal static class TerminalSyntheticCheck
{
    internal static async Task<int> RunAsync()
    {
        try { return await RunCoreAsync(); }
        catch (Exception)
        {
            try { Console.Error.WriteLine("Terminal synthetic check stopped or failed; no live account mode exists."); }
            catch (Exception) { /* A detached terminal may reject even sanitized output. */ }
            return 1;
        }
    }

    private static async Task<int> RunCoreAsync()
    {
        // Refuse before creating listeners or inspecting any input. No redirected fallback.
        if (Console.IsInputRedirected || Console.IsOutputRedirected || Console.IsErrorRedirected)
        {
            Console.Error.WriteLine("Terminal self-test requires interactive input, output and error.");
            return 2;
        }
        bool priorControlC = Console.TreatControlCAsInput;
        try
        {
            Console.TreatControlCAsInput = true;
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(60));
            await using var verification = new SyntheticPeer(stop.Token);
            await using var formal = new SyntheticPeer(stop.Token);
            using var input = new TerminalSyntheticInput();
            var profile = new AccountConnectionProfile(verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1, 1, 2);
            await using var runner = CloudAcceptanceRunner.CreatePrepared(profile, Guid.NewGuid(), input,
                new AcceptanceOptions { ObservationWindow = TimeSpan.FromSeconds(1), OverallTimeout = TimeSpan.FromSeconds(55) });
            try
            {
                var disclosure = runner.Disclosure!;
                input.Bind(disclosure);
                Console.WriteLine("SYNTHETIC LOOPBACK TEST ONLY. Never enter real credentials. No resources or gameplay.");
                Console.WriteLine("Required fake account: synthetic; required fake password: fake_secret");
                Console.WriteLine("Any other input is rejected locally before either credential leg. Input is masked, not an OS-secure handoff.");
                Console.WriteLine($"Verification TCP recipient: {disclosure.Profile.VerificationEndpoint}");
                Console.WriteLine($"Formal TCP recipient: {disclosure.Profile.FormalEndpoint}");
                Console.WriteLine($"Role: {disclosure.Profile.RoleIndex}; platform: {disclosure.Profile.Platform}; language: {disclosure.Profile.Language}");
                Console.WriteLine($"Transmit XOR: {disclosure.Profile.TransmitXor:X2}; receive XOR: {disclosure.Profile.ReceiveXor:X2}");
                Console.WriteLine($"Local selection marker (not authenticated identity): {disclosure.SelectedIdentity}; generation: {disclosure.Generation}");
                Console.WriteLine($"Attempt: {disclosure.AttemptNumber}; validity: {disclosure.Validity.TotalSeconds} seconds from construction, including this prompt.");
                Console.WriteLine(disclosure.Purpose);
                Console.WriteLine(disclosure.Risk);
                Console.WriteLine("Press Y to acknowledge this exact synthetic run. Any other key declines. Escape/Ctrl-C cancel input.");
                var acknowledgement = await TerminalSyntheticInput.ReadKeyAsync(stop.Token);
                if (acknowledgement.Key != ConsoleKey.Y || (acknowledgement.Modifiers & (ConsoleModifiers.Control | ConsoleModifiers.Alt)) != 0)
                {
                    Console.WriteLine("Declined; no credential transmission.");
                    return 3;
                }
                // Acknowledgement is local terminal interaction, not authenticated permission.
                input.StartPeers = () =>
                {
                    input.Verification = verification.Run(SyntheticClient.Verify);
                    input.Formal = formal.Run(async client =>
                    {
                        await client.EnterWorld();
                        while (runner.Snapshot.Receive != ReceiveEvidence.BaselineObserved)
                            await Task.Delay(10, stop.Token);
                        await client.Send(1, 23);
                        await client.Expect(63, 5, payloadLength: 0);
                        await client.ExpectEof();
                    });
                };
                var operation = runner.RunAsync(stop.Token);
                await Task.WhenAny(operation, input.Completed.Task);
                while (!operation.IsCompleted)
                {
                    // Input is now finished, so only this loop owns terminal reads.
                    if (Console.KeyAvailable)
                    {
                        var key = Console.ReadKey(intercept: true);
                        if (key.Key == ConsoleKey.Escape || key.KeyChar == '\u0003') stop.Cancel();
                    }
                    await Task.Delay(20);
                }
                var result = await operation;
                // Rejected input never returns credentials and therefore never connects.
                if (!input.Accepted)
                {
                    if (verification.HasPending || formal.HasPending || input.OwnedBuffersCleared is false)
                        throw new SyntheticTestFailure();
                    Console.WriteLine("Input rejected or cancelled; no credential transmission; owned buffers cleared.");
                    return 3;
                }
                // Successful input starts peers from the callback before Core can connect.
                if (result.Outcome != AcceptanceOutcome.ProtocolCompleteWithReceiveProgress ||
                    result.Cleanup != CleanupDisposition.Released || result.Resources != ResourceEvidence.Disabled ||
                    !input.OwnedBuffersCleared || input.ReturnedCredentials?.IsDisposed != true)
                    throw new SyntheticTestFailure();
                await Task.WhenAll(input.Verification!, input.Formal!);
                Console.WriteLine("PASS: both exact synthetic credential legs, held receive and heartbeat, cleanup and owned-buffer clearing.");
                return 0;
            }
            finally
            {
                // Cancel peer scripts before runner/peer await-using cleanup, including
                // any failure before the formal peer observes a receive baseline.
                stop.Cancel();
            }
        }
        finally
        {
            // A lost terminal may reject restoration. Never expose platform diagnostics.
            try { Console.TreatControlCAsInput = priorControlC; }
            catch (Exception) { /* Terminal loss cannot promise restoration. */ }
        }
    }
}

internal sealed class TerminalSyntheticInput : IAccountLoginInput, IDisposable
{
    private readonly char[] account = new char[255], password = new char[255];
    private AccountLoginDisclosure? expected;
    private int claimed;
    internal readonly TaskCompletionSource Completed = new(TaskCreationOptions.RunContinuationsAsynchronously);
    internal Action? StartPeers;
    internal Task? Verification, Formal;
    internal bool Accepted { get; private set; }
    internal AccountLoginCredentials? ReturnedCredentials { get; private set; }
    internal bool OwnedBuffersCleared => account.All(c => c == '\0') && password.All(c => c == '\0');

    internal void Bind(AccountLoginDisclosure disclosure)
    {
        if (expected is not null) throw new InvalidOperationException("Input already bound.");
        expected = disclosure;
    }

    public async ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token)
    {
        AccountLoginCredentials? owned = null;
        try
        {
            if (Interlocked.Exchange(ref claimed, 1) != 0 || !ReferenceEquals(disclosure, expected)) return null;
            Console.WriteLine("Fake account input:");
            int a = await ReadFieldAsync(account, token);
            Console.WriteLine("Fake password input:");
            int p = await ReadFieldAsync(password, token);
            token.ThrowIfCancellationRequested();
            if (!account.AsSpan(0, a).SequenceEqual("synthetic") ||
                !password.AsSpan(0, p).SequenceEqual("fake_secret")) return null;
            owned = new(account.AsSpan(0, a), password.AsSpan(0, p));
            token.ThrowIfCancellationRequested();
            StartPeers!();
            Accepted = true;
            ReturnedCredentials = owned;
            var result = owned; owned = null;
            return result;
        }
        catch (Exception) { return null; }
        finally { owned?.Dispose(); Dispose(); Completed.TrySetResult(); }
    }

    internal static async Task<ConsoleKeyInfo> ReadKeyAsync(CancellationToken token)
    {
        while (true)
        {
            token.ThrowIfCancellationRequested();
            if (Console.KeyAvailable)
            {
                var key = Console.ReadKey(intercept: true);
                token.ThrowIfCancellationRequested();
                return key;
            }
            await Task.Delay(20, token);
        }
    }

    private static async Task<int> ReadFieldAsync(char[] buffer, CancellationToken token)
    {
        int length = 0;
        while (true)
        {
            var key = await ReadKeyAsync(token);
            if (key.Key == ConsoleKey.Escape || key.KeyChar == '\u0003') throw new OperationCanceledException();
            if (key.Key == ConsoleKey.Enter)
            {
                Console.WriteLine();
                if (length == 0) throw new InvalidOperationException("Empty synthetic input.");
                return length;
            }
            if (key.Key == ConsoleKey.Backspace)
            {
                if (length > 0) { buffer[--length] = '\0'; Console.Write("\b \b"); }
                continue;
            }
            if (key.KeyChar is < ' ' or > '~' || (key.Modifiers & (ConsoleModifiers.Control | ConsoleModifiers.Alt)) != 0 || length == buffer.Length)
                throw new InvalidOperationException("Invalid synthetic input.");
            buffer[length++] = key.KeyChar;
            Console.Write('*');
        }
    }

    public void Dispose()
    {
        CryptographicOperations.ZeroMemory(MemoryMarshal.AsBytes(account.AsSpan()));
        CryptographicOperations.ZeroMemory(MemoryMarshal.AsBytes(password.AsSpan()));
    }
}
