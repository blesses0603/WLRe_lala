using System.Security.Cryptography;
using System.Text;

namespace Lala.Desktop;

internal static class AccountPreferenceIdentity
{
    internal static string For(string account, string group)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(account);
        ArgumentException.ThrowIfNullOrWhiteSpace(group);
        return "account-v1:" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(account.Length + ":" + account + group)));
    }
}

public sealed record AssistantPreferences(bool Cube = false, bool Rewards = false, bool GuildSign = false,
    bool GuildDonate = false, bool ArkDispatch = false, bool ArkQuestions = false, bool ArkFights = false,
    int DonationPlan = 8, int DonationTarget = 3, int GoldBudget = 450, int ArkHours = 1, int StarBudget = 120)
{
    public void Validate()
    {
        if (DonationPlan is < 8 or > 10 || DonationTarget is < 1 or > 5 || GoldBudget < 0 || ArkHours is < 1 or > 6 || StarBudget < 0)
            throw new InvalidDataException("助手設定超出範圍，請檢查捐獻方案、次數與預算。");
    }
}

public sealed record CraftPlanEntry(ushort ItemId, int Batches);
public sealed record CraftPlanPreferences
{
    public CraftPlanEntry[] Entries { get; init; } = [];
    public void Validate()
    {
        if (Entries is null || Entries.Length > 512 || Entries.Any(x => x is null || x.ItemId == 0 || x.Batches is < 1 or > 255))
            throw new InvalidDataException("製作清單最多 512 項，每項需有效物品 ID 與 1～255 批。");
    }
}
