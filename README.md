# PoolMarshall by CodedThought on Raspberry Pi 5

A self-hosted edition of Erik's 18,000-gallon Houston pool dashboard, with a containerized AqualinkD RS485 bridge for the user-reported Jandy AquaLink RS PS6 Pool-Spa controller and single-speed 2 HP PSP200-HV pump.

## What runs on the Pi

One Docker Compose stack contains two services:

- **dashboard**: maintenance checklist and history, water readings, findings, follow-ups, seasonal planning, energy comparisons, SQLite records on a persistent Docker volume, and an AqualinkD status bridge with optional direct pump/spa commands.
- **aqualinkd**: upstream ARM64 image `sfeakes/aqualinkd:v3.1.0`, communicating directly with the controller through a USB-to-RS485 adapter. Its native web interface provides equipment controls. It starts only when the `hardware` profile is explicitly selected.

No cloud account, Home Assistant, MQTT broker, or Sites hosting is required for this edition. The previously published Site is a separate copy and does not synchronize with this Pi. To transfer its records, export a backup from that Site and import it here. The new Pi edition does not publish itself or change the existing Site.

The mobile app provides direct Filter Pump Start/Stop and Spa Enable/Disable controls through a narrowly scoped server bridge. These controls are disabled by default. Native AqualinkD on port 6171 is retained under an optional advanced maintenance section. The main interface does not reproduce the OneTouch layout. The dashboard shows raw upstream status on demand, with a timestamp. A responding HTTP service is not treated as proof of a functioning board connection. No automatic schedule changes, heater setpoints, chemical doses, or inferred inspection results are created. Spa mode can operate configured valves; verify the installation before enabling control.

## Requirements

- Raspberry Pi 5 with 64-bit Raspberry Pi OS or another 64-bit ARM Linux distribution.
- Docker Engine and the Docker Compose plugin installed and working. `docker compose version` must succeed. If your account requires sudo for Docker, prefix the Docker commands accordingly.
- For hardware operation: USB-to-RS485 adapter, verified panel-side wiring, and a suitable protected installation for the Pi, adapter, and power supply. Adapter isolation is recommended. A USB adapter needs a wired connection; it is not a Wi-Fi device.
- The hardware service follows upstream's systemd-journal mount arrangement. Check `/var/run/systemd/journal/socket` and `/var/log/journal`. The journal mounts grant the daemon access to host logs and the journal socket; this stack is intended for a personally administered Pi.
- Board firmware revision, exact panel identity, supported protocols, circuit assignments, bus loading/termination, and any existing iAquaLink connection must be verified before live control. The included `RS-6 Combo` configuration is a candidate based on the supplied model, not an inspection result.

## Start the dashboard first

Extract the ZIP and change into `poolmarshall-pi5` on the Pi:

```bash
cp .env.example .env
nano .env
```

Replace `CHANGE_ME` with a unique password of at least 16 characters. Use a long random alphanumeric value to avoid Compose interpolation issues with dollar signs. Keep `.env` private:

```bash
chmod 600 .env
./preflight.sh
docker compose up -d --build dashboard
docker compose ps
```

The default bind address is `127.0.0.1`. From a computer with SSH access, open a tunnel (replace the username and address):

```bash
ssh -N -L 8080:127.0.0.1:8080 -L 6171:127.0.0.1:6171 your-user@PI_ADDRESS
```

Open `http://localhost:8080` on that computer. Sign in with username **poolside** and the password from `.env`. No sample inspections or issues are preloaded. The dashboard works before the adapter is purchased.

For a phone, arrange access through an authenticated VPN/reverse proxy to the Pi. The bundled HTTP dashboard is intended for a private network or SSH tunnel. Basic authentication by itself does not encrypt traffic. Do not expose either port to the public internet. AqualinkD's native interface has no username/password authentication. If you intentionally change `BIND_ADDRESS` to the Pi's LAN address for trusted-LAN use, both ports become reachable there; configure your network access accordingly. No tunnel, public ingress, or router changes are automated by this package.

