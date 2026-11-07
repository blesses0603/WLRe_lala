// Generated synthetic retained-Python oracle. No official asset success is implied.
using System.Text.Json;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Catalogs.Combat;
public static class CombatCatalogPythonVectors
{
    public const int VectorCount = 195;
    public static IEnumerable<object[]> Sources()
    {
        yield return new object[] { "wlre/services/world/combat_catalog.py", "e98e712296c06611b6578aea7146588d8125bafc5864b9d535474977ffe0a327" };
        yield return new object[] { "wlre/services/world/normal_attack_catalog.py", "05e4cf4ff9f86470c04552cb4dc3d4a8acdbfdda2eb9e4c98ab59a6b66d2e13a" };
        yield return new object[] { "wlre/services/world/itemdata_v1.py", "8ee7e6964e53c3f188ddf9ab761d14e58a238fb01397e4b82369779ca1b549d2" };
        yield return new object[] { "wlre/services/world/item_stack_rules.py", "2ff5e55ae6ec4a1362ea9e2884f132f4af61cabae782a2024f4037f7429cd77c" };
        yield return new object[] { "wlre/services/world/official_lua_codec.py", "d5722eb7d0a4555843cc42108f07b07ee5deb040e50abb5579f9bfc6a5423034" };
        yield return new object[] { "wlre/services/parser_diagnostics.py", "bb9a850e5cbff7504462cc3f24f7a8d192dd0ca96207ea65e18c62c24ea9cbdc" };
    }
    public static IEnumerable<object[]> Cases()
    {
        foreach (var fixture in new[]
        {
            ("combat-catalog-00.json.gz", "8e7055050241bc92118ea7e6afcbc12e1e19f9f90947d006a5257e5ce15e88e5", "2ba1c46157069621a6b0a564428f9675cfe51125d7642196e67da9aa204fbcdd"),
            ("combat-catalog-01.json.gz", "4702855d85b672c3a0fc98f64a7f3c131de910a28e03e0c4465e1efdf77718db", "d0015f5b604659f76a5b1770a8926661a58163e2874d4babc2a0c1368e8e8533"),
            ("combat-catalog-02.json.gz", "6ef1146d9f1ab0a927b1cb0cf119ab882f7f28861fe9fc28f145bcc419139385", "c6c031bb7e70fc72149ad6e48eddd6f52e6dc546e1e8b337d691c85bf6f1274f"),
            ("combat-catalog-03.json.gz", "aaa07b14d7aad9973ef13908f5b2611c49e284d819712d858144fb47079d60bd", "0fe2e4910e37c5645931dce956e99814f9f9d27dcd4bea34d99735336e8ce82c"),
        })
        {
            using var document = JsonDocument.Parse(GzipJson.DecodeResource(
                "Lala.Core.Tests.Catalogs.Combat.Fixtures." + fixture.Item1, fixture.Item2, fixture.Item3));
            foreach (var row in document.RootElement.EnumerateArray())
                yield return new object[] { row.GetProperty("name").GetString()!, row.Clone() };
        }
    }
}
