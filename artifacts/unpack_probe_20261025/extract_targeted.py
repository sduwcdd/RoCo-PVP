"""Offline targeted payload extraction. Adapted from pinned CUE4Parse sources.
No archive writes. Script bytecode is decoded, never executed.
"""
from pathlib import Path
import json,struct,hashlib,zlib,re
import search_directories as sd
from probe import Reader,PAKS
ROOT=sd.ROOT
OUT=ROOT/'battle_analysis';OUT.mkdir(exist_ok=True)
def extract(entry):
 p=PAKS/entry['pak']; before=p.stat()
 with p.open('rb') as f:
  def read(off,size):
   if off<0 or size<0 or size>32*1024*1024 or off+size>before.st_size:raise ValueError('read bounds')
   f.seek(off);b=f.read(size)
   if len(b)!=size:raise ValueError('short read')
   return b
  tail=read(before.st_size-256,256);i=tail.rfind(bytes.fromhex('e1126f5a'));version,off,size=struct.unpack_from('<IQQ',tail,i+4);strategy=tail[-1] if version>=12 else 0
  pc=read(off,size);plain=sd.decrypt(pc,strategy,p.name) if tail[i-1] else pc
  if hashlib.sha1(plain).digest()!=tail[i+24:i+44]:raise ValueError('index hash mismatch')
  r=Reader(plain);r.string();r.read(4+8+4+36+4+8+8+20);encoded=r.read(r.num('I'))
  loc=entry['entry_location']
  if loc<0:raise ValueError('nonencoded entry unsupported')
  e=Reader(encoded,loc);bits=e.num('I');blocksize=e.num('I') if bits&63==63 else (bits&63)<<11
  method=(bits>>23)&63;offset=e.num('I' if bits&(1<<31) else 'Q');usize=e.num('I' if bits&(1<<30) else 'Q');csize=e.num('I' if bits&(1<<29) else 'Q') if method else usize
  enc=bool(bits&(1<<22));nb=(bits>>6)&65535;es=nb>>10;nb&=1023;hdrsize=53+(4+nb*16 if method else 0)
  if usize>8*1024*1024:raise ValueError('payload cap')
  chunks=[];source_chunks=[]
  if method==1:
   start=offset+hdrsize
   for n in range(nb):
    length=csize if nb==1 and not enc else e.num('I');physical=(length+15)//16*16 if enc else length
    raw=read(start,physical);source_chunks.append((start,raw));start+=physical
    data=sd.decrypt(raw,es,entry['name']) if enc else raw
    zd=zlib.decompressobj();out=zd.decompress(data[:length],usize+1)
    if not zd.eof or len(out)>usize:raise ValueError('zlib invalid')
    chunks.append(out)
   payload=b''.join(chunks)
  elif method==0:
   raw=read(offset+hdrsize,(usize+15)//16*16 if enc else usize);source_chunks.append((offset+hdrsize,raw))
   if enc:
    if es>=11:payload=b''.join(sd.decrypt(raw[i:i+4096],es,entry['name']) for i in range(0,len(raw),4096))
    else:payload=sd.decrypt(raw,es,entry['name'])
   else:payload=raw
   payload=payload[:usize]
  else:raise ValueError(f'compression {method} unsupported')
  if len(payload)!=usize:raise ValueError('payload size mismatch')
  outer=payload
  if payload[:8]==struct.pack('<Q',0x7C3F9A215E8B4D26):
   inner,ds=struct.unpack_from('<Ii',payload,8);payload=sd.decrypt(payload[16:],inner,entry['name'])[:ds]
   if len(payload)!=ds:raise ValueError('inner size mismatch')
  if any(read(o,len(b))!=b for o,b in source_chunks):raise ValueError('source changed')
 after=p.stat()
 meta={'pak':p.name,'path':entry['path'],'offset':offset,'declared_size':usize,'compression':method,'payload_strategy':es,'payload_sha256':hashlib.sha256(payload).hexdigest(),'source_ranges_sha256':[{'offset':o,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()} for o,b in source_chunks],'source_ranges_unchanged':True,'stat_unchanged':(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)}
 return payload,meta
