# Pronunciation adaptation test cases

These cases describe expected pronunciation-adapter behavior for `spoken_language=pl`.

The adapter should preserve meaning and avoid translation. For Polish spoken language, Polish text should remain normal Polish text, while English insertions and phrases should be rewritten into Polish-friendly phonetic spelling.

| Input | Expected adapted text | Notes |
| --- | --- | --- |
| `GitHub action failed` | `GitHab ekszyn fejld` | English technical phrases should be rewritten into Polish-friendly phonetic spelling. |
| `TypeScript check passed` | `tajp skrypt check passed` | Technology names may be rewritten when Polish TTS otherwise reads them poorly. |
| `React component rendered` | `reakt component rendered` | Keep the term recognizable while improving Polish pronunciation. |
| `frontend build failed` | `frontend bild fejld` | Short English technical phrases may be phoneticized without translating. |
| `Build failed w module płatności` | `Bild fejld w module płatności` | Polish text stays unchanged; English phrases are phoneticized. |
| `Codex is waiting for plan approval` | `Codex is waiting for plan approval` | Brand/product names can remain unchanged when a phonetic rewrite is not clearly better. |
| `Merge request is ready` | `merdż request is ready` | Common workflow terms may be partially phoneticized. |
