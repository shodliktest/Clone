"""🌐 QUIZ BOT — Admin Panel"""
import streamlit as st
import pandas as pd
from datetime import date, datetime
from zoneinfo import ZoneInfo

st.set_page_config(
    page_title="Quiz Bot Admin",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ══ CUSTOM CSS ════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

:root {
    --bg:       #0a0e1a;
    --surface:  #111827;
    --border:   #1e293b;
    --accent:   #6366f1;
    --accent2:  #22d3ee;
    --green:    #10b981;
    --red:      #f43f5e;
    --yellow:   #f59e0b;
    --text:     #e2e8f0;
    --muted:    #64748b;
}

html, body, [class*="css"] {
    font-family: 'Syne', sans-serif !important;
    background: var(--bg) !important;
    color: var(--text) !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] * { color: var(--text) !important; }

/* Metric kartalar */
[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px !important;
    position: relative;
    overflow: hidden;
}
[data-testid="stMetric"]::before {
    content: '';
    position: absolute; top:0; left:0; right:0; height:2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
}
[data-testid="stMetricValue"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 2rem !important;
    color: var(--text) !important;
}
[data-testid="stMetricLabel"] { color: var(--muted) !important; font-size:0.8rem !important; }

/* Dataframe */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    overflow: hidden;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Space Mono', monospace !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
    transition: all 0.2s !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(99,102,241,0.4) !important;
}
button[kind="secondary"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
}

/* Input */
input, .stTextInput input {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 8px !important;
    font-family: 'Space Mono', monospace !important;
}

/* Radio */
.stRadio label { color: var(--text) !important; }
.stRadio [data-baseweb="radio"] div { border-color: var(--accent) !important; }

/* Progress */
.stProgress > div > div { background: var(--border) !important; border-radius: 99px !important; }
.stProgress > div > div > div {
    background: linear-gradient(90deg, var(--accent), var(--accent2)) !important;
    border-radius: 99px !important;
}

/* Alert */
.stSuccess { background: rgba(16,185,129,0.1) !important; border-color: var(--green) !important; }
.stError   { background: rgba(244,63,94,0.1)  !important; border-color: var(--red)   !important; }
.stWarning { background: rgba(245,158,11,0.1) !important; border-color: var(--yellow)!important; }
.stInfo    { background: rgba(99,102,241,0.1) !important; border-color: var(--accent)!important; }

/* Title */
h1 { font-size: 1.6rem !important; letter-spacing: -0.5px; margin-bottom: 0.3rem !important; }
h2, h3 { color: var(--text) !important; }

/* Expander */
.streamlit-expanderHeader {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
}

/* Tab */
.stTabs [data-baseweb="tab-list"] { background: var(--surface) !important; border-radius: 10px; padding: 4px; }
.stTabs [data-baseweb="tab"] { color: var(--muted) !important; border-radius: 7px !important; }
.stTabs [aria-selected="true"] {
    background: var(--accent) !important;
    color: white !important;
}

