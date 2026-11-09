using System.Net;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class SmallMapHttpTests
{
    private sealed class Handler(long size):HttpMessageHandler
    {
        internal int Requests;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken token)
        {Requests++;var response=new HttpResponseMessage(HttpStatusCode.OK){RequestMessage=request,Content=new ByteArrayContent([])};response.Content.Headers.ContentLength=size;return Task.FromResult(response);}
    }
    [Theory][InlineData(43187027)][InlineData(67108864)]
    public async Task Typed_stream_route_accepts_bounded_declared_size_without_widening_legacy_route(long size)
    {
        var index=BundleSourceFixtures.Index("main-valid");index["bundles"]![0]!["file_size"]=size;
        var manifest=YooAssetManifest.Parse(BundleSourceFixtures.Encode(index));var spec=new BundleSourceSpec("1.3.23",manifest,manifest.Bundles[0]);
        var handler=new Handler(size);using var source=new HttpOfficialResourceSource(handler);
        using var response=await source.OpenBundleStreamAsync(spec,default);Assert.Equal(spec.Url(OfficialResourceOrigin.DefaultHost),response.FinalUrl);
        await Assert.ThrowsAsync<ResourceTransportException>(async()=>{using var rejected=await source.OpenAsync(spec.Url(OfficialResourceOrigin.DefaultHost),default);});Assert.Equal(2,handler.Requests);
    }
    [Fact]
    public async Task Typed_route_rejects_over_limit_before_request()
    {
        var index=BundleSourceFixtures.Index("main-valid");index["bundles"]![0]!["file_size"]=67108865L;
        var manifest=YooAssetManifest.Parse(BundleSourceFixtures.Encode(index));var handler=new Handler(67108865L);using var source=new HttpOfficialResourceSource(handler);
        await Assert.ThrowsAsync<BundleSourceException>(async()=>{using var response=await source.OpenBundleStreamAsync(new("1.3.23",manifest,manifest.Bundles[0]),default);});Assert.Equal(0,handler.Requests);
    }
}
