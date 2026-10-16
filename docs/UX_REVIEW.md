# UX Review — Netmap Rebrand v2

This review covers the rebranded HTML template v2 (`templates/index.html`), based on the multilingual version (`index-multilang.html`).

## Summary

- Netmap visual identity aligned with the chosen palette: navy `#0B1F3B`, blue `#007BFF`, cyan `#00D1FF`, green `#00E676`.
- Logo and payoff in the header, aligned refresh and actions area, panels and metrics with clearer visual hierarchy.
- Table sorting: every main column is sortable. IPv4 addresses are compared numerically (e.g. `.9` sorts before `.20`); missing values stay at the bottom.
- Italian/English switch preserved and persisted in `localStorage`.
- Dark/light theme toggle with `localStorage` persistence.
- Quick IP/MAC copy on both topology cards and table rows; clicking the copy button does not open the device history.
- Responsive: works at 390px viewport width without horizontal overflow; table shows a scroll hint on mobile.

## Tests performed

| Test | Result |
|---|---|
| Initial dark theme renders correctly | ✓ |
| Light/dark toggle switches and persists | ✓ |
| IT/EN texts switch correctly | ✓ |
| IP sorting is numeric | ✓ |
| Search/reset filters work | ✓ |
| Copy to clipboard (IP and MAC) | ✓ |
| Clicking copy does not open history | ✓ |
| No JavaScript errors in test run | ✓ |
| 390px viewport: no horizontal overflow | ✓ |

Tests were performed against simulated data, not live routers. Verify on the production Netmap before considering the release complete.

## Future considerations

### CSV export

To export the current inventory, the browser can generate a CSV from `/api/data` devices. Handle CSV quoting, UTF-8 and an optional BOM for Excel compatibility.

### Paging events

The current `/api/events` endpoint caps at 300 rows (SQLite LIMIT). For a full, reliable history export, the backend needs either a streaming CSV endpoint or a paged endpoint without record loss, respecting the configured retention window.

### Bulk history export

`/api/history?mac=...&hours=...` already returns averaged samples for a single MAC (~500 points per query). Exports of the visible chart data can be done from the browser. Bulk exports of all histories as a single file with completeness guarantees need an aggregated backend endpoint rather than many individual UI exports.