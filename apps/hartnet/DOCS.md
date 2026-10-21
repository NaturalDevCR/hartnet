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

The app saves `/data/project.json` and the preceding version as `/data/project.previous.json`.
Every app startup preserves the patch and starts with output stopped. Runtime values are not
restored. Stopping output stops packets; the gateway may hold its last state. Turn lights off
first if that is the intended result. ArtDmx does not confirm physical state.

Output is manual unicast to configured destinations. Existing universe 0 mappings are preserved.
UDP port 6454 must be available. Discovery sends ArtPoll only when requested and does not alter
the patch. RDM and automatic fixture-personality detection are not implemented.

Profile exports contain relative offsets without installation addresses. Use the advanced editor's
project download for a complete private backup. There is no automatic community-library publishing.
