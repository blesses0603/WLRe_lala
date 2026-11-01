"""Retired legacy ZIP promotion entry point; never installs archives."""
import sys

def main(argv=None):
    print("此舊版 ZIP 升格工具已停用；請使用官方資源同步與驗證流程。", file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
