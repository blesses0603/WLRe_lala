# AssetsTools.NET format reference

The bounded format walker was checked against AssetsTools.NET source commit
`2d66992b60d583d6d82dd6e278d3946cf5827286` (nesrak1/AssetsTools.NET).
The fixed common-string table is copied from
`AssetTools.NET/Standard/AssetsFileFormat/TypeTreeType.cs` at that commit.
This is the only vendored upstream code/data. The remaining bounded cursor,
metadata walker, and raw-LZ4/LZ4HC decoder are original C# implementations.
No upstream compression source (including LZ4Sharp or SevenZip/LZMA) is copied.
The format and allocation review used the upstream MIT-licensed format readers
and UnityPy1.25.4 as independent references.
Python UnityPy1.25.4 and lz4 4.4.5 are fixture-generation tools, not vendored
runtime dependencies; fixture payloads and trees were authored for these tests.
AssetsTools.NET 3.0.5 is used only by independent fixture verification tests.
No runtime package decoder, class database or TypeTreeDumps content is shipped.

MIT License

Copyright (c) 2020 nesrak1

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.