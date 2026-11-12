using Xunit;
using Xunit.Sdk;

namespace Lala.Core.Tests.TestSupport;

public sealed class LazyAssertTests
{
    [Fact]
    public void PassingAssertionDoesNotEvaluateFailureMessage()
    {
        int calls = 0;
        LazyAssert.True(true, () =>
        {
            calls++;
            throw new InvalidOperationException("Passing assertions must not format failure messages.");
        });
        Assert.Equal(0, calls);
    }

    [Fact]
    public void FailingAssertionEvaluatesMessageOnceAndPreservesXunitFailureText()
    {
        const string message = "expected {\"value\":1}; actual {\"value\":2}\n完整診斷";
        int calls = 0;
        bool condition = false;
        var expected = Assert.Throws<TrueException>(() => Assert.True(condition, message));
        var actual = Assert.Throws<TrueException>(() => LazyAssert.True(condition, () =>
        {
            calls++;
            return message;
        }));
        Assert.Equal(1, calls);
        Assert.Equal(expected.Message, actual.Message);
    }
}
