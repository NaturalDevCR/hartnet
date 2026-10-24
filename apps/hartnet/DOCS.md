# Home Assistant OS installation

1. Add `https://github.com/NaturalDevCR/hartnet` to the Apps store repositories and install HartNet.
   For local development, copy this complete directory to `/addons/hartnet` and refresh local apps.
2. Set `api_token` to a random value of at least 16 characters, start the app, and open its web UI.
3. Choose English or Spanish using the language selector. The browser preference is used initially.
4. Import your YAML or create a patch. Review the preview before saving.
5. Install `custom_components/hartnet` through HACS or copy it to `/config/custom_components/hartnet`.
   Restart HA and add HartNet under Settings → Devices & services.
6. Use host `127.0.0.1`, port `8099` and the same token. The app uses host networking.
7. Stop the previous sender and review every slot before enabling output.

The app saves a versioned project/runtime envelope in `/data/project.json`. This internal file
contains both the mapping and accepted values/output intent; use the UI export for portable
project JSON. `/data/project.previous.json` preserves the state preceding a project edit.
Commands update the current state atomically without rotating that project-edit backup.

App restarts restore accepted brightness, color, numbers, switches and selections before sending
any DMX. Output resumes if it was enabled, and stays stopped if manually stopped. Interrupted
transitions restore their final target values. New installations and upgrades from 0.2 (which saved
no runtime values) start stopped and need one initial activation after configuring presets.
Enable **Start on boot** and **Watchdog** in the app settings for automatic host/process recovery.

Corrupt or unsupported stored state prevents startup; it does not silently enable default values.
Stopping output stops packets; the gateway may hold its last state. Turn lights off
first if that is the intended result. ArtDmx does not confirm physical state.

Output defaults to manual unicast. Each node also offers subscribed unicast: while output is enabled,
HartNet polls the configured endpoint every 2.75 seconds, sends only advertised universes and expires
subscriptions after 5.75 seconds without a reply. Missing subscriptions show a waiting status. It also
answers untargeted polls as a controller. Stop output to stop polling/announcements and DMX.

Existing universe 0 mappings are preserved. UDP port 6454 must be available. Explicit discovery works
with output stopped, waits up to three seconds and never alters the patch. RDM and automatic
fixture-personality detection are not implemented. This remains a subset of Art-Net 4.

Profile exports contain relative offsets without installation addresses. Use the advanced editor's
project download for a private configuration backup. A Supervisor app backup also includes runtime state. There is no automatic community-library publishing.
