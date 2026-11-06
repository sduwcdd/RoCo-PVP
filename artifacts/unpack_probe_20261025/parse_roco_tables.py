"""Parse extracted Roco compressed config tables using pinned FRocoBinData.
Missing fields stay missing; localized string IDs retained; all row lengths checked.
"""
import json,struct,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent/'battle_analysis'/'tables'
class Bin:
 def __init__(self,b,local=False):
  self.b=b;self.p=0;self.local=local;self.unresolved=[]
  if self.read(4)!=bytes.fromhex('be17df53'):raise ValueError('Bin magic')
  self.p=len(b)-(28 if local else 68)
  if not local:
   self.dataoff=self.num('q');self.datalen=self.num('q');self.count=self.num('i');self.structsize=self.num('q');doff=self.num('q');dn=self.num('i')
  coff=self.num('q');cn=self.num('i');self.constoff=self.num('q');self.constlen=self.num('q')
  self.constants=self.entries(coff,cn)
  if not local:self.rows=self.entries(doff,dn)
 def read(self,n):
  if n<0 or self.p+n>len(self.b):raise ValueError('Bin bounds')
  v=self.b[self.p:self.p+n];self.p+=n;return v
 def num(self,t):return struct.unpack('<'+t,self.read(struct.calcsize('<'+t)))[0]
 def entries(self,off,n):
  if n<0 or n>1000000:raise ValueError('Entry cap')
  self.p=off;return [tuple(self.num(t) for t in ['I','i','q']) for _ in range(n)]
 def entry(self,index):
  if not 1<=index<=len(self.constants):raise ValueError(f'Constant index {index}')
  _,length,offset=self.constants[index-1]
  if offset<0 or length<0 or offset+length>len(self.b):raise ValueError('Constant bounds')
  return length,offset
 def text(self,index):
  if index==0:return ''
  n,off=self.entry(index);return self.b[off:off+n].decode('utf-8')
 def prop(self,p,loc,depth):
  t=p['Type'];fmt={'EUint32':'I','EInt32':'i','EInt64':'q','EUint64':'Q','EFloat':'f','EBool':'B'}
  if t in fmt:
   v=self.num(fmt[t]);return bool(v) if t=='EBool' else v
  if t=='EString':return self.text(self.num('I'))
  if t=='ELocalizedString':
   i=self.num('i');txt=loc.text(i) if loc and i>0 else ('' if i==0 else None)
   if txt is None:self.unresolved.append(i)
   return {'localization_id':i,'text':txt}
  if t=='EStruct':
   i=self.num('i');n,off=self.entry(i);saved=self.p;self.p=off;v=self.parse_struct(p['Struct'],loc,depth+1)
   if self.p!=off+n:raise ValueError('Nested struct length mismatch')
   self.p=saved;return v
  raise ValueError(f'Unsupported type {t}')
 def parse_struct(self,s,loc,depth=0):
  if depth>32:raise ValueError('Struct recursion')
  props=s['Properties'];flags=self.read((len(props)+7)//8);out={}
  for j,p in enumerate(props):
   if not flags[j//8]&(1<<(7-j%8)):continue
   if p.get('DynamicArray') or p.get('ArrayDim') is not None:
    n,off=self.entry(self.num('i'));stride=p['Size'] if p.get('DynamicArray') else 4
    if not stride or n%stride:raise ValueError('Array size mismatch')
    saved=self.p;self.p=off;v=[self.prop(p,loc,depth) for _ in range(n//stride)]
    if self.p!=off+n:raise ValueError('Array consumption mismatch')
    self.p=saved
   else:v=self.prop(p,loc,depth)
   out[p['Name']]=v
  return out
 def parse_rows(self,s,loc):
  if self.count!=len(self.rows):raise ValueError('Row count mismatch')
  out={}
  for i,(_,length,off) in enumerate(self.rows):
   if not length:continue
   self.p=off;v=self.parse_struct(s,loc)
   if self.p!=off+length:raise ValueError(f'Row {i} length mismatch {self.p-off} vs {length}')
   key=str(v[s['UniqueKey']])
   if key in out:raise ValueError('Duplicate primary key')
   out[key]=v
  return out
if __name__=='__main__':
 summary=[]
 for schema in sorted((ROOT/'BinConf').glob('*.non')):
  name=schema.stem;m={'table':name}
  try:
   s=json.loads(schema.read_text(encoding='utf-8'));raw=(ROOT/'BinDataCompressed'/(name+'.bytes')).read_bytes();b=Bin(raw);lp=ROOT/'BinLocalize/dev_CN'/(name+'.bytes');loc=Bin(lp.read_bytes(),True) if lp.exists() else None
   rows=b.parse_rows(s,loc);dest=ROOT/'parsed';dest.mkdir(exist_ok=True);(dest/(name+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
   m.update(rows=len(rows),declared_rows=b.count,properties=len(s['Properties']),all_row_lengths_verified=True,unresolved_localization_ids=sorted(set(b.unresolved)),binary_sha256=hashlib.sha256(raw).hexdigest(),output=str((dest/(name+'.json')).relative_to(ROOT)))
  except Exception as ex:m['error']=repr(ex)
  summary.append(m);print(json.dumps(m,ensure_ascii=True))
 (ROOT/'parse_report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
