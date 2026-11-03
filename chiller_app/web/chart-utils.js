/* Unit-aware signal selection shared by the chart and its verification. */
(function (root) {
  "use strict";
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const colors = ["#087e80", "#c08328", "#537cc4", "#b2668b", "#728c38", "#7966ad", "#bd6553"];

  function availableSignals(records, units, labels) {
    return Object.entries(units)
      .filter(([key]) => key !== "elapsed_s" && records.some(row => finite(row[key])))
      .map(([key, unit], index) => ({key, unit, title: labels[key] || key,
        color: colors[index % colors.length], dashed: index >= colors.length}));
  }

  function groupSignals(signals, selected) {
    const groups = new Map();
    for (const signal of signals) {
      if (!selected.has(signal.key)) continue;
      if (!groups.has(signal.unit)) groups.set(signal.unit, []);
      groups.get(signal.unit).push(signal);
    }
    return groups;
  }

  function valueExtent(rows, signals) {
    let min = Infinity, max = -Infinity;
    for (const row of rows) for (const {key} of signals) {
      if (finite(row[key])) {min = Math.min(min, row[key]); max = Math.max(max, row[key]);}
    }
    if (!Number.isFinite(min)) return null;
    const pad = Math.max((max - min) * 0.12, Math.max(Math.abs(min), Math.abs(max)) * 0.01, 0.1);
    return [min - pad, max + pad];
  }

  function selectSignals(current, key, checked, single) {
    const selected = new Set(single ? [] : current);
    if (checked) selected.add(key); else selected.delete(key);
    return selected;
  }

  const api = {finite, availableSignals, groupSignals, valueExtent, selectSignals};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ChillerCharts = api;
})(globalThis);
