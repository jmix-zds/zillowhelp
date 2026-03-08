# Ohio Home Search 2026

A single-page home comparison tool built to help our family evaluate and rank houses during our 2026 Ohio home search. Hosted on GitHub Pages and shareable with family as a read-only reference.

## What It Does

The page scores and ranks candidate homes based on five weighted categories, then presents each home with full listing details, financial projections, pros/cons, and a side-by-side comparison table.

**Live page:** `https://[username].github.io/zillowhelp/`

---

## Scoring System

Each home is scored out of **410 points** across five categories:

| Category | Weight | Scale |
|---|---|---|
| Price | 10 | ≤$250K = 10, $250–300K = 8, $300–350K = 5, $350–400K = 3 |
| Drive Time | 10 | ≤10 min = 10, 11–15 min = 7, 16–20 min = 5, 21–25 min = 3 |
| Bedrooms | 8 | 4+ bed = 7, 3 bed = 4, 2 bed = 1 |
| Bathrooms | 7 | 2.5+ ba = 9, 2 ba = 7, 1.5 ba = 5, 1 ba = 1 |
| Sq Footage | 6 | 2,000+ = 10, 1,800–1,999 = 9, 1,600–1,799 = 7, 1,500–1,599 = 5, <1,500 = 4 |

**Score formula:** `(sum of score × weight) / 410`

Score grades:
- **70%+** — Good Match (blue)
- **60–69%** — Fair Match (gold)
- **<60%** — Below Target (red)

Commute is measured to **6923 Stow Rd, Hudson OH 44236** (daughter's school).

---

## Financial Model

Each home card shows three payment scenarios:

1. **Standard recast** — 5% down, put $100K toward a recast at closing, new 30-year loan at 6.00%
2. **Best case recast** — same but $150K recast
3. **Payoff estimate** — both scenarios simulate applying a $30,000 December bonus payment each year

**Monthly payment formula:**
```
monthly_PI = loan × 0.005 / (1 − 1.005^−360)
total = monthly_PI + (annual_tax / 12) + $100 insurance [+ HOA if applicable]
```

---

## How to Add a New House

1. Go to the Redfin listing for the property
2. Save the page: **File → Save Page As → Webpage, HTML Only** (`.html` only, not the `_files` folder)
3. Save it to `~/Documents/Househunting/`
4. Add the commute time to `~/Documents/Househunting/traveltime.txt` in the format:
   ```
   1234 Example St, City, OH 44XXX - XX minutes
   ```
5. Open a Claude Code session in this repo and say: *"Parse [filename].html and add it to index.html"*

Claude will extract all property data from the Redfin HTML (price, beds, baths, sqft, tax, HOA, basement, heating, roof, price history, etc.), calculate the score, calculate all three payment scenarios, and insert the full card into the page.

> **Why Redfin?** Redfin server-renders all property facts into the saved HTML. Zillow renders via JavaScript so saved pages are mostly empty. Redfin gives us tax, HOA, basement type, heating/cooling, roof, and full price history all in one save.

> **Why not fetch directly?** Both Redfin and Zillow block automated web requests (403 errors). The manual save takes about 30 seconds and gives better data.

---

## Project Structure

```
index.html   — The entire page: CSS, HTML, and data in one file
README.md            — This file
```

All CSS and content lives in `index.html` — no build step, no dependencies beyond Google Fonts. It opens directly in a browser or serves from GitHub Pages as-is.

---

## Homes Reviewed

| Rank | Address | Score | Price | Sqft | $/sqft | Commute |
|---|---|---|---|---|---|---|
| 1 | 4556 Fishcreek Rd, Stow | 77% | $244,500 | 1,666 | $147 | 12 min |
| 2 | 5866 Ogilby Dr, Hudson | 75% | $375,000 | 2,016 | $186 | 9 min |
| 3 | 4866 Lovers Ln, Ravenna | 65% | $249,900 | 1,924 | $130 | 24 min |
| 4 | 1799 Oak Hill Dr, Kent | 62% | $250,000 | 1,568 | $159 | 17 min |
| 5 | 10265 Beaver Trl, Aurora | 60% | $275,900 | 1,506 | $183 | 15 min |
| 6 | 9431 Briar Dr, Streetsboro | 59% | $274,800 | 1,836 | $150 | 12 min |
| 7 | 3846 Charring Cross Dr, Stow | 58% | $219,900 | 1,591 | $138 | 14 min |
| 8 | 1620 Sapphire Dr, Hudson | 53% | $330,000 | 1,514 | $218 | 11 min |

*Target: ≤$300K · 4 bedrooms · 1,800+ sqft · ≤15 min to school*
