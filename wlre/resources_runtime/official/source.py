"""唯一正式遊戲資料來源；不接受第三方、舊網域或任意相對路徑。"""
import re
from urllib.parse import urlsplit

OFFICIAL_HOST = 'wlreftpsrc.chinesegamer.net'
ROOT = 'https://' + OFFICIAL_HOST + '/WLN/TW'
PACKAGES = ('DataPackage', 'MainPackage')
_DATA_VERSION = re.compile(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2}\Z')
_RESOURCE_PATH = re.compile(
    r'/WLN/TW/[0-9]{1,4}(?:\.[0-9]{1,4}){2}/(?:ResourcesPC/AssetBundle/'
    r'(?:(?:DataPackage|MainPackage)\.(?:version|bytes|hash)|'
    r'[A-Za-z0-9][A-Za-z0-9_.-]{0,190}\.bundle)|LuaScripts/LuaScriptPathList\.txt)\Z')


def package_url(data_version, package, extension):
    if (not isinstance(data_version, str) or not _DATA_VERSION.fullmatch(data_version)
            or package not in PACKAGES or extension not in ('version', 'bytes', 'hash')):
        raise ValueError('unsupported_official_package_path')
    return f'{ROOT}/{data_version}/ResourcesPC/AssetBundle/{package}.{extension}'


def validate_url(url):
    """只准已識別的必要端點；不開放目錄爬取或任意來源。"""
    if not isinstance(url, str) or len(url) > 1024 or any(c.isspace() for c in url):
        raise ValueError('invalid_official_url')
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ValueError('invalid_official_url') from None
    if (parts.scheme != 'https' or parts.hostname != OFFICIAL_HOST or port is not None
            or parts.username is not None or parts.password is not None or parts.fragment
            or '%' in parts.path or '\\' in parts.path
            or (parts.query and not re.fullmatch(r'[0-9]{1,20}(?:\.[0-9]{1,16})?', parts.query))
            or (parts.path != '/WLN/TW/ResourcePath_PC.dat' and not _RESOURCE_PATH.fullmatch(parts.path))):
        raise ValueError('unapproved_official_source')
    return url
