# Experimental validation and deployment

## Automated coverage

- Eight-fixture sample import: universe 0, full frames, exact addresses/constants and optional
  conversion of standalone dimmers to numbers.
- RGBW output, independent controls, unmapped slots and 8/16/24/32-bit separate bytes.
- Atomic command rejection, overlap detection, bounds and unknown options.
- Profile export without installation addresses.
- ArtDmx endianness, even padding, sequencing and 15-bit address boundaries.
- Minimum 207-byte ArtPollReply and BindIndex nodes.
- Real UDP loopback: transitions, FPS limits, refresh and sender shutdown.
- API authentication, preview without output, persistence and rejection of edits during output.
- Real HA 2026.10.2 with HTTP app and loopback Art-Net: config flow serialization, native
  entities and service calls.
- Browser checks: both languages, saved preference, unchanged user names, imports, number
  controls, patch, profile editor and 1440/390/320px layouts, without enabling DMX.
- App Docker image build.

Automated checks do not replace Supervisor/Ingress installation or physical hardware tests.
HA tests use pytest-homeassistant-custom-component and expose the component directory to HA.

## Existing-installation test sequence

1. Inventory versions, apps, previous sender and consumers.
2. Preserve configuration and registry metadata; install using separate IDs.
3. Check Ingress, imports and profiles with HartNet output stopped.
4. Load the integration and inspect entities without gateway traffic.
5. Compare the full universe and runtime presets before changing senders.
6. Stop the previous sender, then enable HartNet and verify known channels, macros, speed,
   color, brightness and shutdown behavior.
7. Restore the previous sender if equivalence is not established.

A complete universe contains every slot. Testing one fixture does not isolate other controls
in that universe. Use separate destinations/universes or explicitly maintain one buffer owner.

## Restart recovery (0.3)

The local engine/API/protocol suite passes 60 tests; the separate real-HA suite passes 3 tests.
Automated regressions cover active and stopped restarts, all generic control types, light/color
and interrupted fade targets, concurrent commands, failed atomic replacement, strict corrupt-state
rejection and legacy file migration. A real subprocess test sends commands over HTTP, kills the
process with SIGKILL, restarts it and checks the first UDP packet against the acknowledged values.

Socket binding failures retry and can be stopped during backoff. A failed destination does not stop
healthy universes. Unexpected sender task failures produce a failing health probe without exposing
project data. Runtime state and output intent are persisted together with the project; no cleanup
handler is needed for crash recovery.

## Before a stable release

- More amd64/aarch64 Supervisor and HACS validation, physical fixtures and channel tables.
- Broader CCT/RGBWW, reload, profile evolution and connectivity-loss coverage.
- Momentary actions, macro ranges, physical units and resting-state policies.
- RDM/ArtDataRequest, DMX input, source arbitration and ArtSync.
- sACN/KiNet, OFL/GDTF and community catalog adapters.
- Schema migrations and revision-based concurrent edit protection.

## Subscription routing (0.4)

Regressions cover targeted ArtPoll fields, StController announcements, minimum-length replies,
input/output ports, sACN/disabled/non-DMX filtering, multiple BindIndex records, source/advertised-IP
matching, monotonic expiry, explicit withdrawal and stopped output. An actual loopback UDP gateway
verifies no DMX before a matching subscription, withdrawal, expiry and fresh first frames after
resubscription with refresh disabled. Delayed controller replies are cancelled on stop.

Physical gateway validation and full Art-Net 4 conformance remain outstanding. The sender still
uses only explicitly configured destinations. No full-controller certification is claimed.

The 0.4 browser smoke check passes in English/Spanish at 1440/390/320px, including saving subscription
mode offline and recovering it after reload, with zero DMX frames. Ruff passes. The Docker build was
not rerun locally because the Docker daemon was unavailable; the existing CI build remains required.
