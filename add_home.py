#!/usr/bin/env python3
"""
add_home.py — Parse a saved Redfin HTML file and generate a home card for index.html

Usage:
    python3 add_home.py "path/to/redfin_save.html"
    python3 add_home.py "path/to/redfin_save.html" --commute 14

If --commute is omitted, the script reads from ~/Documents/Househunting/traveltime.txt.
Output is printed to stdout so you can review it, then paste into index.html.
"""

import re
import sys
import os
import argparse
import math

TRAVELTIME_FILE = os.path.expanduser("~/Documents/Househunting/traveltime.txt")

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
    if pct >= 70: return "score-b", "var(--blue)",  "Good Match"
    if pct >= 60: return "score-c", "var(--gold)",  "Fair Match"
    return        "score-d", "var(--red)",   "Below Target"

# ---------------------------------------------------------------------------
# Financial model
# ---------------------------------------------------------------------------

def monthly_pi(loan, annual_rate=0.06, years=30):
    r = annual_rate / 12
    n = years * 12
    return loan * r / (1 - (1 + r) ** -n)

def calc_payments(price, tax_annual, hoa_monthly=0):
    down         = price * 0.05
    initial_loan = price - down

    loan_std  = initial_loan - 100_000
    loan_best = initial_loan - 150_000

    pi_std  = monthly_pi(loan_std)
    pi_best = monthly_pi(loan_best)

    mo_tax = tax_annual / 12
    insurance = 100

    total_std  = pi_std  + mo_tax + insurance + hoa_monthly
    total_best = pi_best + mo_tax + insurance + hoa_monthly

    ltv_std  = loan_std  / price * 100
    ltv_best = loan_best / price * 100

    return dict(
        down=down, initial_loan=initial_loan,
        loan_std=loan_std,   pi_std=pi_std,   total_std=total_std,   ltv_std=ltv_std,
        loan_best=loan_best, pi_best=pi_best, total_best=total_best, ltv_best=ltv_best,
        mo_tax=mo_tax, hoa_monthly=hoa_monthly,
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
    # Broader fallback
    m2 = re.search(rf'{re.escape(key)}[:\s]+([^<\n]+)', html, re.IGNORECASE)
    return m2.group(1).strip() if m2 else None

def parse_redfin(html):
    data = {}

    # --- Address & URL ---
    m = re.search(r'<title>([^<]+)</title>', html)
    data['title'] = m.group(1).strip() if m else ''

    m = re.search(r'<meta property="og:url" content="([^"]+)"', html)
    if not m:
        m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    data['url'] = m.group(1) if m else ''

    # --- Parse street address and city/zip from URL ---
    # URL format: .../OH/Streetsboro/572-David-Dr-44241/home/...
    addr_m = re.search(r'/OH/([^/]+)/([^/]+)/home/', data['url'])
    if addr_m:
        city_raw = addr_m.group(1).replace('-', ' ').title()
        slug = addr_m.group(2)  # e.g. "572-David-Dr-44241"
        zip_m = re.search(r'(\d{5})$', slug)
        zip_code = zip_m.group(1) if zip_m else ''
        street_slug = re.sub(r'-\d{5}$', '', slug)  # strip zip
        street = re.sub(r'-', ' ', street_slug).title()
        data['street'] = street
        data['city_line'] = f"{city_raw}, OH {zip_code}"
    else:
        data['street'] = 'TODO: street address'
        data['city_line'] = 'TODO: City, OH zip'

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
        # Fallback: search entryItems
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
    style = li(html, 'Style')
    stories = li(html, 'Stories')
    if style and stories:
        data['style'] = f"{style} · {stories} stor{'y' if stories=='1' else 'ies'}"
    elif style:
        data['style'] = style
    else:
        data['style'] = '—'

    # --- Roof ---
    data['roof'] = li(html, 'Roof') or '—'

    # --- Heating / Cooling ---
    heat = li(html, 'Heating')
    cool = li(html, 'Cooling')
    if heat and cool:
        data['hvac'] = f"{heat} / {cool}"
    elif heat:
        data['hvac'] = heat
    else:
        data['hvac'] = '—'

    # --- Garage ---
    data['garage'] = li(html, 'Garage') or '—'

    # --- Basement ---
    data['basement'] = li(html, 'Basement') or '—'

    # --- Exterior ---
    data['exterior'] = li(html, 'Exterior') or '—'

    # --- Outdoor / Patio ---
    data['outdoor'] = li(html, 'Outdoor') or li(html, 'Patio') or '—'

    # --- Annual Tax ---
    m = re.search(r'Annual Tax Amount[:\s]+\$?([\d,]+)', html, re.IGNORECASE)
    if not m:
        m = re.search(r'Annual Tax[:\s]+\$?([\d,]+)', html, re.IGNORECASE)
    if not m:
        m = re.search(r'Tax[:\s]+\$?([\d,]+)\s*/\s*yr', html, re.IGNORECASE)
    data['tax'] = int(m.group(1).replace(',', '')) if m else 0

    # --- HOA ---
    m = re.search(r'HOA dues[^$]*\$(\d[\d,]*)', html, re.IGNORECASE)
    if not m:
        m = re.search(r'role="button">\$(\d[\d,]*)', html)
    data['hoa'] = int(m.group(1).replace(',', '')) if m else 0

    # --- Days on Market ---
    m = re.search(r'"cumulativeDaysOnMarket\\":(\d+)', html)
    if not m:
        m = re.search(r'cumulativeDaysOnMarket":\s*(\d+)', html)
    data['dom'] = int(m.group(1)) if m else 0

    # --- Price History (simple extraction) ---
    ph_entries = re.findall(
        r'(Listed|Price Change|Relisted|Sold|Pending)[^\$]*\$([\d,]+)',
        html, re.IGNORECASE
    )
    data['price_history'] = ph_entries[:6]  # most recent 6

    # --- $/sqft ---
    if data['sqft']:
        data['price_per_sqft'] = round(data['price'] / data['sqft'])
    else:
        data['price_per_sqft'] = 0

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
    clean = re.sub(r'<[^>]+>', ' ', section)
    clean = re.sub(r'&nbsp;', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    # Redfin's stated range
    range_m = re.search(r'priced between (\$[\d,K]+) (?:to|and) (\$[\d,K]+)', clean, re.IGNORECASE)
    comp_range = f"{range_m.group(1)} – {range_m.group(2)}" if range_m else ''

    comps = []
    parts = re.split(r'(SOLD \w+ \d+, \d+)', clean)
    for i in range(1, len(parts), 2):
        date = parts[i]
        content = parts[i+1] if i+1 < len(parts) else ''

        price_m  = re.search(r'\$([\d,]+)', content)
        beds_m   = re.search(r'(\d+)\s*beds?', content, re.IGNORECASE)
        baths_m  = re.search(r'([\d.]+)\s*baths?', content, re.IGNORECASE)
        sqft_m   = re.search(r'([\d,]+)\s*sq\s*ft', content, re.IGNORECASE)
        addr_m   = re.search(r'(\d+\s+\w[^,]+,\s+\w[^,]+,\s+OH\s+\d+)', content)

        price = int(price_m.group(1).replace(',', '')) if price_m else 0
        beds  = int(beds_m.group(1)) if beds_m else 0
        baths = float(baths_m.group(1)) if baths_m else 0
        sqft_raw = sqft_m.group(1).replace(',', '') if sqft_m else '0'
        sqft  = int(sqft_raw) if sqft_raw != '0' else 0
        addr  = addr_m.group(1).strip() if addr_m else content[:60].strip()

        ppsf = round(price / sqft) if sqft else 0

        # Notes: grab first descriptive fragment after the address
        notes_m = re.search(r'(?:larger|smaller|newer|older|basement)[^\.\n]{0,80}', content, re.IGNORECASE)
        notes = notes_m.group(0).strip() if notes_m else ''

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
    if total <= 1400:  return ""
    if total <= 1800:  return ' style="border-color:rgba(201,151,58,.4);background:rgba(201,151,58,.1)"', ' style="color:var(--gold2)"'
    return                    ' style="border-color:rgba(192,57,43,.4);background:rgba(192,57,43,.1)"',  ' style="color:#e57373"'


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
    """Format number with commas."""
    return f"{n:,}"

def fmtd(n):
    """Format dollar amount."""
    return f"${n:,}"

def generate_pros_cons(d, drive_minutes, fin):
    """Auto-generate pros and cons HTML items from parsed data."""
    pros = []
    cons = []
    price = d['price']
    beds  = d['beds']
    baths = d['baths']
    sqft  = d['sqft']
    year  = int(d['year']) if str(d['year']).isdigit() else 0
    dom   = d['dom']
    hoa   = d['hoa']
    tax   = d['tax']
    lot_raw = str(d.get('lot', '—'))
    garage  = str(d.get('garage', '—'))
    basement = str(d.get('basement', '—')).lower()

    # --- PROS ---
    if price <= 250000:
        pros.append(f"In budget at ${price:,}")
    elif price <= 300000:
        pros.append(f"Reasonably priced at ${price:,} — within target range")

    if drive_minutes <= 10:
        pros.append(f"{drive_minutes} min commute — excellent, exceeds target")
    elif drive_minutes <= 15:
        pros.append(f"{drive_minutes} min commute — well within 15-min target")

    if beds >= 4:
        pros.append(f"{beds} bedrooms — hits the family target")

    if baths >= 2.5:
        pros.append(f"{baths:.1g} baths — great for a family of 4")
    elif baths == 2.0:
        pros.append("2 full baths — meets minimum comfort threshold")

    if sqft >= 1800:
        pros.append(f"Spacious at {sqft:,} sqft — above target")
    elif sqft >= 1600:
        pros.append(f"{sqft:,} sqft — close to 1,800 target")

    if hoa == 0:
        pros.append("No HOA — no monthly association fees")

    if garage and garage not in ('—', 'None', '0'):
        pros.append(f"{garage}-car garage")

    # Lot size
    lot_m = re.search(r'([\d.]+)', lot_raw)
    if lot_m:
        lot_acres = float(lot_m.group(1))
        if lot_acres >= 0.5:
            pros.append(f"Large lot at {lot_acres} acres — good outdoor space")

    if dom <= 7:
        pros.append("Just listed — fresh to market, no stale history")
    elif dom <= 30:
        pros.append(f"Only {dom} days on market — moving quickly")

    if fin['total_best'] < 1200:
        pros.append(f"Best-case payment of ~${round(fin['total_best']):,}/mo — very affordable")

    # --- CONS ---
    if price > 350000:
        cons.append(f"Over budget at ${price:,} — significantly above $300K target")
    elif price > 300000:
        cons.append(f"Over budget at ${price:,} — above $300K target")

    if drive_minutes > 20:
        cons.append(f"{drive_minutes} min commute — well beyond 15-min target")
    elif drive_minutes > 15:
        cons.append(f"{drive_minutes} min commute — exceeds 15-min target")

    if beds < 3:
        cons.append(f"Only {beds} bedrooms — significantly below target of 4")
    elif beds == 3:
        cons.append("3 bedrooms — one short of 4-bed target")

    if baths < 1.5:
        cons.append(f"{baths:.1g} bathroom{'s' if baths != 1 else ''} — significant concern for a family of 4")
    elif baths == 1.5:
        cons.append("1.5 baths — only one full bath for daily use")

    if sqft > 0 and sqft < 1400:
        cons.append(f"Only {sqft:,} sqft — well below 1,800 sqft target")
    elif sqft > 0 and sqft < 1600:
        cons.append(f"{sqft:,} sqft — below 1,800 sqft target")

    if year and year < 1970:
        cons.append(f"{year} build — expect aging mechanicals and systems")
    elif year and year < 1990:
        cons.append(f"{year} build — may need updates to systems/finishes")

    if hoa > 0:
        cons.append(f"HOA ${hoa:,}/mo adds ${hoa*12:,}/yr to cost of ownership")

    if tax > 6000:
        cons.append(f"High annual tax at ${tax:,}/yr (${round(tax/12):,}/mo)")
    elif tax > 4000:
        cons.append(f"Annual tax of ${tax:,}/yr (${round(tax/12):,}/mo) — worth factoring in")

    if dom > 90:
        cons.append(f"{dom} days on market — investigate why it hasn't sold")
    elif dom > 60:
        cons.append(f"{dom} days on market — worth asking why")

    if basement in ('—', 'none', 'sump pump', 'sump pump only'):
        cons.append("No finished basement — limited storm shelter / storage")

    # Format as HTML
    def pro_item(text):
        return f'          <div class="pc-item pro">{text}</div>'
    def con_item(text):
        return f'          <div class="pc-item con">{text}</div>'

    pros_html = '\n'.join(pro_item(p) for p in pros) if pros else pro_item('—')
    cons_html = '\n'.join(con_item(c) for c in cons) if cons else con_item('—')
    return pros_html, cons_html


def generate_card(data, drive_minutes, rank, home_id):
    d = data
    pct, sp, sd, sb, sba, ss = calc_score(d['price'], drive_minutes, d['beds'], d['baths'], d['sqft'])
    fin = calc_payments(d['price'], d['tax'], d['hoa'])
    comps, comp_range = extract_comps(d['_html'])
    pros_html, cons_html = generate_pros_cons(d, drive_minutes, fin)

    grade_cls, grade_color, grade_word = score_grade(pct)
    dl, dc = drive_label(drive_minutes)
    ds_label, ds_cls = drive_score_label(drive_minutes)

    ppsf = d['price_per_sqft']
    baths_display = f"{d['baths']:.1g}" if d['baths'] != int(d['baths']) else str(int(d['baths']))

    # Payment display
    pay_color = payment_color(fin['total_std'])
    if isinstance(pay_color, tuple):
        hfact_style, val_style = pay_color
    else:
        hfact_style, val_style = '', ''

    hoa_line = f" + HOA ${fmt(d['hoa'])}" if d['hoa'] else ''
    no_pmi   = " · No PMI" if fin['ltv_std'] <= 80 else ''

    # Score bar widths (out of max possible per category)
    bar_w = {
        'price':  f"{sp/10*100:.0f}%",
        'drive':  f"{sd/10*100:.0f}%",
        'beds':   f"{sb/7*100:.0f}%",
        'baths':  f"{sba/9*100:.0f}%",
        'sqft':   f"{ss/10*100:.0f}%",
    }

    ph = fmt_price_history(d['price_history'])
    tax_mo = round(d['tax'] / 12)

    # HOA display
    hoa_display = fmtd(d['hoa']) + '/mo' if d['hoa'] else 'None'

    # DOM display
    dom = d['dom']
    if dom == 0 or dom == 1:
        dom_display = "1 — Just listed"
    elif dom < 30:
        dom_display = f"{dom} days"
    elif dom < 60:
        dom_display = f"{dom} days — worth asking why"
    else:
        dom_display = f"{dom} — investigate"

    # Comps table
    comps_html = _comps_html(comps, comp_range, d, ppsf)

    card = f"""
    <!-- HOME {rank} · {d['title'][:40].upper()} -->
    <div class="dcard" id="home-{home_id}">
      <div class="dcard-hero">
        <div class="dcard-hero-left">
          <div class="dcard-rank-badge" style="background:var(--ink3)">#{rank} Ranked</div>
          <div class="dcard-addr">{d['street']}</div>
          <div class="dcard-city">{d['city_line']}</div>
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
              <div style="font-size:11px;color:var(--ink3);margin-top:3px">5% down ({fmtd(round(fin['down']))}) · recast with $100K → {fmtd(round(fin['loan_std']))} loan · 6.00% 30yr · LTV {fin['ltv_std']:.0f}%</div>
            </div>
            <div class="ditem full" style="background:#e8f5e9;border:1px solid #2d7a5a;border-left:4px solid #2d7a5a">
              <div class="ditem-lbl" style="color:#1a5c40">Best Case · $150K recast</div>
              <div class="ditem-val" style="color:#1a5c40">~{fmtd(round(fin['total_best']))}/mo &nbsp;·&nbsp; <span style="font-weight:400;font-size:12px;color:var(--ink3)">P&amp;I {fmtd(round(fin['pi_best']))} + Tax {fmtd(tax_mo)} + Insurance $100{hoa_line}</span></div>
              <div style="font-size:11px;color:var(--ink3);margin-top:3px">{fmtd(round(fin['loan_best']))} loan · LTV {fin['ltv_best']:.0f}%</div>
            </div>
          </div>
        </div>
      </div>

      <div class="pros-cons">
        <div>
          <div class="pc-h pro">Pros</div>
{pros_html}
        </div>
        <div>
          <div class="pc-h con">Watch Out For</div>
{cons_html}
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


def _comps_html(comps, comp_range, data, ppsf):
    if not comps:
        return ''

    rows = []
    # Subject row
    baths_display = f"{data['baths']:.1g}" if data['baths'] != int(data['baths']) else str(int(data['baths']))
    rows.append(f"""            <tr class="ct-subj">
              <td><strong>{data['street']}</strong> <span style="font-size:10px;color:var(--gold2)">(this home)</span></td>
              <td>Listed</td><td class="ct-price">{fmtd(data['price'])}</td>
              <td>{data['beds']} / {baths_display}</td>
              <td>{fmt(data['sqft']) if data['sqft'] else '—'}</td>
              <td>{fmtd(ppsf) if ppsf else '—'}</td>
              <td>—</td>
            </tr>""")

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
    n = len(comps)
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
    print("PARSED DATA SUMMARY")
    print("="*60)
    print(f"  URL:          {d['url']}")
    print(f"  Price:        ${d['price']:,}")
    print(f"  Beds/Baths:   {d['beds']} bed / {d['baths']} bath")
    print(f"  Sqft:         {d['sqft']:,}  (${d['price_per_sqft']}/sqft)")
    print(f"  Year Built:   {d['year']}")
    print(f"  Lot:          {d['lot']}")
    print(f"  Style:        {d['style']}")
    print(f"  Garage:       {d['garage']}")
    print(f"  Basement:     {d['basement']}")
    print(f"  HVAC:         {d['hvac']}")
    print(f"  Roof:         {d['roof']}")
    print(f"  Exterior:     {d['exterior']}")
    print(f"  HOA:          ${d['hoa']}/mo" if d['hoa'] else "  HOA:          None")
    print(f"  Annual Tax:   ${d['tax']:,}/yr  (${round(d['tax']/12)}/mo)")
    print(f"  DOM:          {d['dom']}")
    print(f"  Drive:        {drive_minutes} min")
    print(f"  Score:        {pct}%")
    print(f"  Est/mo (std): ~${round(fin['total_std']):,}")
    print(f"  Est/mo (best):~${round(fin['total_best']):,}")
    print("="*60 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Parse a Redfin HTML save and generate a home card.')
    parser.add_argument('html_file', help='Path to the saved Redfin HTML file')
    parser.add_argument('--commute', type=int, default=None, help='Drive time in minutes to school')
    parser.add_argument('--rank', type=int, default=99, help='Rank number for the card (default: 99)')
    parser.add_argument('--id', type=int, default=99, help='home-N id for the card (default: 99)')
    parser.add_argument('--output', default=None, help='Write card HTML to this file instead of stdout')
    args = parser.parse_args()

    if not os.path.exists(args.html_file):
        print(f"ERROR: File not found: {args.html_file}", file=sys.stderr)
        sys.exit(1)

    with open(args.html_file, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    data = parse_redfin(html)
    data['_html'] = html  # store for comps extraction

    # Commute lookup
    drive_minutes = args.commute
    if drive_minutes is None:
        # Try to match address from filename
        basename = os.path.basename(args.html_file)
        addr_m = re.match(r'(\d+\s+\w[^,]+)', basename)
        addr_fragment = addr_m.group(1) if addr_m else basename[:20]
        drive_minutes = lookup_commute(addr_fragment)
        if drive_minutes is None:
            print(f"WARNING: Could not find commute for '{addr_fragment}' in {TRAVELTIME_FILE}", file=sys.stderr)
            print("         Add it to traveltime.txt or use --commute MINUTES", file=sys.stderr)
            drive_minutes = 0

    pct, *_ = calc_score(data['price'], drive_minutes, data['beds'], data['baths'], data['sqft'])
    fin = calc_payments(data['price'], data['tax'], data['hoa'])

    print_summary(data, drive_minutes, fin, pct)

    card, pct, fin = generate_card(data, drive_minutes, args.rank, args.id)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(card)
        print(f"Card written to: {args.output}")
    else:
        print("\n" + "-"*60)
        print("GENERATED CARD HTML (copy into index.html)")
        print("-"*60)
        print(card)
        print("-"*60)
        print("\nTODOs after pasting:")
        print("  1. Fill in street address and city in dcard-addr / dcard-city")
        print("  2. Replace pros/cons TODO items with real observations")
        print("  3. Replace notes-box TODO with key note")
        print("  4. Replace comps-range TODO with analysis")
        print("  5. Update rankings section, compare table, and header buttons")
        print("  6. Add commute time to traveltime.txt if not already there")


if __name__ == '__main__':
    main()
