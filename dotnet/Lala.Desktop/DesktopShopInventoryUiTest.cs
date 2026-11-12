using System.Collections.Immutable;
using System.Reflection;
using Avalonia.Controls;
using Avalonia;
using Avalonia.Media.Imaging;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.State;
using Lala.Core.World.Eve;

namespace Lala.Desktop;

internal static class DesktopShopInventoryUiTest
{
    internal static async Task RunAsync()
    {
        int checks=0;
        void Check(bool condition,string message){if(!condition)throw new InvalidOperationException("Shop/inventory UI: "+message);checks++;}
        async Task Until(Func<bool> ready){using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(10));while(!ready())await Task.Delay(10,timeout.Token);}
        T Control<T>(Window window,string name) where T:Control=>window.GetVisualDescendants().OfType<T>().Single(c=>c.Name==name);
        void Click(Window window,string name)=>Control<Button>(window,name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        ItemActionConfirmationWindow? Confirm()=>((IClassicDesktopStyleApplicationLifetime)Avalonia.Application.Current!.ApplicationLifetime!).Windows.OfType<ItemActionConfirmationWindow>().SingleOrDefault();
        async Task Capture(Window window,string name)
        {
            if(Program.ScreenshotDirectory is not {} directory)return;
            await Task.Delay(50);
            using var bitmap=new RenderTargetBitmap(new PixelSize((int)Math.Ceiling(window.Bounds.Width),(int)Math.Ceiling(window.Bounds.Height)),new Vector(96,96));
            bitmap.Render(window);using var output=File.Create(Path.Combine(directory,name+".png"));bitmap.Save(output,PngBitmapEncoderOptions.Default);
        }
        using var session=new DesktopSession();var(seed,labels)=DesktopTestData.Create();var first=seed.Bag.Items.OrderBy(p=>p.Key).First();
        var details=(ReviewedItemDetails)Activator.CreateInstance(typeof(ReviewedItemDetails),true)!;
        typeof(ReviewedItemDetails).GetProperty(nameof(ReviewedItemDetails.Kind))!.SetValue(details,(byte)23);
        typeof(ReviewedItemDetails).GetProperty(nameof(ReviewedItemDetails.FitType))!.SetValue(details,(byte)8);
        var args=new object?[17];
        args[0]=typeof(EveV115Indexes).GetConstructors(BindingFlags.NonPublic|BindingFlags.Instance).Single().Invoke([
            ImmutableArray.Create(new EveSceneIndexes(DesktopTestData.SceneId,[],[new(7,3,0,[new(8,first.Value.ItemId,2,3),new(0,0,0,4)])])),false,true,0,1]);
        args[1]=new Dictionary<ushort,ItemDataRow>{{first.Value.ItemId,new(first.Value.ItemId,"測試商品",10,3,0,0,0,details)}};
        args[2]=new Dictionary<ushort,TalkDataRow>();args[3]=new Dictionary<uint,string>();
        args[5]=new Dictionary<ushort,StageDataRow>();args[7]=new Dictionary<ushort,string>();args[9]=new Dictionary<ushort,ExpeditionNpcData>();args[10]=new Dictionary<string,string>();
        var catalog=(OfflineRuntimeCandidate)typeof(OfflineRuntimeCandidate).GetConstructors(BindingFlags.NonPublic|BindingFlags.Instance).Single().Invoke(args);
        var dialogue=seed.Local.Session with {NpcDialogue=new(){Active=true,Phase="choice_unavailable",Scene=DesktopTestData.SceneId,NpcIndex=1,NpcId=12,EffectType=6,EffectPacket=42,OptionIndex=7},EventFlow=new(){Blocked=true}};
        var state=new ServiceStateSnapshot(local:new(dialogue,seed.Local.World,Lala.Core.Battle.BattleEventSnapshot.Empty),bag:seed.Bag,playerKnowledge:seed.PlayerKnowledge,companions:seed.Companions);
        session.Publish(session.Generation,1,state,labels);session.SetCatalogs(session.Generation,catalog);session.SetConnected(session.Generation,true);
        session.SetGameplayState(session.Generation,true,null,[],ImmutableDictionary<string,GameAutomationStatus>.Empty,new(false,"等待"));
        var sent=new List<GameAction>();session.AttachGameSender(session.Generation,a=>{sent.Add(a);return Task.CompletedTask;});
        var npc=new NpcInteractionWindow(session);var inventory=new InventoryWindow(session);npc.Show();inventory.Show();
        try
        {
            await Task.Delay(80);
            var products=Control<ListBox>(npc,"NpcShopProducts");Check(products.ItemCount==1,"verified shop offer appears");products.SelectedIndex=0;
            Check(Control<Button>(npc,"NpcShopBuy").IsEnabled,"verified live shop enables buy");
            Control<TextBox>(npc,"NpcShopQuantity").Text="3";await Capture(npc,"37-npc-shop");Click(npc,"NpcShopBuy");await Until(()=>Confirm() is not null);
            Check(sent.Count==0,"opening purchase confirmation never sends");Click(Confirm()!,"ItemActionCancel");await Until(()=>Confirm() is null);await Task.Delay(30);
            Check(sent.Count==0,"cancelling purchase never sends");Click(npc,"NpcShopBuy");await Until(()=>Confirm() is not null);Click(Confirm()!,"ItemActionConfirm");await Until(()=>sent.Count==1);
            Check(sent[0] is{Kind:"shop",Operation:"buy",Index:8,Count:3,X:7,Key:"42",ExpectedPrice:10},"purchase carries exact offer, quantity, menu receipt and displayed price");
            inventory.SelectBagItem(first.Key);await Capture(inventory,"38-inventory-actions");Click(inventory,"InventoryBagSell");await Until(()=>Confirm() is not null);Click(Confirm()!,"ItemActionConfirm");await Until(()=>sent.Count==2);
            Check(sent[1].Kind=="shop"&&sent[1].Operation=="sell"&&sent[1].Key=="42"&&sent[1].ItemSerial==first.Value.OriginalRecord.Serial,"shop sale carries original slot serial and live menu identity");
            var normal=new ServiceStateSnapshot(local:new(seed.Local.Session,seed.Local.World,Lala.Core.Battle.BattleEventSnapshot.Empty),bag:seed.Bag,playerKnowledge:seed.PlayerKnowledge,companions:seed.Companions);
            session.Publish(session.Generation,2,normal,labels);await Task.Delay(30);Click(inventory,"InventoryBagUse");await Until(()=>sent.Count==3);
            Check(sent[2].Kind=="inventory_item"&&sent[2].Operation=="use"&&sent[2].RecipientId==normal.Player?.RoleId,"ordinary use binds current selected role");
            var sort=Control<ComboBox>(inventory,"InventorySort");sort.SelectedIndex=1;Check(inventory.SelectedBagIndex==first.Key,"display sorting preserves physical slot identity");
            session.Reset("新連線");await Task.Delay(30);Check(!Control<Button>(npc,"NpcShopBuy").IsEnabled&&!Control<Button>(npc,"NpcShopSell").IsEnabled,"old shop cannot act after account generation changes");
            Console.WriteLine($"Desktop shop/inventory UI: {checks} checks passed; synthetic sender only, no official account or spending.");
        }
        finally{Confirm()?.Close(false);inventory.Close();npc.Close();}
    }
}
