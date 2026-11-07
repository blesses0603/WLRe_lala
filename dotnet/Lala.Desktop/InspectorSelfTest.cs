using Lala.Core.Protocol;
using Lala.Presentation;

namespace Lala.Desktop;

internal static class InspectorSelfTest
{
    public static void Run()
    {
        var encoded = Convert.ToHexString(WireCodec.Encode(new Packet(63, 2, new byte[] { 1 })));
        var valid = ProtocolInspectorView.Inspect(encoded);
        Require(valid.Contains("C63-2", StringComparison.Ordinal), "Header missing");
        Require(valid.Contains("payload: 1 bytes", StringComparison.Ordinal), "Length mismatch");
        Require(ProtocolInspectorView.Inspect($"  {encoded}\n") == valid, "Whitespace mismatch");
        var joined = ProtocolInspectorView.Inspect(encoded + encoded);
        Require(joined.Contains("共 2 個完整封包", StringComparison.Ordinal), "Batch mismatch");
        Reject<FormatException>(() => ProtocolInspectorView.Inspect("GG"));
        Reject<FormatException>(() => ProtocolInspectorView.Inspect(""));
        Reject<ProtocolException>(() => ProtocolInspectorView.Inspect(encoded[..^2]));
        Reject<ArgumentException>(() => ProtocolInspectorView.Inspect(new string('A', 196609)));
        using var canceled = new CancellationTokenSource();
        canceled.Cancel();
        Reject<OperationCanceledException>(() => ProtocolInspectorView.Inspect(encoded, canceled.Token));
        Console.WriteLine("Inspector self-test: 9 checks passed. Offline only; no UI/native platform acceptance.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
    private static void Reject<T>(Action action) where T : Exception
    {
        try { action(); } catch (T) { return; }
        throw new InvalidOperationException($"Expected {typeof(T).Name}.");
    }
}
