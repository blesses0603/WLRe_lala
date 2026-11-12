using System.Net.Sockets;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed partial class AccountConnectionRuntimeTests
{
    [Fact]
    public async Task PreparedRetirementClosureAcceptsEofAndRejectsAnyByte()
    {
        await RetiredPeerClosure.AssertAsync(new(), new(), () => ValueTask.FromResult(0));
        await Assert.ThrowsAnyAsync<Xunit.Sdk.XunitException>(() =>
            RetiredPeerClosure.AssertAsync(new(), new(), () => ValueTask.FromResult(1)));
    }

    [Theory]
    [InlineData(SocketError.ConnectionReset)]
    [InlineData(SocketError.ConnectionAborted)]
    public async Task PreparedRetirementClosureAcceptsOnlyTypedRetirementErrors(SocketError code)
    {
        await RetiredPeerClosure.AssertAsync(new(), new(), () =>
            ValueTask.FromException<int>(new SocketException((int)code)));
    }

    [Fact]
    public async Task PreparedRetirementClosurePropagatesUnrelatedFailures()
    {
        Exception[] failures = [new SocketException((int)SocketError.TimedOut),
            new SocketException((int)SocketError.OperationAborted),
            new IOException("other IO"),
            new IOException("wrapped reset", new SocketException((int)SocketError.ConnectionReset)),
            new TimeoutException(), new OperationCanceledException(), new TaskCanceledException(),
            new ObjectDisposedException("synthetic"), new Xunit.Sdk.XunitException("assertion")];
        foreach (var error in failures)
        {
            Assert.Same(error, await Record.ExceptionAsync(() =>
                RetiredPeerClosure.AssertAsync(new(), new(), () => ValueTask.FromException<int>(error))));
            // Synchronous failures from the receive operation must also propagate unchanged.
            Assert.Same(error, await Record.ExceptionAsync(() =>
                RetiredPeerClosure.AssertAsync(new(), new(), () => throw error)));
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task PreparedRetirementClosureRejectsBufferedDataBeforeReceiving(bool incomplete)
    {
        var pending = new Queue<Packet>(); var decoder = new FrameDecoder();
        var bytes = WireCodec.Encode(new Packet(63, 7, [0, 2]));
        foreach (var packet in decoder.Feed(incomplete ? bytes.AsSpan(0, bytes.Length - 1) : bytes))
            pending.Enqueue(packet);
        bool received = false;
        ValueTask<int> Receive()
        {
            received = true;
            return ValueTask.FromException<int>(new SocketException((int)SocketError.ConnectionReset));
        }
        if (incomplete)
            await Assert.ThrowsAsync<ProtocolException>(() => RetiredPeerClosure.AssertAsync(pending, decoder, Receive));
        else
            await Assert.ThrowsAnyAsync<Xunit.Sdk.XunitException>(() => RetiredPeerClosure.AssertAsync(pending, decoder, Receive));
        Assert.False(received);
    }
}