/* Divider */
hr { border-color: var(--border) !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
""", unsafe_allow_html=True)


# ══ BOT START ═════════════════════════════════════════════
@st.cache_resource
def start_bot():
    try:
        from bot import run_in_background
        t = run_in_background()
        if t is None:
            import logging
            logging.getLogger(__name__).error("Bot thread None qaytardi!")
        return t
    except Exception as e:
        import traceback, logging
        logging.getLogger(__name__).error(f"start_bot xato: {e}")
        traceback.print_exc()
        return None

bot_thread = start_bot()


# ══ LOGIN ═════════════════════════════════════════════════
if not st.session_state.get("auth"):
    col = st.columns([1, 2, 1])[1]
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("""
        <div style='text-align:center; margin-bottom:2rem'>
            <div style='font-size:3rem'>🎓</div>
            <h1 style='font-size:1.8rem; background:linear-gradient(135deg,#6366f1,#22d3ee);
                       -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                       font-family:Space Mono,monospace'>QUIZ BOT ADMIN</h1>
            <p style='color:#64748b; font-size:0.85rem'>Admin panel — kirish</p>
        </div>
        """, unsafe_allow_html=True)
        pwd = st.text_input("Parol", placeholder="🔑 Parol...", type="password", label_visibility="collapsed")
        if st.button("→ Kirish", use_container_width=True):
            if pwd == st.secrets.get("ADMIN_PASSWORD", "admin123"):
                st.session_state.auth = True; st.rerun()
            else:
                st.error("❌ Noto'g'ri parol!")
    st.stop()


# ══ SIDEBAR ═══════════════════════════════════════════════
with st.sidebar:
    alive = bot_thread and bot_thread.is_alive()
    st.markdown(f"""
    <div style='padding:16px 0 8px'>
        <div style='font-family:Space Mono,monospace; font-size:1rem; font-weight:700;
                    background:linear-gradient(135deg,#6366f1,#22d3ee);
                    -webkit-background-clip:text; -webkit-text-fill-color:transparent'>
            🎓 QUIZ BOT
        </div>
        <div style='margin-top:8px; display:flex; align-items:center; gap:8px'>
            <div style='width:8px;height:8px;border-radius:50%;
                        background:{"#10b981" if alive else "#f43f5e"};
                        box-shadow:0 0 8px {"#10b981" if alive else "#f43f5e"}'></div>
            <span style='color:#64748b; font-size:0.8rem; font-family:Space Mono,monospace'>
                {"● ONLINE" if alive else "● OFFLINE"}
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    menu = st.radio("Menyu", [
        "📊 Dashboard",
        "💾 RAM Monitor",
        "📋 Testlar",
        "👥 Userlar",
        "🔄 Backup",
        "🏆 Reyting",
    ], label_visibility="collapsed")

    st.markdown("---")

    # Live vaqt
    now = datetime.now()
    st.markdown(f"""
    <div style='font-family:Space Mono,monospace; font-size:0.75rem; color:#64748b; text-align:center'>
        {now.strftime('%Y-%m-%d')}<br>
        <span style='font-size:1.1rem; color:#e2e8f0'>{now.strftime('%H:%M:%S')}</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 Chiqish", use_container_width=True):
        st.session_state.auth = False; st.rerun()


# ══ HELPERS ═══════════════════════════════════════════════
def arc_gauge_html(pct, mb, limit_mb=450):
    """Chiroyli SVG arc gauge — Plotly dan yaxshiroq"""
    color  = "#10b981" if pct < 60 else "#f59e0b" if pct < 80 else "#f43f5e"
    glow   = color
    label  = "YAXSHI" if pct < 60 else "EHTIYOT" if pct < 80 else "KRITIK!"
    # SVG arc hisoblash (270 daraja yoy — pastdan boshlaydi)
    import math
    r = 90; cx = cy = 120
    start_angle = 135  # daraja
    sweep = 270        # to'liq yoy
    used_sweep = sweep * pct / 100

    def polar(angle_deg, radius):
        a = math.radians(angle_deg)
        return cx + radius * math.cos(a), cy + radius * math.sin(a)

    def arc_path(start_deg, end_deg, r_inner, r_outer):
        s1x, s1y = polar(start_deg, r_outer)
        e1x, e1y = polar(end_deg,   r_outer)
        s2x, s2y = polar(end_deg,   r_inner)
        e2x, e2y = polar(start_deg, r_inner)
        large = 1 if abs(end_deg - start_deg) > 180 else 0
        return (f"M {s1x:.2f} {s1y:.2f} "
                f"A {r_outer} {r_outer} 0 {large} 1 {e1x:.2f} {e1y:.2f} "
                f"L {s2x:.2f} {s2y:.2f} "
                f"A {r_inner} {r_inner} 0 {large} 0 {e2x:.2f} {e2y:.2f} Z")

    bg_path   = arc_path(start_angle, start_angle + sweep, 70, 105)
    fill_path = arc_path(start_angle, start_angle + used_sweep, 70, 105) if pct > 0 else ""

    # Tick belgilari: 0%, 25%, 50%, 75%, 100%
    ticks_html = ""
    for tick_pct, tick_label in [(0,"0"), (25,"25"), (50,"50"), (75,"75"), (100,"100")]:
        angle = start_angle + sweep * tick_pct / 100
        tx, ty = polar(angle, 115)
        ticks_html += f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" dominant-baseline="middle" font-size="7" fill="#475569" font-family="Space Mono">{tick_label}</text>'

    return f"""
<div style="background:#0f172a;border:1px solid #1e293b;border-radius:20px;
            padding:24px;text-align:center;position:relative;overflow:hidden">
  <div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 0%,
              {color}10 0%,transparent 70%);pointer-events:none"></div>
  <div style="font-family:'Space Mono',monospace;font-size:0.7rem;color:#475569;
              letter-spacing:3px;margin-bottom:12px">RAM MONITOR</div>
  <svg viewBox="0 0 240 200" width="100%" style="max-width:280px;display:block;margin:0 auto">
    <defs>
      <linearGradient id="arcGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%"   stop-color="{color}" stop-opacity="0.6"/>
        <stop offset="100%" stop-color="{color}"/>
      </linearGradient>
      <filter id="glow">
        <feGaussianBlur stdDeviation="3" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <!-- Orqa fon yoy -->
    <path d="{bg_path}" fill="#1e293b"/>
    <!-- To'ldirilgan yoy -->
    {"<path d='" + fill_path + "' fill='url(#arcGrad)' filter='url(#glow)'/>" if fill_path else ""}
    <!-- Tick belgilari -->
    {ticks_html}
    <!-- Markaziy matn -->
    <text x="120" y="118" text-anchor="middle" font-family="Space Mono" 
          font-size="32" font-weight="bold" fill="{color}">{pct:.0f}</text>
    <text x="120" y="135" text-anchor="middle" font-family="Space Mono" 
          font-size="11" fill="{color}80">%</text>
    <text x="120" y="158" text-anchor="middle" font-family="Syne,sans-serif" 
          font-size="9" fill="#475569">{mb} MB / {limit_mb} MB</text>
    <text x="120" y="173" text-anchor="middle" font-family="Space Mono" 
          font-size="8" fill="{color}" letter-spacing="2">{label}</text>
  </svg>
  <!-- Pastki progress bar -->
  <div style="margin-top:4px;height:3px;background:#1e293b;border-radius:99px;overflow:hidden">
    <div style="height:100%;width:{pct}%;background:{color};
                border-radius:99px;transition:width 1s ease;
                box-shadow:0 0 8px {glow}"></div>
  </div>
</div>"""


def donut_chart(correct, wrong, skipped):
    total = (correct or 0) + (wrong or 0) + (skipped or 0)
    if total == 0: return None
    c_pct = round((correct or 0)*100/total)
    w_pct = round((wrong   or 0)*100/total)
    s_pct = 100 - c_pct - w_pct
    html = f"""
    <div style="display:flex;gap:16px;align-items:center;padding:8px 0">
      <div style="display:flex;flex-direction:column;gap:6px;width:100%">
        <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#e2e8f0">
          <span>✅ To'g'ri</span><span style="color:#10b981">{correct} ({c_pct}%)</span>
        </div>
        <div style="height:8px;background:#1e293b;border-radius:4px">
          <div style="height:8px;width:{c_pct}%;background:#10b981;border-radius:4px"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#e2e8f0">
          <span>❌ Xato</span><span style="color:#f43f5e">{wrong} ({w_pct}%)</span>
        </div>
        <div style="height:8px;background:#1e293b;border-radius:4px">
          <div style="height:8px;width:{w_pct}%;background:#f43f5e;border-radius:4px"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#e2e8f0">
          <span>⏭ O'tkazilgan</span><span style="color:#64748b">{skipped} ({s_pct}%)</span>
        </div>
        <div style="height:8px;background:#1e293b;border-radius:4px">
          <div style="height:8px;width:{s_pct}%;background:#64748b;border-radius:4px"></div>
        </div>
      </div>
    </div>"""
    return html


def bar_chart(data: dict, title=""):
    if not data: return None
    mx = max(data.values()) or 1
    colors = ["#10b981","#22d3ee","#6366f1","#f59e0b","#f43f5e",
              "#8b5cf6","#06b6d4","#84cc16","#ec4899","#14b8a6"]
    rows = ""
    for i,(k,v) in enumerate(sorted(data.items(), key=lambda x: -x[1])):
        c   = colors[i % len(colors)]
        pct = round(v * 100 / mx)
        rows += f"""<div style='margin-bottom:7px'>
          <div style='display:flex;justify-content:space-between;font-size:0.8rem;color:#e2e8f0;margin-bottom:2px'>
            <span>{k}</span><span style='font-family:Space Mono,monospace;color:{c}'>{v}</span>
          </div>
          <div style='height:7px;background:#1e293b;border-radius:4px'>
            <div style='height:7px;width:{pct}%;background:{c};border-radius:4px'></div>
          </div></div>"""
    return f"<div style='padding:4px 0'><div style='font-size:0.78rem;color:#64748b;margin-bottom:8px'>{title}</div>{rows}</div>"


# ══ DASHBOARD ═════════════════════════════════════════════
if menu == "📊 Dashboard":
    from utils.ram_cache import stats, get_tests, get_daily
    s = stats(); daily = get_daily(); tests = get_tests()

    st.markdown("## 📊 Dashboard")
    st.markdown(f"<p style='color:#64748b;font-size:0.85rem;margin-top:-10px'>{date.today().strftime('%A, %d %B %Y')}</p>", unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 Testlar",          s["tests"],   help="RAM da saqlangan testlar")
    c2.metric("👥 Foydalanuvchilar",  s["users"],   help="RAM da saqlangan userlar")
    c3.metric("📊 Bugungi natijalar", s["daily_r"], help="Kanalga yuborilmagan natijalar")
    c4.metric("💾 RAM",              f"{s['mb']} MB", f"{s['pct']}% band")

    st.markdown("---")

    left, right = st.columns([2, 1])

    with left:
        st.markdown("#### 📈 Bugungi faollik")
        rows = []
        cat_count = {}
        correct_total = wrong_total = skip_total = 0
        for uid, udata in daily.items():
            for r in udata.get("results", []):
                test = next((t for t in tests if t.get("test_id")==r.get("test_id")), {})
                cat  = test.get("category", "Boshqa")
                cat_count[cat] = cat_count.get(cat, 0) + 1
                correct_total += r.get("correct_count", 0)
                wrong_total   += r.get("wrong_count", 0)
                skip_total    += r.get("skipped_count", 0)
                mode_icon = "📊" if r.get("mode") == "poll" else "▶️"
                pass_icon = "✅" if r.get("percentage", 0) >= 60 else "❌"
                rows.append({
                    "": pass_icon,
                    "Rejim": mode_icon,
                    "User": str(uid)[-6:],
                    "Test": r.get("test_id", "?"),
                    "Natija": f"{r.get('percentage',0):.1f}%",
                    "Vaqt": str(r.get("completed_at", ""))[:16],
                })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=220)
            # Fan bo'yicha bar chart
            if cat_count:
                html = bar_chart(cat_count, "Fan bo'yicha urinishlar")
                if html: st.markdown(html, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style='text-align:center;padding:60px;color:#64748b;
                        border:1px dashed #1e293b;border-radius:12px;margin-top:10px'>
                <div style='font-size:2rem'>📭</div>
                <div style='margin-top:8px'>Bugun natija yo'q</div>
            </div>
            """, unsafe_allow_html=True)

    with right:
        st.markdown("#### 🎯 Javoblar tahlili")
        html = donut_chart(correct_total, wrong_total, skip_total)
        if html: st.markdown(html, unsafe_allow_html=True)

        total_ans = correct_total + wrong_total + skip_total
        if total_ans > 0:
            acc = round(correct_total / total_ans * 100, 1)
            color = "#10b981" if acc >= 70 else "#f59e0b" if acc >= 50 else "#f43f5e"
            st.markdown(f"""
            <div style='text-align:center;padding:12px;background:#111827;
                        border:1px solid #1e293b;border-radius:10px;margin-top:-10px'>
                <div style='color:#64748b;font-size:0.75rem'>Umumiy aniqlik</div>
                <div style='font-family:Space Mono,monospace;font-size:1.8rem;color:{color}'>{acc}%</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 🤖 Bot holati")
        alive = bot_thread and bot_thread.is_alive()
        st.markdown(f"""
        <div style='padding:14px;background:#111827;border:1px solid #1e293b;
                    border-radius:10px;display:flex;align-items:center;gap:12px'>
            <div style='width:12px;height:12px;border-radius:50%;
                        background:{"#10b981" if alive else "#f43f5e"};
                        box-shadow:0 0 10px {"#10b981" if alive else "#f43f5e"};
                        animation:{"pulse 2s infinite" if alive else "none"}'></div>
            <div>
                <div style='font-family:Space Mono,monospace;font-size:0.9rem'>
                    {"ONLINE" if alive else "OFFLINE"}
                </div>
                <div style='color:#64748b;font-size:0.75rem'>Telegram bot</div>
            </div>
        </div>
        <style>@keyframes pulse {{0%,100%{{opacity:1}}50%{{opacity:0.5}}}}</style>
        """, unsafe_allow_html=True)


# ══ RAM MONITOR ═══════════════════════════════════════════
elif menu == "💾 RAM Monitor":
    from utils.ram_cache import stats, refresh_tests, clear_daily

    st.markdown("## 💾 RAM Monitor")
    s = stats()

    # ── Yuqori qator: arc gauge + 4 karta ──────────────────
    col_g, col_i = st.columns([1, 1])

    with col_g:
        import streamlit.components.v1 as components
        components.html(arc_gauge_html(s["pct"], s["mb"]), height=320, scrolling=False)

    with col_i:
        st.markdown("<br>", unsafe_allow_html=True)
        color_map = {
            "tests":    ("#6366f1", "📋", "Testlar",          f"{s['tests']} ta"),
            "users":    ("#22d3ee", "👥", "Userlar",          f"{s['users']} ta"),
            "daily_r":  ("#10b981", "📊", "Bugungi natijalar", f"{s['daily_r']} ta"),
            "limit":    ("#475569", "💽", "RAM Limit",         "450 MB"),
        }
        for key, (color, icon, label, value) in color_map.items():
            filled = s.get(key, 0) / 450 * 100 if key == "mb" else None
            st.markdown(f"""
            <div style='display:flex;justify-content:space-between;align-items:center;
                        padding:12px 16px;margin-bottom:7px;background:#0f172a;
                        border:1px solid #1e293b;border-radius:10px;
                        border-left:3px solid {color};position:relative;overflow:hidden'>
                <div style='position:absolute;inset:0;background:linear-gradient(90deg,{color}08,transparent);
                            pointer-events:none'></div>
                <span style='color:#94a3b8;font-size:0.83rem;z-index:1'>{icon} {label}</span>
                <span style='font-family:Space Mono,monospace;font-size:1rem;
                             color:{color};font-weight:700;z-index:1'>{value}</span>
            </div>
            """, unsafe_allow_html=True)

        # RAM hajm mini bar
        mb_pct = min(s["mb"] / 450 * 100, 100)
        bar_color = "#10b981" if mb_pct < 60 else "#f59e0b" if mb_pct < 80 else "#f43f5e"
        st.markdown(f"""
        <div style='background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:12px 16px'>
            <div style='display:flex;justify-content:space-between;margin-bottom:8px'>
                <span style='color:#94a3b8;font-size:0.83rem'>💾 Ishlatilgan hajm</span>
                <span style='font-family:Space Mono,monospace;color:{bar_color};font-size:0.9rem'>
                    {s['mb']} / 450 MB
                </span>
            </div>
            <div style='height:6px;background:#1e293b;border-radius:99px;overflow:hidden'>
                <div style='height:100%;width:{mb_pct:.1f}%;background:{bar_color};
                            border-radius:99px;box-shadow:0 0 8px {bar_color}'></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Alert ───────────────────────────────────────────────
    if s["pct"] >= 80:
        st.error(f"🚨 RAM **{s['pct']}%** to'lgan! Darhol flush qiling yoki cache tozalang.")
    elif s["pct"] >= 60:
        st.warning(f"⚠️ RAM **{s['pct']}%** to'lgan. Kuzatib boring.")
    else:
        st.success(f"✅ RAM holati yaxshi — **{s['pct']}%** band")

    # ── Amallar ─────────────────────────────────────────────
    st.markdown("#### ⚡ Amallar")
    col_a, col_b, col_c = st.columns(3)

    actions = [
        (col_a, "#6366f1", "🔄", "TEST CACHE",      "TG kanaldan qayta yuklanadi",    None),
        (col_b, "#f43f5e", "🗑", "NATIJALAR RAM",   f"{s['daily_r']} ta natija bor",  None),
        (col_c, "#22d3ee", "🔃", "YANGILASH",       "Statistikani refresh qilish",    None),
    ]
    btns = []
    for col, color, icon, title, desc, _ in actions:
        with col:
            st.markdown(f"""
            <div style='padding:14px 16px;background:#0f172a;border:1px solid #1e293b;
                        border-top:2px solid {color};border-radius:10px;margin-bottom:8px'>
                <div style='color:#475569;font-size:0.7rem;letter-spacing:2px;margin-bottom:4px'>{title}</div>
                <div style='font-size:0.85rem;color:#cbd5e1'>{desc}</div>
            </div>
            """, unsafe_allow_html=True)

    with col_a:
        if st.button("🔄 Test cache tozalash", use_container_width=True):
            refresh_tests(); st.success("✅ Test cache tozalandi!")
    with col_b:
        if st.button("🗑 Natijalar RAMini tozalash", use_container_width=True, type="secondary"):
            clear_daily(); st.success("✅ Natijalar tozalandi!")
    with col_c:
        if st.button("🔃 Yangilash", use_container_width=True):
            st.rerun()


# ══ TESTLAR ═══════════════════════════════════════════════
elif menu == "📋 Testlar":
    from utils.ram_cache import get_tests, refresh_tests
    st.markdown("## 📋 Testlar")

    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🔄 TG dan yukla", use_container_width=True):
            refresh_tests(); st.info("Keyingi so'rovda TG dan oladi.")

    tests = get_tests()
    if not tests:
        st.info("RAM bo'sh. Bot testlarni TG kanaldan yuklaydi.")
    else:
        # Statistika kartalar
        cats = {}
        total_q = total_plays = 0
        for t in tests:
            c = t.get("category", "Boshqa")
            cats[c] = cats.get(c, 0) + 1
            total_q += len(t.get("questions", []))
            total_plays += t.get("solve_count", 0)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Jami testlar",  len(tests))
        c2.metric("Jami savollar", total_q)
        c3.metric("Jami urinish",  total_plays)
        c4.metric("Fanlar soni",   len(cats))

        # Fan bo'yicha chart
        if cats:
            html = bar_chart(cats, "Fanlari bo'yicha testlar")
            if html: st.markdown(html, unsafe_allow_html=True)

        st.markdown("#### 📄 Test ro'yxati")
        vis_map = {"public": "🌍", "link": "🔗", "private": "🔒"}
        diff_map= {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}
        df = pd.DataFrame([{
            "Kod":      t.get("test_id",""),
            "Nomi":     t.get("title","?"),
            "Fan":      t.get("category",""),
            "Qiyinlik": diff_map.get(t.get("difficulty",""),""),
            "Savollar": len(t.get("questions",[])),
            "Urinish":  t.get("solve_count",0),
            "O'rtacha": f"{t.get('avg_score',0):.1f}%",
            "Ko'rinish":vis_map.get(t.get("visibility",""),""),
        } for t in tests])
        st.dataframe(df, use_container_width=True, height=400)
        st.caption(f"Jami: {len(tests)} ta test RAM da")


# ══ USERLAR ═══════════════════════════════════════════════
elif menu == "👥 Userlar":
    from utils.ram_cache import get_users
    st.markdown("## 👥 Foydalanuvchilar")

    users = list(get_users().values())
    if not users:
        st.info("Hali user yo'q.")
    else:
        active  = sum(1 for u in users if u.get("total_tests",0) > 0)
        blocked = sum(1 for u in users if u.get("is_blocked"))
        avg_all = round(sum(u.get("avg_score",0) for u in users) / len(users), 1) if users else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Jami userlar", len(users))
        c2.metric("Faol (test ishlagan)", active)
        c3.metric("Bloklangan", blocked)
        c4.metric("O'rtacha natija", f"{avg_all}%")

        # Top 10 bo'yicha chart
        top = sorted(users, key=lambda x: x.get("avg_score", 0), reverse=True)[:10]
        if top:
            names  = [u.get("name","?")[:18] for u in top]
            scores = [u.get("avg_score",0) for u in top]
            rows   = ""
            for nm, sc in zip(names, scores):
                col = "#10b981" if sc>=70 else "#f59e0b" if sc>=50 else "#f43f5e"
                rows += f"""
                <div style='margin-bottom:6px'>
                  <div style='display:flex;justify-content:space-between;
                              font-size:0.8rem;color:#e2e8f0;margin-bottom:2px'>
                    <span>{nm}</span>
                    <span style='font-family:Space Mono,monospace;color:{col}'>{sc:.1f}%</span>
                  </div>
                  <div style='height:7px;background:#1e293b;border-radius:4px'>
                    <div style='height:7px;width:{sc}%;background:{col};border-radius:4px'></div>
                  </div>
                </div>"""
            import streamlit.components.v1 as _c
            _c.html(f"""<div style='background:transparent;padding:4px 0;font-family:sans-serif'>
              <div style='font-size:0.78rem;color:#64748b;margin-bottom:8px'>Top 10 Foydalanuvchilar</div>
              {rows}</div>""", height=len(top)*46+30)

        st.markdown("#### 👥 Userlar ro'yxati")
        df = pd.DataFrame([{
            "ID":       u.get("telegram_id"),
            "Ism":      u.get("name","?"),
            "Testlar":  u.get("total_tests",0),
            "O'rtacha": f"{u.get('avg_score',0):.1f}%",
            "Holat":    "🚫" if u.get("is_blocked") else "✅",
            "Qo'shildi":str(u.get("created_at",""))[:10],
        } for u in sorted(users, key=lambda x: x.get("total_tests",0), reverse=True)])
        st.dataframe(df, use_container_width=True, height=400)


# ══ BACKUP ════════════════════════════════════════════════
elif menu == "🔄 Backup":
    from config import STORAGE_CHANNEL_ID
    from utils.ram_cache import get_daily, clear_daily, stats
    from utils import tg_db

    st.markdown("## 🔄 Kunlik Backup")

    if not STORAGE_CHANNEL_ID:
        st.error("⚠️ STORAGE_CHANNEL_ID sozlanmagan! secrets.toml tekshiring.")
        st.code('STORAGE_CHANNEL_ID = "-1003776515681"'); st.stop()

    daily = get_daily()
    s     = stats()
    total = s["daily_r"]
    dates = tg_db.get_backup_dates()

    # Status kartalar
    c1, c2, c3 = st.columns(3)
    c1.metric("RAM dagi natijalar",  total,      help="Kanalga yuborilmagan")
    c2.metric("Saqlangan backuplar", len(dates),  help="Telegram kanalda")
    c3.metric("Kanal ID",            str(STORAGE_CHANNEL_ID))

    st.markdown("---")

    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.markdown("#### ⚡ Qo'lda Backup")
        st.markdown(f"""
        <div style='padding:16px;background:#111827;border:1px solid #1e293b;
                    border-radius:10px;margin-bottom:12px'>
            <div style='color:#64748b;font-size:0.8rem'>RAM DA KUTAYOTGAN NATIJALAR</div>
            <div style='font-family:Space Mono,monospace;font-size:2rem;margin-top:4px'>
                {total} <span style='font-size:0.9rem;color:#64748b'>ta</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("💾 Kanalga yuborish", use_container_width=True, type="primary"):
            if not daily:
                st.warning("📭 RAM da natija yo'q.")
            else:
                with st.spinner("Yuklanmoqda..."):
                    import asyncio
                    async def do_flush():
                        return await tg_db.upload_backup(daily, str(date.today()))
                    try:
                        loop = asyncio.new_event_loop()
                        mid  = loop.run_until_complete(do_flush()); loop.close()
                        if mid:
                            clear_daily()
                            st.success(f"✅ Backup yuborildi! msg_id = {mid}")
                            st.balloons()
                        else:
                            st.error("❌ Xato. Bot kanal huquqlarini tekshiring.")
                    except Exception as e:
                        st.error(f"❌ {e}")

    with col_r:
        st.markdown("#### 📅 Backup tarixi")
        if dates:
            for i, d in enumerate(dates[:10]):
                is_today = d == str(date.today())
                st.markdown(f"""
                <div style='display:flex;justify-content:space-between;align-items:center;
                            padding:10px 14px;margin-bottom:4px;background:#111827;
                            border:1px solid {"#6366f1" if is_today else "#1e293b"};
                            border-radius:8px'>
                    <span style='font-family:Space Mono,monospace;font-size:0.85rem'>
                        {"📌 " if is_today else "📄 "}{d}
                    </span>
                    <span style='color:{"#6366f1" if is_today else "#64748b"};font-size:0.75rem'>
                        {"bugun" if is_today else f"#{i+1}"}
                    </span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style='text-align:center;padding:40px;color:#64748b;
                        border:1px dashed #1e293b;border-radius:10px'>
                📭 Hali backup yo'q
            </div>
            """, unsafe_allow_html=True)


# ══ REYTING ═══════════════════════════════════════════════
elif menu == "🏆 Reyting":
    from utils.db import get_leaderboard
    st.markdown("## 🏆 Reyting")

    docs = get_leaderboard(limit=50)
    if not docs:
        st.info("📭 Hali reyting ma'lumoti yo'q.")
    else:
        # Podium — Top 3
        top3 = docs[:3]
        medals = ["🥇","🥈","🥉"]
        cols_p = st.columns(3)
        order = [1, 0, 2]  # 2-chi, 1-chi, 3-chi (podium style)
        heights = ["60px", "90px", "40px"]
        for col, idx in zip(cols_p, order):
            if idx < len(top3):
                u = top3[idx]
                with col:
                    st.markdown(f"""
                    <div style='text-align:center;padding:20px 10px;background:#111827;
                                border:1px solid #1e293b;border-radius:12px;
                                border-top:3px solid {"#f59e0b" if idx==0 else "#94a3b8" if idx==1 else "#cd7c2f"}'>
                        <div style='font-size:2rem'>{medals[idx]}</div>
                        <div style='font-weight:700;margin-top:6px;font-size:0.9rem'>{u.get("name","?")[:18]}</div>
                        <div style='font-family:Space Mono,monospace;font-size:1.3rem;
                                    color:{"#f59e0b" if idx==0 else "#94a3b8" if idx==1 else "#cd7c2f"};
                                    margin-top:4px'>{u.get("avg_score",0):.1f}%</div>
                        <div style='color:#64748b;font-size:0.75rem;margin-top:4px'>{u.get("total_tests",0)} ta test</div>
                    </div>
                    """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Horizontal bar chart
        names  = [u.get("name","?")[:22] for u in docs[:15]]
        scores = [u.get("avg_score",0) for u in docs[:15]]
        rows   = ""
        for i,(nm,sc) in enumerate(zip(names,scores)):
            col = "#10b981" if sc>=70 else "#f59e0b" if sc>=50 else "#f43f5e"
            medal = ["🥇","🥈","🥉"][i] if i<3 else f"{i+1}."
            rows += f"""
            <div style='display:flex;align-items:center;gap:10px;margin-bottom:7px'>
              <span style='width:28px;text-align:right;font-size:0.8rem;
                           color:#64748b;flex-shrink:0'>{medal}</span>
              <div style='flex:1'>
                <div style='display:flex;justify-content:space-between;
                            font-size:0.82rem;color:#e2e8f0;margin-bottom:2px'>
                  <span>{nm}</span>
                  <span style='font-family:Space Mono,monospace;color:{col}'>{sc:.1f}%</span>
                </div>
                <div style='height:8px;background:#1e293b;border-radius:4px'>
                  <div style='height:8px;width:{sc}%;background:{col};border-radius:4px'></div>
                </div>
              </div>
            </div>"""
        st.markdown(f"""
        <div style='padding:8px 0;max-height:500px;overflow-y:auto'>{rows}</div>
        """, unsafe_allow_html=True)

        # To'liq jadval
        with st.expander("📋 To'liq ro'yxat"):
            rows = []
            for i, u in enumerate(docs):
                rows.append({
                    "O'rin":   medals[i] if i<3 else f"{i+1}.",
                    "Ism":     u.get("name","?"),
                    "ID":      u.get("telegram_id",""),
                    "Testlar": u.get("total_tests",0),
                    "O'rtacha":f"{u.get('avg_score',0):.1f}%",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