## Add RS485 hardware

Have the panel's connections identified from its documentation by a qualified installer. Do not connect the board's power terminals to USB adapter data terminals. This package intentionally does not guess connector pin numbers, wire colors, or termination values.

Once the adapter is connected to the Pi:

```bash
ls -l /dev/serial/by-id/
nano .env
```

Set `RS485_DEVICE` to the adapter's full stable path, such as the actual `/dev/serial/by-id/...` returned on your Pi. Do not copy a fabricated identifier. If the adapter has no stable ID, a udev rule or verified `/dev/ttyUSB0` path is needed; numbering can change after a reboot.

Review `config/aqualinkd.conf` against the identified panel. Then:

```bash
./preflight.sh --hardware
docker compose --profile hardware up -d --build
docker compose logs --tail=100 aqualinkd
```

The USB host device is mapped into the container as `/dev/ttyUSB0`. No privileged container or whole `/dev` mount is used. After an adapter disconnect/reconnect, check its path and recreate the hardware service if needed:

```bash
docker compose --profile hardware up -d --force-recreate aqualinkd
```

Use the SSH tunnel described above and open `http://localhost:6171` for AqualinkD's native interface. Inspect communications and equipment labels before commanding anything. Clicking the dashboard's **Fetch controller status** only reads `/api/status`; it does not send equipment commands. Status tiles show only values returned by the controller; unavailable, sentinel, and zero temperature values remain unknown. They are not independent sensor verification. The UI displays when the last HTTP response was fetched; panel freshness remains unverified.

The single-speed pump supports on/off through its assigned controller circuit. This package does not assume variable-speed telemetry, actual flow, power draw, or remote speed selection. Actual status and available sensors depend on your installation.

## Optional direct app controls

After the panel and Filter_Pump/Spa circuit assignments have been verified, set `POOL_CONTROL_ENABLED=true` in `.env` and recreate the dashboard:

```bash
docker compose up -d --build --force-recreate dashboard
```

Then tap **Controls**, refresh status, and use the explicit Start/Stop or Enable/Disable buttons. Each command asks for confirmation. The backend permits only the two named circuits with values 0 or 1, checks that a non-placeholder panel response and circuit state exist, and reports requests as submitted, not physically confirmed. Refresh to inspect the subsequent response. A timeout leaves the outcome unknown; check status before retrying. The board's original protections still apply. To lock controls again, set the flag to false and recreate the dashboard. No command has been tested against your physical equipment.

## Appearance and mobile layout

The mobile layout includes Home, Controls, Care, Water, and Plan navigation, large touch targets, logged-reading summaries, quick care actions, and follow-up cards. The interface now follows the supplied codedthought logo: royal blue, bright cyan, deep navy, and golden-yellow accents. These are visual matches to the supplied raster reference, not a claimed official brand-token specification. A custom circuit-and-water app icon is included at 192px, 512px, Apple touch size, favicon size, and full generated resolution. The web manifest requests standalone display where supported; offline shell caching is included after the first successful load where service workers are supported. Adding the app to the home screen depends on your browser and secure-origin requirements. An HTTP LAN address may not offer installation.

## Schedules and protection

Keep Jandy's existing onboard schedules and freeze protection in place. The package disables AqualinkD's optional scheduler and panel-clock synchronization, and does not override freeze protection. The day/night comparison is a planning calculator only. Changing its inputs does not program the controller. AqualinkD can send real commands once started and connected; the dashboard does not certify the installation as safe.

## Naming and upgrade compatibility

The product is now **PoolMarshall by CodedThought**. This package changes the app title, home-screen name, branding, and exported filenames. It retains the existing Compose project name `poolside`, volume `poolside-data`, database filename, `POOLSIDE_PASSWORD` setting, login username `poolside`, browser storage keys, and internal bridge interface so existing records and installations continue to work. Use the same `.env` and configuration when replacing an earlier package; back up first.

## Data and backups

