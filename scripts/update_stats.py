#!/usr/bin/env python3
"""Writes assets/github-stats.svg from live GitHub data. Standard library only."""
import datetime as dt, json, os, re, sys, urllib.request
from pathlib import Path

USER = os.environ.get("STATS_USER", "manascse99")
URL = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
TOKEN = os.environ.get("GH_TOKEN", "")
ROOT = Path(__file__).resolve().parent.parent
NAVY, BLUE, RED, WHITE, MUTED, PANEL, LINE = "#070b16", "#247bff", "#ff354f", "#f4f6fb", "#a9b4c9", "#0d1526", "#1c2a44"
STEPS = [1, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(URL, body, {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json", "User-Agent": "profile-stats"})
    with urllib.request.urlopen(req, timeout=40) as r:
        out = json.load(r)
    if out.get("errors"):
        msg = json.dumps(out["errors"])[:800]
        if not out.get("data") or not out["data"].get("user"):
            raise RuntimeError(msg)
        print("Partial GitHub response, continuing:", msg, file=sys.stderr)
    return out["data"]


def today():
    mins = int(os.environ.get("STATS_TZ_MINUTES", "330"))
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=mins)).date()


def fetch():
    q = """query($u:String!){user(login:$u){pullRequests(first:1){totalCount} merged:pullRequests(first:1,states:MERGED){totalCount}
      contributionsCollection{contributionYears}}}"""
    u = gql(q, {"u": USER})["user"]
    years = u["contributionsCollection"]["contributionYears"]
    parts = " ".join(f'y{y}:contributionsCollection(from:"{y}-01-01T00:00:00Z",to:"{y}-12-31T23:59:59Z"){{totalCommitContributions contributionCalendar{{totalContributions weeks{{contributionDays{{date contributionCount}}}}}}}}' for y in years)
    yd = gql(f"query($u:String!){{user(login:$u){{{parts}}}}}", {"u": USER})["user"] if years else {}
    days = {}
    for v in yd.values():
        if not v:
            continue
        for w in v["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = max(days.get(d["date"], 0), d["contributionCount"])
    stars, repos, after, langs = 0, 0, None, {}
    q = """query($u:String!,$a:String){user(login:$u){repositories(first:100,after:$a,ownerAffiliations:OWNER,privacy:PUBLIC){
      totalCount pageInfo{hasNextPage endCursor} nodes{stargazerCount isFork languages(first:8,orderBy:{field:SIZE,direction:DESC}){edges{size node{name}}}}}}}"""
    while True:
        r = gql(q, {"u": USER, "a": after})["user"]["repositories"]
        repos = r["totalCount"]
        for n in filter(None, r["nodes"]):
            stars += n["stargazerCount"]
            if not n["isFork"]:
                for e in n["languages"]["edges"]:
                    langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
        if not r["pageInfo"]["hasNextPage"]:
            break
        after = r["pageInfo"]["endCursor"]
    months = month_keys(today())
    raised, merged, after = dict.fromkeys(months, 0), dict.fromkeys(months, 0), None
    cutoff = months[0] + "-01"
    q = """query($u:String!,$a:String){user(login:$u){pullRequests(first:100,after:$a,orderBy:{field:CREATED_AT,direction:DESC}){
      pageInfo{hasNextPage endCursor} nodes{createdAt mergedAt}}}}"""
    done = False
    while not done:
        r = gql(q, {"u": USER, "a": after})["user"]["pullRequests"]
        for n in filter(None, r["nodes"]):
            if n["createdAt"][:10] < cutoff:
                done = True
                break
            raised[n["createdAt"][:7]] = raised.get(n["createdAt"][:7], 0) + 1
            if n["mergedAt"] and n["mergedAt"][:7] in merged:
                merged[n["mergedAt"][:7]] += 1
        if not r["pageInfo"]["hasNextPage"]:
            break
        after = r["pageInfo"]["endCursor"]
    return {
        "contributions": sum(v["contributionCalendar"]["totalContributions"] for v in yd.values() if v),
        "prs": u["pullRequests"]["totalCount"],
        "merged": u["merged"]["totalCount"],
        "commits": sum(v["totalCommitContributions"] for v in yd.values() if v),
        "repos": repos,
        "stars": stars,
        "days": days,
        "raised_m": raised,
        "merged_m": merged,
        "langs": langs,
    }


def month_keys(t):
    out = []
    y, m = t.year, t.month
    for _ in range(12):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def streaks(days, t):
    """Returns current, longest (len,start,end), best day (count,date), active day count."""
    known = {dt.date.fromisoformat(k): v for k, v in days.items()}
    known = {k: v for k, v in known.items() if k <= t}
    if not known:
        return 0, (0, None, None), (0, None), 0
    cur = t if known.get(t, 0) > 0 else t - dt.timedelta(days=1)
    current = 0
    while known.get(cur, 0) > 0:
        current += 1
        cur -= dt.timedelta(days=1)
    best, run, start = (0, None, None), 0, None
    d, end = min(known), t
    while d <= end:
        if known.get(d, 0) > 0:
            if run == 0:
                start = d
            run += 1
            if run >= best[0]:
                best = (run, start, d)
        else:
            run = 0
        d += dt.timedelta(days=1)
    bd = max(known, key=lambda k: (known[k], k))
    return current, best, (known[bd], bd), sum(1 for v in known.values() if v > 0)


def tier(v):
    got = [s for s in STEPS if v >= s]
    return got[-1] if got else None


def shell(p, H, title, desc, head, accent, note, body, extra_css=""):
    W = 1000
    hero = (ROOT / "assets/hero.svg").read_text(encoding="utf8")
    faces = "".join(f for f in re.findall(r"@font-face\{.*?\}", hero) if "MS Display" in f or "MS Mono" in f)
    css = f"@keyframes {p}-in{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}.{p}-in{{animation:{p}-in .6s ease-out both}}.d{{font-family:'MS Display','Arial Narrow',Arial,sans-serif;font-weight:700}}.m{{font-family:'MS Mono','Courier New',monospace}}" + extra_css
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="{p}-t {p}-d"><title id="{p}-t">{title}</title><desc id="{p}-d">{desc}</desc><style>{faces}{css}</style><defs><linearGradient id="{p}-edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE}"/><stop offset=".55" stop-color="{LINE}"/><stop offset="1" stop-color="{RED}"/></linearGradient><pattern id="{p}-dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="#7f95c4" opacity=".16"/></pattern><linearGradient id="{p}-bar" x1="0" x2="1"><stop offset="0" stop-color="{BLUE}"/><stop offset=".68" stop-color="{BLUE}"/><stop offset=".68" stop-color="{RED}"/><stop offset="1" stop-color="{RED}"/></linearGradient><clipPath id="{p}-frame"><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="26"/></clipPath></defs><g clip-path="url(#{p}-frame)"><rect width="{W}" height="{H}" fill="{NAVY}"/><rect width="{W}" height="{H}" fill="url(#{p}-dots)"/><rect width="{W}" height="6" fill="url(#{p}-bar)"/></g><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="26" fill="none" stroke="url(#{p}-edge)" stroke-width="1.5"/><text x="44" y="100" class="d" font-size="72" fill="{WHITE}">{head} <tspan fill="{BLUE}">{accent}</tspan></text><text x="956" y="98" text-anchor="end" class="m" font-size="18" fill="{MUTED}">{note}</text>{body}<style>@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}</style></svg>'''


def render(d, stamp):
    f = lambda k: f"{d[k]:,}" if d else "—"
    cards = [("contributions", "TOTAL CONTRIBUTIONS", BLUE), ("prs", "PRS RAISED", RED), ("merged", "PRS MERGED", BLUE), ("commits", "COMMITS", RED), ("repos", "PUBLIC REPOS", BLUE), ("stars", "STARS EARNED", RED)]
    W, H = 1000, 530
    g = ""
    for i, (k, lab, c) in enumerate(cards):
        x, y = 44 + (i % 3) * 310, 136 + (i // 3) * 146
        g += f'<g class="g-in" style="animation-delay:{.15 + .1 * i:.2f}s"><rect x="{x}" y="{y}" width="292" height="130" rx="18" fill="{PANEL}" stroke="{LINE}" stroke-width="1.5"/><rect x="{x + 22}" y="{y + 20}" width="40" height="5" rx="2.5" fill="{c}"/><text x="{x + 22}" y="{y + 84}" class="d" font-size="60" fill="{c}">{f(k)}</text><text x="{x + 22}" y="{y + 113}" class="m" font-size="18" fill="{WHITE}">{lab}</text></g>'
    badges = [(tier(d[k]), n, c) for k, n, c in [("contributions", "CONTRIBUTIONS", BLUE), ("prs", "PRS RAISED", RED), ("merged", "PRS MERGED", BLUE), ("commits", "COMMITS", RED)] if tier(d[k])] if d else []
    x = 44
    for i, (t, n, c) in enumerate(badges):
        label = f"{t:,}+ {n}"
        w = 58 + len(label) * 9
        g += f'<g class="g-in" style="animation-delay:{.8 + .1 * i:.2f}s"><rect x="{x}" y="442" width="{w}" height="50" rx="25" fill="{c}" fill-opacity=".14" stroke="{c}" stroke-width="1.5"/><path transform="translate({x + 24} 467)" d="M0-10 3-3 10.5-2.5 4.700 2.200 6.600 9.500 0 5.500-6.600 9.500-4.700 2.200-10.500-2.500-3-3Z" fill="{c}"/><text x="{x + 44}" y="472" class="m" font-size="15" fill="{WHITE}">{label}</text></g>'
        x += w + 10
    if not badges:
        g += f'<text x="44" y="474" class="m" font-size="18" fill="{MUTED}">{"BADGES UNLOCK WITH YOUR FIRST CONTRIBUTIONS" if d else "BADGES APPEAR AFTER THE FIRST SYNC"}</text>'
    note = f"UPDATED {stamp.upper()}" if d else "WAITING FOR FIRST SYNC"
    desc = "; ".join(f"{l}: {f(k)}" for k, l, _ in cards) + f". {note}."
    return shell("g", 530, f"GitHub stats for {USER}", desc, "GITHUB", "STATS", note, g)


HEAT = ["#141d31", "#123a7a", "#1a5bc0", "#247bff", "#9cc4ff"]


def fmt(x):
    return x.strftime("%d %b %y").upper()


def render_activity(d, stamp, t):
    note = f"UPDATED {stamp.upper()}" if d else "WAITING FOR FIRST SYNC"
    days = {dt.date.fromisoformat(k): v for k, v in (d["days"] if d else {}).items()}
    start = t - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)
    pos = sorted(v for k, v in days.items() if v > 0 and start <= k <= t)
    q = [pos[int(len(pos) * x)] for x in (.25, .5, .75)] if pos else [1, 2, 3]
    lvl = lambda v: 0 if v <= 0 else 1 + sum(v > c for c in q)
    x0, y0, step, size = 45, 192, 17, 14
    cols, labels, last = {}, "", -9
    cur = start
    while cur <= t:
        w = (cur - start).days // 7
        y = y0 + ((cur.weekday() + 1) % 7) * step
        cols.setdefault(w, []).append(f'<rect x="{x0 + w * step}" y="{y}" width="{size}" height="{size}" rx="3" fill="{HEAT[lvl(days.get(cur, 0))]}"/>')
        if cur.day <= 7 and cur.weekday() == 6 and w - last >= 3:
            labels += f'<text x="{x0 + w * step}" y="178" class="m" font-size="15" fill="{MUTED}">{cur.strftime("%b").upper()}</text>'
            last = w
        cur += dt.timedelta(days=1)
    grid = "".join(f'<g class="a-in" style="animation-delay:{.1 + w * .012:.3f}s">{"".join(c)}</g>' for w, c in sorted(cols.items()))
    yr = sum(v for k, v in days.items() if start <= k <= t)
    sub = f"{yr:,} CONTRIBUTIONS IN THE LAST YEAR" if d else "YOUR REAL GRAPH APPEARS AFTER THE FIRST SYNC"
    leg = f'<text x="44" y="134" class="m" font-size="18" fill="{WHITE}">{sub}</text><text x="809" y="349" text-anchor="end" class="m" font-size="15" fill="{MUTED}">LESS</text>'
    for i, c in enumerate(HEAT):
        leg += f'<rect x="{819 + i * 19}" y="336" width="15" height="15" rx="3" fill="{c}"/>'
    leg += f'<text x="956" y="349" text-anchor="end" class="m" font-size="15" fill="{MUTED}">MORE</text>'
    if d:
        cur_s, long_s, best, active = streaks(d["days"], t)
        unit = lambda n: f"{n:,} DAY" + ("" if n == 1 else "S")
        rng = f"{fmt(long_s[1])} – {fmt(long_s[2])}" if long_s[1] else "NO STREAK YET"
        cs = [(unit(cur_s), "CURRENT STREAK", "KEEP IT GOING" if cur_s else "START TODAY", BLUE), (unit(long_s[0]), "LONGEST STREAK", rng, RED), (f"{best[0]:,}", "BEST DAY", fmt(best[1]) if best[1] else "-", BLUE), (f"{active:,}", "ACTIVE DAYS", "ALL TIME", RED)]
    else:
        cur_s, long_s = 0, (0, None, None)
        cs = [("—", "CURRENT STREAK", "AFTER SYNC", BLUE), ("—", "LONGEST STREAK", "AFTER SYNC", RED), ("—", "BEST DAY", "AFTER SYNC", BLUE), ("—", "ACTIVE DAYS", "AFTER SYNC", RED)]
    body = labels + grid + leg
    for i, (v, l, sm, c) in enumerate(cs):
        x = 44 + i * 231
        body += f'<g class="a-in" style="animation-delay:{.8 + .1 * i:.2f}s"><rect x="{x}" y="366" width="219" height="138" rx="18" fill="{PANEL}" stroke="{LINE}" stroke-width="1.5"/><rect x="{x + 20}" y="384" width="40" height="5" rx="2.5" fill="{c}"/><text x="{x + 20}" y="438" class="d" font-size="48" fill="{WHITE}">{v}</text><text x="{x + 20}" y="466" class="m" font-size="17" fill="{WHITE}">{l}</text><text x="{x + 20}" y="489" class="m" font-size="14" fill="{MUTED}">{sm}</text></g>'
    desc = f"{sub}. Current streak {cur_s} days. Longest streak {long_s[0]} days. {note}."
    return shell("a", 536, f"Contribution graph for {USER}", desc, "CONTRIBUTION", "GRAPH", note, body)


LANG = ["#247bff", "#ff354f", "#0ea58a", "#bd8400", "#9468f0"]
OTHER = "#6b7890"


def bar(x, y, w, h, fill):
    r = min(4, h, w / 2)
    b = y + h
    return f'<path class="p-b" d="M{x} {b}V{y + r:.1f}Q{x} {y:.1f} {x + r} {y:.1f}H{x + w - r}Q{x + w} {y:.1f} {x + w} {y + r:.1f}V{b}Z" fill="{fill}"'


def render_prs(d, stamp, t):
    from xml.sax.saxutils import escape
    note = f"UPDATED {stamp.upper()}" if d else "WAITING FOR FIRST SYNC"
    months = month_keys(t)
    ra = [d["raised_m"].get(m, 0) for m in months] if d else [0] * 12
    me = [d["merged_m"].get(m, 0) for m in months] if d else [0] * 12
    top = max(ra + me + [0])
    nice = next((n for n in (4, 8, 12, 20, 40, 80, 120, 200, 400, 800, 1200, 2000, 4000) if n >= top), top or 4)
    bx, by, ph = 84, 416, 230
    body = f'<rect x="44" y="124" width="16" height="16" rx="4" fill="{BLUE}"/><text x="68" y="138" class="m" font-size="17" fill="{WHITE}">RAISED</text><rect x="156" y="124" width="16" height="16" rx="4" fill="{RED}"/><text x="180" y="138" class="m" font-size="17" fill="{WHITE}">MERGED</text><text x="956" y="138" text-anchor="end" class="m" font-size="17" fill="{MUTED}">LAST 12 MONTHS</text>'
    for i in range(5):
        v, y = nice * i // 4, by - ph * i / 4
        body += f'<line x1="{bx}" y1="{y}" x2="956" y2="{y}" stroke="{LINE}" stroke-width="{1.5 if i == 0 else 1}"/><text x="74" y="{y + 5}" text-anchor="end" class="m" font-size="14" fill="{MUTED}">{v}</text>'
    gw = (956 - bx) / 12
    peak_r, peak_m = (ra.index(max(ra)) if any(ra) else -1), (me.index(max(me)) if any(me) else -1)
    delay = 0
    for i, m in enumerate(months):
        x = bx + gw * i + (gw - 54) / 2
        for k, (v, c, px) in enumerate(((ra[i], BLUE, x), (me[i], RED, x + 28))):
            if v:
                h = max(3, ph * v / nice)
                body += bar(round(px, 1), round(by - h, 1), 26, round(h, 1), c) + f' style="animation-delay:{.2 + i * .05 + k * .03:.2f}s"/>'
                if (k == 0 and i == peak_r) or (k == 1 and i == peak_m):
                    body += f'<text class="p-in" style="animation-delay:1.1s" x="{px + 13:.1f}" y="{by - h - 8:.1f}" text-anchor="middle" font-family="MS Mono,monospace" font-size="15" fill="{WHITE}">{v}</text>'
        body += f'<text x="{bx + gw * (i + .5):.1f}" y="{by + 24}" text-anchor="middle" class="m" font-size="14" fill="{MUTED}">{dt.date(int(m[:4]), int(m[5:]), 1).strftime("%b").upper()}</text>'
    if not any(ra + me):
        msg = "NO PULL REQUESTS IN THE LAST 12 MONTHS" if d else "YOUR PR GRAPH APPEARS AFTER THE FIRST SYNC"
        body += f'<text x="{(bx + 956) / 2}" y="{by - ph / 2 + 6}" text-anchor="middle" class="m" font-size="20" fill="{MUTED}">{msg}</text>'
    body += f'<text x="44" y="488" class="m" font-size="18" fill="{WHITE}">TOP LANGUAGES</text>'
    langs = sorted((d["langs"] if d else {}).items(), key=lambda kv: -kv[1])
    total = sum(v for _, v in langs)
    if total:
        rows = [(n, v, LANG[i]) for i, (n, v) in enumerate(langs[:5])]
        rest = sum(v for _, v in langs[5:])
        if rest:
            rows.append(("Other", rest, OTHER))
        x, usable = 44.0, 912 - 2 * (len(rows) - 1)
        for n, v, c in rows:
            w = max(3, usable * v / total)
            body += f'<rect class="p-in" style="animation-delay:1s" x="{x:.1f}" y="504" width="{w:.1f}" height="18" fill="{c}"/>'
            x += w + 2
        for i, (n, v, c) in enumerate(rows):
            lx, ly = 44 + (i % 3) * 306, 558 + (i // 3) * 32
            body += f'<g class="p-in" style="animation-delay:1.2s"><rect x="{lx}" y="{ly - 14}" width="16" height="16" rx="4" fill="{c}"/><text x="{lx + 26}" y="{ly}" class="m" font-size="18" fill="{WHITE}">{escape(n[:18])} {v * 100 / total:.1f}%</text></g>'
    else:
        body += f'<text x="44" y="536" class="m" font-size="18" fill="{MUTED}">{"NO LANGUAGE DATA YET" if d else "LANGUAGES APPEAR AFTER THE FIRST SYNC"}</text>'
    css = "@keyframes p-b{from{transform:scaleY(0)}to{transform:none}}.p-b{transform-box:fill-box;transform-origin:50% 100%;animation:p-b .7s cubic-bezier(.16,1,.3,1) both}"
    summary = ", ".join(f"{m}: {r} raised, {q} merged" for m, r, q in zip(months, ra, me))
    return shell("p", 630, f"Pull request graph for {USER}", f"{summary}. {note}.", "PULL", "REQUESTS", note, body, css)


def main():
    data = fetch() if TOKEN else None
    t = today()
    stamp = t.strftime("%d %b %Y")
    outs = {"github-stats": render(data, stamp), "github-activity": render_activity(data, stamp, t), "github-prs": render_prs(data, stamp, t)}
    for name, svg in outs.items():
        (ROOT / f"assets/{name}.svg").write_text(svg, encoding="utf8")
    print({k: v for k, v in data.items() if k not in ("days",)} if data else "No GH_TOKEN: wrote the waiting-for-first-sync cards")


if __name__ == "__main__":
    sys.exit(main())
