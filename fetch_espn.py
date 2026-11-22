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

def exp(p):
    tot = wsum = 0
    for v, w in ((p["s"], .30), (p["l15"], .25), (p["l30"], .15), (p["l7"], .10), (p["pr"], .20)):
        if v is not None: tot += v * w; wsum += w
    return tot / wsum if wsum else 0

def avail(p): return 0 if p["inj"] in ("O", "IR", "SUS") else (0.6 if p["inj"] == "DTD" else 1)

def sp_date(sp): return ANCHOR_DATE + timedelta(days=sp - ANCHOR_SP)
def key(d): return d.strftime("%m-%d")

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
    pts, by, live = {}, {}, {}
    for e in d.get("schedule", []):
        if e.get("matchupPeriodId") != mu: continue
        for side in ("home", "away"):
            x = e.get(side)
            if not x: continue
            tid = x["teamId"]
            pb = {k: v for k, v in (x.get("pointsByScoringPeriod") or {}).items() if int(k) < sp}
            lv = (x.get("rosterForCurrentScoringPeriod") or {}).get("appliedStatTotal", 0) or 0
            by[tid] = {k: round(v) for k, v in pb.items()}
            live[tid] = round(lv); pts[tid] = round(sum(pb.values()) + lv)
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
            "pts": pts.get(tid, 0), "live": live.get(tid, 0), "by": by.get(tid, {}), "r": r})
    # agentes libres
    flt = {"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "filterSlotIds": {"value": [0,1,2,3,4,5,6,11]},
           "limit": 300, "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
           "filterStatsForTopScoringPeriodIds": {"value": 5, "additionalValue": [f"00{SEASON}", f"10{SEASON}", f"01{SEASON}", f"02{SEASON}", f"03{SEASON}"]}}}
    fa_raw = http(BASE + "?view=kona_player_info", {**ck, "x-fantasy-filter": json.dumps(flt)})
    fas = []
    for en in fa_raw.get("players", []):
        p = pdata(en["player"])
        if p["gp"] < 4: continue
        own = round((en["player"].get("ownership") or {}).get("percentOwned", 0))
        ws = "W" if en.get("status") == "WAIVERS" else "F"
        fas.append((max(v for v in (p["l15"], p["l30"], p["s"]) if v is not None) if any(v is not None for v in (p["l15"], p["l30"], p["s"])) else 0,
                    [p["n"], p["t"], p["inj"], p["pos"], p["s"], p["gp"], p["l7"], p["l15"], p["l30"], p["pr"], p["mn"], ws, own, p["id"]], p))
    fas.sort(key=lambda x: -x[0]); fas = fas[:45]
    # calendario NBA (hora del este)
    sched = {}
    day = now.date()
    while day <= sp_date(n1):
        try:
            sb = http("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=" + day.strftime("%Y%m%d"))
            lst = []
            for ev in sb.get("events", []):
                cs = ev["competitions"][0]["competitors"]
                ab = {c["homeAway"]: ALIAS.get(c["team"]["abbreviation"], c["team"]["abbreviation"]) for c in cs}
                t = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
                lst.append(f"{ab['away']}@{ab['home']} {t:%H:%M}")
            sched[key(day)] = sorted(lst, key=lambda s: s.split()[1])
        except Exception as e:
            print("calendario fallo", day, type(e).__name__)
        day += timedelta(days=1)
    # minas de oro
    mine = next(t for t in teams if t["id"] == ME)
    def g_in(team, days_):
        n = 0
        for k in days_:
            for g in sched.get(k, []):
                a, h = g.split()[0].split("@")
                if team in (a, h): n += 1
        return n
    keys = sorted(sched); soon = keys[:2]
    base = []
    for r in mine["r"]:
        if r[2] == "IR" or r[0] in PROTECTED: continue
        p = dict(n=r[0], t=r[1], inj=r[3], s=r[5], l7=r[7], l15=r[8], l30=r[9], pr=r[10])
        base.append(exp(p) * avail(p))
    base.sort(); worst = base[0] if base else 0
    gold = []
    for _, _, p in fas:
        e = exp(p); v = e * avail(p); g = g_in(p["t"], soon)
        if g == 0 or avail(p) == 0: continue
        gain = v - worst
        if gain >= 4 and e >= 24:
            trend = (p["l15"] or 0) - (p["s"] or 0)
            why = f"{g} juego{'s' if g > 1 else ''} en 2 dias" + (f", subiendo +{trend:.0f}" if trend >= 4 else "")
            gold.append({"n": p["n"], "t": p["t"], "pos": p["pos"], "inj": p["inj"], "e": round(e, 1), "gain": round(gain, 1), "why": why})
    gold.sort(key=lambda x: -x["gain"]); gold = gold[:8]
    out = {"u": now.isoformat(timespec="minutes"), "sp": sp, "mu": mu,
           "muD": f"{sp_date(c0).day}-{sp_date(c1).day} {MESES[sp_date(c1).month - 1]}", "me": ME,
           "cur": cur, "nxt": nxt, "spd": spd, "teams": teams, "fa": [x[1] for x in fas], "sched": sched, "gold": gold}
    with open("data.json", "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    # avisos de minas de oro (solo las nuevas)
    try: state = json.load(open("state.json"))
    except Exception: state = {}
    seen = state.get("gold", {}); nowts = int(time.time())
    seen = {k: v for k, v in seen.items() if nowts - v < 36 * 3600}
    new = [g for g in gold if g["n"] not in seen]
    for g in new[:3]:
        ntfy("Mina de oro: " + g["n"], f"{g['n']} ({g['t']}) rinde ~{g['e']} pts por juego, +{g['gain']} sobre tu mas flojo. {g['why']}.", "high")
        seen[g["n"]] = nowts
    json.dump({"gold": seen}, open("state.json", "w"))
    print(f"ok: {len(teams)} equipos, {len(fas)} agentes libres, {len(gold)} minas de oro, {len(new)} avisos nuevos")

if __name__ == "__main__":
    main()
