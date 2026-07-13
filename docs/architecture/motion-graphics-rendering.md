# Motion Graphics Rendering

The FFmpeg boundary remains provider-neutral and uses subprocess argument arrays with `shell=False`. Timeline layers resolve to a fixed preset registry. Current image motion supports static frames, slow zoom, and horizontal pan in the renderer; the schema reserves additional deterministic presets for incremental renderer expansion.

ASS subtitle files are generated from validated cues, written atomically under the project subtitle directory, hashed, and included in production render metadata. Scene transitions use validated cut/fade behavior. Outputs are written to a temporary path and atomically moved into their versioned final path after FFmpeg succeeds.

Production rendering requires an approved timeline and exact active approved assets whose files still match their recorded hashes. A changed timeline or asset hash produces a different plan fingerprint. Approved renders cannot be overwritten.

The engine does not accept arbitrary filter graphs, execute through a shell, download media, or bypass asset rights and approval checks.
