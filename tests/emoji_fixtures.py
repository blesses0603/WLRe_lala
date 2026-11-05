import hashlib,struct
from unittest.mock import patch
from PIL import Image
from wlre.services.world.emoji_database import import_catalog
RAW=struct.pack('<I',2)+struct.pack('<BBBIB',1,0,1,10,0)+struct.pack('<BBBIB',2,0,2,11,1)
PIN=hashlib.sha256(RAW).hexdigest()
def sprites(color='blue'):
    return [('Emoji_001_1',Image.new('RGBA',(24,22),color)),('Emoji_002_1',Image.new('RGBA',(22,24),color))]
def catalog(database,key='a'*64,color='blue'):
    with patch('wlre.services.world.emoji_database.KNOWN_SHA256',PIN):
        return import_catalog(database,key,{'EmojiData_C':RAW,'bundle_test':color.encode()},lambda:iter(sprites(color)))
