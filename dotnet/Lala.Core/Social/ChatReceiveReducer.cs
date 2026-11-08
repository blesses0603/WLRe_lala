using System.Collections.Immutable;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Receive-only composition of Python ChatPanel's bounded receipts and NameBook.
/// Source-state names are learned player/nearby/guild/event. Nearby/guild use ascending role ID
/// because their Core maps do not retain Python insertion order. Profile learning is an explicit
/// completion: Python decodes profiles but its current UI does not handle them. No UI or I/O.</summary>
public static class ChatReceiveReducer
{
    public const int MaximumUnicodeCodeUnits = 127; // Unicode8's even byte length is at most 254.
    public const int MaximumAnnouncementCharacters = ushort.MaxValue - 2 - 4;

    public static ChatReceiveSnapshot Apply(ChatReceiveSnapshot state, ServerEvent observation, double observedAt,
        WorldPlayer? player, PartyEventSnapshot party, GuildEventSnapshot guild)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(party);
        ArgumentNullException.ThrowIfNull(guild);
        if (!double.IsFinite(observedAt)) throw new ArgumentOutOfRangeException(nameof(observedAt));
        var chat = observation is ServerSocialEvent { Event: SocialPacketEvent value } && value.Main == 2 ? value : null;
        // Rescan when names can change, or a chat receipt needs a current label. Unrelated
        // observations preserve the same bounded immutable projection without extra allocations.
        if (chat is null && observation is not ServerLayoutEvent { Event: WorldPlayerEvent } &&
            observation is not ServerSocialEvent { Event: NearbyPlayerEvent or GuildRosterEvent or GuildMemberProfileEvent })
            return state;
        Validate(chat);
        var names = LearnNames(state.Names, player, party, guild, chat);
        var messages = state.Messages;
        if (!ReferenceEquals(names, state.Names))
            for (int i = 0; i < messages.Length; i++)
            {
                var row = messages[i];
                var name = DisplayName(row.RoleId, names, row.Scope);
                // Python keeps a cached label when its name-book entry has been evicted.
                if (name != row.RoleId.ToString(CultureInfo.InvariantCulture) && name != row.Name)
                    messages = messages.SetItem(i, row with { Name = name });
            }
        var feedback = state.LatestFeedback;
        var profile = state.LatestProfile;
        var received = state.ReceivedMessageCount;
        if (chat is not null)
        {
            var receipt = new ChatReceiveObservation(chat, observedAt, player?.RoleId);
            switch (chat)
            {
                case ChatMessageEvent message:
                    var scope = ChatNameScope.ForMessage(message);
                    Append(new(receipt, message.RoleId, scope, DisplayName(message.RoleId, names, scope)));
                    break;
                case ChatAnnouncementEvent:
                    Append(new(receipt, 0, ChatNameScope.Local, "系統"));
                    break;
                case ChatProfileEvent: profile = receipt; break;
                case ChatNoticeEvent or ChatResultEvent: feedback = receipt; break;
            }
        }
        return new(messages, names, feedback, profile, received);

