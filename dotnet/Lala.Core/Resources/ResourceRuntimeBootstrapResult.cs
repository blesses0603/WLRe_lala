using System.Data.Common;
using Microsoft.Data.Sqlite;

namespace Lala.Core.Resources;

internal enum ResourceRuntimeReadback { NotAttempted, Failed, Matched }

/// <summary>Historical result, not a transaction, live admission capability or promise of
/// rollback. Confirmed/uncertain storage survives later readback, source, cancellation or cleanup
/// failure. A publication can subsequently be revoked; reacquire the owner's Current.</summary>
internal sealed class ResourceRuntimeBootstrapResult(bool storageAttempted, ResourceInventoryWriteOutcome storageOutcome,
    bool commitAdmitted, ResourceInventoryReceipt? receipt, ResourceRuntimeReadback readback,
    bool sourcesRechecked, ResourceRuntimePublication? publication, Exception? failure)
{
    internal AccountResourceStorageOutcome ItemImageStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    internal AccountResourceStorageOutcome PortraitStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    internal AccountResourceStorageOutcome EmojiStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    internal bool StorageAttempted { get; } = storageAttempted;
    internal ResourceInventoryWriteOutcome StorageOutcome { get; } = storageOutcome;
    internal bool CommitAdmitted { get; } = commitAdmitted;
    internal ResourceInventoryReceipt? Receipt { get; } = receipt;
    internal ResourceRuntimeReadback Readback { get; } = readback;
    internal bool SourcesRechecked { get; } = sourcesRechecked;
    internal ResourceRuntimePublication? Publication { get; } = publication;
    internal bool WasPublished => Publication is not null;
    internal Exception? Failure { get; } = failure;
    internal bool CanLogin => false;
    internal bool CanSendPackets => false;
}

/// <summary>Offline fault/lifecycle instrumentation only. A wrapper must own/dispose the
/// concrete supplied connection. No production factory accepts these hooks; offline owners
/// remain non-authorizing even when a wrapper invents provider results.</summary>
internal sealed class ResourceRuntimeBootstrapTestHooks
{
    // Owned synthetic image injection tests storage/revocation only; offline owners never admit.
    internal Func<OfflinePreparedRuntimeCandidate, ItemImageBatch>? ItemImagesForOfflineTest { get; init; }
    internal Func<OfflinePreparedRuntimeCandidate, PortraitRuntimeBatch>? PortraitsForOfflineTest { get; init; }
    internal Action? BeforePortraitCommitAdmission { get; init; }
    internal Func<OfflinePreparedRuntimeCandidate, EmojiRuntimeBatch>? EmojisForOfflineTest { get; init; }
    internal Action? BeforeEmojiCommitAdmission { get; init; }
    internal Action? BeforeImageCommitAdmission { get; init; }
    internal Func<SqliteConnection, DbConnection>? WrapConnection { get; init; }
    internal Func<Task>? BeforeWrite { get; init; }
    internal Action? BeforeCommitAdmission { get; init; }
    internal Func<Task>? BeforeReadback { get; init; }
    internal Func<Task>? BeforeCacheWrite { get; init; }
    internal Func<Task>? AfterCacheWrite { get; init; }
}
