using System.Text;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Social;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed partial class AccountConnectionRuntimeTests
{
    [Fact]
    public async Task PublicFinalNonChatPublicationKeepsCoalescedReceiptsAndNextGenerationStartsEmpty()
    {
        var session = new AccountSession();
        var first = await Round(true);
        var historical = first.State.Chat;
        Assert.Equal(3, historical.Messages.Length);
        Assert.Equal(3, historical.ReceivedMessageCount);
        Assert.All(historical.Messages, row => Assert.Equal(17u, row.Receipt.OwnRoleId));
        Assert.Equal(new[] { "known-local", "known-local", "known-cross" }, historical.Messages.Select(row => row.Name));
        Assert.Equal("duplicate-private", Assert.IsType<ChatMessageEvent>(historical.Messages[0].Receipt.Event).Text);
        var duplicate = Assert.IsType<ChatMessageEvent>(historical.Messages[1].Receipt.Event);
        Assert.Equal("duplicate-private", duplicate.Text); Assert.Equal(7u, duplicate.RoleId);
        Assert.Empty(duplicate.Items);
        Assert.Equal(ChatNameScope.Server(0), historical.Messages[2].Scope);
        Assert.IsType<ChatResultEvent>(historical.LatestFeedback!.Event);
        Assert.IsType<ChatProfileEvent>(historical.LatestProfile!.Event);
        Assert.Equal("heartbeat_request", first.State.Observation!.EventType);
        Assert.True(first.ResourceHeld); Assert.False(first.State.IsCompleteState);
        var second = await Round(false);
        Assert.NotEqual(first.Attempt, second.Attempt);
        Assert.Empty(second.State.Chat.Messages);
        Assert.Empty(second.State.Chat.Names.Names);
        Assert.Null(second.State.Chat.LatestFeedback); Assert.Null(second.State.Chat.LatestProfile);
        Assert.Equal(3, historical.Messages.Length);
        Assert.Equal("known-local", historical.Messages[0].Name);

        async Task<AccountReceivePublication> Round(bool includeChat)
        {
            await using var verification = new Peer(); await using var formal = new Peer();
            var finish = Signal(); var ready = Signal();
            var verify = verification.Run(Verify);
            var serve = formal.Run(async client =>
            {
                await EnterWorld(client);
                if (includeChat)
                {
                    var same = new Packet(2, 1, new PacketWriter().U32(7).U8(0).Raw(ChatText("duplicate-private")).U32(0).Build());
                    var cross = new Packet(2, 28, new PacketWriter().U16(0).U32(7).Raw(ChatText("known-cross")).Raw(new byte[16])
                        .U8(0).Raw(ChatText("cross-private")).U32(0).Build());
                    var profile = new Packet(2, 18, new PacketWriter().U32(7).U8(1).Raw(ChatText("known-local")).Raw(new byte[16]).U8(1).Build());
                    // Multiple frames and a final unrelated commit are sent before the host reads.
                    await client.Send(same, same, cross, profile, new Packet(2, 21, new PacketWriter().U32(7).Build()),
                        new Packet(2, 13, [0]), new Packet(1, 23));
                }
                else await client.Send(new Packet(1, 23));
                await client.Expect(63, 5); ready.SetResult();
                // The runtime has already stopped and released the connection before finish.
                await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
            });
            long generation = session.Begin("synthetic", "loopback-chat").Generation;
            await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
                new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "synthetic"))));
            var running = runtime.RunAsync();
            await ready.Task.WaitAsync(Guard);
            await WaitFor(() => runtime.Publication?.Revision == (includeChat ? 11 : 5));
            var publication = runtime.Publication!;
            Assert.True(runtime.Snapshot.ResourceHeld); Assert.False(runtime.Snapshot.CanSendCommands);
            Assert.False(session.ConfirmResources(generation, "same", "same", true));
            runtime.Stop(); Assert.Null(runtime.Publication);
            var result = await running.WaitAsync(Guard); Assert.True(result.ResourcesReleased);
            finish.SetResult(); await Task.WhenAll(verify, serve).WaitAsync(Guard);
            return publication;
        }
    }

    private static byte[] ChatText(string value)
    {
        byte[] bytes = Encoding.Unicode.GetBytes(value);
        return new PacketWriter().U8(bytes.Length).Raw(bytes).Build();
    }
}
