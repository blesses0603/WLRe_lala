"""有界原生 GUI CI 驗收；真實模組入口保留 multiprocessing spawn 相容。"""
import argparse
import faulthandler
import unittest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-directory', default='tests')
    parser.add_argument('--pattern', default='test*.py')
    parser.add_argument('--timeout', type=float, default=90)
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 300:
        parser.error('timeout 必須大於 0 且不超過 300 秒')

    def arm():
        faulthandler.dump_traceback_later(args.timeout, exit=True)

    class NativeResult(unittest.TextTestResult):
        def startTest(self, test):
            arm()
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            arm()  # 也約束類別 teardown／下一個 setup。

    arm()
    try:
        suite = unittest.defaultTestLoader.discover(args.start_directory, pattern=args.pattern)
        result = unittest.TextTestRunner(verbosity=2, resultclass=NativeResult).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    raise SystemExit(main())
