# Source check - topic packs 01 and 03 (checked 2026-09-28)

Web search was rate-limited (HTTP 429); sources fetched directly (Europe PMC, arXiv, Wikipedia). Wikipedia rows are secondary only.


## 01_birds_dinosaurs

| id | verdict | corrected wording | URL | evidence |
|---|---|---|---|---|
| f_theropod_descent | SUPPORTED | - | https://doi.org/10.1016/j.cub.2015.08.003 | Brusatte et al. 2015 abstract: "Birds evolved from theropod dinosaurs during the Jurassic (around 165-150 million years ago)". |
| f_k_pg_survival | SUPPORTED_WITH_CORRECTION | Only some lineages of birds (the ancestors of today's crown-group birds, Neornithes) survived the end-Cretaceous extinction ~66 Mya; all non-avian dinosaurs and other early bird lineages (e.g. enantiornithines) died out. Source does not say 'beaked'. | https://doi.org/10.1016/j.cub.2018.04.062 | Field et al. 2018: the K-Pg catastrophe "eliminated even the closest stem-group relatives of Neornithes"; survivors were predominantly non-arboreal lineages. |
| f_archaeopteryx | SUPPORTED | - | https://en.wikipedia.org/wiki/Archaeopteryx | Wikipedia: Late Jurassic "around 150 million years ago"; "jaws with sharp teeth, a long bony tail ... feathers". (Secondary source; primary = Solnhofen fossil literature, not fetched.) |
| f_feathered_dinos | SUPPORTED | - | https://en.wikipedia.org/wiki/Sinosauropteryx | Wikipedia: Sinosauropteryx "among the first dinosaurs discovered from the Yixian Formation in Liaoning Province". Chen et al. Nature 1998 primary page not fetched; note its covering is simple filamentous 'protofeathers'. |
| f_wishbone | SUPPORTED_WITH_CORRECTION | The bird wishbone (furcula) is formed by midline fusion of the clavicles; furculae occur in nearly all major theropod clades, including many non-avian theropods. Source does not specifically confirm Tyrannosaurus. | https://doi.org/10.1002/jmor.10724 | Nesbitt et al. 2009 (J. Morphol. 270:856): "The furcula is a structure formed by the midline fusion of the clavicles... Furculae occur in nearly all major clades of theropods". |
| f_medullary | SUPPORTED_WITH_CORRECTION | Schweitzer et al. 2005 reported endosteal bone tissue in T. rex marrow cavities and hypothesized it is homologous to avian medullary bone (debated); not established as identical. | https://doi.org/10.1126/science.1112158 | Schweitzer et al. 2005 abstract: "we hypothesize that these tissues are homologous to specialized avian tissues known as medullary bone". |

## 03_time_crystals

| id | verdict | corrected wording | URL | evidence |
|---|---|---|---|---|
| f_wilczek | SUPPORTED | - | https://doi.org/10.1103/physrevlett.109.160401 | Wilczek, PRL 109, 160401 (2012) 'Quantum Time Crystals' (arXiv 1202.2539): spontaneous breaking of time translation symmetry in a closed quantum system; later literature describes a time crystal as periodic motion in its ground state (Autti et al. 2022). |
| f_no_go | SUPPORTED | - | https://doi.org/10.1103/physrevlett.114.251603 | Watanabe & Oshikawa, PRL 114, 251603 (2015): "We then prove a no-go theorem that rules out the possibility of time crystals defined as such, in the ground state or in the [thermal equilibrium]". |
| f_floquet | SUPPORTED | - | https://doi.org/10.1103/physrevlett.117.090402 | Else, Bauer, Nayak, PRL 117, 090402 (2016): time-translation symmetry breaking in many-body-localized driven systems; Choi et al. describe 'temporal correlations at integer multiples of the fundamental driving period'. |
| f_2017_labs | SUPPORTED | - | https://doi.org/10.1038/nature21413 | Zhang et al. Nature 543:217 (2017): "first experimental observation of a discrete time crystal, in an interacting spin chain of trapped atomic ions"; Choi et al. Nature 543:221 (2017) doi:10.1038/nature21426, disordered dipolar (NV) system. Preprints Aug-Sep 2016. Ytterbium/Maryland/Harvard details not in abstracts read. |
| f_google_2021 | SUPPORTED_WITH_CORRECTION | In 2021 (arXiv July 2021; Nature 601, 531, published 2022) Google reported an eigenstate-ordered discrete time crystal on a superconducting-qubit processor. The '20 qubits' figure was NOT confirmed by the abstract. | https://arxiv.org/abs/2107.13571 | Mi et al. abstract: "implement a continuous family of tunable CPHASE gates on an array of superconducting qubits to experimentally observe an eigenstate-ordered DTC". |
| f_no_perpetual_motion | SUPPORTED_WITH_CORRECTION | A time crystal is not a perpetual-motion machine or free-energy source: it needs a periodic drive and does no useful work. Do not say it 'takes energy from the drive' - in the many-body-localized versions it does not continuously absorb net energy (it avoids heating). | https://en.wikipedia.org/wiki/Time_crystal | Wikipedia: "such a crystal does not spontaneously convert thermal energy into mechanical work, and it cannot serve as a perpetual store of work". Secondary source only. |
