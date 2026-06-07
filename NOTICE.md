# Attribution & provenance

`nora-nxdn` is a clean-room **re-implementation in Python** of the NXDN
protocol layer. The on-air constants and algorithms it relies on were derived
by studying the open-source DSD family of decoders, which is the canonical
reference for NXDN. This project carries those derivations forward and is
therefore licensed **GPL-3.0-or-later** to remain compatible with its sources.

## Derived constants and where they came from

| Constant / algorithm | Source project | File |
| --- | --- | --- |
| Frame sync words (`NXDN_*_SYNC`) | DSD (szechyjs/dsd) | `include/dsd.h` |
| PN95 dibit scrambler (LFSR seed `0xE4`, taps 0/4) | DSD-FME (lwvmobile/dsd-fme) | `src/nxdn_deperm.c` |
| LICH code -> burst-type table | DSD-FME | `src/nxdn_frame.c` |
| Block interleave maps (`PERM_*`) | DSD-FME / OP25 | `include/nxdn_const.h` |
| AMBE interleave schedule (nW/nX/nY/nZ) | DSD (szechyjs/dsd) | `include/nxdn_const.h` |
| 4FSK dibit slicer regions | DSD-FME | `src/dsd_dibit.c` |

- **DSD** — © DSD Author, ISC license.
- **DSD-FME** — "Florida Man Edition", GPL-3.0; incorporates portions of
  **OP25** (© Max H. Parke KA1RBI and contributors), GPL-3.0.

This project ships **no** vocoder. NXDN voice uses the proprietary AMBE+2
vocoder; decoded voice frames must be handed to an external decoder
(mbelib / an AMBE hardware dongle / DSD itself). No AMBE/IMBE source is
included or required to build this package.

## License text

The full GNU General Public License v3 is available at
<https://www.gnu.org/licenses/gpl-3.0.txt>. See `LICENSE`.
