"""Cross-process read/modify/write locks and replace-only JSON writes."""
from contextlib import contextmanager
import json,os,tempfile,threading,time
from pathlib import Path

_registry={}
_registry_lock=threading.Lock()
_local=threading.local()


@contextmanager
def file_lock(file,timeout=5):
    key=str(Path(file).resolve())
    with _registry_lock:mutex=_registry.setdefault(key,threading.RLock())
    with mutex:
        depths=getattr(_local,'depths',{})
        if depths.get(key):
            depths[key]+=1
            try:yield
            finally:depths[key]-=1
            return
        lockfile=Path(key+'.lock');lockfile.parent.mkdir(parents=True,exist_ok=True)
        with lockfile.open('a+b') as stream:
            stream.seek(0,2)
            if stream.tell()==0:stream.write(b'0');stream.flush()
            deadline=time.monotonic()+timeout
            while True:
                try:
                    if os.name=='nt':
                        import msvcrt
                        stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except (OSError,BlockingIOError):
                    if time.monotonic()>=deadline:raise TimeoutError('設定檔正由其他程式使用，請稍後重試')
                    time.sleep(0.02)
            _local.depths=depths;depths[key]=1
            try:yield
            finally:
                depths.pop(key,None)
                if os.name=='nt':
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def write_json(file,value):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=file.name+'.',dir=file.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,file)
    finally:Path(name).unlink(missing_ok=True)
