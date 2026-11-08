using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;

namespace Lala.Cloud.Acceptance;

/// <summary>Test-only loopback peer. It owns and clears every received frame instead of
/// passing synthetic login payloads into a decoder that makes unerasable public copies.</summary>
internal sealed class SyntheticPeer : IAsyncDisposable
{
    private readonly TcpListener listener = new(IPAddress.Loopback, 0);
    private readonly CancellationTokenSource stop;
    private Task? running;
    private Socket? accepted;

    internal SyntheticPeer(CancellationToken token)
    {
        stop = CancellationTokenSource.CreateLinkedTokenSource(token);
        listener.Start();
    }

    internal IPEndPoint Endpoint => (IPEndPoint)listener.LocalEndpoint;
    internal bool HasPending => listener.Pending();

    internal Task Run(Func<SyntheticClient, Task> script)
    {
        if (running is not null) throw new SyntheticTestFailure();
        return running = RunCoreAsync(script);
    }

    private async Task RunCoreAsync(Func<SyntheticClient, Task> script)
    {
        using var socket = await listener.AcceptSocketAsync(stop.Token).ConfigureAwait(false);
        accepted = socket;
        using var client = new SyntheticClient(socket, stop.Token);
        await script(client).ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync()
    {
        await stop.CancelAsync().ConfigureAwait(false);
        accepted?.Dispose();
        listener.Stop();
        if (running is not null)
            try { await running.ConfigureAwait(false); }
            catch (Exception error) when (error is SocketException or IOException or OperationCanceledException or ObjectDisposedException) { }
        stop.Dispose();
    }
}

internal sealed class SyntheticClient(Socket socket, CancellationToken token) : IDisposable
{
    private const byte Xor = 0xAD;
    private readonly byte[] header = new byte[4];

    internal async Task Expect(byte main, byte sub, byte? first = null, int? payloadLength = null)
    {
        byte[]? body = null;
        try
        {
            await ReadExactly(header).ConfigureAwait(false);
            for (int i = 0; i < header.Length; i++) header[i] ^= Xor;
            SyntheticSelfTests.Check(header[0] == 0xC4 && header[1] == 0xC6);
            int length = BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(2));
            SyntheticSelfTests.Check(length is >= 2 and <= 1024);
            body = new byte[length];
            await ReadExactly(body).ConfigureAwait(false);
            for (int i = 0; i < body.Length; i++) body[i] ^= Xor;
            SyntheticSelfTests.Check(body[0] == main && body[1] == sub);
            if (first is { } value) SyntheticSelfTests.Check(body.Length > 2 && body[2] == value);
            if (payloadLength is { } count) SyntheticSelfTests.Check(body.Length == count + 2);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(header);
            if (body is not null) CryptographicOperations.ZeroMemory(body);
        }
    }

    private async Task ReadExactly(Memory<byte> destination)
    {
        int offset = 0;
        while (offset < destination.Length)
        {
            int count = await socket.ReceiveAsync(destination[offset..], SocketFlags.None, token).ConfigureAwait(false);
            SyntheticSelfTests.Check(count != 0);
            offset += count;
        }
    }

    /// <summary>Takes ownership of the supplied, synthetic payload and clears both buffers.</summary>
    internal async Task Send(byte main, byte sub, byte[]? payload = null)
    {
        byte[]? bytes = null;
        try
        {
            int payloadLength = payload?.Length ?? 0;
            bytes = new byte[6 + payloadLength];
            bytes[0] = 0xC4; bytes[1] = 0xC6;
            BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(2), checked((ushort)(2 + payloadLength)));
            bytes[4] = main; bytes[5] = sub;
            payload?.CopyTo(bytes, 6);
            for (int i = 0; i < bytes.Length; i++) bytes[i] ^= Xor;
            int offset = 0;
            while (offset < bytes.Length)
            {
                int count = await socket.SendAsync(bytes.AsMemory(offset), SocketFlags.None, token).ConfigureAwait(false);
                SyntheticSelfTests.Check(count != 0);
                offset += count;
            }
        }
        finally
        {
            if (bytes is not null) CryptographicOperations.ZeroMemory(bytes);
            if (payload is not null) CryptographicOperations.ZeroMemory(payload);
        }
    }

    internal async Task ExpectEof(bool closeSend = false)
    {
        if (closeSend) socket.Shutdown(SocketShutdown.Send);
        // Any extra login, heartbeat, resource request, or gameplay command fails the test.
        byte[] bytes = new byte[1];
        try { SyntheticSelfTests.Check(await socket.ReceiveAsync(bytes, SocketFlags.None, token).ConfigureAwait(false) == 0); }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }

    internal static async Task Verify(SyntheticClient client)
    {
        await client.Expect(63, 7, 0).ConfigureAwait(false);
        await client.Send(63, 7, [0, 0]).ConfigureAwait(false);
        await client.ExpectEof(closeSend: true).ConfigureAwait(false);
    }

    internal async Task EnterWorld(bool initialFirst = false)
    {
        await Expect(63, 7, 2).ConfigureAwait(false);
        await Send(63, 7, [0, 2]).ConfigureAwait(false);
        await Send(63, 1, RolePayload()).ConfigureAwait(false);
        await Expect(63, 2, 1, 1).ConfigureAwait(false);
        if (initialFirst) await Send(1, 11).ConfigureAwait(false);
        await Send(3, 1, WorldPayload()).ConfigureAwait(false);
        if (!initialFirst) await Send(1, 11).ConfigureAwait(false);
        await Expect(12, 1, payloadLength: 0).ConfigureAwait(false);
        await Expect(3, 2, payloadLength: 0).ConfigureAwait(false);
    }

    private static byte[] RolePayload()
    {
        var bytes = new byte[89];
        bytes[0] = 1; bytes[2] = 1; bytes[3] = 1;
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(8), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(12), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(16), 1);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(44), 1);
        return bytes;
    }

    private static byte[] WorldPayload()
    {
        var bytes = new byte[37];
        BinaryPrimitives.WriteUInt32LittleEndian(bytes, 17);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(5), 101);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(7), 20);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(9), 30);
        return bytes;
    }

    public void Dispose() => CryptographicOperations.ZeroMemory(header);
}

internal sealed class SyntheticTestFailure(int assertionLine = 0, AcceptanceResult? result = null)
    : Exception("Synthetic assertion failed.")
{
    internal int AssertionLine { get; } = assertionLine;
    internal AcceptanceResult? Result { get; } = result;
}
