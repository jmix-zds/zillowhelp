#!/usr/bin/env python3
"""
add_home.py — Parse saved Redfin HTML files and generate home cards for index.html

Usage:
    python3 add_home.py                          # scan ~/Documents/Househunting/*.html
    python3 add_home.py path/to/redfin.html      # single file
    python3 add_home.py path/to/redfin.html --commute 14

Commute times are read from ~/Documents/Househunting/traveltime.txt automatically.
Output is printed to stdout — review it, then hand to Claude to insert into index.html.
"""

import re
import sys
import os
import argparse
import math
import glob

HOUSEHUNTING_DIR  = os.path.expanduser("~/Documents/Househunting")
TRAVELTIME_FILE   = os.path.join(HOUSEHUNTING_DIR, "traveltime.txt")


# ---------------------------------------------------------------------------
# Address parser
# ---------------------------------------------------------------------------

def parse_address(title):
    """Return (street_addr, city_state_zip) from a Redfin page title."""
    # Strip everything from " - " onward: "4866 Lovers Ln, Ravenna, OH 44266 - 3 Bed..."
    clean = re.sub(r'\s*[-–|]\s.*$', '', title).strip()
    # Match "123 Street, City, OH 12345"
    m = re.match(r'^(.+?),\s+([^,]+,\s*OH\s*\d+)$', clean)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Fallback: first comma split
    parts = clean.split(',', 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else '')


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_price(price):
    if price <= 250000:  return 10
    if price <= 300000:  return 8
    if price <= 350000:  return 5
    if price <= 400000:  return 3
    return 1

def score_drive(minutes):
    if minutes <= 10:  return 10
    if minutes <= 15:  return 7
    if minutes <= 20:  return 5
    if minutes <= 25:  return 3
    return 1

def score_beds(beds):
    if beds >= 4:  return 7
    if beds == 3:  return 4
    if beds == 2:  return 1
    return 0

def score_baths(baths):
    if baths >= 2.5:  return 9
    if baths == 2.0:  return 7
    if baths == 1.5:  return 5
    if baths == 1.0:  return 1
    return 0

def score_sqft(sqft):
    if sqft >= 2000:  return 10
    if sqft >= 1800:  return 9
    if sqft >= 1600:  return 7
    if sqft >= 1500:  return 5
    return 4

def calc_score(price, drive, beds, baths, sqft):
    sp  = score_price(price)
    sd  = score_drive(drive)
    sb  = score_beds(beds)
    sba = score_baths(baths)
    ss  = score_sqft(sqft)
    total = sp*10 + sd*10 + sb*8 + sba*7 + ss*6
    pct   = total / 410 * 100
    return round(pct), sp, sd, sb, sba, ss

def score_grade(pct):
    if pct >= 80: return "score-a", "var(--green)", "Strong Match"
    if pct >= 60: return "score-c", "var(--gold)",  "Fair Match"
    return        "score-d", "var(--red)",   "Below Target"


# ---------------------------------------------------------------------------
# Financial model
# ---------------------------------------------------------------------------

def monthly_pi(loan, annual_rate=0.06, years=30):
    if loan <= 0:
        return 0.0
    r = annual_rate / 12
    n = years * 12
    return loan * r / (1 - (1 + r) ** -n)

def simulate_payoff(loan, annual_rate=0.06, monthly_base=None, annual_bonus=30_000):
    """Simulate payoff applying monthly P&I + $30K December bonus each year.
    Returns (years_to_payoff, total_interest_paid)."""
    if loan <= 0:
        return 0.0, 0
    if monthly_base is None:
        monthly_base = monthly_pi(loan, annual_rate)
    balance       = float(loan)
    total_interest = 0.0
    month         = 0
    while balance > 0 and month < 360:
        month += 1
        interest       = balance * (annual_rate / 12)
        total_interest += interest
        principal      = monthly_base - interest
        balance       -= principal
        if balance <= 0:
            break
        if month % 12 == 0:          # December bonus
            balance -= annual_bonus
            if balance <= 0:
                break
    return round(month / 12, 1), round(total_interest)

