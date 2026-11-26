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
* **Exploratory results** (E2, E3, E5, E6, optional extensions) are not confirmatory evidence.
* **The contribution** is the controlled evaluation of immediate walking-state relay selection in bounded-copy
  opportunistic forwarding under these assumptions.
