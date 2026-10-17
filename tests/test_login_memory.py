import ctypes
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wlre.storage import login_memory as memory;from wlre.storage import server_lines

class LoginMemory(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.file=Path(self.temp.name)/'中文設定'/'login_memory.json'
        self.encrypted={};self.calls=[]
        def crypt(raw,entropy,decrypt=False):
            self.calls.append((entropy,decrypt))
            if decrypt:
                value,key=self.encrypted[raw]
                if key!=entropy:raise memory.MemoryError('context mismatch')
                return value
            token=b'ciphertext-'+str(len(self.encrypted)).encode()
            self.encrypted[token]=(raw,entropy);return token
        self.crypto=patch.object(memory,'_crypt',side_effect=crypt).start();self.addCleanup(patch.stopall)
    def save(self,account='test-A',password='FAKE-password-123',line=101,remember=True):
        return memory.save('example.invalid',16988,account,password,True,remember,self.file,line_id=line,line_name=f'測試 {line} 線')
    def test_default_empty_and_opt_in(self):
        self.assertEqual(memory.list_entries(self.file),[]);self.assertIsNone(memory.load(file=self.file))
        memory.save('example.invalid',16988,'test-A','secret',False,False,self.file)
        self.assertFalse(self.file.exists());self.crypto.assert_not_called()
    def test_multi_account_round_trip_and_no_plaintext_password(self):
        a=self.save();b=self.save('test-B','FAKE-password-B')
        self.assertEqual(len(memory.list_entries(self.file)),2)
        self.assertEqual(memory.load(a,self.file)['password'],'FAKE-password-123')
        self.assertEqual(memory.load(b,self.file)['password'],'FAKE-password-B')
        self.assertNotIn('FAKE-password',self.file.read_text())
    def test_same_account_different_lines_are_independent(self):
        a=self.save(line=101);b=self.save(line=102)
        self.assertNotEqual(a,b);self.assertEqual(len(memory.list_entries(self.file)),2)
        self.assertEqual(memory.load(b,self.file)['line_id'],102)
    def test_update_existing_entry_does_not_duplicate(self):
        key=self.save();self.assertEqual(self.save(password='new-fake-password'),key)
        self.assertEqual(len(memory.list_entries(self.file)),1)
        self.assertEqual(memory.load(key,self.file)['password'],'new-fake-password')
    def test_selection_persists_last_used_without_logging_in(self):
        a=self.save();self.save('test-B')
        memory.select(a,self.file);self.assertEqual(memory.load(file=self.file)['key'],a)
    def test_only_account_does_not_call_encryption(self):
        key=self.save(remember=False);self.crypto.assert_not_called()
        value=memory.load(key,self.file);self.assertEqual(value['password'],'');self.assertFalse(value['remember_password'])
    def test_forget_one_password_preserves_other_accounts(self):
        a=self.save();b=self.save('test-B')
        memory.forget_password(a,self.file)
        self.assertFalse(memory.load(a,self.file)['remember_password'])
        self.assertTrue(memory.load(b,self.file)['remember_password'])
    def test_delete_one_and_last_entry(self):
        a=self.save();b=self.save('test-B');memory.delete(a,self.file)
        self.assertEqual(memory.load(file=self.file)['key'],b)
        memory.delete(b,self.file);self.assertFalse(self.file.exists())
    def test_unchecking_account_deletes_only_matching_entry(self):
        a=self.save();b=self.save('test-B')
        memory.save('example.invalid',16988,'test-A','unused',False,False,self.file,line_id=101)
        self.assertIsNone(memory.load(a,self.file));self.assertIsNotNone(memory.load(b,self.file))
    def test_encryption_failure_never_writes_plaintext_or_overwrites(self):
        self.save();original=self.file.read_bytes();self.crypto.side_effect=memory.MemoryError('encryption failed')
        with self.assertRaises(memory.MemoryError):self.save(password='do-not-save')
        self.assertEqual(self.file.read_bytes(),original)
    def test_decryption_failure_keeps_account_and_empty_password(self):
        a=self.save();self.crypto.side_effect=memory.MemoryError('cannot decrypt')
        data=memory.load(a,self.file);self.assertTrue(data['password_error']);self.assertEqual(data['password'],'')
        self.assertEqual(data['account'],'test-A')
    def test_corrupt_data_is_not_exposed(self):
        self.file.parent.mkdir();self.file.write_text('invalid FAKE-secret')
        with self.assertRaisesRegex(memory.MemoryError,'損壞') as error:memory.load(file=self.file)
        self.assertNotIn('FAKE-secret',str(error.exception))
    def test_invalid_selected_key_is_rejected(self):
        self.save();data=json.loads(self.file.read_text());data['selected']='bad';self.file.write_text(json.dumps(data))
        with self.assertRaises(memory.MemoryError):memory.load(file=self.file)
    def test_invalid_port_and_missing_password_rejected(self):
        with self.assertRaises(memory.MemoryError):memory.save('example.invalid',0,'test','pass',True,True,self.file)
        with self.assertRaises(memory.MemoryError):self.save(password='')
        self.assertFalse(self.file.exists())
    def test_metadata_bound_encryption(self):
        self.save(line=101);first=self.calls[-1][0]
        self.save(line=102);self.assertNotEqual(first,self.calls[-1][0])
    @unittest.skipUnless(os.name=='nt','Requires native Windows DPAPI')
    def test_native_windows_dpapi_roundtrip(self):
        patch.stopall()
        secret=b'FAKE-test-password';cipher=memory._crypt(secret,b'test-context')
        self.assertNotEqual(cipher,secret);self.assertEqual(memory._crypt(cipher,b'test-context',True),secret)

class ServerLines(unittest.TestCase):
    def example(self):return [{'id':1,'name':'測試服'},{'id':102,'address':'b.invalid','port':16989},{'id':101,'address':'a.invalid','port':16988}]
    def test_original_server_list_parsing_uses_actual_endpoints(self):
        rows=server_lines.parse(self.example());self.assertEqual([r['id'] for r in rows],[101,102])
        self.assertIn('1線',rows[0]['name']);self.assertEqual(rows[0]['host'],'a.invalid');self.assertEqual(rows[1]['port'],16989)
    def test_invalid_or_empty_lines_rejected(self):
        for data in ([],[{'id':1}], [{'id':101,'address':'x','port':0}], [{'id':101,'address':'bad host','port':123}],self.example()+[self.example()[1]]):
            with self.subTest(data=data),self.assertRaises(ValueError):server_lines.parse(data)
    def test_bundled_official_lines_and_endpoint_lookup(self):
        rows=server_lines.load()
        self.assertEqual([r['id'] for r in rows],[101,102,103,104,105,201,202])
        self.assertTrue(all(r['port']==16988 for r in rows))
        self.assertEqual(server_lines.for_endpoint(rows,'34.81.10.22',16988)['id'],101)
        self.assertIsNone(server_lines.for_endpoint(rows,'unknown.invalid',16988))
        self.assertEqual(len({r['host'] for r in rows}),7)


class WindowsAdapter(unittest.TestCase):
    def test_dpapi_user_scope_blob_contract_and_native_memory_release(self):
        buffers=[];flags_seen=[];freed=[]
        class Function:
            def __init__(self,handler):self.handler=handler
            def __call__(self,*args):return self.handler(*args)
        def perform(decrypt,source,description,entropy,reserved,prompt,flags,output):
            self.assertEqual(flags,1);self.assertIsNone(reserved);self.assertIsNone(prompt)
            self.assertEqual(ctypes.string_at(entropy._obj.data,entropy._obj.size),b'context')
            self.assertEqual(ctypes.string_at(source._obj.data,source._obj.size),b'cipher' if decrypt else b'FAKE-secret')
            if decrypt:self.assertIsNone(description)
            payload=b'FAKE-secret' if decrypt else b'cipher'
            buffer=ctypes.create_string_buffer(payload);buffers.append(buffer)
            output._obj.size=len(payload);output._obj.data=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte));flags_seen.append(flags)
            return 1
        from types import SimpleNamespace
        crypt=SimpleNamespace(CryptProtectData=Function(lambda *args:perform(False,*args)),CryptUnprotectData=Function(lambda *args:perform(True,*args)))
        kernel=SimpleNamespace(LocalFree=Function(lambda pointer:freed.append(pointer)))
        def dll(name,**kwargs):
            self.assertTrue(kwargs['use_last_error']);return crypt if name=='crypt32' else kernel
        with patch.object(memory.os,'name','nt'),patch.object(ctypes,'WinDLL',side_effect=dll,create=True):
            self.assertEqual(memory._crypt(b'FAKE-secret',b'context'),b'cipher')
            self.assertEqual(memory._crypt(b'cipher',b'context',True),b'FAKE-secret')
        self.assertEqual(flags_seen,[1,1]);self.assertEqual(len(freed),2)

if __name__=='__main__':unittest.main(verbosity=2)
