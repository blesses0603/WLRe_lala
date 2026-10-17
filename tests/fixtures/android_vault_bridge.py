"""Real Java bridge/AES regression; Android Keystore storage is stubbed."""
import sys
sys.path.insert(0, sys.argv[1])
import jnius_config
jnius_config.add_classpath(sys.argv[2])
from jnius import autoclass as actual, cast
from unittest.mock import patch
from types import SimpleNamespace
from android_app.vault import AndroidCipher
keygen = actual('javax.crypto.KeyGenerator').getInstance('AES')
keygen.init(256)
key = keygen.generateKey()
class Store:
    def load(self, _): pass
    def containsAlias(self, alias): return False
    def getKey(self, alias, _): return key
class Gen:
    def init(self, spec):
        spec = cast('VaultBuilder', spec)
        assert spec.mode == 'GCM' and spec.padding == 'NoPadding' and spec.bits == 256
    def generateKey(self): return key
props = SimpleNamespace(PURPOSE_ENCRYPT=1, PURPOSE_DECRYPT=2,
    BLOCK_MODE_GCM='GCM', ENCRYPTION_PADDING_NONE='NoPadding')
def classes(name):
    if name == 'java.security.KeyStore': return SimpleNamespace(getInstance=lambda _: Store())
    if name == 'android.security.keystore.KeyProperties': return props
    if name == 'android.security.keystore.KeyGenParameterSpec$Builder': return actual('VaultBuilder')
    if name == 'javax.crypto.KeyGenerator': return SimpleNamespace(getInstance=lambda *_: Gen())
    return actual(name)
with patch('jnius.autoclass', side_effect=classes):
    cipher = AndroidCipher()
    raw = bytes(range(256)) + '帳密測試'.encode()
    envelope = cipher.encrypt(raw)
    assert cipher.decrypt(envelope) == raw
    assert cipher.encrypt(raw)['iv'] != envelope['iv']
    print('Actual PyJNIUS Java varargs and AES-GCM full-byte roundtrip passed')
