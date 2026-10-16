# Presence detection on the Opal: iwinfo vs hostapd

## What we know

### Echo Dot — likely false positives from Netmap

We observed multiple samples where iwinfo wlan0 assoclist did not show the Echo Dot, while ubus call hostapd.wlan0 get_clients continued to report it with assoc: true and authorized: true.

This is concrete evidence that Netmap may declare it offline even when the access point still considers it associated. It is not, however, absolute proof that the Echo Dot maintained connectivity in every instant.

### Echo Dot — no explicit disconnections in the collected logs

[Further investigation needed with hostapd-level logging]

## Recommendations for Netmap

1. Use hostapd get_clients (ubus) as the primary source for client presence on the Opal.
2. Keep iwinfo assoclist only for RSSI/traffic data when hostapd agrees a client is present.
3. Add OPAL_MISSING_GRACE_SECONDS to avoid false disconnects when the driver drops a client from the radio view for a few polls.
4. Log discrepancies between hostapd and iwinfo at DEBUG level for future analysis.

