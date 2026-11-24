#!/usr/bin/env python3
"""Lee tu liga privada de ESPN Fantasy y escribe data.json (y avisa por ntfy).
Solo usa la libreria estandar de Python. Las cookies vienen de variables de entorno
(secrets de GitHub), nunca del codigo."""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

LEAGUE, SEASON, ME = 378370914, 2027, 1
ET = ZoneInfo("America/New_York")
BASE = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{SEASON}/segments/0/leagues/{LEAGUE}"
ANCHOR_SP, ANCHOR_DATE = 33, date(2026, 11, 21)   # periodo de puntuacion 33 = 21 nov 2026
PROTECTED = {"Shai Gilgeous-Alexander", "Alperen Sengun", "Austin Reaves"}
OWNERS = {1: "Leo", 2: "Hugo", 3: "Arturo", 4: "Diego", 5: "Angel", 6: "Diego"}
TEAMS = {1:"ATL",2:"BOS",3:"NO",4:"CHI",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GS",10:"HOU",11:"IND",12:"LAC",13:"LAL",14:"MIA",15:"MIL",16:"MIN",17:"BKN",18:"NY",19:"ORL",20:"PHI",21:"PHX",22:"POR",23:"SAC",24:"SA",25:"OKC",26:"UTAH",27:"WSH",28:"TOR",29:"MEM",30:"CHA"}
ALIAS = {"UTA":"UTAH","WAS":"WSH","GSW":"GS","NYK":"NY","SAS":"SA","NOP":"NO","PHO":"PHX","BRK":"BKN"}
SLOT = {0:"PG",1:"SG",2:"SF",3:"PF",4:"C",5:"G",6:"F",11:"UTIL",12:"BE",13:"IR"}
INJ = {"DAY_TO_DAY":"DTD","OUT":"O","INJURY_RESERVE":"IR","SUSPENSION":"SUS"}
MESES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]

class AuthError(Exception): pass

def http(url, headers=None, tries=3):
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    h.update(headers or {})
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403): raise AuthError(f"ESPN respondio {e.code}")
            if i == tries - 1: raise
        except Exception:
            if i == tries - 1: raise
        time.sleep(3 * (i + 1))

def team_env():
    """{abreviatura: [puntos a favor por juego, puntos en contra por juego]} desde la tabla de posiciones de ESPN.
    Sirve para un ajuste chico por rival (defensa y ritmo). Si falla, devuelve ({}, motivo) y la app lo ignora."""
    why, names = [], set()
    for url in ("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings",
                "https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings?region=us&lang=en&contentorigin=espn&type=0&level=1"):
        try:
            j = http(url, tries=2)
        except Exception as e:
            why.append(type(e).__name__); continue
        out = {}
        def walk(x):
            if isinstance(x, dict):
                t = x.get("team")
                if isinstance(t, dict) and isinstance(x.get("stats"), list):
                    st = {z.get("name"): z.get("value") for z in x["stats"] if isinstance(z, dict)}
                    names.update(k for k in st if k)
                    gp = st.get("gamesPlayed")
                    pf, pa = st.get("avgPointsFor"), st.get("avgPointsAgainst")
                    if pf is None and gp and st.get("pointsFor") is not None: pf = st["pointsFor"] / gp
                    if pa is None and gp and st.get("pointsAgainst") is not None: pa = st["pointsAgainst"] / gp
                    ab = t.get("abbreviation")
                    if ab and pf and pa: out[ALIAS.get(ab, ab)] = [round(float(pf), 1), round(float(pa), 1)]
                for v in x.values(): walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
        walk(j)
        if len(out) >= 28: return out, "ok"
        why.append(f"{len(out)} equipos")
    if names: why.append("stats: " + ",".join(sorted(names))[:240])
    return {}, " | ".join(why)

