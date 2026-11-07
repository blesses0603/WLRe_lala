// Generated from retained Python command_envelope and connection_health; synthetic only.
namespace Lala.Core.Tests.Diagnostics;
public static class PythonDiagnosticVectors
{
    public static IEnumerable<object?[]> CommandCases()
    {
        yield return new object?[] { null, null, "指令格式錯誤：type 必須是有效的指令名稱", "invalid" };
        yield return new object?[] { 42, null, "指令格式錯誤：type 必須是有效的指令名稱", "invalid" };
        yield return new object?[] { false, null, "指令格式錯誤：type 必須是有效的指令名稱", "invalid" };
        yield return new object?[] { "", null, "指令格式錯誤：type 必須是有效的指令名稱", "invalid" };
        yield return new object?[] { "walk", "walk", null, "walk" };
        yield return new object?[] { "start_auto_battle", "start_auto_battle", null, "start_auto_battle" };
        yield return new object?[] { "_", "_", null, "invalid" };
        yield return new object?[] { "__", "__", null, "invalid" };
        yield return new object?[] { "_x_", "_x_", null, "_x_" };
        yield return new object?[] { "0", "0", null, "0" };
        yield return new object?[] { "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", null, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" };
        yield return new object?[] { "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", null, "指令格式錯誤：type 必須是有效的指令名稱", "invalid" };
        yield return new object?[] { "技能", "技能", null, "invalid" };
        yield return new object?[] { "😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀", "😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀", null, "invalid" };
        yield return new object?[] { "😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀", null, "指令格式錯誤：type 必須是有效的指令名稱", "invalid" };
        yield return new object?[] { "a b", "a b", null, "invalid" };
        yield return new object?[] { "a\nb", "a\nb", null, "invalid" };
        yield return new object?[] { "secret:login=dummy", "secret:login=dummy", null, "invalid" };
        yield return new object?[] { "x\u0000y", "x\u0000y", null, "invalid" };
        yield return new object?[] { "１２", "１２", null, "invalid" };
        yield return new object?[] { "Ω", "Ω", null, "invalid" };
        yield return new object?[] { "é", "é", null, "invalid" };
    }
    public static IEnumerable<object?[]> HealthSequence()
    {
        yield return new object?[] { "publish", 0, false, "waiting", 0, null, 0, false };
        yield return new object?[] { "publish", 0.5d, false, null, null, null, null, false };
        yield return new object?[] { "receive", 0.5d, false, null, null, null, null, false };
        yield return new object?[] { "publish", 0.5d, true, "receiving", 0, 1700000000.0d, 1, false };
        yield return new object?[] { "publish", 1.0d, false, null, null, null, null, false };
        yield return new object?[] { "publish", 1.5d, false, "receiving", 1.0d, 1700000000.0d, 1, false };
        yield return new object?[] { "publish", 120.5d, false, "quiet", 120.0d, 1700000000.0d, 1, false };
        yield return new object?[] { "receive", 121, false, null, null, null, null, false };
        yield return new object?[] { "publish", 121, true, "receiving", 0, 1700000000.0d, 2, false };
        yield return new object?[] { "wall_back", 122, false, null, null, null, null, false };
        yield return new object?[] { "publish", 122, false, "receiving", 1, 1700000000.0d, 2, false };
        yield return new object?[] { "publish", 43201, false, "quiet", 43080, 1700000000.0d, 2, false };
        yield return new object?[] { "receive", 43202, false, null, null, null, null, false };
        yield return new object?[] { "publish", 43202, true, "receiving", 0, 1699913600.0d, 3, false };
        yield return new object?[] { "close", 43202, false, "closed", 0, 1699913600.0d, 3, true };
        yield return new object?[] { "receive", 43203, false, null, null, null, null, true };
        yield return new object?[] { "publish", 43203, false, "closed", 0, 1699913600.0d, 4, true };
    }
}
