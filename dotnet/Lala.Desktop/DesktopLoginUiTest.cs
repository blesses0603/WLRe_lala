using System.Net;
using System.Net.Sockets;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
using Lala.Core.Protocol;

namespace Lala.Desktop;

/// <summary>Real UI-to-Core login using only synthetic loopback peers.</summary>
internal static class DesktopLoginUiTest
{
    internal static async Task RunAsync()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var token = deadline.Token;
        using var verification = new TcpListener(IPAddress.Loopback, 0);
        using var formal = new TcpListener(IPAddress.Loopback, 0);
        verification.Start(); formal.Start();
        using var session = new DesktopSession();
        int opened = 0;
        var login = new LoginWindow(session, () => opened++, () => { }); login.Show();
        try
        {
            Fill("LoginVerification", verification.LocalEndpoint.ToString()!); Fill("LoginFormal", formal.LocalEndpoint.ToString()!);
            Fill("LoginTx", "173"); Fill("LoginRx", "173"); Fill("LoginPlatform", "1"); Fill("LoginLanguage", "2");
            Fill("LoginAccount", "synthetic"); await Task.Delay(50, token); Fill("LoginPassword", "fake_password");
            Click(login, "LoginSubmit");
            using var verifySocket = await verification.AcceptSocketAsync(token);
            Check(!Find<TextBox>(login, "LoginFormal").IsEnabled && !Find<Button>(login, "LoginSubmit").IsEnabled, "profile and duplicate login frozen during attempt");
            await Confirm();
            var verifyPeer = new Peer(verifySocket, token);
            await verifyPeer.Expect(63, 7, 0); await verifyPeer.Send(new(63, 7, [0, 0]));
            Check(await verifySocket.ReceiveAsync(new byte[1], SocketFlags.None, token) == 0, "verification socket released");
            using var formalSocket = await formal.AcceptSocketAsync(token);
            await Until(() => Dialog() is not null);
            Check(formalSocket.Available == 0, "formal credentials wait for their own confirmation");
            await Confirm();
            var peer = new Peer(formalSocket, token); await peer.Expect(63, 7, 2);
            await peer.Send(new(63, 7, [0, 2]));
            await peer.Send(new(63, 1, new PacketWriter().U8(1).U8(0).U8(1).U8(1)
                .U32(1).U32(1).U32(1).U32(1).Raw(new byte[8]).U32(0).U8(0).U8(0).U32(0).U32(0)
                .U8(0).U8(0).U16(1).Raw(new byte[8]).U8(0).Raw(new byte[34]).Build()));
            var roles = Find<ComboBox>(login, "LoginRoles");
            await Until(() => roles.ItemCount == 1);
            Check(roles.SelectedIndex == -1 && !Find<Button>(login, "LoginEnterRole").IsEnabled, "no automatic role selection");
            Check(formalSocket.Available == 0, "role selection waits for the user");
            roles.SelectedIndex = 0; Click(login, "LoginEnterRole"); await peer.Expect(63, 2, 1);
            await peer.Send(new(3, 1, new PacketWriter().U32(17).U8(0).U16(101).U16(20).U16(30)
                .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build()));
            await peer.Send(new(1, 11)); await peer.Expect(12, 1); await peer.Expect(3, 2);
            await Until(() => opened == 1);
            Check(session.Snapshot.Player?.RoleId == 17 && !session.CanSendGameCommands, "Core publication reaches presentation with commands held");
            Check(string.IsNullOrEmpty(Find<TextBox>(login, "LoginPassword").Text), "password UI cleared after acquisition");
            await login.StopAsync();
            Check(await formalSocket.ReceiveAsync(new byte[1], SocketFlags.None, token) == 0, "stop waits for transport release");
            Check(session.Snapshot.Player is null, "stop clears stale account state");
            // Second attempt: close while waiting for verification approval. No credential bytes.
            Fill("LoginAccount", "synthetic"); await Task.Delay(50, token); Fill("LoginPassword", "fake_password"); Click(login, "LoginSubmit");
            using var declinedSocket = await verification.AcceptSocketAsync(token);
            await Until(() => Dialog() is not null); login.Close();
            await Until(() => !login.IsVisible);
            Check(await declinedSocket.ReceiveAsync(new byte[1], SocketFlags.None, token) == 0, "close during confirmation sends no credentials");
            Check(!formal.Pending(), "cancelled login never connects the formal peer");
            Console.WriteLine("Desktop login UI: 11 loopback assertions passed (synthetic credentials only).");
        }
        finally { await login.StopAsync(); login.Close(); }
        void Fill(string name, string value) => Find<TextBox>(login, name).Text = value;
        Window? Dialog() => (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.Windows
            .FirstOrDefault(w => w.Title == "確認本次帳密傳送");
        async Task Confirm() { await Until(() => Dialog() is not null); Click(Dialog()!, "LoginSendConfirm"); await Until(() => Dialog() is null); }
        async Task Until(Func<bool> condition) { while (!condition()) await Task.Delay(10, token); }
    }
    private static T Find<T>(Control root, string name) where T : Control => root.GetVisualDescendants().OfType<T>().Single(c => c.Name == name);
    private static void Click(Control root, string name)
    {
        var button = Find<Button>(root, name); Check(button.IsEnabled, "clicked control enabled");
        button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
    }
    private static void Check(bool condition, string message) { if (!condition) throw new InvalidOperationException("Synthetic login UI: " + message); }
    private sealed class Peer(Socket socket, CancellationToken token)
    {
        private readonly FrameDecoder decoder = new();
        private readonly Queue<Packet> packets = new();
        internal async Task Expect(byte main, byte sub, byte? first = null)
        {
            while (packets.Count == 0)
            {
                var bytes = new byte[4096]; int count = await socket.ReceiveAsync(bytes, SocketFlags.None, token);
                Check(count > 0, "expected handshake packet");
                foreach (var packet in decoder.Feed(bytes.AsSpan(0, count))) packets.Enqueue(packet);
            }
            var value = packets.Dequeue(); Check(value.Main == main && value.Sub == sub && (first is null || value.Payload.Span[0] == first), "expected protocol step");
        }
        internal async Task Send(Packet packet)
        {
            var bytes = WireCodec.Encode(packet); int sent = 0;
            while (sent < bytes.Length) sent += await socket.SendAsync(bytes.AsMemory(sent), SocketFlags.None, token);
        }
    }
}