def ntfy(title, msg, prio="default"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic: return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=msg.encode("utf-8"),
              headers={"Title": title.encode("ascii", "ignore").decode(), "Priority": prio, "Tags": "basketball"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print("ntfy fallo:", type(e).__name__)

def r1(x): return None if x is None else round(float(x), 1)

def stat_row(player, sid):
    for s in player.get("stats", []):
        if s.get("id") == sid: return s
    return None

def avg(player, sid):
    s = stat_row(player, sid)
    if not s: return None
    v = s.get("appliedAverage")
    return r1(v) if v is not None else None

def pdata(player):
    s0 = stat_row(player, f"00{SEASON}")
    gp = mn = None
    if s0 and s0.get("stats"):
        gp = s0["stats"].get("42"); m = s0["stats"].get("40")
        if gp and m: mn = r1(m / gp)
    eg = player.get("eligibleSlots", [])
    pos = "/".join(SLOT[i] for i in sorted(eg) if i in (0,1,2,3,4)) or "UTIL"
    return dict(n=player["fullName"], t=TEAMS.get(player.get("proTeamId"), "?"),
        inj=INJ.get(player.get("injuryStatus", ""), ""), pos=pos,
        s=avg(player, f"00{SEASON}"), gp=int(gp or 0), l7=avg(player, f"01{SEASON}"),
        l15=avg(player, f"02{SEASON}"), l30=avg(player, f"03{SEASON}"),
        pr=avg(player, f"10{SEASON}"), mn=mn, id=player["id"])

def entry_pts(en, per):
    """puntos fantasy de un jugador en un periodo de puntuacion (None si ESPN no lo trae)"""
    pe = en.get("playerPoolEntry") or {}
    v = pe.get("appliedStatTotal")
    if v is None:
        for st_ in (pe.get("player") or {}).get("stats", []):
            if st_.get("statSourceId") == 0 and st_.get("statSplitTypeId") == 5 and st_.get("scoringPeriodId") == per:
                v = st_.get("appliedTotal"); break
    return None if v is None else round(float(v), 1)

def day_points(roster, per):
    """-> ({id: puntos}, suma de titulares redondeada) de un rosterForCurrentScoringPeriod"""
    out, tot = {}, 0.0
    for en in (roster or {}).get("entries", []):
        pid = en.get("playerId") or (en.get("playerPoolEntry") or {}).get("id")
        v = entry_pts(en, per)
        if pid is None or v is None: continue
        out[str(pid)] = v
        if SLOT.get(en.get("lineupSlotId"), "BE") not in ("BE", "IR"): tot += v
    return out, round(tot)

def exp(p):
    tot = wsum = 0
    for v, w in ((p["s"], .30), (p["l15"], .25), (p["l30"], .15), (p["l7"], .10), (p["pr"], .20)):
        if v is not None: tot += v * w; wsum += w
    return tot / wsum if wsum else 0

def avail(p): return 0 if p["inj"] in ("O", "IR", "SUS") else (0.6 if p["inj"] == "DTD" else 1)

def sp_date(sp): return ANCHOR_DATE + timedelta(days=sp - ANCHOR_SP)
def key(d): return d.strftime("%m-%d")

def league_extra(d, mu):
    """Datos de la liga que usa la pestana Traits: tamano del roster, rival de cada semana y reglas de intercambio.
    Todo es opcional: si ESPN no lo da (o cambia el formato) se omite y la app usa valores por defecto."""
    x = {}
    st = d.get("settings") or {}
    try:
        cnt = (st.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
        rs = sum(int(v) for v in cnt.values() if isinstance(v, (int, float)) and v > 0)
        if 12 <= rs <= 25: x["rs"] = rs
        ir = cnt.get("13")
        if isinstance(ir, (int, float)) and 0 <= ir <= 5: x["ir"] = int(ir)
    except Exception as e: print("rs fallo", type(e).__name__)
    try:
        ts = st.get("tradeSettings") or {}
        tr = {}
        dl = ts.get("deadlineDate")
        if isinstance(dl, (int, float)) and dl > 0: tr["dl"] = datetime.fromtimestamp(dl / 1000, ET).strftime("%Y-%m-%d")
        for k, n in (("revisionHours", "rev"), ("vetoVotesRequired", "veto")):
            if isinstance(ts.get(k), (int, float)): tr[n] = int(ts[k])
        if tr: x["tr"] = tr
    except Exception as e: print("tr fallo", type(e).__name__)
    try:
        ss = st.get("scheduleSettings") or {}
        ps = {}
        if isinstance(ss.get("matchupPeriodCount"), int): ps["n"] = ss["matchupPeriodCount"]
        if isinstance(ss.get("playoffTeamCount"), int): ps["po"] = ss["playoffTeamCount"]
        if ps: x["ps"] = ps
    except Exception as e: print("ps fallo", type(e).__name__)
    try:
        op = {}
        for e in d.get("schedule", []):
            m = e.get("matchupPeriodId")
            if not isinstance(m, int) or m < mu or m > mu + 3: continue
            h = (e.get("home") or {}).get("teamId"); a = (e.get("away") or {}).get("teamId")
            if h is None or a is None: continue
            op.setdefault(str(m), {})[str(h)] = a; op[str(m)][str(a)] = h
        if op: x["op"] = op
    except Exception as e: print("op fallo", type(e).__name__)
    return x

def main():
    s2, swid = os.environ.get("ESPN_S2", ""), os.environ.get("ESPN_SWID", "")
    if not s2 or not swid:
        print("Faltan los secrets ESPN_S2 y ESPN_SWID"); sys.exit(2)
    ck = {"Cookie": f"espn_s2={s2}; SWID={swid}"}
    now = datetime.now(ET)
    try:
        d = http(BASE + "?view=mTeam&view=mRoster&view=mMatchup&view=mSettings", ck)
    except AuthError as e:
        ntfy("Fantasy: cookies caducadas", "El robot no pudo entrar a ESPN. Renueva ESPN_S2 y ESPN_SWID en GitHub.", "high")
        print("AUTH:", e); sys.exit(3)
    sp = d["scoringPeriodId"]; mu = d["status"]["currentMatchupPeriod"]
    mps = d["settings"]["scheduleSettings"].get("matchupPeriods", {})
    def span(m):
        l = mps.get(str(m))
        if l and len(l) >= 5: return min(l), max(l)      # lista real de periodos de puntuacion
        a = 28 + 7 * (m - 5); return a, a + 6           # semana 5 empezo en el periodo 28 (lunes 16 nov); semanas de 7 dias
    c0, c1 = span(mu); n0, n1 = span(mu + 1)
    cur = {"start": key(sp_date(c0)), "end": key(sp_date(c1))}
    nxt = {"start": key(sp_date(n0)), "end": key(sp_date(n1))}
    spd = {str(i): key(sp_date(i)) for i in range(c0, sp + 1)}
    # puntos de la semana
    pts, by, live, rcs = {}, {}, {}, {}
    for e in d.get("schedule", []):
        if e.get("matchupPeriodId") != mu: continue
        for side in ("home", "away"):
            x = e.get(side)
            if not x: continue
            tid = x["teamId"]
            pb = {k: v for k, v in (x.get("pointsByScoringPeriod") or {}).items() if int(k) < sp}
            lv = (x.get("rosterForCurrentScoringPeriod") or {}).get("appliedStatTotal", 0) or 0
            rcs[tid] = x.get("rosterForCurrentScoringPeriod")
            by[tid] = {k: round(v) for k, v in pb.items()}
            live[tid] = round(lv); pts[tid] = round(sum(pb.values()) + lv)
    try: state = json.load(open("state.json"))
    except Exception: state = {}
    pdc = state.get("pd", {})                      # cache de dias ya cerrados: {periodo: {equipo: {id: pts}}}
    pdc = {k: v for k, v in pdc.items() if int(k) >= c0}
    dbg = {"hoy_ok": [], "hoy_mal": {}, "dias_ok": [], "dias_mal": {}}
    # fuerza de los equipos para el ajuste por rival: se renueva cada 6 h; si falla, reintenta cada 30 min y no rompe nada
    tm = state.get("tm") or {}
    if (not tm.get("d") and time.time() - tm.get("try", 0) > 1800) or time.time() - tm.get("t", 0) > 6 * 3600:
        tm["try"] = time.time()
        try: got, why = team_env()
        except Exception as e: got, why = {}, type(e).__name__
        if got: tm["d"], tm["t"] = got, time.time()
        tm["why"] = why
    state["tm"] = tm
    dbg["tm"] = [len(tm.get("d") or {}), tm.get("why")]
    pdt = {tid: {} for tid in live}                # {equipo: {"MM-DD": {id: pts}}}
    today_k = key(sp_date(sp))
    for tid, rc in rcs.items():
        pts_, chk = day_points(rc, sp)
        if pts_ and abs(chk - live.get(tid, 0)) <= 2: pdt[tid][today_k] = pts_; dbg["hoy_ok"].append(tid)
        else: dbg["hoy_mal"][str(tid)] = [len(pts_), chk, live.get(tid)]
    for per in range(c0, sp):
        bad = state.setdefault("pdbad", {})
        if str(per) not in pdc and time.time() - bad.get(str(per), 0) > 1800:   # si falla, reintenta cada 30 min
            try:
                dd = http(BASE + f"?view=mMatchup&scoringPeriodId={per}", ck); got = {}
                for e in dd.get("schedule", []):
                    if e.get("matchupPeriodId") != mu: continue
                    for side in ("home", "away"):
                        x = e.get(side)
                        if not x: continue
                        tid = x["teamId"]; pts_, chk = day_points(x.get("rosterForCurrentScoringPeriod"), per)
                        want = by.get(tid, {}).get(str(per))
                        if pts_ and want is not None and abs(chk - want) <= 2: got[str(tid)] = pts_
                        else: dbg["dias_mal"][f"{per}/{tid}"] = [len(pts_), chk, want]
                if got: pdc[str(per)] = got
                else: bad[str(per)] = int(time.time())
            except Exception as ex:
                dbg["dias_mal"][str(per)] = type(ex).__name__
        for tid_s, v in (pdc.get(str(per)) or {}).items():
            if int(tid_s) in pdt: pdt[int(tid_s)][key(sp_date(per))] = v
        if str(per) in pdc: dbg["dias_ok"].append(per)
    state["pd"] = pdc
    teams = []
    for t in d["teams"]:
        tid = t["id"]; rec = (t.get("record") or {}).get("overall", {})
        acq = ((t.get("transactionCounter") or {}).get("matchupAcquisitionTotals") or {}).get(str(mu), 0)
        r = []
        for en in t["roster"]["entries"]:
            p = pdata(en["playerPoolEntry"]["player"])
            r.append([p["n"], p["t"], SLOT.get(en["lineupSlotId"], "BE"), p["inj"], p["pos"], p["s"], p["gp"], p["l7"], p["l15"], p["l30"], p["pr"], p["mn"], p["id"]])
        teams.append({"id": tid, "name": t.get("name") or (t.get("location", "") + " " + t.get("nickname", "")).strip(),
            "owner": OWNERS.get(tid, ""), "rec": f"{rec.get('wins', 0)}-{rec.get('losses', 0)}", "acq": int(acq),
            "pts": pts.get(tid, 0), "live": live.get(tid, 0), "by": by.get(tid, {}), "pd": pdt.get(tid, {}), "r": r})
    # agentes libres
    flt = {"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "filterSlotIds": {"value": [0,1,2,3,4,5,6,11]},
           "limit": 500, "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
           "filterStatsForTopScoringPeriodIds": {"value": 5, "additionalValue": [f"00{SEASON}", f"10{SEASON}", f"01{SEASON}", f"02{SEASON}", f"03{SEASON}"]}}}
    fa_raw = http(BASE + "?view=kona_player_info", {**ck, "x-fantasy-filter": json.dumps(flt)})
    fas, extra = [], []
    for en in fa_raw.get("players", []):
        p = pdata(en["player"])
        if p["gp"] < 1: continue
        own = round((en["player"].get("ownership") or {}).get("percentOwned", 0))
        ws = "W" if en.get("status") == "WAIVERS" else "F"
        row = [p["n"], p["t"], p["inj"], p["pos"], p["s"], p["gp"], p["l7"], p["l15"], p["l30"], p["pr"], p["mn"], ws, own, p["id"]]
        if p["gp"] < 4: extra.append(row); continue          # muestra muy chica: solo para el buscador
        fas.append((max(v for v in (p["l15"], p["l30"], p["s"]) if v is not None) if any(v is not None for v in (p["l15"], p["l30"], p["s"])) else 0, row, p))
    fas.sort(key=lambda x: -x[0])
    extra += [x[1] for x in fas[45:]]                         # el resto de agentes libres, para "Mi radar"
    fas = fas[:45]
    # calendario NBA (hora del este) + estado de los partidos del dia actual
    sched, gs = {}, {}
    sbc = {}
    def get_sb(day_):
        if day_ not in sbc: sbc[day_] = http("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=" + day_.strftime("%Y%m%d"))
        return sbc[day_]
    def teams_of(ev):
        cs = ev["competitions"][0]["competitors"]
        return {c["homeAway"]: ALIAS.get(c["team"]["abbreviation"], c["team"]["abbreviation"]) for c in cs}
    day = now.date()
    while day <= sp_date(n1):
        try:
            lst = []
            for ev in get_sb(day).get("events", []):
                ab = teams_of(ev)
                t = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
                lst.append(f"{ab['away']}@{ab['home']} {t:%H:%M}")
            sched[key(day)] = sorted(lst, key=lambda s: s.split()[1])
        except Exception as e:
            print("calendario fallo", day, type(e).__name__)
        day += timedelta(days=1)
    try:
        for ev in get_sb(sp_date(sp)).get("events", []):
            ab = teams_of(ev); stt = ev.get("status") or ev["competitions"][0].get("status") or {}
            row = [(stt.get("type") or {}).get("state", "pre"), stt.get("period", 0), stt.get("displayClock", "")]
            gs[ab["away"]] = row; gs[ab["home"]] = row
    except Exception as e:
        print("estado de partidos fallo", type(e).__name__)
    # minas de oro: agente libre + a quien soltar, respetando los espacios por posicion
    mine = next(t for t in teams if t["id"] == ME)
    today = key(now.date()); nowt = now.strftime("%H:%M")
    SL = [("PG",), ("SG",), ("SF",), ("PF",), ("C",), ("PG", "SG"), ("SF", "PF"), None, None, None]
    def game(team, day):
        for g in sched.get(day, []):
            m, tm = g.split(); a_, h_ = m.split("@")
            if team in (a_, h_): return tm
        return None
    def slots_for(pos):
        ps = pos.split("/"); return [i for i, x in enumerate(SL) if x is None or any(q in ps for q in x)]
    def best_day(R, day):
        M = 1 << len(SL); dp = [-1.0] * M; dp[0] = 0.0
        for p in R:
            if p["slot"] == "IR": continue
            tm = game(p["t"], day)
            if tm is None or (day == today and tm <= nowt): continue
            if p.get("from") and day < p["from"]: continue
            v = p["e"] * avail(p)
            if v <= 0: continue
            nd = dp[:]
            for m in range(M):
                if dp[m] < 0: continue
                for sl in p["sl"]:
                    if m >> sl & 1: continue
                    nm = m | (1 << sl); w = dp[m] + v
                    if w > nd[nm]: nd[nm] = w
            dp = nd
        return max(dp)
    def total(R, days_): return sum(best_day(R, d) for d in days_)
    def mk(r):
        p = dict(n=r[0], t=r[1], slot=r[2], inj=r[3], pos=r[4], s=r[5], l7=r[7], l15=r[8], l30=r[9], pr=r[10])
        p["e"] = exp(p); p["sl"] = slots_for(p["pos"]); return p
    wk_days = [d for d in sorted(sched) if today <= d <= cur["end"]]
    nx_days = [d for d in sorted(sched) if nxt["start"] <= d <= nxt["end"]]
    both = wk_days + nx_days; soon = sorted(sched)[:2]
    base = [mk(r) for r in mine["r"]]
    b_wk, b_both = total(base, wk_days), total(base, both)
    top7 = {p["n"] for p in sorted([p for p in base if p["slot"] != "IR"], key=lambda p: -p["e"])[:7]}
    drops = sorted([p for p in base if p["slot"] != "IR" and p["n"] not in PROTECTED and p["n"] not in top7], key=lambda p: p["e"] * avail(p))[:6]
    cand = []
    for _, row, p in fas:
        f = dict(p); f["slot"] = "BE"; f["e"] = exp(f); f["sl"] = slots_for(f["pos"])
        if row[11] == "W": f["from"] = nxt["start"]
        if avail(f) == 0 or not any(game(f["t"], d) for d in soon) or row[11] == "W": continue
        cand.append((f["e"] * avail(f), f))
    cand.sort(key=lambda x: -x[0]); gold = []
    for _, f in cand[:10]:
        best = None
        for dp_ in drops:
            if f["e"] * avail(f) < dp_["e"] * avail(dp_) + 2: continue
            R = [x for x in base if x["n"] != dp_["n"]] + [f]
            gw, gb = total(R, wk_days) - b_wk, total(R, both) - b_both
            if best is None or gb > best[2]: best = (dp_, gw, gb)
        if not best: continue
        dp_, gw, gb = best
        if gb < 12: continue
        fe, de = f["e"] * avail(f), dp_["e"] * avail(dp_)
        largo = fe >= de + 3 and (f["gp"] >= 8)
        gold.append({"n": f["n"], "t": f["t"], "pos": f["pos"], "inj": f["inj"], "e": round(f["e"], 1),
            "drop": dp_["n"], "dropE": round(de, 1), "gw": round(gw), "gain": round(gb),
            "label": "Para mucho tiempo" if largo else "Solo esta semana",
            "why": f"{round(f['e'],1)} pts fantasy/juego vs {round(de,1)}"})
    gold.sort(key=lambda x: -x["gain"]); gold = gold[:6]
    out = {"u": now.isoformat(timespec="minutes"), "sp": sp, "mu": mu,
           "muD": f"{sp_date(c0).day}-{sp_date(c1).day} {MESES[sp_date(c1).month - 1]}", "me": ME,
           "cur": cur, "nxt": nxt, "spd": spd, "teams": teams, "fa": [x[1] for x in fas], "sched": sched, "gold": gold,
           "gs": gs, "gsd": today_k, "fs": extra, "tm": tm.get("d") or {}, "dbg": dbg}
    try: out.update(league_extra(d, mu))
    except Exception as e: print("league_extra fallo", type(e).__name__)
    with open("data.json", "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    # avisos de minas de oro (solo las nuevas)
    seen = state.get("gold", {}); nowts = int(time.time())
    seen = {k: v for k, v in seen.items() if nowts - v < 36 * 3600}
    new = [g for g in gold if g["n"] not in seen]
    for g in new[:3]:
        ntfy("Mina de oro: " + g["n"],
             f"Agrega a {g['n']} ({g['t']}): {g['e']} pts fantasy por juego.\nSuelta a {g['drop']} ({g['dropE']}).\n+{g['gain']} pts esperados en 2 semanas ({g['gw']:+d} esta semana).\n{g['label']}." + (" Hazlo despues del domingo." if g['gw'] < -2 else ""), "high")
        seen[g["n"]] = nowts
    state["gold"] = seen
    json.dump(state, open("state.json", "w"), separators=(",", ":"))
    print(f"ok: {len(teams)} equipos, {len(fas)} agentes libres, {len(gold)} minas de oro, {len(new)} avisos nuevos")

if __name__ == "__main__":
    main()
