"""User data locations; legacy paths remain readable during migration."""
import os
from pathlib import Path

def data_root(base=None):
    return Path(base) if base is not None else Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')/'WLRE_LaLa'

def account_file(key,suffix='.json',base=None):
    if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('帳號設定識別碼錯誤')
    return data_root(base)/'accounts'/(key+suffix)

def favorites_file():return data_root()/'crafting_favorites.json'
def legacy_favorites_file():return Path.home()/'.wlre_client'/'crafting_favorites.json'
def error_log_file():return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'WLRE_Client'/'error.log'
