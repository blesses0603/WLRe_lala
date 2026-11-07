using Android.Runtime;
using Avalonia.Android;
using Lala.Presentation;

namespace Lala.Android;

// Avalonia 12 initializes the app at Android application scope. Activities use
// IActivityApplicationLifetime.MainViewFactory to obtain a fresh view.
[global::Android.App.Application]
public sealed class MainApplication(nint javaReference, JniHandleOwnership transfer)
    : AvaloniaAndroidApplication<App>(javaReference, transfer);
