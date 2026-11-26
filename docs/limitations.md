# Limitations

* **Synthetic venue and mobility.** The layout, zone probabilities, dwell times, group structure and separation
  process are modelling assumptions, not measurements of a real festival. They were not tuned to any result.
* **Participating smartphones only.** Node counts are relative densities of devices running the app, not crowd
  densities; real crowds also attenuate and obstruct radio signals, which is not modelled.
* **Idealised radio.** Unit-disc range, instant discovery, no interference, no connection setup, no loss and no
  OS background restrictions by default. Optional impairments exist but have no calibrated values. The model is
  not a Bluetooth, Wi-Fi Direct or Nearby Connections model.
* **Simulated motion classification.** Walking/stationary states come from the mobility model; errors are
  synthetic flips, not sensor-derived classification.
* **Synthetic friend groups.** Survey respondents are not simulation nodes; survey percentages are not targets.
* **Energy.** Completed transfers are an activity indicator. They do not measure battery use, discovery energy,
  control overhead, setup cost or interference. No battery saving is claimed.
* **Generalisation.** Results do not automatically transfer to real festivals; there is no Android validation.
* **Scope of comparison.** MWS is not claimed to be the first mobility-aware algorithm; published algorithms
  that were not implemented (Spray-and-Focus, Kawecki & Schoeneich, Social Spray-and-Wait) are not compared.
  The historical-motion variant is an internal ablation, not a reproduction of any published method.
* **Structural features of the scenario (from the pilot).** Separated friends rejoin physically within the
  model, so D15 is near ceiling for spray-based algorithms; with equal copy budgets, BSW and MWS normally spend
  all tokens within the lifetime, so T is (near-)identical by construction. These limit what H2 and H3 can show.
* **Zero-variance comparisons.** When every paired difference is identical (e.g. D15 at ceiling, T fixed by the
  shared budget) the paired t-test is undefined; such tests are reported as statistically inconclusive, with the
  observed difference and a structural explanation, never decided by assigning p = 0 or 1.
* **Reunion of separated friends.** In the pilot 95-97 % of separated pairs met directly again before expiry, and
  the rejoin rule strongly affects D5 (X4); the primary rule is a modelling assumption, not a measurement.
* **Spreading speed.** MWS restricts early relays to walkers, so it spreads copies more slowly than BSW (spray
  completion about 82 s vs 33 s at 100 nodes, pilot); this is reported, not tuned.
* **Supporting efficiency metrics** describe how copies are spent; they are activity indicators, not energy.
* **Published mobility-aware baseline not reproduced.** The Kawecki & Schoeneich (2016) article could not be
  inspected (publisher access gate), so no faithful implementation was attempted and no comparison is claimed.
* **Timing of revisions.** The revised zero-variance rule, supporting metrics and X1-X4 were defined after the
  first confirmatory batch had been inspected; if that batch is kept, these additions are exploratory.
* **Exploratory results** (E2, E3, E5, E6, optional extensions) are not confirmatory evidence.
* **The contribution** is the controlled evaluation of immediate walking-state relay selection in bounded-copy
  opportunistic forwarding under these assumptions.