        void Append(ChatReceiveMessage row)
        {
            if (messages.Length == ChatReceiveSnapshot.MaximumMessages) messages = messages.RemoveAt(0);
            messages = messages.Add(row);
            received++;
        }
    }

    // Match the Python UI's plain_text sender label without rewriting raw event content
    // or the name book. A future host must still treat every selected string as untrusted.
    private static string DisplayName(uint role, ChatNameBook names, ChatNameScope scope) => role == 0 ? "系統"
        : Regex.Replace(names.Name(role, scope), "<[^>]{0,500}>", "", RegexOptions.CultureInvariant);

    private static ChatNameBook LearnNames(ChatNameBook previous, WorldPlayer? player,
        PartyEventSnapshot party, GuildEventSnapshot guild, SocialPacketEvent? chat)
    {
        // Private mutable staging is never published or shared with a historical snapshot.
        var names = previous.Names.ToDictionary();
        var order = new LinkedList<ChatNameIdentity>(previous.LearnOrder);
        var nodes = new Dictionary<ChatNameIdentity, LinkedListNode<ChatNameIdentity>>();
        for (var node = order.First; node is not null; node = node.Next) nodes.Add(node.Value, node);
        bool touched = false;
        if (player is not null) Learn(player.RoleId, player.Name);
        foreach (var person in party.Nearby.OrderBy(pair => pair.Key)) Learn(person.Value.RoleId, person.Value.Name);
        foreach (var person in guild.Members.OrderBy(pair => pair.Key)) Learn(person.Value.RoleId, person.Value.Name);
        if (chat is ChatMessageEvent message) Learn(message.RoleId, message.Name, ChatNameScope.ForMessage(message));
        if (chat is ChatProfileEvent profile) Learn(profile.RoleId, profile.Name);
        return touched ? new(names.ToImmutableDictionary(), order.ToImmutableArray()) : previous;

        void Learn(uint role, string? raw, ChatNameScope scope = default)
        {
            if (role == 0 || string.IsNullOrEmpty(raw) || raw == role.ToString(CultureInfo.InvariantCulture)) return;
            RequireText(raw, MaximumUnicodeCodeUnits);
            var name = string.Concat(raw.Where(c => c >= 32 && c != 127));
            if (name.Length == 0) return;
            var key = new ChatNameIdentity(role, scope);
            names[key] = name;
            if (nodes.Remove(key, out var old)) order.Remove(old);
            nodes.Add(key, order.AddLast(key));
            if (names.Count > ChatNameBook.MaximumNames)
            {
                var first = order.First!;
                names.Remove(first.Value); nodes.Remove(first.Value); order.RemoveFirst();
            }
            touched = true; // Even an identical valid learn refreshes recency, as in Python.
        }
    }

    // Packet decoding already enforces these bounds. The public typed-event overload must
    // not retain arbitrarily large hand-built text, item arrays or nested plugin arrays.
    private static void Validate(SocialPacketEvent? chat)
    {
        switch (chat)
        {
            case null: return;
            case ChatMessageEvent message:
                string? expected = message.Sub switch
                {
                    1 or 10 => "世界", 2 => "區域", 3 or 17 => "密語", 5 => "隊伍",
                    6 => "組織", 27 or 28 => "跨服", _ => null
                };
                if (expected is null || message.Channel != expected) throw new ProtocolException("Invalid received chat channel.");
                RequireText(message.Text, MaximumUnicodeCodeUnits);
                if (message.Name is not null) RequireText(message.Name, MaximumUnicodeCodeUnits);
                if (message.ReplyText is not null) RequireText(message.ReplyText, MaximumUnicodeCodeUnits);
                if (message.Items.IsDefault || message.Items.Length > byte.MaxValue ||
                    message.ReplyItems is { } replies && (replies.IsDefault || replies.Length > byte.MaxValue))
                    throw new ProtocolException("Invalid received chat item collection.");
                foreach (var item in message.Items)
                    if (item is null || item.Plugins.IsDefault || item.Plugins.Length != 4 ||
                        item.Plugins.Any(plugin => plugin is null) || !double.IsFinite(item.AvailableTime) || !double.IsFinite(item.LimitedTime))
                        throw new ProtocolException("Invalid received chat item.");
                break;
            case ChatAnnouncementEvent announcement: RequireText(announcement.Text, MaximumAnnouncementCharacters); break;
            case ChatProfileEvent profile: RequireText(profile.Name, MaximumUnicodeCodeUnits); break;
            case ChatNoticeEvent notice: RequireText(notice.Text, MaximumUnicodeCodeUnits); break;
            case ChatResultEvent result: RequireText(result.Text, MaximumUnicodeCodeUnits); break;
            default: throw new ProtocolException("Unsupported received chat observation.");
        }
    }

    private static void RequireText(string text, int maximum)
    {
        if (text is null || text.Length > maximum) throw new ProtocolException("Invalid received chat text length.");
        // Validate UTF-16 without leaking the supplied content through an encoder exception.
        try { _ = new UnicodeEncoding(false, false, true).GetByteCount(text); }
        catch (EncoderFallbackException) { throw new ProtocolException("Invalid received chat text encoding."); }
    }
}