Maintenance records live at `/data/poolside.db` in the persistent `poolside-data` Docker volume, not in the container image. A normal rebuild or `docker compose down` preserves the volume. **Do not use `docker compose down -v` unless you intend to delete those records.**

Use **Export backup** in the dashboard for portable JSON backups, and copy the `config` directory separately to retain AqualinkD configuration and any future schedules. Import replaces the dashboard maintenance record after confirmation; it does not alter the hardware configuration. Exported backups can contain private notes.

A local browser recovery copy is attempted, but the Pi database is the active source. Save indicators show pending/success/failure. Use one editing browser at a time. Revision conflicts are rejected rather than silently overwriting another browser's changes. On a conflict or failed save, export the browser's records, then reload and reconcile. When the Pi cannot be reached, a cached record can be edited locally. If no cached record exists, editing is blocked. Maintenance edits are queued and retried when online, with revision conflicts preserved for manual reconciliation. Equipment commands are never queued or replayed. Offline shell reload requires a secure context with service-worker support; otherwise keep the already loaded page open. Save must complete before closing the browser.

## Operations

```bash
docker compose ps
docker compose logs --tail=100 dashboard
docker compose --profile hardware stop
```

Version updates should be intentional. Review the upstream release notes, back up records and config, update the pinned image tag, pull, and recreate the hardware service. Do not use native self-update to change binaries inside a container; recreate the image instead.

## Validation and limits

Prepared November 13, 2026. The twelve included server integration tests cover authentication, write validation, database persistence and revision conflicts, the read-only status bridge, rejection of arbitrary equipment command routes, default control lockout, allowed-circuit restrictions, and blocking commands when panel status is unverified. JavaScript syntax, shell syntax, and Compose YAML structure were checked. Docker is unavailable in the preparation environment, so image startup, Docker Compose's own configuration validation, ARM64 execution, USB timing, and live controller operation have NOT been tested. Run the preflight and local checks on the Pi. Nothing has been installed on your Pi remotely.

To rerun the software tests on a machine with Python 3:

```bash
python3 test_server.py
# Optional: Node.js is needed only to run the arithmetic tests, not to host the app.
node test_math.cjs
```

## References

- AqualinkD source and license: https://github.com/aqualinkd/AqualinkD
- Upstream container instructions: https://hub.docker.com/r/sfeakes/aqualinkd
- ARM64 image tags: https://hub.docker.com/r/sfeakes/aqualinkd/tags
- Version-matched configuration: https://github.com/aqualinkd/AqualinkD/blob/v3.1.0/release/aqualinkd.conf
- Version-matched container entrypoint: https://github.com/aqualinkd/AqualinkD/blob/v3.1.0/docker/aqualinkd-docker.cmd
- Hardware requirements: https://aqualinkd.github.io/details/
- Docker installation documentation: https://docs.docker.com/engine/install/

This bundle references the upstream image; it does not redistribute AqualinkD binaries or source. Review upstream licensing and safety documentation before modifying or redistributing it. Dashboard water-care and energy references remain linked within the app. The web interface remains guidance and record keeping, not a substitute for equipment inspection.


## Owner-toolkit update, November 13, 2026

Use the **Care toolkit** button in the header or Home page. The new workflows include:

