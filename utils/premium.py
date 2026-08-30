"""Global Premium ID access control."""
import logging
from datetime import datetime, timezone, timedelta
from utils import supabase_client as sb
log=logging.getLogger(__name__); UTC=timezone.utc; _cache={}; _ttl=30
def now(): return datetime.now(UTC)
def parse(v):
    if not v:return None
    if isinstance(v,datetime): return v if v.tzinfo else v.replace(tzinfo=UTC)
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00")); return d if d.tzinfo else d.replace(tzinfo=UTC)
    except: return None
def invalidate(uid=None):
    if uid is None:_cache.clear()
    else:_cache.pop(int(uid),None)
async def get(uid):
    uid=int(uid); ts=now().timestamp(); h=_cache.get(uid)
    if h and h[0]>ts:return h[1]
    try:r=(await sb.select("premium_users",filters={"user_id":uid},limit=1)); row=r[0] if r else None
    except Exception as e: log.error("premium lookup %s: %s",uid,e); row=None
    _cache[uid]=(ts+_ttl,row); return row
async def is_active(uid):
    r=await get(uid); e=parse(r.get("expires_at")) if r else None; return bool(e and e>now())
async def grant(uid,days,by=None,extend=True):
    if not 1<=int(days)<=3650: raise ValueError("days 1..3650")
    uid=int(uid); n=now(); old=await get(uid); olde=parse(old.get("expires_at")) if old else None
    base=max(n,olde) if extend and olde and olde>n else n; exp=base+timedelta(days=int(days))
    row={"user_id":uid,"started_at":(old.get("started_at") if extend and olde and olde>n else n.isoformat()),"expires_at":exp.isoformat(),"granted_by":int(by) if by else None,"updated_at":n.isoformat()}
    await sb.upsert("premium_users",row,on_conflict="user_id"); invalidate(uid); return row
async def revoke(uid): await sb.delete("premium_users","user_id",int(uid)); invalidate(uid)
async def active_list(limit=100):
    rows=await sb.select("premium_users",order="expires_at",desc=True,limit=limit); n=now(); return [r for r in rows if (parse(r.get("expires_at")) or n)>n]
async def can_access(meta,uid):
    allowed=meta.get("allowed_users") or []
    try:a={int(x) for x in allowed}
    except:a=set()
    return not a or int(uid) in a or await is_active(uid)
