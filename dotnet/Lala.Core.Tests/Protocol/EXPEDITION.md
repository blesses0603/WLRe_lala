# S31 expedition packet parity

The offline `ExpeditionDecoder` ports every recognized S31 branch from `wlre/network/expedition.py`. It does not send commands, run expedition scheduling or mutate account state.

`generate_expedition_packet_vectors.py` generates 160 deterministic synthetic packet/expected-event pairs by invoking the retained Python decoder. C# compares every decoded field and event kind. Another 160 cases exercise prefix truncation and trailing-byte rejection, respecting variable reward records and the deliberately opaque S31-15 body. One test covers unknown packets and collection immutability.

S31-19 retains Python's last-write-wins behavior for repeated quest indices and requires the final show byte. S31-15 reports only extension byte count; it deliberately does not guess extension semantics. Skill-level bytes and reserved fields are consumed without exposing unreviewed values. All collection data created by the decoder is immutable.
