# Instruments cited in the corpus but absent from the treaties bundle

Census of instrument mentions across GC (7,216 ¶) + JUR (40 shards) + SP (46 shards),
2026-07-27. **`near art-ref`** counts mentions immediately followed by an article
reference — the number that matters for popover coverage, since only those would light up.

**Why adding an instrument is cheap and high-leverage:** since v19.65 the frontend
resolves leading instrument names against the `/api/treaties` bundle (`name_full`) and the
popover reads article text from the same bundle. Adding an entry to the ask-api bundle
(abbr + name_full + articles[]) makes both the correct linking AND the popover work with
**zero frontend changes**.

| # | Instrument | mentions | near art-ref | GC | JUR | SP |
|--:|---|--:|--:|--:|--:|--:|
| 1 | European Convention on Human Rights (ECHR) | 2901 | 145 | 5 | 2282 | 614 |
| 2 | Universal Declaration of Human Rights (UDHR) | 1652 | 132 | 59 | 123 | 1470 |
| 3 | Geneva Conventions 1949 (+Protocols) | 914 | 50 | 28 | 51 | 835 |
| 4 | UN Guiding Principles on Business and Human Rights | 707 | 0 | 7 | 4 | 696 |
| 5 | UN Charter | 665 | 36 | 37 | 45 | 583 |
| 6 | UNDRIP (Indigenous Peoples Declaration) | 642 | 31 | 14 | 53 | 575 |
| 7 | 1951 Refugee Convention | 548 | 21 | 24 | 344 | 180 |
| 8 | Declaration on Human Rights Defenders | 455 | 5 | 2 | 3 | 450 |
| 9 | Nelson Mandela Rules (SMR) | 417 | 9 | 4 | 198 | 215 |
| 10 | Rome Statute of the ICC | 415 | 24 | 16 | 53 | 346 |
| 11 | American Convention on Human Rights (ACHR) | 404 | 53 | 9 | 52 | 343 |
| 12 | African Charter (Banjul, ACHPR) | 328 | 56 | 6 | 4 | 318 |
| 13 | Framework Convention on Climate Change (UNFCCC) | 309 | 13 | 8 | 6 | 295 |
| 14 | Enforced Disappearance Declaration (1992) | 269 | 2 | 0 | 15 | 254 |
| 15 | Guiding Principles on Internal Displacement | 265 | 0 | 1 | 2 | 262 |
| 16 | ILO Conventions (other/unspecified) | 247 | 7 | 18 | 29 | 200 |
| 17 | Vienna Convention on the Law of Treaties (VCLT) | 236 | 3 | 16 | 149 | 71 |
| 18 | Vienna Declaration and Programme of Action | 226 | 0 | 13 | 1 | 212 |
| 19 | CTOC (Palermo Convention, org. crime) | 203 | 5 | 7 | 4 | 192 |
| 20 | Kampala Convention (IDPs, AU) | 181 | 2 | 0 | 0 | 181 |
| 21 | Hague Conventions (other) | 179 | 2 | 3 | 66 | 110 |
| 22 | Convention on Biological Diversity | 161 | 6 | 1 | 0 | 160 |
| 23 | Istanbul Convention (violence against women) | 139 | 2 | 0 | 24 | 115 |
| 24 | ILO Convention No. 169 (Indigenous) | 125 | 2 | 3 | 14 | 108 |
| 25 | Genocide Convention | 121 | 0 | 8 | 12 | 101 |
| 26 | Body of Principles (detention) | 120 | 1 | 2 | 16 | 102 |
| 27 | Arab Charter on Human Rights | 97 | 16 | 0 | 0 | 97 |
| 28 | Aarhus Convention | 94 | 2 | 0 | 0 | 94 |
| 29 | European Social Charter | 89 | 10 | 7 | 10 | 72 |
| 30 | Basic Principles on the Use of Force (law enforcement) | 88 | 2 | 4 | 11 | 73 |
| 31 | Paris Principles (NHRIs) | 88 | 0 | 6 | 5 | 77 |
| 32 | Bangkok Rules (women prisoners) | 85 | 0 | 1 | 17 | 67 |
| 33 | Slavery Conventions (1926/1956) | 84 | 5 | 0 | 2 | 82 |
| 34 | EU Charter of Fundamental Rights | 64 | 6 | 1 | 16 | 47 |
| 35 | Beijing Rules (juvenile justice) | 63 | 0 | 5 | 6 | 52 |
| 36 | ILO Convention No. 182 (Worst Forms of Child Labour) | 61 | 1 | 4 | 0 | 57 |
| 37 | UNESCO Convention against Discrimination in Education | 56 | 3 | 7 | 4 | 45 |
| 38 | Havana Rules (juveniles deprived of liberty) | 44 | 0 | 2 | 0 | 42 |
| 39 | ILO Convention No. 189 (Domestic Workers) | 40 | 0 | 2 | 0 | 38 |
| 40 | Paris Agreement (climate) | 40 | 0 | 1 | 8 | 31 |

## Recommendation tiers

**Tier 1 — add now (high mentions × high near-ref × article text freely available):**
UDHR, ECHR, Geneva Conventions I-IV + AP I/II, UN Charter, UNDRIP, 1951 Refugee
Convention, Rome Statute, ACHR, African Charter. Together these cover ~75% of all
near-art-ref mentions among missing instruments. ECHR alone is #1 overall (dominant in
JUR — treaty bodies routinely compare with Strasbourg case law).

**Tier 2 — add if Tier 1 goes well (soft-law with stable numbering):**
Nelson Mandela Rules, Beijing/Bangkok/Havana/Tokyo Rules, Body of Principles, Basic
Principles on the Use of Force, Paris Principles, UNGPs (Guiding Principles are
"principle N", not "article N" — needs a term tweak in the popover header).

**Tier 3 — skip for now:** VCLT (cited for interpretation doctrine, rarely per-article
in a way readers need popped), UNFCCC/CBD/Paris Agreement (peripheral to the corpus),
ILO conventions (long tail of many instruments, each individually rare).

## Where the data comes from / caveats
- Alias-based canonicalisation; "Geneva Conventions" and "Hague Conventions" are families
  counted together. ILO split: No. 169/189/182/138 counted separately, rest pooled.
- `raw_unmatched` residue (see instrument-census.json) is dominated by bare "the
  Covenant/Convention/Declaration" anaphora — resolvable only per-document, not counted here.
- Counts are mentions, not paragraphs; a paragraph naming an instrument 3× counts 3.