def calc_payments(price, tax_annual, hoa_monthly=0):
    # --- Standard: 5% down + $100K recast ---
    down_std     = price * 0.05
    loan_std     = price - down_std - 100_000
    loan_std     = max(loan_std, 0)
    pi_std       = monthly_pi(loan_std)
    ltv_std      = loan_std / price * 100

    # --- Best Case: $25K flat down + $180K recast ---
    down_best    = 25_000
    loan_best    = price - down_best - 180_000
    loan_best    = max(loan_best, 0)
    pi_best      = monthly_pi(loan_best)
    ltv_best     = loan_best / price * 100

    mo_tax       = tax_annual / 12
    insurance    = 100

    total_std    = pi_std  + mo_tax + insurance + hoa_monthly
    total_best   = pi_best + mo_tax + insurance + hoa_monthly

    payoff_std_yrs,  interest_std  = simulate_payoff(loan_std,  monthly_base=pi_std)
    payoff_best_yrs, interest_best = simulate_payoff(loan_best, monthly_base=pi_best)

    return dict(
        down_std=down_std,   down_best=down_best,
        loan_std=loan_std,   pi_std=pi_std,   total_std=total_std,   ltv_std=ltv_std,
        loan_best=loan_best, pi_best=pi_best, total_best=total_best, ltv_best=ltv_best,
        mo_tax=mo_tax,       hoa_monthly=hoa_monthly,
        payoff_std_yrs=payoff_std_yrs,   interest_std=interest_std,
        payoff_best_yrs=payoff_best_yrs, interest_best=interest_best,
    )


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def li(html, key):
    """Extract value from a Redfin entryItem like 'Key: Value'."""
    pattern = rf'class="entryItem[^"]*"[^>]*>[^<]*{re.escape(key)}[^<]*:([^<]+)<'
    m = re.search(pattern, html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(rf'{re.escape(key)}[:\s]+([^<\n]+)', html, re.IGNORECASE)
    return m2.group(1).strip() if m2 else None

def parse_redfin(html):
    data = {}

    # --- Title / Address ---
    m = re.search(r'<title>([^<]+)</title>', html)
    data['title'] = m.group(1).strip() if m else ''
    data['street'], data['city_zip'] = parse_address(data['title'])

    # --- URL ---
    m = re.search(r'<meta property="og:url" content="([^"]+)"', html)
    if not m:
        m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    data['url'] = m.group(1) if m else ''

    # --- Price ---
    m = re.search(r'\$(\d[\d,]+)\s*(?:<[^>]+>)?\s*(?:List Price|listing price)', html, re.IGNORECASE)
    if not m:
        m = re.search(r'"listingPrice"\s*:\s*(\d+)', html)
    if not m:
        m = re.search(r'class="[^"]*price[^"]*"[^>]*>\s*\$?([\d,]+)', html, re.IGNORECASE)
    data['price'] = int(m.group(1).replace(',', '')) if m else 0

    # --- Beds / Baths / Sqft from meta description ---
    m = re.search(r'content="For Sale:\s*(\d+)\s*beds?,\s*([\d.]+)\s*baths?\s*[·•]\s*([\d,]+)\s*sq', html, re.IGNORECASE)
    if m:
        data['beds']  = int(m.group(1))
        data['baths'] = float(m.group(2))
        data['sqft']  = int(m.group(3).replace(',', ''))
    else:
        bm = re.search(r'Bedrooms?[:\s]+(\d+)', html, re.IGNORECASE)
        data['beds']  = int(bm.group(1)) if bm else 0
        bam = re.search(r'Bathrooms?[:\s]+([\d.]+)', html, re.IGNORECASE)
        data['baths'] = float(bam.group(1)) if bam else 0
        sm = re.search(r'Finished Sq\. Ft\.[:\s]+([\d,]+)', html, re.IGNORECASE)
        if not sm:
            sm = re.search(r'(\d[\d,]+)\s*sq(?:\.|uare)?\s*ft', html, re.IGNORECASE)
        data['sqft']  = int(sm.group(1).replace(',', '')) if sm else 0

    # --- Year Built ---
    m = re.search(r'Year Built[:\s]+(\d{4})', html, re.IGNORECASE)
    data['year'] = m.group(1) if m else '—'

    # --- Lot Size ---
    raw = li(html, 'Lot Size')
    data['lot'] = raw if raw else '—'

    # --- Style / Stories ---
    style   = li(html, 'Style')
    stories = li(html, 'Stories')
    if style and stories:
        data['style'] = f"{style} · {stories} stor{'y' if stories=='1' else 'ies'}"
    elif style:
        data['style'] = style
    else:
        data['style'] = '—'

    # --- Roof / HVAC / Garage / Basement / Exterior / Outdoor ---
    data['roof']     = li(html, 'Roof')     or '—'
    heat = li(html, 'Heating')
    cool = li(html, 'Cooling')
    if heat and cool:
        data['hvac'] = f"{heat} / {cool}"
    elif heat:
        data['hvac'] = heat
    else:
        data['hvac'] = '—'
    data['garage']   = li(html, 'Garage')   or '—'
    data['basement'] = li(html, 'Basement') or '—'
    data['exterior'] = li(html, 'Exterior') or '—'
    data['outdoor']  = li(html, 'Outdoor')  or li(html, 'Patio') or '—'

    # --- Annual Tax ---
    m = re.search(r'Annual Tax Amount[:\s]+\$?([\d,]+)', html, re.IGNORECASE)
    if not m:
        m = re.search(r'Annual Tax[:\s]+\$?([\d,]+)', html, re.IGNORECASE)
    if not m:
        # JSON: "taxesDue":2432.8
        m = re.search(r'"taxesDue"[:\s]+([\d,]+(?:\.\d+)?)', html)
    if not m:
        m = re.search(r'Tax[:\s]+\$?([\d,]+)\s*/\s*yr', html, re.IGNORECASE)
    data['tax'] = int(float(m.group(1).replace(',', ''))) if m else 0

    # --- HOA --- (try JSON field first, then structured label)
    m = re.search(r'monthlyHoaDues[\\\"]+\s*:+\s*(\d+)', html, re.IGNORECASE)
    if not m:
        m = re.search(r'"HOA Dues"[^"]*"[^"]*\$(\d[\d,]*)', html, re.IGNORECASE)
    if not m:
        # Tight match: "HOA dues" then within 40 chars a $NNN/mo pattern
        m = re.search(r'HOA dues[^$\n]{0,40}\$(\d[\d,]*)\s*/\s*mo', html, re.IGNORECASE)
    data['hoa'] = int(m.group(1).replace(',', '')) if m else 0

    # --- Days on Market ---
    m = re.search(r'"cumulativeDaysOnMarket\\":(\d+)', html)
    if not m:
        m = re.search(r'cumulativeDaysOnMarket":\s*(\d+)', html)
    data['dom'] = int(m.group(1)) if m else 0

    # --- Price History ---
    ph_entries = re.findall(
        r'(Listed|Price Change|Relisted|Sold|Pending)[^\$]*\$([\d,]+)',
        html, re.IGNORECASE
    )
    data['price_history'] = ph_entries[:6]

    # --- $/sqft ---
    data['price_per_sqft'] = round(data['price'] / data['sqft']) if data['sqft'] else 0

    return data


# ---------------------------------------------------------------------------
# Comps extraction
# ---------------------------------------------------------------------------

def extract_comps(html):
    start = html.find('<div class="comps">')
    if start == -1:
        return [], ''

    section = html[start:start+80000]
    section = re.sub(r'<svg[^>]*>.*?</svg>', '', section, flags=re.DOTALL)
    section = re.sub(r'<img[^>]*>', '', section)
    section = re.sub(r'<ul class="bp-Carousel[^"]*".*?</ul>', '', section, flags=re.DOTALL)
    clean   = re.sub(r'<[^>]+>', ' ', section)
    clean   = re.sub(r'&nbsp;', ' ', clean)
    clean   = re.sub(r'\s+', ' ', clean).strip()

    range_m    = re.search(r'priced between (\$[\d,K]+) (?:to|and) (\$[\d,K]+)', clean, re.IGNORECASE)
    comp_range = f"{range_m.group(1)} – {range_m.group(2)}" if range_m else ''

    comps = []
    parts = re.split(r'(SOLD \w+ \d+, \d+)', clean)
    for i in range(1, len(parts), 2):
        date    = parts[i]
        content = parts[i+1] if i+1 < len(parts) else ''

        price_m = re.search(r'\$([\d,]+)', content)
        beds_m  = re.search(r'(\d+)\s*beds?', content, re.IGNORECASE)
        baths_m = re.search(r'([\d.]+)\s*baths?', content, re.IGNORECASE)
        sqft_m  = re.search(r'([\d,]+)\s*sq\s*ft', content, re.IGNORECASE)
        addr_m  = re.search(r'(\d+\s+\w[^,]+,\s+\w[^,]+,\s+OH\s+\d+)', content)

        price    = int(price_m.group(1).replace(',', '')) if price_m else 0
        beds     = int(beds_m.group(1)) if beds_m else 0
        baths    = float(baths_m.group(1)) if baths_m else 0
        sqft_raw = sqft_m.group(1).replace(',', '') if sqft_m else '0'
        sqft     = int(sqft_raw) if sqft_raw != '0' else 0
        addr     = addr_m.group(1).strip() if addr_m else content[:60].strip()
        ppsf     = round(price / sqft) if sqft else 0

        notes_m = re.search(r'(?:larger|smaller|newer|older|basement)[^\.\n]{0,80}', content, re.IGNORECASE)
        notes   = notes_m.group(0).strip() if notes_m else ''

        comps.append(dict(date=date, price=price, beds=beds, baths=baths,
                          sqft=sqft, ppsf=ppsf, addr=addr, notes=notes))

    return comps, comp_range


# ---------------------------------------------------------------------------
# Commute lookup
# ---------------------------------------------------------------------------

def lookup_commute(address_fragment):
    """Search traveltime.txt for a matching address and return minutes."""
    if not os.path.exists(TRAVELTIME_FILE):
        return None
    fragment = address_fragment.lower().strip()
    with open(TRAVELTIME_FILE) as f:
        for line in f:
            if fragment in line.lower():
                m = re.search(r'(\d+)\s*minutes?', line, re.IGNORECASE)
                if m:
                    return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Drive banner helpers
# ---------------------------------------------------------------------------

def drive_label(minutes):
    if minutes <= 10:  return "Excellent commute", "var(--green)"
    if minutes <= 15:  return "Good commute",      "var(--gold)"
    if minutes <= 20:  return "Moderate commute",  "var(--gold)"
    return                    "Long commute",       "var(--red)"

def drive_score_label(minutes):
    if minutes <= 10:  return "10/10", "drive-hi"
    if minutes <= 15:  return "7/10",  "drive-med"
    if minutes <= 20:  return "5/10",  "drive-med"
    if minutes <= 25:  return "3/10",  "drive-lo"
    return                    "1/10",  "drive-lo"


# ---------------------------------------------------------------------------
# Score bar helpers
# ---------------------------------------------------------------------------

def bar_color(val, max_val):
    pct = val / max_val
    if pct >= 0.8:  return "fill-green"
    if pct >= 0.5:  return "fill-gold"
    return                 "fill-red"

def bar_text_color(val, max_val):
    pct = val / max_val
    if pct >= 0.8:  return "var(--green)"
    if pct >= 0.5:  return "var(--gold)"
    return                 "var(--red)"


# ---------------------------------------------------------------------------
# Monthly payment color
# ---------------------------------------------------------------------------

def payment_color(total):
    if total <= 1400:  return '', ''
    if total <= 1800:  return (' style="border-color:rgba(201,151,58,.4);background:rgba(201,151,58,.1)"',
                                ' style="color:var(--gold2)"')
    return                    (' style="border-color:rgba(192,57,43,.4);background:rgba(192,57,43,.1)"',
                                ' style="color:#e57373"')


# ---------------------------------------------------------------------------
# Price history formatter
# ---------------------------------------------------------------------------

def fmt_price_history(entries):
    if not entries:
        return 'No history available'
    parts = []
    for action, price in entries[:4]:
        parts.append(f"{action.capitalize()} ${int(price.replace(',', '')):,}")
    return ' · '.join(parts)


# ---------------------------------------------------------------------------
# HTML card generator
# ---------------------------------------------------------------------------

def fmt(n):
    return f"{n:,}"

def fmtd(n):
    return f"${n:,}"

def generate_card(data, drive_minutes, rank, home_id):
    d = data
    pct, sp, sd, sb, sba, ss = calc_score(d['price'], drive_minutes, d['beds'], d['baths'], d['sqft'])
    fin = calc_payments(d['price'], d['tax'], d['hoa'])
    comps, comp_range = extract_comps(d['_html'])

    grade_cls, grade_color, grade_word = score_grade(pct)
    dl, dc  = drive_label(drive_minutes)
    ds_label, ds_cls = drive_score_label(drive_minutes)

    ppsf          = d['price_per_sqft']
    baths_display = f"{d['baths']:.1g}" if d['baths'] != int(d['baths']) else str(int(d['baths']))
    street        = d['street']
    city_zip      = d['city_zip']

    hfact_style, val_style = payment_color(fin['total_std'])
    hoa_line  = f" + HOA ${fmt(d['hoa'])}" if d['hoa'] else ''
    no_pmi    = " · No PMI" if fin['ltv_std'] <= 80 else ''

    bar_w = {
        'price': f"{sp/10*100:.0f}%",
        'drive': f"{sd/10*100:.0f}%",
        'beds':  f"{sb/7*100:.0f}%",
        'baths': f"{sba/9*100:.0f}%",
        'sqft':  f"{ss/10*100:.0f}%",
    }

    ph      = fmt_price_history(d['price_history'])
    tax_mo  = round(d['tax'] / 12)
    hoa_display = fmtd(d['hoa']) + '/mo' if d['hoa'] else 'None'

    dom = d['dom']
    if dom == 0 or dom == 1:
        dom_display = "1 — Just listed"
    elif dom < 30:
        dom_display = f"{dom} days"
    elif dom < 60:
        dom_display = f"{dom} days — worth asking why"
    else:
        dom_display = f"{dom} — investigate"

    # Payoff display
    def payoff_str(yrs, interest):
        yrs_label = f"~{yrs:.0f} yr" if yrs == int(yrs) else f"~{yrs} yrs"
        return f"{yrs_label} payoff · ~{fmtd(interest)} interest"

    std_payoff  = payoff_str(fin['payoff_std_yrs'],  fin['interest_std'])
    best_payoff = payoff_str(fin['payoff_best_yrs'], fin['interest_best'])

    comps_html = _comps_html(comps, comp_range, d, ppsf, street)

    card = f"""
    <!-- HOME {rank} · {street.upper()} -->
    <div class="dcard" id="home-{home_id}">
      <div class="dcard-hero">
        <div class="dcard-hero-left">
          <div class="dcard-rank-badge" style="background:var(--ink3)">#{rank} Ranked</div>
          <div class="dcard-addr">{street}</div>
          <div class="dcard-city">{city_zip}</div>
          <a class="dcard-url" href="{d['url']}" target="_blank">View on Redfin ↗</a>
          <div class="dcard-hero-facts">
            <div class="hfact"><div class="hfact-val">{fmtd(d['price'])}</div><div class="hfact-lbl">List Price</div></div>
            <div class="hfact"><div class="hfact-val">{d['beds']} / {baths_display}</div><div class="hfact-lbl">Bed / Bath</div></div>
            <div class="hfact"><div class="hfact-val">{fmt(d['sqft'])}</div><div class="hfact-lbl">Sq Ft</div></div>
            <div class="hfact"><div class="hfact-val">{fmtd(ppsf)}</div><div class="hfact-lbl">Per Sq Ft</div></div>
            <div class="hfact"><div class="hfact-val">{d['lot']}</div><div class="hfact-lbl">Lot Size</div></div>
            <div class="hfact"{hfact_style}><div class="hfact-val"{val_style}>~{fmtd(round(fin['total_std']))}</div><div class="hfact-lbl">Est. /month</div></div>
          </div>
        </div>
        <div class="dcard-big-score">
          <div class="big-circle {grade_cls}">
            <div class="big-circle-num" style="color:{grade_color}">{pct}%</div>
            <div class="big-circle-lbl" style="color:{grade_color}">score</div>
          </div>
          <div class="grade-word" style="color:{grade_color}">{grade_word}</div>
        </div>
      </div>

      <div class="drive-banner">
        <div class="drive-banner-left">
          <div class="drive-icon">🚗</div>
          <div>
            <div class="drive-time" style="color:{dc}">{drive_minutes} min</div>
            <div class="drive-label">to daughter's school &nbsp;·&nbsp; <strong style="color:{dc}">{dl}</strong></div>
            <div class="drive-school">6923 Stow Rd, Hudson OH 44236</div>
          </div>
        </div>
        <div class="drive-score-pill {ds_cls}">Location Score: {ds_label}</div>
      </div>

      <div class="dcard-body">
        <div class="scores-section">
          <h4>Scorecard</h4>
          <div class="score-rows">
            <div class="srow">
              <div class="srow-lbl">Price</div>
              <div class="srow-track"><div class="srow-fill {bar_color(sp,10)}" style="width:{bar_w['price']}"></div></div>
              <div class="srow-val" style="color:{bar_text_color(sp,10)}">{sp}</div>
            </div>
            <div class="srow">
              <div class="srow-lbl">Drive Time</div>
              <div class="srow-track"><div class="srow-fill {bar_color(sd,10)}" style="width:{bar_w['drive']}"></div></div>
              <div class="srow-val" style="color:{bar_text_color(sd,10)}">{sd}</div>
            </div>
            <div class="srow">
              <div class="srow-lbl">Bedrooms</div>
              <div class="srow-track"><div class="srow-fill {bar_color(sb,7)}" style="width:{bar_w['beds']}"></div></div>
              <div class="srow-val" style="color:{bar_text_color(sb,7)}">{sb}</div>
            </div>
            <div class="srow">
              <div class="srow-lbl">Bathrooms</div>
              <div class="srow-track"><div class="srow-fill {bar_color(sba,9)}" style="width:{bar_w['baths']}"></div></div>
              <div class="srow-val" style="color:{bar_text_color(sba,9)}">{sba}</div>
            </div>
            <div class="srow">
              <div class="srow-lbl">Sq Footage</div>
              <div class="srow-track"><div class="srow-fill {bar_color(ss,10)}" style="width:{bar_w['sqft']}"></div></div>
              <div class="srow-val" style="color:{bar_text_color(ss,10)}">{ss}</div>
            </div>
            <div class="srow-divider">Personal Assessment</div>
            <div class="srow">
              <div class="srow-lbl">Condition</div>
              <div class="srow-track"><div class="srow-fill fill-gold" style="width:50%"></div></div>
              <div class="srow-val" style="color:var(--gold)">—</div>
            </div>
            <div class="srow">
              <div class="srow-lbl">Potential</div>
              <div class="srow-track"><div class="srow-fill fill-gold" style="width:50%"></div></div>
              <div class="srow-val" style="color:var(--gold)">—</div>
            </div>
            <div class="srow">
              <div class="srow-lbl">Gut Feel</div>
              <div class="srow-track"><div class="srow-fill fill-gold" style="width:50%"></div></div>
              <div class="srow-val" style="color:var(--gold)">—</div>
            </div>
          </div>
        </div>

        <div class="details-section">
          <h4>Listing Details</h4>
          <div class="detail-grid">
            <div class="ditem"><div class="ditem-lbl">Style</div><div class="ditem-val">{d['style']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Year Built</div><div class="ditem-val">{d['year']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Lot Size</div><div class="ditem-val">{d['lot']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Garage</div><div class="ditem-val">{d['garage']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Basement</div><div class="ditem-val">{d['basement']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Heating / Cooling</div><div class="ditem-val">{d['hvac']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Roof</div><div class="ditem-val">{d['roof']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Exterior</div><div class="ditem-val">{d['exterior']}</div></div>
            <div class="ditem"><div class="ditem-lbl">Outdoor</div><div class="ditem-val">{d['outdoor']}</div></div>
            <div class="ditem"><div class="ditem-lbl">HOA</div><div class="ditem-val">{hoa_display}</div></div>
            <div class="ditem"><div class="ditem-lbl">Annual Tax</div><div class="ditem-val">{fmtd(d['tax'])}/yr ({fmtd(tax_mo)}/mo)</div></div>
            <div class="ditem"><div class="ditem-lbl">Days on Market</div><div class="ditem-val">{dom_display}</div></div>
            <div class="ditem full"><div class="ditem-lbl">Price History</div><div class="ditem-val">{ph}</div></div>
            <div class="ditem full" style="background:var(--gold-light);border:1px solid var(--gold)">
              <div class="ditem-lbl" style="color:var(--gold)">Est. Monthly Payment · Standard</div>
              <div class="ditem-val">~{fmtd(round(fin['total_std']))}/mo &nbsp;·&nbsp; <span style="font-weight:400;font-size:12px">P&amp;I {fmtd(round(fin['pi_std']))} + Tax {fmtd(tax_mo)} + Insurance $100{hoa_line}{no_pmi}</span></div>
              <div style="font-size:11px;color:var(--ink3);margin-top:3px">5% down ({fmtd(round(fin['down_std']))}) · recast with $100K → {fmtd(round(fin['loan_std']))} loan · 6.00% 30yr · LTV {fin['ltv_std']:.0f}% · {std_payoff}</div>
            </div>
            <div class="ditem full" style="background:#e8f5e9;border:1px solid #2d7a5a;border-left:4px solid #2d7a5a">
              <div class="ditem-lbl" style="color:#1a5c40">Best Case · $25K down + $180K recast</div>
              <div class="ditem-val" style="color:#1a5c40">~{fmtd(round(fin['total_best']))}/mo &nbsp;·&nbsp; <span style="font-weight:400;font-size:12px;color:var(--ink3)">P&amp;I {fmtd(round(fin['pi_best']))} + Tax {fmtd(tax_mo)} + Insurance $100{hoa_line}</span></div>
              <div style="font-size:11px;color:var(--ink3);margin-top:3px">{fmtd(round(fin['loan_best']))} loan · LTV {fin['ltv_best']:.0f}% · {best_payoff}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="pros-cons">
        <div>
          <div class="pc-h pro">Pros</div>
          <!-- TODO: add pros -->
          <div class="pc-item pro">TODO</div>
        </div>
        <div>
          <div class="pc-h con">Watch Out For</div>
          <!-- TODO: add cons -->
          <div class="pc-item con">TODO</div>
        </div>
      </div>

      <div class="notes-box">
        <div class="notes-box-h">Key Note</div>
        <p>TODO: add key note</p>
      </div>
{comps_html}
    </div><!-- end home-{home_id} -->
"""
    return card, pct, fin


def _comps_html(comps, comp_range, data, ppsf, street=''):
    if not comps:
        return ''

    baths_display = f"{data['baths']:.1g}" if data['baths'] != int(data['baths']) else str(int(data['baths']))
    subj_addr = street or 'This home'
    rows = [f"""            <tr class="ct-subj">
              <td><strong>{subj_addr}</strong> <span style="font-size:10px;color:var(--gold2)">(this home)</span></td>
              <td>Listed</td><td class="ct-price">{fmtd(data['price'])}</td>
              <td>{data['beds']} / {baths_display}</td>
              <td>{fmt(data['sqft']) if data['sqft'] else '—'}</td>
              <td>{fmtd(ppsf) if ppsf else '—'}</td>
              <td>—</td>
            </tr>"""]

    for c in comps:
        rows.append(f"""            <tr>
              <td>{c['addr']}</td>
              <td>{c['date'].replace('SOLD ','')}</td>
              <td class="ct-price">{fmtd(c['price']) if c['price'] else '—'}</td>
              <td>{c['beds']} / {c['baths']:.1g}</td>
              <td>{fmt(c['sqft']) if c['sqft'] else '—'}</td>
              <td>{fmtd(c['ppsf']) if c['ppsf'] else '—'}</td>
              <td>{c['notes'][:50] if c['notes'] else '—'}</td>
            </tr>""")

    rows_html = '\n'.join(rows)
    n       = len(comps)
    summary = f"Comps range: <strong>{comp_range}</strong>" if comp_range else f"{n} nearby recent sales"

    return f"""
      <div class="comps-section">
        <div class="comps-section-h">Nearby Recently Sold <span>{n} comps · from Redfin listing</span></div>
        <table class="comps-table">
          <thead>
            <tr><th>Address</th><th>Sold Date</th><th>Price</th><th>Beds/Ba</th><th>Sq Ft</th><th>$/sqft</th><th>Notes</th></tr>
          </thead>
          <tbody>
{rows_html}
          </tbody>
        </table>
        <div class="comps-range">{summary} &nbsp;·&nbsp; TODO: add analysis</div>
      </div>
"""


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(data, drive_minutes, fin, pct):
    d = data
    print("\n" + "="*60)
    print(f"  {d['street']}, {d['city_zip']}")
    print("="*60)
    print(f"  URL:           {d['url']}")
    print(f"  Price:         ${d['price']:,}")
    print(f"  Beds/Baths:    {d['beds']} bed / {d['baths']} bath")
    print(f"  Sqft:          {d['sqft']:,}  (${d['price_per_sqft']}/sqft)")
    print(f"  Year Built:    {d['year']}")
    print(f"  Lot:           {d['lot']}")
    print(f"  Style:         {d['style']}")
    print(f"  Garage:        {d['garage']}")
    print(f"  Basement:      {d['basement']}")
    print(f"  HVAC:          {d['hvac']}")
    print(f"  Roof:          {d['roof']}")
    print(f"  Exterior:      {d['exterior']}")
    if d['hoa']:
        print(f"  HOA:           ${d['hoa']}/mo")
    else:
        print(f"  HOA:           None")
    print(f"  Annual Tax:    ${d['tax']:,}/yr  (${round(d['tax']/12)}/mo)")
    print(f"  DOM:           {d['dom']}")
    print(f"  Drive:         {drive_minutes} min")
    print(f"  Score:         {pct}%")
    print(f"  Std /mo:       ~${round(fin['total_std']):,}  ({fin['payoff_std_yrs']}yr payoff, ~${fin['interest_std']:,} interest)")
    print(f"  Best case /mo: ~${round(fin['total_best']):,}  ({fin['payoff_best_yrs']}yr payoff, ~${fin['interest_best']:,} interest)")
    print("="*60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_file(html_file, commute_override=None):
    """Parse one HTML file, return (data, drive_minutes, fin, pct) or None on error."""
    if not os.path.exists(html_file):
        print(f"ERROR: File not found: {html_file}", file=sys.stderr)
        return None

    with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    data       = parse_redfin(html)
    data['_html'] = html
    data['_file'] = html_file

    drive_minutes = commute_override
    if drive_minutes is None:
        # Try street address from parsed title first, then filename
        addr_fragment = data['street'] or os.path.basename(html_file)[:20]
        drive_minutes = lookup_commute(addr_fragment)
        if drive_minutes is None:
            # Fallback: match by filename
            basename      = os.path.basename(html_file)
            addr_m        = re.match(r'(\d+\s+\w[^,]+)', basename)
            addr_fragment = addr_m.group(1) if addr_m else basename[:20]
            drive_minutes = lookup_commute(addr_fragment)
        if drive_minutes is None:
            print(f"WARNING: No commute found for '{data['street']}' in {TRAVELTIME_FILE}", file=sys.stderr)
            print(f"         Add it to traveltime.txt or use --commute MINUTES", file=sys.stderr)
            drive_minutes = 0

    pct, *_ = calc_score(data['price'], drive_minutes, data['beds'], data['baths'], data['sqft'])
    fin      = calc_payments(data['price'], data['tax'], data['hoa'])

    return data, drive_minutes, fin, pct


def main():
    parser = argparse.ArgumentParser(description='Parse Redfin HTML saves and generate home cards.')
    parser.add_argument('html_file', nargs='?', default=None,
                        help='Path to a saved Redfin HTML file (omit to scan ~/Documents/Househunting/)')
    parser.add_argument('--commute', type=int, default=None,
                        help='Drive time in minutes (only used with a single file)')
    args = parser.parse_args()

    # ---- Collect files to process ----
    if args.html_file:
        files = [os.path.expanduser(args.html_file)]
    else:
        pattern = os.path.join(HOUSEHUNTING_DIR, '*.html')
        files   = sorted(glob.glob(pattern))
        if not files:
            print(f"No HTML files found in {HOUSEHUNTING_DIR}", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(files)} HTML file(s) in {HOUSEHUNTING_DIR}")

    # ---- Parse all files ----
    results = []
    for f in files:
        commute = args.commute if args.html_file else None
        result  = process_file(f, commute_override=commute)
        if result:
            results.append(result)

    if not results:
        print("No files parsed successfully.", file=sys.stderr)
        sys.exit(1)

    # ---- Sort by score descending ----
    results.sort(key=lambda r: r[3], reverse=True)

    # ---- Print all summaries ----
    print("\n" + "="*60)
    print(f"  RANKINGS ({len(results)} homes)")
    print("="*60)
    for rank, (data, drive, fin, pct) in enumerate(results, 1):
        print(f"  #{rank}  {pct}%  {data['street']}  (~${round(fin['total_best']):,}/mo best case · {fin['payoff_best_yrs']}yr payoff)")
    print()

    for rank, (data, drive, fin, pct) in enumerate(results, 1):
        print_summary(data, drive, fin, pct)

    # ---- Generate all cards ----
    print("\n" + "="*60)
    print("GENERATED CARD HTML — paste into index.html in order shown")
    print("="*60)

    for home_id, (rank, (data, drive, fin, pct)) in enumerate(
            ((r, result) for r, result in enumerate(results, 1)), 1):
        card, *_ = generate_card(data, drive, rank, home_id)
        print(card)

    print("="*60)
    print("\nTODOs after pasting:")
    print("  1. Fill in pros/cons for each card")
    print("  2. Add key note / summary paragraph for each card")
    print("  3. Add comps analysis sentence for each card")
    print("  4. Update rankings section, compare table, and header buttons")
    print("  5. Add personal scores once evaluated in person")


if __name__ == '__main__':
    main()
