"""Validated account-scoped expedition preferences with atomic persistence."""
import json
from wlre.storage.paths import account_file
from wlre.storage.atomic import file_lock,write_json
from wlre.services.expedition import preferences,validate

def settings_file(key):return account_file(key,'.expedition.json')
def load(key):
    path=settings_file(key)
    with file_lock(path):
        return validate(json.loads(path.read_text(encoding='utf8'))) if path.exists() else preferences()
def save(key,value):
    checked=validate(value);path=settings_file(key)
    with file_lock(path):write_json(path,checked)
