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

## Installation observations

The first HA OS amd64 installation completed app build/start, Ingress API access, eight-fixture
import and three-profile export with output stopped and zero packets. HACS download was verified.
Integration 0.1.1 fixed config-flow serialization, with probatio regression coverage. After an
authorized HA restart the integration loaded, creating four RGBW lights and four numbers.
Legacy entity IDs were preserved. New entities correctly remained unavailable while output was stopped.

Version 0.2.0 adds English/Spanish UI and English repository documentation. The Party Button
migration is described separately in [party-migration.md](party-migration.md).

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

## Before a stable release

- More amd64/aarch64 Supervisor and HACS validation, physical fixtures and channel tables.
- Broader CCT/RGBWW, reload, profile evolution and connectivity-loss coverage.
- Momentary actions, macro ranges, physical units and resting-state policies.
- RDM/ArtDataRequest, DMX input, source arbitration and ArtSync.
- sACN/KiNet, OFL/GDTF and community catalog adapters.
- Schema migrations and revision-based concurrent edit protection.
