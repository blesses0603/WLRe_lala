using System.Collections.Immutable;
using Lala.Core.Resources;

namespace Lala.Core.Sessions.Discovery;

public enum OfficialServerDiscoveryFailure
{
    InvalidVersion, InvalidDocument, InvalidEndpoint, InvalidResponse, Redirect, Status,
    Headers, Size, VersionChanged, Timeout, Transport, Cleanup
}

/// <summary>Sanitized failure. Remote bodies, handler exception details and secrets are not retained.</summary>
public sealed class OfficialServerDiscoveryException(OfficialServerDiscoveryFailure failure)
    : IOException("Server discovery failed: " + failure)
{
    public OfficialServerDiscoveryFailure Failure { get; } = failure;
}

/// <summary>Read-only candidate metadata, not an authenticated or authorized destination.</summary>
public sealed class OfficialServerLineCandidate
{
    public int Id { get; }
    public int GroupId { get; }
    public string Name { get; }
    public string Host { get; }
    public int Port { get; }
    public bool CanLogin => false;
    public bool CanSendPackets => false;
    internal OfficialServerLineCandidate(int id, string name, string host, int port)
        => (Id, GroupId, Name, Host, Port) = (id, id / 100, name, host, port);
}

/// <summary>Historical HTTPS metadata observation, not freshness, publisher-signature,
/// verification-server, account-authentication, resource-readiness or transmission authority.</summary>
public sealed class OfficialServerCandidateSnapshot
{
    public OfficialVersionSnapshot Version { get; }
    public string ExactUrl { get; }
    public string ContentSha256 { get; }
    public string CatalogIdentity { get; }
    public ImmutableArray<OfficialServerLineCandidate> Lines { get; }
    public bool TlsOriginObserved { get; }
    public bool PublisherSignatureVerified => false;
    public bool VerificationEndpointVerified => false;
    public bool CanLogin => false;
    public bool CanSendPackets => false;

    internal OfficialServerCandidateSnapshot(OfficialVersionSnapshot version, string url, string contentSha256,
        string identity, ImmutableArray<OfficialServerLineCandidate> lines, bool production)
        => (Version, ExactUrl, ContentSha256, CatalogIdentity, Lines, TlsOriginObserved) =
            (version, url, contentSha256, identity, lines, production);

    /// <summary>Explicit selection from this snapshot only. Does not create a connection profile,
    /// choose a verification endpoint, authenticate an account or approve data transmission.</summary>
    public bool TrySelectLine(int id, out OfficialServerLineCandidate? candidate)
    {
        candidate = Lines.FirstOrDefault(line => line.Id == id);
        return candidate is not null;
    }
}
