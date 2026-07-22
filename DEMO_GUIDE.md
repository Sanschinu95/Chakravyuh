# CHAKRAVYUH — Demo & Video Guide

Everything needed to record a 4-minute demo video and to answer the questions
that follow it.

---

## 0. Pre-flight (do this 10 minutes before recording)

```bash
# 1. Seed the database (only needed once)
.venv\Scripts\python.exe scripts\seed_db.py

# 2. Generate the overnight red team artifact so the Red team tab is instant.
#    Skipping this means the first click there takes ~2 minutes.
.venv\Scripts\python.exe scripts\run_redteam.py

# 3. Start both servers
.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8000 --reload
npm run dev --prefix frontend
```

Then, in the browser, **click through every tab once before recording.** The
Corridor Risk Index reaches three external feeds and takes ~18 seconds the
first time; after that it is 8 ms. You do not want that pause on camera.

**Checklist before you hit record**

- [ ] `http://localhost:5173` loads, top bar shows `4,630 crude imports kbd`
- [ ] Map draws corridors, arcs, refineries
- [ ] Risk tab shows four corridors with scores
- [ ] Red team tab shows an attack (not a spinner)
- [ ] Browser zoom at 100%, window ≥ 1600 px wide
- [ ] Close DevTools, hide bookmarks bar

---

## 1. The one-sentence pitch

> India imports 4.6 million barrels of crude a day and 43% of it passes through
> a single strait. CHAKRAVYUH is an anticipatory resilience system that turns a
> disruption signal into an executable, grade-valid procurement plan in about
> five seconds — and every night it attacks India's own supply chain to find
> the weaknesses nobody has reported yet.

## 2. What makes it different (say this early)

Most teams will build: news feed → risk score → map → "buy from West Africa."
Four things here are structurally different:

| Moat | The claim | Where to show it |
|---|---|---|
| **Solver, not vibes** | A real OR-Tools linear program picks the barrels, respecting crude diet, tanker tonnage, voyage time and berth capacity | Plan tab |
| **Red team self-play** | An LLM agent attacks our own defence pipeline nightly, scored by the solvers | Red team tab |
| **Peacetime portfolio** | Priced insurance against what the red team found | Red team tab, lower half |
| **Self-grading** | We publish our own lead time and Brier score, including when it's bad | Risk tab → Backtest |

---

## 3. The 4-minute script

Timings are generous — practise once and trim.

### Beat 1 — Calm state (0:00–0:35)

**Do:** Land on the map. Let it sit for two seconds. Point at the top bar.

> "This is India's crude supply network as it actually is. 4,630 thousand
> barrels a day arriving from 21 grades across 13 countries into 12 refineries.
> The strategic reserve holds 39 million barrels — 8.4 days of cover.
>
> The orange rings are chokepoints. Forty-three percent of everything you see
> passes through this one — the Strait of Hormuz."

**Do:** Click the **Strait of Hormuz** chip in the left rail to isolate it.

> "One click isolates a lane so you can see exactly what depends on it."

### Beat 2 — Honesty legend (0:35–0:55)

**Do:** Open the **Honesty legend** section in the left rail.

> "Before anything else — this. Every number in this system is colour-coded by
> where it came from. Green is fetched live right now. Amber is static
> reference data. Blue is a real archive replayed on a clock. Purple is our own
> model. Nothing simulated is ever shown as live.
>
> Right now Brent is genuinely live. GDELT is blocked from this network, so
> it's serving the replay archive, and it says so. We'd rather show you a
> downgraded claim than a fake one."

> ⚠️ **This is your credibility moment.** Judges reward explicit test harnesses
> and punish discovered fakery. Do not skip it.

### Beat 3 — The backtest (0:55–1:25)

**Do:** Risk tab → scroll to Backtest.

> "Does the risk index actually lead anything? We replayed the June 2025
> US–Iran standoff. The Corridor Risk Index crossed its alert threshold on
> 11 June. Brent gapped 7.9% on the 13th. That's a 48-hour lead time.
>
> The Brier score is 0.46, which is bad, and we're showing it to you anyway.
> The index measures the *level* of corridor risk, not the hazard of a further
> gap — so after the spike it correctly stays red, and every one of those days
> scores as a false alarm. On the onset window alone the Brier is 0.08. We
> publish both."

### Beat 4 — The shock (1:25–2:10)

**Do:** Scenarios → **Hormuz partial closure**. Let the loading overlay run.

> "Now a live scenario. Hormuz at 50% for 21 days."

**Do:** Point at the overlay as stages tick over.

> "That's the real pipeline — cascade, then the procurement optimiser, then the
> reserve schedule, then the justification. Five seconds."

**Do:** Cascade tab.

> "The cascade is explicit. 553 thousand barrels a day of supply gone. Refinery
> runs cut. Brent up 6.9%. And this line is the whole thesis —"

**Do:** Point at *stranded* chips.

> "— 1,700 thousand barrels a day of crude that is grade-compatible and for
> sale, but cannot physically reach an Indian berth inside the window. Bonny
> Light is 23 days away. Mars Blend is 39. You cannot solve a three-week
> Hormuz closure by buying from Nigeria. That falls out of the model — we
> didn't assert it."

