"""唯一正式遊戲資料來源；不接受第三方、舊網域或任意相對路徑。"""
import re

OFFICIAL_HOST = 'wlreftpsrc.chinesegamer.net'
ROOT = 'https://' + OFFICIAL_HOST + '/WLN/TW'
PACKAGES = ('DataPackage', 'MainPackage')
_DATA_VERSION = re.compile(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2}\Z')


def package_url(data_version, package, extension):
    if (not isinstance(data_version, str) or not _DATA_VERSION.fullmatch(data_version)
            or package not in PACKAGES or extension not in ('version', 'bytes', 'hash')):
        raise ValueError('unsupported_official_package_path')
    return f'{ROOT}/{data_version}/ResourcesPC/AssetBundle/{package}.{extension}'
