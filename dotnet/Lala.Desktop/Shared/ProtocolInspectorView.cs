using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Lala.Core.Protocol;
using Button = Avalonia.Controls.Button;
using Orientation = Avalonia.Layout.Orientation;

namespace Lala.Presentation;

/// <summary>Offline migration diagnostic. Never opens a socket or sends a command.</summary>
public sealed class ProtocolInspectorView : UserControl
{
    private readonly TextBox _input = new() { AcceptsReturn = true, MinHeight = 140, MaxLength = 196608,
        TextWrapping = TextWrapping.Wrap, PlaceholderText = "輸入 XOR 編碼後的十六進位封包；可使用空白分隔" };
    private readonly TextBox _output = new() { AcceptsReturn = true, IsReadOnly = true, MinHeight = 180,
        TextWrapping = TextWrapping.Wrap, Text = "尚未解析。此工具不會連線遊戲。" };
    private readonly Button _decode = new() { Content = "離線解析", MinHeight = 44 };
    private readonly TextBlock _status = new() { Text = "離線模式 · 不含登入或遊戲操作", TextWrapping = TextWrapping.Wrap };
    private CancellationTokenSource? _pending;

    public ProtocolInspectorView()
    {
        var sample = new Button { Content = "載入合成範例", MinHeight = 44 };
        var cancel = new Button { Content = "取消", MinHeight = 44 };
        sample.Click += (_, _) => { CancelInspection(); _input.Text = Convert.ToHexString(WireCodec.Encode(new Packet(63, 2, new byte[] { 1 }))); };
        cancel.Click += (_, _) => CancelInspection();
        _decode.Click += async (_, _) => await DecodeAsync();
        DetachedFromVisualTree += (_, _) => CancelInspection();
        Content = new ScrollViewer
        {
            Content = new StackPanel
            {
                Margin = new Thickness(24), Spacing = 14,
                Children =
                {
                    new TextBlock { Text = "LaLa  ·  共用核心驗證", FontSize = 26, FontWeight = FontWeight.Bold,
                        Foreground = Brush.Parse("#82CFFF"), TextWrapping = TextWrapping.Wrap },
                    new TextBlock { Text = "C#/.NET ＋ Avalonia｜遷移中，不能替代現有遊戲客戶端。", TextWrapping = TextWrapping.Wrap },
                    new Border { Padding = new Thickness(14), Background = Brush.Parse("#16314D"), CornerRadius = new CornerRadius(8),
                        Child = new TextBlock { Text = "已接入共用封包解析。帳號、戰鬥、地圖、自動任務及 Android 背景連線尚未完成移植。不要在這裡貼登入封包或真實帳密。", TextWrapping = TextWrapping.Wrap } },
                    new TextBlock { Text = "離線封包檢查", FontSize = 20 }, _input,
                    new WrapPanel { Orientation = Orientation.Horizontal, Children = { _decode, sample, cancel } },
                    _status, _output,
                    new TextBlock { Text = "只顯示封包標頭與長度，不顯示 payload。範例是合成測試資料，不會執行角色選擇。輸入不寫入檔案。", TextWrapping = TextWrapping.Wrap }
                }
            }
        };
    }

    public void CancelInspection()
    {
        _pending?.Cancel();
        _pending = null;
        _decode.IsEnabled = true;
        _status.Text = "已停止離線解析；未傳送任何資料。";
    }

    private async Task DecodeAsync()
    {
        CancelInspection();
        var source = new CancellationTokenSource();
        _pending = source;
        _decode.IsEnabled = false;
        _status.Text = "正在背景解析…";
        var input = _input.Text ?? "";
        try
        {
            var result = await Task.Run(() => Inspect(input, source.Token), source.Token);
            if (!ReferenceEquals(_pending, source) || source.IsCancellationRequested) return;
            _output.Text = result;
            _status.Text = "離線解析完成；沒有網路連線。";
        }
        catch (OperationCanceledException) { }
        catch (Exception error) when (error is FormatException or ProtocolException or ArgumentException)
        {
            if (ReferenceEquals(_pending, source))
            {
                _output.Text = "輸入不符合封包格式。請檢查十六進位字元、框架標頭與完整長度。";
                _status.Text = "安全拒絕無效資料；沒有網路連線。";
            }
        }
        finally
        {
            if (ReferenceEquals(_pending, source)) { _pending = null; _decode.IsEnabled = true; }
            source.Dispose();
        }
    }

    public static string Inspect(string input, CancellationToken cancellationToken = default)
    {
        if (input.Length > 196608) throw new ArgumentException("Input is too large.");
        var hex = new StringBuilder(input.Length);
        foreach (var c in input)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!char.IsWhiteSpace(c)) hex.Append(c);
        }
        var bytes = Convert.FromHexString(hex.ToString());
        if (bytes.Length == 0) throw new FormatException("No frame supplied.");
        var decoder = new FrameDecoder();
        var packets = decoder.Feed(bytes);
        decoder.Finish();
        var output = new StringBuilder($"共 {packets.Count} 個完整封包，{bytes.Length} bytes。\n");
        for (var i = 0; i < packets.Count && i < 100; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var packet = packets[i];
            output.AppendLine($"#{i + 1}  C{packet.Main}-{packet.Sub}  payload: {packet.Payload.Length} bytes");
        }
        if (packets.Count > 100) output.AppendLine("僅列出前 100 個標頭。");
        return output.ToString();
    }
}
