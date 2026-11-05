"""Synthetic minimap artwork for UI tests; no bundled official pixels."""
from types import SimpleNamespace
import io
from PIL import Image

class Images:
    def __init__(self,key,models):
        self.catalog_key=key;self.models=frozenset(models)
    def png(self,model):
        if model not in self.models:return None
        output=io.BytesIO();Image.new('RGBA',(1024,1024),(12,34,56,255)).save(output,format='PNG')
        return output.getvalue()


def attach(runtime,models=None):
    if getattr(runtime,'catalog_identity',None) is None:
        runtime.catalog_identity=SimpleNamespace(key='synthetic-maps')
    if models is None:models=[row['model_id'] for row in runtime.stages.values()]
    runtime.smallmaps=Images(runtime.catalog_identity.key,models)
    return runtime
