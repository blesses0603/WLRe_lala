using System.Collections.Immutable;
using Lala.Core.Protocol;
using Lala.Core.Social.Ark;

namespace Lala.Core.Gameplay;

internal sealed record GuildSell(ushort Id, byte Kind, byte SaveIndex, byte BaseCount, byte BaseKind, ushort BaseFormula,
    byte SecondKind, ushort SecondFormula, byte LimitKind, byte TotalCount, byte LimitFlag);
internal sealed record ArkAgentSkill(byte Kind, ushort Initial, ushort Add, byte Maximum);
internal sealed record ArkFightDefinition(byte Kind, byte Agent, ImmutableArray<ArkAward> Awards);
internal sealed record GameSocialCatalog(string Identity, ImmutableDictionary<ushort, GuildSell> Sell,
    ImmutableDictionary<ushort, (byte Kind, ushort Value)> Formulas, ImmutableDictionary<byte, byte> GuildLimits,
    ImmutableDictionary<byte, ImmutableArray<ushort>> StarPrices, ImmutableDictionary<byte, ImmutableArray<ArkAgentSkill>> Agents,
    ImmutableDictionary<ushort, ArkFightDefinition> Fights)
{
    internal static GameSocialCatalog Parse(IReadOnlyDictionary<string, byte[]> sources, string identity, CancellationToken token)
    {
        static (PacketReader Reader, int Count) Open(byte[] bytes, int maximum)
        {
            if (bytes.Length > 8 * 1024 * 1024) throw new ProtocolException("社交資料表超過上限。");
            var r = new PacketReader(bytes); int count = r.I32();
            if (count < 1 || count > maximum) throw new ProtocolException("社交資料筆數無效。");
            return (r, count);
        }
        var sell = ImmutableDictionary.CreateBuilder<ushort, GuildSell>();
        var (r, count) = Open(sources["UISellData_C"], 10000);
        for (int n = 0; n < count; n++)
        {
            token.ThrowIfCancellationRequested();
            ushort id = r.U16(); byte kind = r.U8(), save = r.U8(), baseCount = r.U8(), baseKind = r.U8(); ushort formula = r.U16();
            byte secondKind = r.U8(); ushort secondFormula = r.U16(); r.U16(); r.U8(); byte limitKind = r.U8(), total = r.U8(); r.Take(24); byte flag = r.U8();
            if (id == 0 || sell.ContainsKey(id)) throw new ProtocolException("捐獻方案索引無效。");
            sell.Add(id, new(id, kind, save, baseCount, baseKind, formula, secondKind, secondFormula, limitKind, total, flag));
        }
        r.End();
        var formulas = ImmutableDictionary.CreateBuilder<ushort, (byte, ushort)>();
        (r, count) = Open(sources["FormulaData_C"], 65535);
        for (int n = 0; n < count; n++) { token.ThrowIfCancellationRequested(); ushort id = r.U16(); byte kind = r.U8(); ushort value = r.U16(); r.Take(22); if (id == 0 || formulas.ContainsKey(id)) throw new ProtocolException("價格公式索引無效。"); formulas.Add(id, (kind, value)); }
        r.End();
        var limits = ImmutableDictionary.CreateBuilder<byte, byte>();
        (r, count) = Open(sources["OrganizationFunctionData_C"], 255);
        for (int n = 0; n < count; n++) { token.ThrowIfCancellationRequested(); byte level = r.U8(); r.U32(); byte limit = r.U8(); r.Take(30); if (level == 0 || limit == 0 || limits.ContainsKey(level)) throw new ProtocolException("組織上限無效。"); limits.Add(level, limit); }
        r.End();
        var stars = ImmutableDictionary.CreateBuilder<byte, ImmutableArray<ushort>>();
        (r, count) = Open(sources["ArkStarData_C"], 10000);
        for (int n = 0; n < count; n++) { token.ThrowIfCancellationRequested(); byte id = r.U8(); var prices = Enumerable.Range(0, 6).Select(_ => r.U16()).ToImmutableArray(); if (id == 0 || stars.ContainsKey(id)) throw new ProtocolException("星球索引無效。"); stars.Add(id, prices); }
        r.End();
        var agents = ImmutableDictionary.CreateBuilder<byte, ImmutableArray<ArkAgentSkill>>();
        (r, count) = Open(sources["ArkAgentData_C"], 10000);
        for (int n = 0; n < count; n++)
        {
            token.ThrowIfCancellationRequested(); byte id = r.U8(); r.Take(26);
            var skills = ImmutableArray.CreateBuilder<ArkAgentSkill>();
            for (int i = 0; i < 2; i++) { byte kind = r.U8(); r.U16(); r.U32(); ushort initial = r.U16(), add = r.U16(); byte maximum = r.U8(); r.U16(); if (maximum == 0) throw new ProtocolException("情報員技能上限無效。"); skills.Add(new(kind, initial, add, maximum)); }
            if (id == 0 || agents.ContainsKey(id)) throw new ProtocolException("情報員索引無效。"); agents.Add(id, skills.ToImmutable());
        }
        r.End();
        var fightMatches = new List<ImmutableDictionary<ushort, ArkFightDefinition>>();
        foreach (bool tail in new[] { false, true })
        {
            try
            {
                var fights = ImmutableDictionary.CreateBuilder<ushort, ArkFightDefinition>();
                (r, count) = Open(sources["ArkFightData_C"], 10000);
                for (int n = 0; n < count; n++)
                {
                    token.ThrowIfCancellationRequested(); ushort id = r.U16(); byte kind = r.U8(); int size = r.U16();
                    if (size > 1024 || size % 2 != 0) throw new ProtocolException("方舟圖示長度無效。");
                    _ = new System.Text.UnicodeEncoding(false, false, true).GetString(r.Take(size));
                    r.Take(30); byte agent = r.U8();
                    var awards = Enumerable.Range(0, 5).Select(_ => new ArkAward(r.U8(), r.U32(), r.U32())).ToImmutableArray();
                    if (tail && r.U8() > 1) throw new ProtocolException("方舟尾端旗標無效。");
                    if (id == 0 || fights.ContainsKey(id)) throw new ProtocolException("方舟事件索引無效。"); fights.Add(id, new(kind, agent, awards));
                }
                r.End(); fightMatches.Add(fights.ToImmutable());
            }
            catch (Exception error) when (error is ProtocolException or System.Text.DecoderFallbackException) { }
        }
        if (fightMatches.Count != 1 || new ushort[] { 8, 9, 10 }.Any(id => !sell.ContainsKey(id))) throw new ProtocolException("社交資料格式未知或不完整。");
        return new(identity, sell.ToImmutable(), formulas.ToImmutable(), limits.ToImmutable(), stars.ToImmutable(), agents.ToImmutable(), fightMatches[0]);
    }
}
