"""Optional command-line inspection; sends only HTTPS GET to approved official CDN."""
import argparse
import json
from wlre.services.official_version import check_official_versions


def main(argv=None):
    parser = argparse.ArgumentParser(description="官方資源版本唯讀檢測（尚未驗證 CDN 版本路徑）")
    parser.add_argument("--main-url", help="已確認的官方 MainPackage .version/.txt/.json URL")
    parser.add_argument("--data-url", help="已確認的官方 DataPackage .version/.txt/.json URL")
    parser.add_argument("--strict", action="store_true", help="未能確認相同資源版本時以非零結束")
    args = parser.parse_args(argv)
    sources = {"MainPackage": args.main_url, "DataPackage": args.data_url}
    result = check_official_versions(sources)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return (0 if not args.strict or result["status"] == "same_resources" else
            1 if result["status"] == "resources_changed" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
