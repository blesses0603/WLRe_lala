using System.Security.Cryptography;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class RuntimeBundleCacheWriterTests
{
    [Fact]
    public async Task DownloadsUseExactPythonPathsAndReadOnlyReaderCanReverifyThem()
    {
        using var directory = new TestDirectory();
        var downloaded = FixtureSource(0);
        var cached = FixtureSource(1, BundleAcquisition.Cache);
        await new RuntimeBundleCacheWriter(directory.Root).StoreAsync([downloaded, cached]);
        string destination = Destination(directory.Root, downloaded);
        Assert.Equal(BundleSourceFixtures.Payload(downloaded.Spec.Name), await File.ReadAllBytesAsync(destination));
        Assert.False(File.Exists(Destination(directory.Root, cached)));
        Assert.Single(Directory.GetFiles(directory.Root, "*", SearchOption.AllDirectories));
        using var stream = await new RuntimeBundleCacheReader(directory.Root).OpenReadAsync(downloaded.Spec, default);
        Assert.NotNull(stream);
        using var copy = new MemoryStream();
        await stream.CopyToAsync(copy);
        Assert.Equal(downloaded.Sha256, VerifiedBundleSource.Verify(downloaded.Spec, copy.ToArray(), BundleAcquisition.Cache).Sha256);
        Assert.False(typeof(RuntimeBundleCacheWriter).IsPublic);
    }

    [Fact]
    public async Task ExistingSameBytesAreReusedWithoutStagingOrChangingTimestamp()
    {
        using var directory = new TestDirectory();
        var source = FixtureSource();
        string path = Destination(directory.Root, source);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllBytesAsync(path, BundleSourceFixtures.Payload(source.Spec.Name));
        File.SetLastWriteTimeUtc(path, new DateTime(2000, 1, 2, 3, 4, 5, DateTimeKind.Utc));
        var before = File.GetLastWriteTimeUtc(path);
        await new RuntimeBundleCacheWriter(directory.Root, _ => throw new InvalidOperationException("Unexpected rewrite"))
            .StoreAsync([source, source]);
        Assert.Equal(before, File.GetLastWriteTimeUtc(path));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Theory]
    [InlineData("short")]
    [InlineData("long")]
    [InlineData("checksum")]
    public async Task CorruptExistingFileRemainsUntilCompleteReplacement(string corruption)
    {
        using var directory = new TestDirectory();
        var source = FixtureSource();
        byte[] expected = BundleSourceFixtures.Payload(source.Spec.Name);
        byte[] original = corruption switch { "short" => expected[..^1], "long" => [.. expected, 1], _ => new byte[expected.Length] };
        string path = Destination(directory.Root, source);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllBytesAsync(path, original);
        bool staged = false, published = false;
        await new RuntimeBundleCacheWriter(directory.Root, stage =>
        {
            if (stage == RuntimeBundleCacheWriteStage.BeforePublish) { staged = true; Assert.Equal(original, File.ReadAllBytes(path)); }
            if (stage == RuntimeBundleCacheWriteStage.Published) { published = true; Assert.Equal(expected, File.ReadAllBytes(path)); }
        }).StoreAsync([source]);
        Assert.True(staged); Assert.True(published);
        Assert.Equal(expected, await File.ReadAllBytesAsync(path));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Fact]
    public async Task CacheOnlyAndEmptyBatchesDoNotCreateDirectories()
    {
        using var directory = new TestDirectory();
        var writer = new RuntimeBundleCacheWriter(directory.Root);
        await writer.StoreAsync([]);
        await writer.StoreAsync([FixtureSource(acquisition: BundleAcquisition.Cache)]);
        Assert.False(Directory.Exists(directory.Root));
    }

    [Fact]
    public async Task PreCanceledBatchHasNoFilesystemEffects()
    {
        using var directory = new TestDirectory();
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            new RuntimeBundleCacheWriter(directory.Root).StoreAsync([FixtureSource()], cancellation.Token));
        Assert.Equal(cancellation.Token, error.CancellationToken);
        Assert.False(Directory.Exists(directory.Root));
    }

    [Theory]
    [InlineData("TemporaryCreated")]
    [InlineData("ChunkCopied")]
    [InlineData("BeforePublish")]
    [InlineData("BeforeMove")]
    public async Task CancellationBeforePublicationCleansOnlyOwnedTemporaryFile(string cancelAtName)
    {
        var cancelAt = Enum.Parse<RuntimeBundleCacheWriteStage>(cancelAtName);
        using var directory = new TestDirectory();
        using var cancellation = new CancellationTokenSource();
        var source = SyntheticSource("large.bundle", new byte[128 * 1024]);
        string path = Destination(directory.Root, source);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        string unrelated = Path.Combine(Path.GetDirectoryName(path)!, ".bundle_other_writer.partial");
        await File.WriteAllBytesAsync(unrelated, [123]);
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            new RuntimeBundleCacheWriter(directory.Root, stage => { if (stage == cancelAt) cancellation.Cancel(); })
                .StoreAsync([source], cancellation.Token));
        Assert.Equal(cancellation.Token, error.CancellationToken);
        Assert.False(File.Exists(path));
        Assert.Equal(new[] { unrelated }, Directory.GetFiles(directory.Root, "*", SearchOption.AllDirectories));
        Assert.Equal(new byte[] { 123 }, await File.ReadAllBytesAsync(unrelated));
    }

    [Fact]
    public async Task CancellationAfterPublicationReportsCancellationButMayLeaveVerifiedFile()
    {
        using var directory = new TestDirectory();
        using var cancellation = new CancellationTokenSource();
        var source = FixtureSource();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            new RuntimeBundleCacheWriter(directory.Root, stage =>
            { if (stage == RuntimeBundleCacheWriteStage.Published) cancellation.Cancel(); }).StoreAsync([source], cancellation.Token));
        Assert.Equal(BundleSourceFixtures.Payload(source.Spec.Name), await File.ReadAllBytesAsync(Destination(directory.Root, source)));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Fact]
    public async Task ConcurrentSameContentWritersConvergeWithoutTemporaryFiles()
    {
        using var directory = new TestDirectory();
        var source = SyntheticSource("concurrent.bundle", new byte[1024 * 1024]);
        var start = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var tasks = Enumerable.Range(0, 8).Select(async _ =>
        {
            await start.Task;
            await new RuntimeBundleCacheWriter(directory.Root).StoreAsync([source]);
        }).ToArray();
        start.SetResult();
        await Task.WhenAll(tasks);
        Assert.Equal(new byte[1024 * 1024], await File.ReadAllBytesAsync(Destination(directory.Root, source)));
        Assert.Single(Directory.GetFiles(directory.Root, "*", SearchOption.AllDirectories));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Theory]
    [InlineData("valid")]
    [InlineData("corrupt")]
    [InlineData("missing")]
    public async Task FailedMoveAcceptsOnlyFullyVerifiedCompetitor(string competitor)
    {
        using var directory = new TestDirectory();
        var source = FixtureSource();
        byte[] expected = BundleSourceFixtures.Payload(source.Spec.Name);
        string destination = Destination(directory.Root, source);
        bool published = false;
        var writer = new RuntimeBundleCacheWriter(directory.Root, stage =>
        {
            if (stage == RuntimeBundleCacheWriteStage.Published) published = true;
            if (stage != RuntimeBundleCacheWriteStage.BeforeMove) return;
            // Force the actual filesystem move to fail on every OS, after staging was
            // verified and the destination check missed. A winner may have arrived.
            File.Delete(Assert.Single(Directory.GetFiles(directory.Root, "*.partial", SearchOption.AllDirectories)));
            if (competitor != "missing")
                File.WriteAllBytes(destination, competitor == "valid" ? expected : new byte[expected.Length]);
        });
        if (competitor == "valid") await writer.StoreAsync([source]);
        else await Assert.ThrowsAnyAsync<IOException>(() => writer.StoreAsync([source]));
        Assert.False(published);
        if (competitor == "missing") Assert.False(File.Exists(destination));
        else Assert.Equal(competitor == "valid" ? expected : new byte[expected.Length], await File.ReadAllBytesAsync(destination));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(true, true)]
    public async Task WindowsBlockedReplacementAcceptsOnlyVerifiedCompetitor(bool readOnly, bool corrupt)
    {
        if (!OperatingSystem.IsWindows()) return;
        using var directory = new TestDirectory();
        var source = FixtureSource();
        byte[] expected = BundleSourceFixtures.Payload(source.Spec.Name);
        byte[] competingBytes = corrupt ? new byte[expected.Length] : expected;
        string destination = Destination(directory.Root, source);
        FileStream? competingReader = null;
        bool published = false;
        try
        {
            var writer = new RuntimeBundleCacheWriter(directory.Root, stage =>
            {
                if (stage == RuntimeBundleCacheWriteStage.Published) published = true;
                if (stage != RuntimeBundleCacheWriteStage.BeforeMove) return;
                File.WriteAllBytes(destination, competingBytes);
                if (readOnly) File.SetAttributes(destination, FileAttributes.ReadOnly);
                else competingReader = new FileStream(destination, FileMode.Open, FileAccess.Read, FileShare.Read);
            });
            if (!corrupt) await writer.StoreAsync([source]);
            else
            {
                var error = await Record.ExceptionAsync(() => writer.StoreAsync([source]));
                Assert.NotNull(error);
                // Windows reports a denied replacement as access denied or a sharing
                // violation. Neither may become success for mismatching bytes.
                Assert.Contains(error.GetType(), new[] { typeof(IOException), typeof(UnauthorizedAccessException) });
            }
            Assert.False(published);
            Assert.Equal(competingBytes, await File.ReadAllBytesAsync(destination));
            AssertNoTemporaryFiles(directory.Root);
        }
        finally
        {
            competingReader?.Dispose();
            if (File.Exists(destination)) File.SetAttributes(destination, FileAttributes.Normal);
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task CompetitorPublishedValidDestinationSurvivesCancelledOrCorruptStaging(bool cancel)
    {
        using var directory = new TestDirectory();
        using var cancellation = new CancellationTokenSource();
        byte[] expected = new byte[128 * 1024];
        var source = SyntheticSource("ordered-race.bundle", expected);
        string destination = Destination(directory.Root, source);
        var first = new RuntimeBundleCacheWriter(directory.Root, stage =>
        {
            if (stage != RuntimeBundleCacheWriteStage.BeforePublish) return;
            // Deterministic overlap: first writer has staged, then a second real writer
            // publishes valid bytes before the first is cancelled or its stage is damaged.
            using var competingCancellation = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            new RuntimeBundleCacheWriter(directory.Root).StoreAsync([source], competingCancellation.Token)
                .GetAwaiter().GetResult();
            Assert.Equal(expected, File.ReadAllBytes(destination));
            if (cancel) cancellation.Cancel();
            else
            {
                string temporary = Assert.Single(Directory.GetFiles(directory.Root, "*.partial", SearchOption.AllDirectories));
                byte[] bytes = File.ReadAllBytes(temporary); bytes[0] ^= 1;
                File.WriteAllBytes(temporary, bytes);
            }
        });
        if (cancel)
        {
            var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
                first.StoreAsync([source], cancellation.Token).WaitAsync(TimeSpan.FromSeconds(20)));
            Assert.True(cancellation.IsCancellationRequested);
            Assert.Equal(cancellation.Token, error.CancellationToken);
        }
        else await Assert.ThrowsAsync<InvalidDataException>(() =>
            first.StoreAsync([source], cancellation.Token).WaitAsync(TimeSpan.FromSeconds(20)));
        Assert.Equal(expected, await File.ReadAllBytesAsync(destination));
        Assert.Single(Directory.GetFiles(directory.Root, "*", SearchOption.AllDirectories));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Fact]
    public async Task StagedTamperingFailsVerificationAndPreservesOldDestination()
    {
        using var directory = new TestDirectory();
        var source = FixtureSource();
        string path = Destination(directory.Root, source);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllBytesAsync(path, [42]);
        await Assert.ThrowsAsync<InvalidDataException>(() => new RuntimeBundleCacheWriter(directory.Root, stage =>
        {
            if (stage != RuntimeBundleCacheWriteStage.BeforePublish) return;
            string temporary = Assert.Single(Directory.GetFiles(directory.Root, "*.partial", SearchOption.AllDirectories));
            byte[] bytes = File.ReadAllBytes(temporary); bytes[0] ^= 1; File.WriteAllBytes(temporary, bytes);
        }).StoreAsync([source]));
        Assert.Equal(new byte[] { 42 }, await File.ReadAllBytesAsync(path));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Fact]
    public async Task PublicationFailureCleansTemporaryAndIsNotReportedAsSuccess()
    {
        using var directory = new TestDirectory();
        var source = FixtureSource();
        string path = Destination(directory.Root, source);
        await Assert.ThrowsAsync<IOException>(() => new RuntimeBundleCacheWriter(directory.Root, stage =>
        { if (stage == RuntimeBundleCacheWriteStage.BeforePublish) Directory.CreateDirectory(path); }).StoreAsync([source]));
        Assert.True(Directory.Exists(path));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Fact]
    public async Task InstalledBytesAreReverifiedAfterPublication()
    {
        using var directory = new TestDirectory();
        var source = FixtureSource();
        string path = Destination(directory.Root, source);
        await Assert.ThrowsAsync<InvalidDataException>(() => new RuntimeBundleCacheWriter(directory.Root, stage =>
        { if (stage == RuntimeBundleCacheWriteStage.Published) File.WriteAllBytes(path, [0]); }).StoreAsync([source]));
        AssertNoTemporaryFiles(directory.Root);
    }

    [Fact]
    public async Task CleanupFailureDoesNotHideCancellationAndIsMarkedExplicitly()
    {
        using var directory = new TestDirectory();
        using var cancellation = new CancellationTokenSource();
        var source = FixtureSource();
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new RuntimeBundleCacheWriter(directory.Root, stage =>
        {
            if (stage != RuntimeBundleCacheWriteStage.BeforePublish) return;
            string temporary = Assert.Single(Directory.GetFiles(directory.Root, "*.partial", SearchOption.AllDirectories));
            File.Delete(temporary); Directory.CreateDirectory(temporary);
            cancellation.Cancel();
        }).StoreAsync([source], cancellation.Token));
        Assert.Equal(cancellation.Token, error.CancellationToken);
        Assert.Equal("Cleanup", error.Data[ResourceCleanup.FailureMarker]);
        Assert.False(File.Exists(Destination(directory.Root, source)));
    }

    [Theory]
    [InlineData("root")]
    [InlineData("official_sync")]
    [InlineData("bundles")]
    [InlineData("package")]
    [InlineData("version")]
    [InlineData("hash")]
    [InlineData("leaf")]
    [InlineData("dangling-root")]
    [InlineData("dangling-leaf")]
    public async Task ObservedDirectoryAndLeafLinksAreRejectedWithoutWritingTheirTargets(string component)
    {
        // Windows symlink creation requires privileges or Developer Mode; Unix CI exercises links.
        if (OperatingSystem.IsWindows()) return;
        using var directory = new TestDirectory();
        var source = FixtureSource();
        string root = directory.Root;
        string path = Destination(root, source);
        string link = component switch
        {
            "root" or "dangling-root" => directory.Root,
            "official_sync" => Path.Combine(root, "official_sync"),
            "bundles" => Path.Combine(root, "official_sync", "bundles"),
            "package" => Path.Combine(root, "official_sync", "bundles", source.Spec.Package),
            "version" => Path.Combine(root, "official_sync", "bundles", source.Spec.Package, source.Spec.PackageVersion),
            "hash" => Path.GetDirectoryName(path)!,
            _ => path
        };
        string target = Path.Combine(directory.Base, "target");
        Directory.CreateDirectory(Path.GetDirectoryName(link)!);
        bool leaf = component.EndsWith("leaf", StringComparison.Ordinal);
        bool dangling = component.StartsWith("dangling", StringComparison.Ordinal);
        if (!dangling)
        {
            if (leaf) File.WriteAllBytes(target, [77]);
            else Directory.CreateDirectory(target);
        }
        if (leaf) File.CreateSymbolicLink(link, target);
        else Directory.CreateSymbolicLink(link, target);
        try
        {
            await Assert.ThrowsAsync<IOException>(() => new RuntimeBundleCacheWriter(root).StoreAsync([source]));
            if (!dangling && leaf) Assert.Equal(new byte[] { 77 }, File.ReadAllBytes(target));
            if (!dangling && !leaf) Assert.Empty(Directory.GetFileSystemEntries(target));
            if (dangling) Assert.False(File.Exists(target) || Directory.Exists(target));
        }
        finally
        {
            if (leaf || dangling) File.Delete(link);
            else Directory.Delete(link);
        }
    }

    [Fact]
    public async Task PlatformAliasesAboveSelectedDataRootAreAllowed()
    {
        if (OperatingSystem.IsWindows()) return;
        using var directory = new TestDirectory();
        var source = FixtureSource();
        string target = Path.Combine(directory.Base, "actual");
        Directory.CreateDirectory(target);
        Directory.CreateSymbolicLink(directory.Root, target);
        string root = Path.Combine(directory.Root, "selected-data");
        try
        {
            await new RuntimeBundleCacheWriter(root).StoreAsync([source]);
            Assert.Equal(BundleSourceFixtures.Payload(source.Spec.Name), await File.ReadAllBytesAsync(
                Destination(Path.Combine(target, "selected-data"), source)));
        }
        finally { Directory.Delete(directory.Root); }
    }

    [Fact]
    public async Task ObservedTemporaryLinkIsRejectedAndCleanupDoesNotFollowIt()
    {
        if (OperatingSystem.IsWindows()) return;
        using var directory = new TestDirectory();
        var source = FixtureSource();
        string target = Path.Combine(directory.Base, "target");
        await File.WriteAllBytesAsync(target, [99]);
        string? temporary = null;
        try
        {
            var error = await Assert.ThrowsAsync<IOException>(() => new RuntimeBundleCacheWriter(directory.Root, stage =>
            {
                if (stage != RuntimeBundleCacheWriteStage.BeforePublish) return;
                temporary = Assert.Single(Directory.GetFiles(directory.Root, "*.partial", SearchOption.AllDirectories));
                File.Delete(temporary); File.CreateSymbolicLink(temporary, target);
            }).StoreAsync([source]));
            Assert.Equal("Cleanup", error.Data[ResourceCleanup.FailureMarker]);
            Assert.Equal(new byte[] { 99 }, await File.ReadAllBytesAsync(target));
            Assert.False(File.Exists(Destination(directory.Root, source)));
        }
        finally { if (temporary is not null) File.Delete(temporary); }
    }

    [Fact]
    public async Task WholeBatchDownloadCountIsBoundedBeforeAnyFilesystemMutation()
    {
        using var directory = new TestDirectory();
        var sources = Enumerable.Range(0, 25).Select(i => SyntheticSource("count-" + i + ".bundle", [1])).ToArray();
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => new RuntimeBundleCacheWriter(directory.Root).StoreAsync(sources));
        Assert.Equal(BundleSourceFailure.Budget, error.Failure);
        Assert.False(Directory.Exists(directory.Root));
        await new RuntimeBundleCacheWriter(directory.Root).StoreAsync(sources[..24]);
        Assert.Equal(24, Directory.GetFiles(directory.Root, "*.bundle", SearchOption.AllDirectories).Length);
    }

    [Fact]
    public async Task AggregateByteBoundIncludesAllHandlesAndAcceptsExactLimit()
    {
        using var directory = new TestDirectory();
        var source = SyntheticSource("bounded.bundle", new byte[16 * 1024 * 1024]);
        var error = await Assert.ThrowsAsync<BundleSourceException>(() =>
            new RuntimeBundleCacheWriter(directory.Root).StoreAsync([source, source, FixtureSource()]));
        Assert.Equal(BundleSourceFailure.Budget, error.Failure);
        Assert.False(Directory.Exists(directory.Root));
        await new RuntimeBundleCacheWriter(directory.Root).StoreAsync([source, source]);
        Assert.Equal(16 * 1024 * 1024, new FileInfo(Destination(directory.Root, source)).Length);
        Assert.Single(Directory.GetFiles(directory.Root, "*.bundle", SearchOption.AllDirectories));
    }

    [Fact]
    public async Task MutableCollectionIsSnapshottedBeforeWriting()
    {
        using var directory = new TestDirectory();
        var sources = new List<VerifiedBundleSource> { FixtureSource(0), FixtureSource(1) };
        await new RuntimeBundleCacheWriter(directory.Root, _ => sources.Clear()).StoreAsync(sources);
        Assert.Equal(2, Directory.GetFiles(directory.Root, "*.bundle", SearchOption.AllDirectories).Length);
    }

    [Fact]
    public void RelativeDataRootIsNotAccepted() => Assert.Throws<ArgumentException>(() => new RuntimeBundleCacheWriter("relative-root"));

    private static VerifiedBundleSource FixtureSource(int index = 0, BundleAcquisition acquisition = BundleAcquisition.UntrustedSourceDownload)
    {
        var manifest = YooAssetManifest.Parse(BundleSourceFixtures.Bytes("data-valid"));
        var spec = BundleSourcePlan.Create(manifest, "1.3.21").Entries[index].Spec;
        return VerifiedBundleSource.Verify(spec, BundleSourceFixtures.Payload(spec.Name), acquisition);
    }

    private static VerifiedBundleSource SyntheticSource(string name, byte[] bytes)
    {
        var manifest = YooAssetManifest.Parse(BundleSourceFixtures.Bytes("data-valid"));
        var entry = new YooBundleEntry(name, 0, Convert.ToHexStringLower(MD5.HashData(bytes)),
            ManifestIdentity.Crc32LittleEndian(bytes), bytes.Length, false, [], []);
        return VerifiedBundleSource.Verify(new("1.3.21", manifest, entry), bytes, BundleAcquisition.UntrustedSourceDownload);
    }

    private static string Destination(string root, VerifiedBundleSource source) =>
        Path.Combine(root, "official_sync", "bundles", source.Spec.Package, source.Spec.PackageVersion, source.Spec.Md5, source.Spec.Name);

    private static void AssertNoTemporaryFiles(string root) => Assert.Empty(Directory.GetFiles(root, "*.partial", SearchOption.AllDirectories));

    private sealed class TestDirectory : IDisposable
    {
        internal string Base { get; }
        internal string Root => Path.Combine(Base, "data");
        internal TestDirectory()
        {
            Base = Path.Combine(Path.GetTempPath(), "lala-bundle-cache-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Base);
        }
        public void Dispose() => Directory.Delete(Base, recursive: true);
    }
}
