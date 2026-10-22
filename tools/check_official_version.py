"""CLI: verify live official PC versions before any game login."""
import argparse
import json

from wlre.services.game_version_gate import run_prelogin_check


def main(argv=None):
    parser = argparse.ArgumentParser(description="官方 PC YooAsset 三階段線上版本查詢")
    parser.add_argument("--main-url", help="進階診斷：已驗證的 MainPackage URL")
    parser.add_argument("--data-url", help="進階診斷：已驗證的 DataPackage URL")
    parser.add_argument("--strict", action="store_true",
                        help="版本有異動回傳 1，無法驗證回傳 2")
    args = parser.parse_args(argv)
    if args.main_url or args.data_url:
        result = run_prelogin_check({
            "MainPackage": args.main_url, "DataPackage": args.data_url})
    else:
        result = run_prelogin_check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.strict:
        return 0
    return {"version_identifiers_match": 0, "blocked": 1}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
