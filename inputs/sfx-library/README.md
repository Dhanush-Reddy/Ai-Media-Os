# Sound Effects Library

Sound-effect compilations are imported into one of two locations:

- `quarantine/`: clips with unknown or incomplete commercial-use rights. The renderer must not use
  these clips automatically.
- `approved/`: clips imported with a recorded license or permission that permits commercial use.

Recognizable platform, game, film, or character sounds remain `BLOCKED` even when a compilation
uploader grants permission, unless rights to the underlying recording are separately verified.

Run `scripts/import-reference-sfx-compilation.ps1` with the source files to reproduce the cuts and
catalog. Only use `-CommercialUseConfirmed` together with a specific non-`UNKNOWN` `-License` value
and retained proof of permission.
