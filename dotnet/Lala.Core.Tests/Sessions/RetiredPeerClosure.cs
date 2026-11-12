using System.Net.Sockets;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Sessions;

// Shared only by fixtures observing an explicit local retirement, never normal peer EOF.
internal static class RetiredPeerClosure
{
    internal static async Task AssertAsync(Queue<Packet> pending, FrameDecoder decoder, Func<ValueTask<int>> receive)
    {
        Assert.Empty(pending); decoder.Finish();
        // Explicit retirement may reset instead of negotiating a peer-led FIN on Windows.
        // Observe closure without sending into an already-retired socket.
        int count;
        try { count = await receive(); }
        catch (SocketException error) when (error.SocketErrorCode is SocketError.ConnectionReset or SocketError.ConnectionAborted)
        {
            return;
        }
        Assert.Equal(0, count);
    }
}