- Pool/spa profiles with separate care logs and custom water targets. The existing Jandy hardware connection remains assigned to the original Houston pool only; selecting a new profile never remaps or enables physical equipment.
- Extended manual tests: total/free chlorine, bromine, pH, total alkalinity, calcium hardness, CYA, temperature, salt, TDS, borates, magnesium hardness and filter pressure. Sanitizer type starts unknown. Chemistry photos are compressed manual attachments, not analyzed measurements.
- Water reports with parameter-specific prior-test labels, current-only pH/sanitizer, custom target ranges, reports, CSV/share, and time-window trend charts. Slow-changing test lookback defaults to a configurable 30 days relative to the latest test; old source dates stay visible.
- Supply inventory, storage locations, label ingredients/strength, low-stock thresholds, recorded usage/restocking, stock reconciliation, and monthly priced-consumption totals. Unknown prices remain unpriced; totals can be partial. Initial stock and prices require user entry.
- Ordered treatment steps, partial quantities, awaiting-retest status, label-specific separation/circulation notes and reminders. Treatment quantities do not automatically deduct inventory; log the corresponding product use explicitly. No dose is dispensed, and the app never declares water safe to swim.
- Dated maintenance reminders, optional repeat intervals after completion, snooze, and calendar exports. Due badges update when the app is opened; no background push, SMS, or email delivery is included.
- Equipment models, serials, install/warranty dates, condition labels, verified clean-pressure baselines, service notes and feeder-setting history. Feeder changes are records only; they do not operate hardware.
- Pool-volume, dry chlorine/salt/CYA mass balance, label-based ppm dose, partial water-replacement, fill-duration, and conventional adjusted-LSI calculators. No acid/pH-demand estimator or liquid-product density assumption is supplied. Borate adjustment is not guessed: use independently corrected carbonate alkalinity when borates are present or unknown. This is not Pooli's proprietary CSI.
- Cumulative pool/household meter readings, elapsed-use comparisons, bucket-test notes, and local fill countdowns. These do not confirm leaks or shut off the hose.
- On-demand NWS forecasts for Houston city center, with transparent weather-related care checklists and guided cloudy/green-water, flow, rain, water-loss and bromine checks. This is rule-based guidance, not a generative AI chat or photo diagnosis. The Pi requires internet access for NWS; forecast failures retain prior timestamped data.
- Cached offline shell and local maintenance-edit queue, with explicit revision conflict protection. Browser local-storage limits still apply; small photo attachments can exhaust it. Export backups regularly. API responses and physical commands are not cached by the service worker. An HTTP LAN address may not support service workers; localhost through an SSH tunnel or properly configured HTTPS can.

The stored request limit is now 20 MB for a maintenance record; keep photo attachments modest. Browser quota can be lower. Cross-device editing is still single-owner, optimistic-concurrency editing, not real-time multi-user collaboration.

### Implemented alternatives and unavailable integrations

This is an independent implementation of owner workflows described at https://pooli.app/features/. No Pooli code, assets, proprietary calibration, product catalog, subscription system, or AI service is used. Its calibrated strip scanner, Percy AI/image interpretation, community, member benefits, and professional routing/billing are not integrated. The app includes a **Feature coverage** page so these limitations are visible. Manual photo records and rule-based checks do not substitute for a validated scanner or AI service.

### Arithmetic references and validation

The conventional LSI expression is documented at https://poollab.poolpower.com.au/langelier/; CYA correction factors are interpolated from the PHTA table at https://www.phta.org/pub/?id=25A114B4-1866-DAAC-99FB-277001B3C020. No thermodynamic CSI accuracy or product equivalence to Pooli is claimed. The dry-dose calculator performs a concentration-by-mass calculation using US gallons to liters and entered active mass percentage; its output is mass, not cups or liquid volume. Label-based ppm scaling is linear and explicitly excludes pH demand.

CDC chemistry and handling references: https://www.cdc.gov/healthy-swimming/about/home-pool-and-hot-tub-water-treatment-and-testing.html and https://www.cdc.gov/healthy-swimming/media/pdfs/Pool-Chemical-Safety-USE-poster-p.pdf. Weather source: https://www.weather.gov/documentation/services-web-api. No chemicals are mixed or water-safety certification issued by this software.

The update passed 12 server integration tests and 12 arithmetic/boundary checks, plus browser page/navigation and dose-output checks. Server tests include asset serving and mocked NWS fixed-host/caching behavior. The NWS live request, photo-capture hardware, offline reconnect lifecycle, ARM64 containers and physical RS485 control remain unverified in the preparation environment. Native share/calendar behavior depends on the browser/device. New names remain suggestions only; the current app name has not changed.
