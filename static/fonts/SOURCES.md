# Vendored fonts

| File | Source | SHA-256 |
|---|---|---|
| `InterVariable.woff2` | Inter v4.1 (released 2024-11-16), `web/InterVariable.woff2` inside the release archive | `693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3` |
| `LICENSE.txt` | Same archive, `LICENSE.txt` (SIL Open Font License 1.1) | `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a` |

- Release archive: `https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip`, 33,707,794 bytes, SHA-256 `9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`. Upstream publishes no checksum, so these hashes are as downloaded on 2026-10-04.
- Only the upright variable font (weights 100–900) is vendored; italics are not used.
- A test checks the hashes above, so a changed font file fails the build.
