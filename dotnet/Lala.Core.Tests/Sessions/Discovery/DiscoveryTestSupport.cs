using System.Net;
using System.Text;
using System.Text.Json;
using Lala.Core.Resources;
using Lala.Core.Sessions.Discovery;

namespace Lala.Core.Tests.Sessions.Discovery;

internal static class DiscoveryTestSupport
{
    internal const string DataVersion = "1.3.23";
    internal const string Manifest = "1296_2026_11_04_13_34_19_13";
    internal const string Url = "https://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.23/ResourcesPC/ServerList.txt";
    internal static byte[] Bytes(string text) => Encoding.UTF8.GetBytes(text);
    internal static byte[] List(string host = "8.8.8.8", int port = 16988) => JsonSerializer.SerializeToUtf8Bytes(new object[]
    { new { id = 1, name = "測試群組" }, new { id = 101, name = "測試一線", address = host, port } });
    internal static OfficialVersionSnapshot Snapshot(string data = DataVersion, string exe = "1.3.0",
        string dataPackage = Manifest, string mainPackage = Manifest, string checkedAt = "2026-11-05T00:00:00Z")
        => OfficialVersionSnapshot.Parse(JsonSerializer.SerializeToUtf8Bytes(new
        {
            schema_version = 1, origin = "official_pc_version_endpoint", data_ver = data, exe_version = exe,
            packages = new { DataPackage = dataPackage, MainPackage = mainPackage },
            checked_at_utc = checkedAt, assets_ready = false
        }));
    internal sealed class Source : IOfficialServerDiscoverySource
    {
        internal int Observations, Fetches, Disposals;
        internal byte[] Raw = List();
        internal Func<int, CancellationToken, ValueTask<OfficialVersionSnapshot>>? Observe;
        internal Func<string, CancellationToken, ValueTask<byte[]>>? Fetch;
        public ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token)
            { Observations++; return Observe?.Invoke(Observations, token) ?? ValueTask.FromResult(Snapshot()); }
        public ValueTask<byte[]> FetchAsync(string version, CancellationToken token)
        { Fetches++; return Fetch?.Invoke(version, token) ?? ValueTask.FromResult(Raw); }
        public void Dispose() => Disposals++;
    }
    internal sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        internal readonly List<string> Requests = [];
        internal int Disposals;
        internal Action? OnDispose;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Requests.Add(request.RequestUri!.OriginalString);
            return send(request, token);
        }
        protected override void Dispose(bool disposing) { Disposals++; OnDispose?.Invoke(); base.Dispose(disposing); }
    }
    internal sealed class Body(byte[] raw) : MemoryStream(raw, writable: false)
    {
        internal int Reads, Disposals;
        internal bool ThrowRead, ThrowDispose;
        internal Func<CancellationToken, Task>? BeforeRead;
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            Reads++;
            if (BeforeRead is not null) await BeforeRead(cancellationToken);
            if (ThrowRead) throw new IOException("SECRET remote body exception");
            return await base.ReadAsync(buffer, cancellationToken);
        }
        protected override void Dispose(bool disposing)
        {
            Disposals++;
            base.Dispose(disposing);
            if (ThrowDispose) throw new IOException("SECRET body cleanup exception");
        }
    }
    internal sealed class Content(Body body, bool throwDispose = false) : HttpContent
    {
        internal int Opens, Disposals;
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => throw new NotSupportedException();
        protected override Task<Stream> CreateContentReadStreamAsync() { Opens++; return Task.FromResult<Stream>(body); }
        protected override void Dispose(bool disposing)
        {
            Disposals++;
            if (throwDispose) throw new IOException("SECRET content cleanup exception");
            base.Dispose(disposing);
        }
    }
    internal static Handler Versions() => new((request, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
    {
        RequestMessage = request,
        Content = new ByteArrayContent(Bytes(request.RequestUri!.AbsolutePath.EndsWith(".dat", StringComparison.Ordinal)
            ? "[{\"ExeVer\":\"1.3.0\",\"DataVer\":\"1.3.23\"}]" : Manifest))
    }));
    internal static Handler Reply(Content content, HttpStatusCode status = HttpStatusCode.OK,
        Action<HttpResponseMessage>? edit = null) => new((request, _) =>
    {
        var response = new HttpResponseMessage(status) { RequestMessage = request, Content = content };
        edit?.Invoke(response);
        return Task.FromResult(response);
    });
    internal sealed class Clock : TimeProvider
    {
        internal readonly List<Timer> Timers = [];
        public override DateTimeOffset GetUtcNow() => new(2026, 11, 5, 0, 0, 0, TimeSpan.Zero);
        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        { var timer = new Timer(callback, state); Timers.Add(timer); return timer; }
        internal sealed class Timer(TimerCallback callback, object? state) : ITimer
        {
            internal int Disposals;
            internal TimeSpan DueTime;
            public bool Change(TimeSpan dueTime, TimeSpan period) { DueTime = dueTime; return true; }
            internal void Fire() => callback(state);
            public void Dispose() => Disposals++;
            public ValueTask DisposeAsync() { Dispose(); return ValueTask.CompletedTask; }
        }
    }
}
