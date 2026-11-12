using Xunit;

namespace Lala.Core.Tests.TestSupport;

// Large diagnostic JSON is only needed when an assertion actually fails.
internal static class LazyAssert
{
    internal static void True(bool condition, Func<string> failureMessage) =>
        Assert.True(condition, condition ? null : failureMessage());
}
