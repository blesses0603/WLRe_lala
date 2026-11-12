using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.Social;
using Xunit;

namespace Lala.Core.Tests.Social.Chat;

public sealed class ChatReceivePipelineTests
{
    [Fact]
    public async Task MalformedLaterFrameLeavesPreviouslyCommittedChatIntact()
    {
        var packet = new Packet(2, 1, new PacketWriter().U32(7).U8(0).U8(2).Raw([65, 0]).U32(0).Build());
        byte[] bytes = [.. WireCodec.Encode(packet), .. WireCodec.Encode(new Packet(2, 1, [7, 0, 0, 0, 0, 2, 1]))];
        await using var attempt = new ReceiveAttempt(new Once(bytes), 0xAD, () => 123, (_, at) => new(at));
        var result = await attempt.RunAsync().WaitAsync(TimeSpan.FromSeconds(10));
        Assert.Equal(ReceiveEnd.InvalidPayload, result.End);
        Assert.True(result.ResourcesReleased);
        Assert.Equal(1, result.Publication.Revision);
        var row = Assert.Single(result.Publication.Snapshot.Chat.Messages);
        Assert.Equal("A", Assert.IsType<ChatMessageEvent>(row.Receipt.Event).Text);
        Assert.Null(row.Receipt.OwnRoleId);
    }

    private sealed class Once(byte[] bytes) : IReceiveTransport
    {
        private int offset;
        public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken token)
        {
            int count = Math.Min(destination.Length, bytes.Length - offset);
            bytes.AsMemory(offset, count).CopyTo(destination); offset += count;
            return ValueTask.FromResult(count);
        }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
