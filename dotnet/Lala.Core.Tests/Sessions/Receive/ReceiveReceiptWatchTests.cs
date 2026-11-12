using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed partial class ReceiveAttemptTests
{
    [Fact]
    public async Task Automatic_admission_waits_for_the_complete_receive_batch()
    {
        var entered=Signal();var release=Signal();int calls=0;
        var transport=new ScriptedTransport([Wire([Ping,Ping])]);
        await using var attempt=new Lala.Core.Sessions.Receive.ReceiveAttempt(transport,0xAD,()=>1,(_,now)=>new(now),
            beforeCommit:async(_,token)=>{if(++calls==2){entered.TrySetResult();await release.Task.WaitAsync(token);}});
        var run=attempt.RunAsync();
        try
        {
            await entered.Task.WaitAsync(Timeout);
            Assert.Equal(1,attempt.Latest.Revision);Assert.False(attempt.BatchDrained);
            release.TrySetResult();var result=await run.WaitAsync(Timeout);
            Assert.Equal(2,result.Publication.Revision);Assert.True(attempt.BatchDrained);
        }
        finally{release.TrySetResult();}
    }

    [Fact]
    public async Task Whole_frame_processing_preserves_good_commits_before_a_corrupt_tail()
    {
        byte[] input=[..Wire([World,new Packet(26,4,[10,0,0,0])]),0,0,0,0];
        await using var attempt=Attempt(new ScriptedTransport([input]));
        var result=await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(Lala.Core.Sessions.Receive.ReceiveEnd.InvalidFrame,result.End);
        Assert.Equal(2,result.Publication.Revision);Assert.Equal(10u,result.Publication.Snapshot.Local.Session.Gold.Amount);
    }

    [Fact]
    public async Task Active_receipt_is_folded_once_even_when_display_ring_overflows_before_consumer_reads()
    {
        int matched=0;
        var plan=new GameActionPlan(new(33,5),"party","test",s=>s,s=>matched==1)
            {ObserveReceipt=e=>{if(e.Type=="gold_snapshot")matched++;}};
        var watch=new GameReceiptWatch(plan);watch.Arm(0);
        var transport=new PushTransport();await using var attempt=Attempt(transport,readSize:65536);
        var run=attempt.RunAsync();using var lease=attempt.WatchReceipts(watch);
        var packets=new List<Packet>{World,new(26,4,[1,0,0,0])};
        for(int i=0;i<750;i++)packets.Add(new(22,2,[1,0,20,0,30,0,1]));
        transport.Push(Wire(packets));transport.Push([]);
        var result=await run.WaitAsync(Timeout);
        Assert.Equal(Lala.Core.Sessions.Receive.ReceiveEnd.Completed,result.End);
        Assert.Equal(750+2,result.Publication.Revision);
        Assert.DoesNotContain(result.Publication.Events,e=>e.Type=="gold_snapshot");
        Assert.True(watch.Acknowledged(result.Publication.Snapshot));Assert.Equal(1,matched);
    }
    [Fact]
    public void Unarmed_or_pre_write_receipts_cannot_complete_an_operation()
    {
        int matched=0;var watch=new GameReceiptWatch(new(new(33,5),"party","test",s=>s,s=>matched>0){ObserveReceipt=e=>matched++});
        watch.Observe(new(1,33,2,"team_flag",""));Assert.False(watch.Acknowledged(new()));
        watch.Arm(10);watch.Observe(new(10,33,2,"team_flag",""));Assert.False(watch.Acknowledged(new()));
        watch.Observe(new(11,33,2,"team_flag",""));watch.Observe(new(11,33,2,"team_flag",""));Assert.Equal(1,matched);
    }
}
