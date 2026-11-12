using Lala.Core.Gameplay;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class GameActionHistoryTests
{
    [Fact]
    public void Status_updates_replace_the_same_operation_without_collapsing_another_operation_or_error()
    {
        var history=new GameActionHistory();object first=new(),second=new();
        history.Record(first,17,new("戰鬥操作","正在送出",true));
        history.Record(second,17,new("戰鬥操作","已停止重送",Uncertain:true));
        history.Record(first,17,new("戰鬥操作","等待確認",true));
        history.Record(first,17,new("戰鬥操作","已確認"));
        Assert.Equal(2,history.Lines.Length);
        Assert.Contains("已確認",history.Lines[0]);Assert.Contains("已停止重送",history.Lines[1]);
        Assert.DoesNotContain(history.Lines,line=>line.Contains("正在送出")||line.Contains("等待確認"));
    }

    [Fact]
    public void History_is_bounded_and_scoped_to_the_selected_character()
    {
        var history=new GameActionHistory();
        for(int i=0;i<250;i++)history.Record(new(),17,new("操作",$"結果 {i}"));
        Assert.Equal(200,history.Lines.Length);Assert.EndsWith("結果 50",history.Lines[0]);
        history.Record(new(),18,new("操作","另一角色"));
        Assert.Single(history.Lines);Assert.Equal(18u,history.Role);
    }
}
