import asyncio, importlib.util
from datetime import datetime, timezone, timedelta
spec=importlib.util.spec_from_file_location('premium','utils/premium.py'); m=importlib.util.module_from_spec(spec)
# fake utils imports
import sys, types
sb=types.SimpleNamespace(); utils=types.ModuleType('utils'); utils.supabase_client=sb
sys.modules['utils']=utils;sys.modules['utils.supabase_client']=sb
spec.loader.exec_module(m)
class FakeSB:
    def __init__(self): self.rows={}
    async def select(self,*a,filters=None,**k):
        uid=filters['user_id']; return [self.rows[uid]] if uid in self.rows else []
    async def upsert(self,t,row,on_conflict=None): self.rows[row['user_id']]=row; return [row]
    async def delete(self,t,c,v): self.rows.pop(v,None); return []
f=FakeSB(); sb.select=f.select;sb.upsert=f.upsert;sb.delete=f.delete
async def main():
    m.invalidate(); meta={'allowed_users':[111]}
    assert await m.can_access(meta,111)
    assert not await m.can_access(meta,222)
    r=await m.grant(222,30,999,extend=True)
    assert await m.can_access(meta,222)
    first=m.parse(r['expires_at'])
    r2=await m.grant(222,10,999,extend=True)
    assert m.parse(r2['expires_at']) > first
    await m.revoke(222); assert not await m.can_access(meta,222)
    # public/unrestricted remains public
    assert await m.can_access({'allowed_users':[]},333)
    # expired premium denied
    f.rows[333]={'user_id':333,'expires_at':(m.now()-timedelta(seconds=1)).isoformat()};m.invalidate(333)
    assert not await m.can_access(meta,333)
    print('PREMIUM_ACCESS_TESTS_PASSED')
asyncio.run(main())
