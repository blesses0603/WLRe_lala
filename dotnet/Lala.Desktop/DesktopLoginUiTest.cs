using System.Net;
using System.Net.Sockets;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using Avalonia.Input;
using Avalonia.VisualTree;
using Lala.Core.Protocol;

namespace Lala.Desktop;

/// <summary>Real UI-to-Core login using only synthetic loopback peers.</summary>
internal static class DesktopLoginUiTest
{
    internal static async Task RunAsync()
    {
        await CatalogAdmissionAsync();
        await ChangedTargetBeforeTcpAsync();
        await ResourceAdmissionAsync();
        await DesktopLoginProfilesTest.RunAsync();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var token = deadline.Token;
        using var verification = new TcpListener(IPAddress.Loopback, 0);
        using var formal = new TcpListener(IPAddress.Loopback, 0);
        verification.Start(); formal.Start();
        using var session = new DesktopSession();
        int opened = 0;
        var profile = new Lala.Core.Sessions.AccountConnectionProfile((IPEndPoint)verification.LocalEndpoint, (IPEndPoint)formal.LocalEndpoint, 173, 173, 1, 1, 2);
        var source = new OfflineDesktopServerCatalog(new(101, "地球", "1線", profile), new(201, "水星", "1線", profile));
        var login = new LoginWindow(session, () => opened++, () => { }, source); login.Show();
        try
        {
            await Until(() => Find<ComboBox>(login, "LoginServer").ItemCount == 2);
            Find<ComboBox>(login, "LoginServer").SelectedIndex = 0;
            await Task.Delay(50, token);
            Fill("LoginAccount", "synthetic"); await Task.Delay(50, token); Fill("LoginPassword", "fake_password");
            Click(login, "LoginSubmit");
            using var verifySocket = await verification.AcceptSocketAsync(token);
            Check(!Find<ComboBox>(login, "LoginLine").IsEnabled && !Find<Button>(login, "LoginSubmit").IsEnabled, "profile and duplicate login frozen during attempt");
            Check(!Find<Button>(login, "LoginSaveIdentity").IsEnabled && !Find<CheckBox>(login, "LoginRememberAccount").IsEnabled,
                "saved account edits are frozen during connection");
            var verifyPeer = new Peer(verifySocket, token);
            await verifyPeer.Expect(63, 7, 0); await verifyPeer.Send(new(63, 7, [0, 0]));
            Check(await verifySocket.ReceiveAsync(new byte[1], SocketFlags.None, token) == 0, "verification socket released");
            using var formalSocket = await formal.AcceptSocketAsync(token);
            var peer = new Peer(formalSocket, token); await peer.Expect(63, 7, 2);
            Check(Dialog() is null, "one Login click reaches both peers without credential confirmation dialogs");
            await peer.Send(new(63, 7, [0, 2]));
            byte[] Role(byte index, string name, bool locked)
            {
                var bytes = System.Text.Encoding.Unicode.GetBytes(name);
                return new PacketWriter().U8(index).U8((byte)bytes.Length).Raw(bytes).U8(18).U8(3)
                    .U32(140).U32(100).U32(80).U32(50).Raw(new byte[8]).U32(0).U8(0).U8(0).U32(0).U32(0)
                    .U8(0).U8(0).U16(1).Raw(new byte[8]).U8(locked ? (byte)1 : (byte)0).Raw(new byte[34]).Build();
            }
            await peer.Send(new(63, 1, Role(1, "介面測試角色", false).Concat(Role(2, "介面測試鎖定角色", true)).ToArray()));
            var roles = Find<ListBox>(login, "LoginRoles");
            await Until(() => roles.ItemCount == 2);
            Check(roles.SelectedIndex == -1 && !Find<Button>(login, "LoginEnterRole").IsEnabled, "no automatic role selection");
            Check(formalSocket.Available == 0, "role selection waits for the user");
            Check(!Find<ListBoxItem>(login, "LoginRoleCard2").IsEnabled, "locked role cards are disabled");
            Check(Find<Image>(login, "LoginRoleElement1").Source == DesktopAssets.Bitmap("elements/Icon_Element004.png"),
                "fire role card uses the original official fire sprite");
            roles.SelectedIndex = 1;
            Check(!Find<Button>(login, "LoginEnterRole").IsEnabled && formalSocket.Available == 0, "a locked card cannot admit role selection or transmit a choice");
            roles.SelectedIndex = 0;
            if (Program.ScreenshotDirectory is {} directory)
            {
                await Task.Delay(80, token); login.UpdateLayout();
                using var bitmap = new Avalonia.Media.Imaging.RenderTargetBitmap(new PixelSize((int)Math.Ceiling(login.Bounds.Width), (int)Math.Ceiling(login.Bounds.Height)), new Vector(96, 96));
                bitmap.Render(login); using var file = File.Create(Path.Combine(directory, "03b-login-role-cards.png"));
                bitmap.Save(file, Avalonia.Media.Imaging.PngBitmapEncoderOptions.Default);
            }
            login.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyDownEvent, Key = Key.Enter });
            await peer.Expect(63, 2, 1);
            await peer.Send(new(3, 1, new PacketWriter().U32(17).U8(0).U16(101).U16(20).U16(30)
                .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build()));
            await peer.Send(new(1, 11)); await peer.Expect(12, 1); await peer.Expect(3, 2);
            await Until(() => opened == 1);
            Check(session.Snapshot.Player?.RoleId == 17 && !session.CanSendGameCommands, "Core publication reaches presentation with commands held");
            Check(string.IsNullOrEmpty(Find<TextBox>(login, "LoginPassword").Text), "password UI cleared after acquisition");
            Check(session.IsConnected && session.CanSendChat, "completed handshake installs the live chat channel");
            await session.SendChatAsync("區域", "介面測試聊天", null);
            var chatPacket = await peer.Expect(2, 2, 0);
            var chatReader = new PacketReader(chatPacket.Payload.Span);
            Check(chatReader.U8() == 0 && chatReader.Unicode8() == "介面測試聊天" && chatReader.U32() == 0 && chatReader.Remaining == 0,
                "chat sends the Python-compatible Unicode payload on the existing formal connection");
            await peer.Send(new(2, 13, [0]));
            await Until(() => session.Snapshot.Chat.LatestFeedback is not null);
            await login.StopAsync();
            Check(await formalSocket.ReceiveAsync(new byte[1], SocketFlags.None, token) == 0, "stop waits for transport release");
            Check(session.Snapshot.Player is null, "stop clears stale account state");
            Check(!session.IsConnected && !session.CanSendChat, "stop retires the chat channel and live connection state");
            // Second attempt: close while waiting for the verification response.
            Fill("LoginAccount", "synthetic"); await Task.Delay(50, token); Fill("LoginPassword", "fake_password"); Click(login, "LoginSubmit");
            using var declinedSocket = await verification.AcceptSocketAsync(token);
            await new Peer(declinedSocket, token).Expect(63, 7, 0); login.Close();
            await Until(() => !login.IsVisible);
            Check(await declinedSocket.ReceiveAsync(new byte[1], SocketFlags.None, token) == 0, "close during verification releases the socket without resending credentials");
            Check(!formal.Pending(), "cancelled login never connects the formal peer");
            Console.WriteLine("Desktop login UI: 18 loopback assertions passed (synthetic credentials only).");
        }
        finally { await login.StopAsync(); login.Close(); }
        void Fill(string name, string value) => Find<TextBox>(login, name).Text = value;
        Window? Dialog() => (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.Windows
            .FirstOrDefault(w => w.Title == "確認本次帳密傳送");
        async Task Until(Func<bool> condition) { while (!condition()) await Task.Delay(10, token); }
    }
    private static async Task ResourceAdmissionAsync()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        using var session = new DesktopSession();
        using var verification = new TcpListener(IPAddress.Loopback, 0);
        using var formal = new TcpListener(IPAddress.Loopback, 0);
        verification.Start(); formal.Start();
        var root = Path.Combine(Path.GetTempPath(), "lala-resource-ui-" + Guid.NewGuid().ToString("N"));
        var profile = new Lala.Core.Sessions.AccountConnectionProfile((IPEndPoint)verification.LocalEndpoint, (IPEndPoint)formal.LocalEndpoint, 173, 173, 1, 3, 0);
        var login = new LoginWindow(session, () => { }, () => { }, new OfflineDesktopServerCatalog(new DesktopServerLine(101, "地球", "1線", profile)), resourceRoot: () => root);
        login.Show();
        Window? Dialog(string title) => (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.Windows.FirstOrDefault(w => w.Title == title);
        async Task Fill()
        {
            Find<ComboBox>(login, "LoginServer").SelectedIndex = 0;
            await Task.Delay(50, deadline.Token);
            Find<TextBox>(login, "LoginAccount").Text = "synthetic";
            await Task.Delay(50, deadline.Token);
            Find<TextBox>(login, "LoginPassword").Text = "fake_password";
        }
        try
        {
            await Fill(); Click(login, "LoginSubmit");
            using var socket = await verification.AcceptSocketAsync(deadline.Token);
            await new Peer(socket, deadline.Token).Expect(63, 7, 0);
            Check(Dialog("確認本次資源下載與寫入") is null, "resource-enabled login connects without a resource confirmation dialog");
            Check(Dialog("確認本次帳密傳送") is null, "resource-enabled login sends credentials without a second confirmation dialog");
            Check(!Directory.Exists(root), "resource-enabled login starts no resource writes before login completes");
            Check(!session.CanSendGameCommands, "automatic connection never admits general game commands");
            await login.StopAsync();
            Check(await socket.ReceiveAsync(new byte[1], SocketFlags.None, deadline.Token) == 0 && !formal.Pending(), "stop during verification releases transport and prevents formal connection");
            Check(!Directory.Exists(root) && string.IsNullOrEmpty(Find<TextBox>(login, "LoginPassword").Text), "cancelled automatic login leaves no resource writes and clears credentials");
            Console.WriteLine("Desktop resource admission: 6 loopback assertions passed; no official HTTP or resource writes.");
        }
        finally { await login.ShutdownAsync(); login.Close(); }
    }
    private static async Task ChangedTargetBeforeTcpAsync()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var verification = new TcpListener(IPAddress.Loopback,0);
        using var formal = new TcpListener(IPAddress.Loopback,0);
        verification.Start(); formal.Start();
        using var session = new DesktopSession();
        var profile = new Lala.Core.Sessions.AccountConnectionProfile((IPEndPoint)verification.LocalEndpoint,(IPEndPoint)formal.LocalEndpoint,173,173,1,3,0);
        var original = new DesktopServerCatalogSnapshot([new(101,"地球","1線",profile)],"synthetic",System.Diagnostics.Stopwatch.GetTimestamp());
        var changed = original with { Lines = [] };
        Check(DesktopLoginTarget.Matches(original,original,101),"same target remains selectable");
        Check(!DesktopLoginTarget.Matches(original,changed,101),"removed line rejected");
        Check(!DesktopLoginTarget.Matches(original,original with { Lines = original.Lines.Concat(original.Lines).ToArray() },101),"ambiguous line rejected");
        var different = new Lala.Core.Sessions.AccountConnectionProfile(profile.VerificationEndpoint,profile.FormalEndpoint,172,173,1,3,0);
        Check(!DesktopLoginTarget.Matches(original,original with { Lines = [new(101,"地球","1線",different)] },101),"changed protocol rejected");
        int calls=0;
        var login=new LoginWindow(session,()=>throw new InvalidOperationException("must not enter world"),()=>{},
            new Catalog(_=>Task.FromResult(++calls==1?original:changed)));
        login.Show();
        try
        {
            Find<ComboBox>(login,"LoginServer").SelectedIndex=0;
            Find<TextBox>(login,"LoginAccount").Text="synthetic";
            Find<TextBox>(login,"LoginPassword").Text="fake_password";
            Click(login,"LoginSubmit");
            while(calls<2) await Task.Delay(10,deadline.Token);
            await login.Pending;
            Check(!verification.Pending()&&!formal.Pending(),"changed discovery rejects before any game TCP");
            Check(string.IsNullOrEmpty(Find<TextBox>(login,"LoginPassword").Text),"failed revalidation clears secrets");
            Console.WriteLine("Desktop login target: 6 offline/loopback checks passed.");
        }
        finally { await login.StopAsync(); login.Close(); }
    }
    private sealed class Catalog(Func<CancellationToken, Task<DesktopServerCatalogSnapshot>> load) : IDesktopServerCatalog
    {
        public Task<DesktopServerCatalogSnapshot> LoadAsync(CancellationToken token) => load(token);
    }
    private static async Task CatalogAdmissionAsync()
    {
        using var session = new DesktopSession();
        var profile = new Lala.Core.Sessions.AccountConnectionProfile(new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 2), 173, 173, 1, 3, 0);
        DesktopServerLine[] rows = [new(101, "地球", "1線", profile), new(102, "地球", "2線", profile), new(201, "水星", "1線", null)];
        var snapshot = new DesktopServerCatalogSnapshot(rows, "synthetic", System.Diagnostics.Stopwatch.GetTimestamp());
        bool fail = false;
        var source = new Catalog(_ => fail ? Task.FromException<DesktopServerCatalogSnapshot>(new IOException("private failure must not appear")) : Task.FromResult(snapshot));
        var login = new LoginWindow(session, () => { }, () => { }, source); login.Show();
        try
        {
            var servers = Find<ComboBox>(login, "LoginServer"); var lines = Find<ComboBox>(login, "LoginLine");
            Check(servers.SelectedIndex == -1 && !Find<Button>(login, "LoginSubmit").IsEnabled, "catalog never chooses a server for the user");
            servers.SelectedIndex = 0;
            Check(lines.ItemCount == 2 && lines.SelectedIndex == 0 && !Find<Button>(login, "LoginSubmit").IsEnabled, "Python group selects its first available line; empty credentials cannot enable login");
            Find<TextBox>(login, "LoginAccount").Text = "synthetic"; Find<TextBox>(login, "LoginPassword").Text = "fake";
            lines.SelectedIndex = 1;
            Check(string.IsNullOrEmpty(Find<TextBox>(login, "LoginAccount").Text) && string.IsNullOrEmpty(Find<TextBox>(login, "LoginPassword").Text), "line change clears both credential fields");
            servers.SelectedIndex = 1;
            Check(!Find<Button>(login, "LoginSubmit").IsEnabled, "unknown protocol profile is blocked");
            servers.SelectedIndex = 0; fail = true; login.StartDiscovery();
            Check(servers.ItemCount == 0 && lines.ItemCount == 0 && !Find<Button>(login, "LoginSubmit").IsEnabled, "refresh failure retires the previous catalog");
            Check(!login.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text?.Contains("private failure") == true), "source failure details are sanitized");
            fail = false; snapshot = snapshot with { ObservedAt = System.Diagnostics.Stopwatch.GetTimestamp() - 301L * System.Diagnostics.Stopwatch.Frequency };
            login.StartDiscovery(); servers.SelectedIndex = 0;
            Check(!Find<Button>(login, "LoginSubmit").IsEnabled, "stale catalog cannot enable login");
            Check(!login.GetVisualDescendants().Any(c => c.Name is "LoginVerification" or "LoginFormal" or "LoginTxXor" or "LoginRxXor"), "technical connection input removed");
        }
        finally { await login.ShutdownAsync(); login.Close(); }
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var finished = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var pending = new LoginWindow(session, () => { }, () => { }, new Catalog(async token =>
        {
            started.SetResult();
            try { await Task.Delay(Timeout.Infinite, token); return snapshot; }
            finally { finished.SetResult(); }
        }));
        pending.Show(); await started.Task;
        await pending.StopAsync();
        Check(finished.Task.IsCompleted && !Find<Button>(pending, "LoginSubmit").IsEnabled, "stop cancels and awaits catalog cleanup");
        pending.Close();
        var gated = new LoginWindow(session, () => { }, () => { }, new OfflineDesktopServerCatalog(rows), resourcesReady: _ => false);
        gated.Show(); Find<ComboBox>(gated, "LoginServer").SelectedIndex = 0;
        Check(!Find<Button>(gated, "LoginSubmit").IsEnabled, "opening login directly cannot bypass retired prelogin resources");
        await gated.ShutdownAsync(); gated.Close();
        Console.WriteLine("Desktop catalog UI: 10 offline assertions passed (no official HTTP or game sockets).");
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
        internal async Task<Packet> Expect(byte main, byte sub, byte? first = null)
        {
            while (packets.Count == 0)
            {
                var bytes = new byte[4096]; int count = await socket.ReceiveAsync(bytes, SocketFlags.None, token);
                Check(count > 0, "expected handshake packet");
                foreach (var packet in decoder.Feed(bytes.AsSpan(0, count))) packets.Enqueue(packet);
            }
            var value = packets.Dequeue(); Check(value.Main == main && value.Sub == sub && (first is null || value.Payload.Span[0] == first), "expected protocol step");
            return value;
        }
        internal async Task Send(Packet packet)
        {
            var bytes = WireCodec.Encode(packet); int sent = 0;
            while (sent < bytes.Length) sent += await socket.SendAsync(bytes.AsMemory(sent), SocketFlags.None, token);
        }
    }
}
