# Game compatibility

Games actually tested against Lithium, on this dev machine (Mac mini,
Apple M4 Pro, macOS 15.7.7). This is not a "should work" list — every
entry here has actually been launched and played, at least briefly, on
the current build. See `docs/plan.md` for the overall project roadmap
and `docs/context.md` for stack-wide (not game-specific) known
limitations.

## Status legend

- **Playable** — runs and can be played through normally. Any caveats
  are noted per-game.
- **Playable with issues** — runs and is playable, but has a specific,
  known, reproducible problem (visual, audio, a missing feature) that
  doesn't block actually playing.
- **Not working** — doesn't reach gameplay (crashes, hangs, or fails to
  install).

## Tested games

| Game                    | Engine | Graphics API     | Status               | Notes                                               |
| ----------------------- | ------ | ---------------- | -------------------- | --------------------------------------------------- |
| Hollow Knight: Silksong | Unity  | D3D11 (via DXVK) | Playable with issues | [hollow-knight-silksong](hollow-knight-silksong.md) |

## Adding a new entry

1. Play through enough of the game to exercise its core loop (menu,
   actual gameplay, save/quit) — not just a launch check.
2. Note the engine and primary graphics API if known (helps spot
   patterns across games later).
3. If something's broken, root-cause it the way every other bug in this
   project has been handled: real logs/traces, not guesses (see
   `docs/troubleshooting.md`). Link to a `docs/context.md` entry or a
   memory writeup for anything with real investigation behind it, rather
   than duplicating the detail here.
4. Add a row to the table above and a short per-game section following
   the Silksong example.
