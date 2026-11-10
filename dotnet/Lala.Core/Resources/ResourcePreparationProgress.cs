namespace Lala.Core.Resources;

/// <summary>Observed current phase, never a login permit or estimated overall percentage.</summary>
public sealed record ResourcePreparationProgress(string Phase, int? Completed = null, int? Total = null, bool IsFinished = false);
internal sealed class ResourceProgressState
{
    private readonly object gate = new();
    private ResourcePreparationProgress value = new("等待開始");
    internal ResourcePreparationProgress Snapshot { get { lock(gate) return value; } }
    internal void Set(string phase, int? completed = null, int? total = null, bool finished = false)
    {
        if ((completed is null) != (total is null) || completed < 0 || total <= 0 || completed > total)
            throw new ArgumentOutOfRangeException(nameof(completed));
        lock(gate) { if (!value.IsFinished) value = new(phase, completed, total, finished); }
    }
}
