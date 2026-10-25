# Web sahifada majburiy obunani qo'llash (web repo ga qo'shiladi)

Bot har foydalanuvchining obuna holatini Supabase `force_join_status` jadvaliga yozadi
(o'zgarganda yoki 20 daqiqada bir), sozlama esa `force_join_config` (id=1) da turadi.
Web sahifa (login.html / web_test.html / edit.html) YUKLANISHIDA shuni tekshirsin:

```js
async function fjGate(sb, uid) {
  const { data: cfg } = await sb.from('force_join_config').select('enabled,channels').eq('id', 1).maybeSingle();
  if (!cfg || !cfg.enabled || !(cfg.channels || []).length) return true;      // majburiy obuna o'chiq
  const { data: st } = await sb.from('force_join_status').select('ok,checked_at').eq('user_id', uid).maybeSingle();
  const fresh = st && (Date.now() - new Date(st.checked_at).getTime()) < 24 * 3600 * 1000;
  return !!(st && st.ok && fresh);
}
// if (!(await fjGate(sb, uid))) { show("Avval botga o'ting, majburiy kanallarga a'zo bo'ling va /start bosing"); return; }
```
Eslatma: login hozir `?uid=` orqali ishlaydi (tasdiqlanmagan), shuning uchun bu — to'liq himoya emas,
faqat oddiy foydalanuvchini to'xtatadi. To'liq himoya uchun Telegram `initData` imzosini serverda tekshirish kerak.
