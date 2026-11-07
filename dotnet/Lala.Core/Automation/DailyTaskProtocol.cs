using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Automation;

public sealed record TaskMarks(byte DailyValue, byte WeeklyValue, byte DailyDone, byte DailyReward,
    byte DailyEventA, byte DailyEventB, ushort WeeklyDone, byte WeeklyReward, byte WeeklyEventA, byte WeeklyEventB);
public abstract record DailyTaskEvent;
public sealed record TaskSnapshot(TaskMarks Marks, ImmutableArray<byte> DailyProgress,
    ImmutableArray<byte> WeeklyProgress, bool DailyEventActive, bool WeeklyEventActive) : DailyTaskEvent;
public sealed record TaskGroups(byte DailyGroup, byte WeeklyGroup) : DailyTaskEvent;
public sealed record TaskMarksChanged(TaskMarks Marks) : DailyTaskEvent;
public sealed record TaskProgress(byte Cycle, byte TaskId, byte Count) : DailyTaskEvent;
public sealed record TaskUnknownUpdate(byte Kind) : DailyTaskEvent;
public sealed record TaskAward(byte Kind, uint Id, uint Value);
public sealed record TaskRewardNotice(byte Kind, ImmutableArray<TaskAward> Awards) : DailyTaskEvent;
public sealed record TaskError(byte Code) : DailyTaskEvent
{
    public string Message => DailyTaskProtocol.ErrorMessage(Code);
}

/// <summary>S124-1/2/3 exact layouts; notices retain the Python opaque unknown-kind/tail policy.</summary>
public static class DailyTaskProtocol
{
    public static string ErrorMessage(byte code) => code switch
    {
        1 => "條件未完成", 2 => "超過群組數量", 3 => "索引超過", 4 => "無任務資料", 5 => "設定標記失敗",
        6 => "檢查給獎失敗", 7 => "給獎失敗", 8 => "已領取", 9 => "無條件種類", 10 => "不在活動期間",
        11 => "積分不足", 12 => "付費獎勵未授權", 13 => "獎勵資料種類無效", 14 => "獎勵資料數量為零",
        15 => "背包空間不足", _ => "未知每日任務錯誤"
    };
    public static DailyTaskEvent? Decode(Packet packet)
    {
        if (packet.Main != 124 || packet.Sub is < 1 or > 5) return null;
        var r = new PacketReader(packet.Payload.Span);
        DailyTaskEvent result;
        switch (packet.Sub)
        {
            case 1:
                var daily = r.U8(); var weekly = r.U8();
                var dp = r.Take(8).ToArray().ToImmutableArray(); var wp = r.Take(12).ToArray().ToImmutableArray();
                var marks = ReadMarksTail(r, daily, weekly);
                var de = r.U8(); var we = r.U8(); r.End();
                if (de > 1 || we > 1) throw new ProtocolException("每日任務活動旗標無效");
                return new TaskSnapshot(marks, dp, wp, de != 0, we != 0);
            case 2: result = new TaskGroups(r.U8(), r.U8()); break;
            case 3:
                var change = r.U8();
                if (change == 1) result = new TaskMarksChanged(ReadMarksTail(r, r.U8(), r.U8()));
                else if (change == 2)
                {
                    var count = r.U8(); var id = r.U8(); var cycle = r.U8();
                    r.End();
                    if (cycle is not (1 or 2) || id < 1 || id > (cycle == 1 ? 8 : 12))
                        throw new ProtocolException("每日任務進度種類或格位無效");
                    return new TaskProgress(cycle, id, count);
                }
                else { r.Take(r.Remaining); return new TaskUnknownUpdate(change); }
                break;
            case 4:
                var kind = r.U8();
                if (kind is not (1 or 2)) return new TaskRewardNotice(kind, []);
                int tail = kind == 2 ? 9 : 0;
                if (r.Remaining < tail || (r.Remaining - tail) % 9 != 0) throw new ProtocolException("每日任務獎勵封包長度無效");
                var awards = ImmutableArray.CreateBuilder<TaskAward>();
                while (r.Remaining > tail) awards.Add(new(r.U8(), r.U32(), r.U32()));
                r.Take(tail); result = new TaskRewardNotice(kind, awards.ToImmutable()); break;
            default: result = new TaskError(r.U8()); break;
        }
        r.End(); return result;
    }
    private static TaskMarks ReadMarksTail(PacketReader r, byte daily, byte weekly) =>
        new(daily, weekly, r.U8(), r.U8(), r.U8(), r.U8(), r.U16(), r.U8(), r.U8(), r.U8());
}
