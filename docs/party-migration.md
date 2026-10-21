# Reversible Party Button migration

Existing label-driven lighting coordinators can route Party Button effects to HartNet without
changing music, timers, button triggers or the shared lighting policy.

## Preparation

Keep private copies of the original project, runtime presets, affected entity registry labels,
automation/script configs and the previous sender's YAML. Do not commit installation addresses,
credentials or backups. Record original hashes and check for concurrent edits before writing.

For coordinators accepting only lights and switches, clone the standalone scalar profile for the
macro fixtures and change that clone to a dimmer. Leave speed fixtures as numbers. This keeps
macro brightness presets compatible with existing `light.turn_on` and `light.turn_off` actions.
Reload the integration to register the additional lights; preserve obsolete number registry entries.

## Cutover

1. Keep HartNet output stopped. Copy legacy brightness, color and speed presets into its runtime
   state. Compare the complete 512-slot resting frame, including independent speed values.
2. Back up and disable only the previous Art-Net YAML platform for the affected destination.
   Validate HA configuration and obtain restart confirmation before restarting Core.
3. Confirm the previous sender is stopped. Enable HartNet and verify entity availability.
4. Transfer the party-effects and managed-light labels from the old spots/macros to the new
   HartNet lights. Preserve all other label members, including independent switches.
5. Dry-run the coordinator and verify the effective party target set. A full party run also starts
   audio and should be an intentional user test.

From 0.3 onward, app restarts restore presets and the previous output intent automatically. A
manual stop remains stopped. The one-time upgrade from 0.2 needs the captured runtime presets
restored before enabling output, since that version saved only the patch. Enable Start on boot
and Watchdog for host/process recovery. A Core-only restart leaves the independent app running.

## Rollback

Stop HartNet output first. Restore each entity's recorded labels and restore the original sender
YAML using the current-file hash to avoid overwriting unrelated edits. Validate configuration and
restart Core with confirmation. Verify legacy entities and the original party target set. Restore
only affected objects; a whole-system restore is unnecessary for this migration.
