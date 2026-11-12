namespace Lala.Core.Sessions;

/// <summary>Port of network/resource_safety.py. Unknown commands fail closed.</summary>
public static class ResourceSafetyPolicy
{
    public static bool AllowsDuringHold(string kind, string? action = null, bool? enabled = null) => kind switch
    {
        "chat" or "stop_auto_battle" or "stop_roaming" or "stop_walk" or
        "stop_expedition" or "stop_alchemy" or "reset_efficiency" => true,
        "craft" => action is "stop_auto" or "plan_pause",
        "automatic_flows" or "instance_auto_reward" => enabled is false,
        "daily_assistant" => action == "stop",
        "star_ark" or "guild_actions" => action == "pause",
        "daily_tasks" or "time_cube" => action == "auto" && enabled is false,
        _ => false
    };
}