### Beat 5 — The answer (2:10–2:55)

**Do:** Plan tab.

> "So here's what to actually do. The optimiser closes 90% of the gap for
> ₹247 crore above baseline. First replacement cargo berths on day 8.9.
>
> Every line is executable: the right API gravity and sulfur for that specific
> refinery's crude diet, on a vessel class that can berth there, with a real
> voyage time."

**Do:** Point at binding constraints.

> "And this is what a solver gives you that a language model cannot — the
> binding constraint, read off the LP's dual values. Not 'supply is tight.'
> *Suezmax tonnage out of the Arabian Gulf, at a shadow price of $750 a
> barrel.* That tells a procurement officer exactly what to fix."

**Do:** Tender tab.

> "And it doesn't stop at a recommendation. Here's a draft tender — grade spec
> checked against the buyer's diet, laycan computed from the voyage, quantity
> from the solver, real pricing formula. From alert to a document you could
> send, in five seconds."

### Beat 6 — The red team (2:55–3:35)

**Do:** Red team tab.

> "Here's the part no news feed can give you. Every night an agent attacks our
> own supply chain with a $50 million budget, looking for maximum damage per
> dollar. It has the simulator and the optimiser as tools, so it *runs* attacks
> rather than imagining them — the solvers score it, not its own claims.
>
> Last night it found this: Hormuz and the Cape simultaneously. $49 million to
> inflict $101 billion. That combination beat our own brute-force sweep, and
> nobody wrote it in a scenario file."

**Do:** Scroll to portfolio.

> "And then the answer to it. This is a shopping list for *right now*, while
> everything is calm — charter options, storage leases, term diversification.
> ₹218 crore of pre-positioned optionality against ₹20,000 crore of expected
> loss.
>
> Note the ceiling: a total Hormuz closure caps at 27% mitigated. No amount of
> money reopens a closed strait, and we refuse to pretend otherwise."

### Beat 7 — Judge as adversary + close (3:35–4:00)

**Do:** Left rail → **Stress test**. Build something. Run it.

> "And you don't have to trust our scenarios. Build your own disruption — any
> chokepoint, any severity, any duration — and it runs the identical pipeline.
> No special-casing."

**Close:**

> "McKinsey put the stabilisation gap after a major supply shock at 47 days.
> Ours is five seconds to a plan, and a priced shopping list the night before.
> That's the difference between watching a crisis and being ready for one."

---

## 4. Q&A — the hard questions

**"Is the data real?"**
> The network topology, refinery crude diets, voyage times and SPR capacities
> are curated from public sources — UN Comtrade, PPAC, EIA chokepoint data,
> company disclosures. Brent is live via yfinance. OFAC SDN is live. GDELT is
> blocked on this network so it replays a reconstructed June 2025 archive,
> which is labelled `corpus: reconstructed` in the payload. AIS needs a key we
> don't have, so vessel positions are replay and can never show as live.

**"Isn't the LLM just making up the numbers?"**
> The opposite — that's the core design rule. Every number comes from the
> deterministic cascade or an OR-Tools program. The LLM writes the
> justification paragraph and the tender cover note, and drives the red team's
> hypotheses. Even there, the red team's *damage* is measured by the solvers;
> its own claims are ignored. Turn the API key off and the whole system still
> runs, with a deterministic narration labelled as such.

**"92× return on the portfolio seems too good."**
> It's leverage against tail risk, and both assumptions are on screen. Attack
> probabilities are scaled from damage-per-dollar and peak at 12% — that's a
> modelling choice, not a forecast. And mitigation is capped: 45% at best,
> falling with severity, so a total closure caps at 27%. Our first version
> reported 100% neutralisation and a 116× return; we added the physical ceiling
> because that number was not believable.

**"Why is the Brier score bad?"**
> Because we report it honestly. The index measures risk level, not the hazard
> of a further price gap, so it stays red after the spike and those days count
> as false alarms. Onset-window Brier is 0.08. The fix is a separate
> hazard-rate model, which we scoped out rather than fake.

**"What's the scalability story?"**
> Corridors, refineries, suppliers and routes are all config — seven CSVs and a
> generator. Pointing this at another importing country is a dataset swap, not
> a rewrite. The solver, cascade and red team don't know anything about India.

**"What would you do next?"**
> Live AIS with a real key; a hazard-rate model to fix the Brier; options-
> implied volatility instead of the realized-vol proxy; and a second country to
> prove the config-swap claim.

---

## 5. Recording tips

- **Resolution:** 1920×1080, browser at 100% zoom, window ≥ 1600 px wide.
- **Don't narrate the UI** ("now I click here"). Narrate the *decision*.
- **Let the loading overlay play.** It's evidence that real solvers are
  running — don't cut it out.
- **Numbers to say out loud:** 43% through Hormuz · 48-hour lead · 5 seconds to
  a plan · $750/bbl shadow price · 2,047× damage per dollar · ₹218 crore vs
  ₹20,000 crore.
- **Have a fallback clip.** Record the red team tab separately in case the live
  run is slow on the day.
- If the basemap fails (no internet), the data layers still draw on a plain
  background. Mention it's a deliberate fallback rather than apologising.
