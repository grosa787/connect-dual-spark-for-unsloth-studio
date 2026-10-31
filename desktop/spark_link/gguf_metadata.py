"""Bounded GGUF v2/v3 metadata parser; never maps or downloads model tensors."""
import struct
from urllib.request import Request,urlopen

class NeedMoreData(ValueError): pass

def parse_header(data):
    position=0
    def take(size):
        nonlocal position
        if size<0 or position+size>len(data): raise NeedMoreData('GGUF metadata exceeds current header range')
        value=data[position:position+size]; position+=size
        return value
    def number(fmt): return struct.unpack('<'+fmt,take(struct.calcsize(fmt)))[0]
    def string_value():
        size=number('Q')
        if size>8*1024*1024: raise ValueError('GGUF string is too large')
        return take(size).decode('utf-8',errors='replace')
    formats={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
    def value(kind,depth=0):
        if depth>3: raise ValueError('Nested GGUF array is invalid')
        if kind in formats: return number(formats[kind])
        if kind==8: return string_value()
        if kind==9:
            element,count=number('I'),number('Q')
            if count>1000000: raise ValueError('GGUF metadata array is too large')
            if element in formats:
                size=struct.calcsize(formats[element])
                raw=take(count*size)
                return list(struct.unpack('<'+formats[element]*count,raw)) if count<=4096 else None
            return [value(element,depth+1) for _ in range(count)]
        raise ValueError('Unknown GGUF metadata type')
    if take(4)!=b'GGUF': raise ValueError('File is not GGUF')
    if number('I') not in (2,3): raise ValueError('Unsupported GGUF version')
    tensors,count=number('Q'),number('Q')
    if count>100000: raise ValueError('Too many GGUF metadata fields')
    metadata={}
    for _ in range(count):
        key=string_value()
        if len(key)>256: raise ValueError('Invalid GGUF metadata key')
        kind=number('I')
        # Hyperparameters precede tokenizer tables in standard llama.cpp exports.
        # Missing fields remain unknown rather than reading unbounded token tables.
        if key.startswith('tokenizer.') and 'general.architecture' in metadata: break
        metadata[key]=value(kind)
    return metadata


def read_remote_header(url):
    for size in (65536,262144,1048576,4194304,8388608):
        request=Request(url,headers={'Range':f'bytes=0-{size-1}','User-Agent':'Spark-Link/1.1'})
        with urlopen(request,timeout=15) as response:
            data=response.read(size)
        try: return parse_header(data)
        except NeedMoreData:
            if len(data)<size: raise
    raise ValueError('GGUF metadata could not be read within the 8 MiB limit')
