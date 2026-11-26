# User interface: LinkUp Explorer

The LinkUp Explorer is a plain-language replay of one genuine simulator run, built for people with no
technical background (students, examiners, festival-goers) as well as researchers. It extends the optional
dashboard (specification section 30).

```powershell
python main.py explorer --nodes 100 --seed 1            # writes results/explorer/linkup_explorer_N100_s1.html
python main.py explorer --nodes 200 --seed 3 --style brutalist
streamlit run dashboard/app.py                          # same explorer, with point-and-click settings
```

The output is **one self-contained HTML file** (about 1-3 MB). It opens by double-click in any modern browser,
works offline, and can be emailed or put on a USB stick for a viva.

## What the viewer sees

| Element | Plain-language purpose |
|---|---|
| Header | One sentence explaining the situation: no mobile signal, phones pass messages within 10 m. |
| Message to follow | Every generated message is listed ("phone 34 -> friend 61, sent 05:08"). The default is message 1 (the first one written) - a neutral choice, not a hand-picked success. |
| Method / Compare two | Four sharing methods with everyday names: *Hand-delivery only* (Direct Delivery), *Copy to everyone* (Epidemic), *Limited copies* (BSW), *Walker-first limited copies* (MWS). "Compare two" shows two maps side by side on exactly the same crowd and message. A one-line summary sits under each map; "How does it decide?" expands the full rule and the research name. |
| Map | Festival areas labelled above each box; filled dots walk (with a short tail showing direction), hollow dots stand. The sender is a square tagged FROM, the friend a diamond tagged TO (turns green with a tick when delivered). Thick rings mark phones carrying a copy, with a number showing how many copies each controls. Arrows animate each hand-over (green arrow = delivery). The selected person shows a dashed 10 m reach circle. Lines join the sender's and friend's groups; a dashed red line marks someone who wandered away. |
| Status under each map | Phones carrying the message now, delivered or not, number of hand-overs so far. |
| Timeline | Festival clock, Play/Pause, +/-1 s, Restart, speeds 1x/5x/15x/60x, a slider, a shaded strip for the 5-minute target and markers for sent / delivered / deleted. Keyboard: Space, Left/Right (Shift = 10 s). |
| "What has happened so far" | A plain-language story generated from the event log, e.g. "Phone 63 met phone 73 and passed a copy. Phone 73 is standing still. That is allowed now because the message is over 60 seconds old." Newest entry first and highlighted. |
| How to read the map | Always-visible legend with the same symbols as the map, plus toggles (all friend groups, mark separated people, other messages' hand-overs, phone numbers). |
| Selected person | Click any dot: walking or standing (with speed), area, friend group, whether they are with their group, who is within reach, which messages they carry. |
| Whole festival, right now | Messages written so far, delivered so far and copies stored per method; the run's final results with the caution "One simulated run only". |
| Glossary | "What do these words mean?" defines phone, walking, friend group, separated, in reach, copy/carrier, copy allowance, delivered, hand-over. |
| Guided tour | Six short steps shown on first visit (and from "How it works"): festival, map, the followed message, choosing methods, the clock, the story. |
| About this replay | Number of phones, seed, reach, copy limit, scenario hash and code version, plus the limitations in one sentence. |

## Integrity of what is shown

* All positions, walking states, separation states, friend groups, messages, hand-overs, deliveries, buffer
  drops and counters come from the simulator's own scenario and event log (`dashboard/explorer_export.py`).
  `tests/test_dashboard.py` checks that the embedded data equal the engine's outputs (positions to 1 cm,
  walking and separation states exactly, every hand-over and delivery, per-second counters, final metrics).
* The browser only replays these records. Movement inside a second is drawn as a straight line between the
  recorded positions, which is exactly how the mobility model moves people.
* The page never shows invented metrics. Results for a single run are labelled as such; conclusions are
  pointed to the experiment results.

## Visual styles (switchable in the header; no glow effects, no gradients)

Screenshots: `docs/ui_styles/` (same moment, same message, compare mode and single view).

| Style | Look | Strengths | Watch-outs |
|---|---|---|---|
| **Minimal** (`style_minimal.png`) | Warm off-white, rounded cards, one dark accent, system sans-serif | Calmest and most comfortable for reading the story; prints well | The least distinctive of the three |
| **Brutalist** (`style_brutalist.png`) | Cream paper, 3 px black borders, hard offset shadows, bold uppercase headings, yellow highlights | Highest contrast; the newest story step is highlighted in yellow, so "what just happened" jumps out; very memorable in a demo | Typewriter body font is slightly slower to read in long passages |
| **Cyberpunk** (`style_cyberpunk.png`) | Near-black, flat neon cyan/magenta/yellow, cut corners, 10 m grid on the map | Striking on projectors in dark rooms; the grid helps judge the 10 m reach | Dark background and monospace text are harder in bright rooms |

**Recommendation:** use **Brutalist** for demonstrations and the viva. It is the most striking and also the
easiest for a first-time viewer to follow, because its high contrast and yellow "latest step" highlight point
to what is happening. Use **Minimal** for printed figures and long reading. Set the default with
`--style brutalist` (viewers can still switch, and their choice is remembered in their browser).

Colour is never the only carrier of meaning: walking vs standing is filled vs hollow, sender vs friend is
square vs diamond with FROM/TO tags, delivery adds a tick, carriers have a thick ring and a number, and every
symbol is explained in the legend.

## Layout and accessibility

* Wide screens: maps on the left, explanation panels on the right. Below 1,080 px the panels move under the
  map; below 900 px the two compared maps stack. Verified at 520 px wide (`narrow_width_brutalist.png`).
* Keyboard support, visible focus rings, ARIA labels on controls, a polite live region for the story.
* The page needs no internet access and no installed fonts (system fonts only).
