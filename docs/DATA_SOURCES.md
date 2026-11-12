# Data sources

Every item below is real data from an official open-access source unless marked synthetic. Raw
downloads stay in the git-ignored `data/raw/<source>/`; `data/manifest.csv` records source, URL or
DOI, license, retrieval time, sha256, size and record count for every file
(`data_tools/build_manifest.py`; re-check with `data_tools/verify_manifest.py`). Only licenses that
allow research use are kept (CC0, CC BY, CC BY-NC, CC BY-SA, CC BY-NC-SA).

**LI-RADS labels.** None of the open CT datasets has LI-RADS *feature* labels (APHE, washout,
capsule); those exist only in AMPLIFAI (access pending). WAW-TACE does give a per-lesion pre-TACE
LI-RADS *category* and diameter. No LI-RADS label is ever derived by us where a dataset has none.

| Source | What it is | Real? | Size used | License | How obtained | Use |
| --- | --- | --- | --- | --- | --- | --- |
| Radiopaedia, PMC (manual) | Radiologist-written LI-RADS cases entered by hand | real | 5 cases | CC BY-NC-SA 3.0 / CC BY 4.0 | manual entry (no scraping) | text evaluation |
| Europe PMC | Open-access LI-RADS articles; candidate cases with the stated category | real | 1,184 articles found, 941 license-compatible, 936 full texts, **59 candidates** (42 articles; 11 from per-lesion tables) | CC BY, CC BY-NC, CC0, CC BY-NC-SA | REST API, 3 queries, cached | text evaluation after human review |
| WAW-TACE (Zenodo 12741586) | Multiphase CT of 233 HCC patients before TACE; tumour masks; clinical data | real | clinical table, CT metadata, 378 tumour masks (2.3 MB); CT zips (4 x 9.9-12.9 GB) **not downloaded (decision)** | CC BY 4.0 | Zenodo API, md5-verified | size measurement; label analysis |
| HCC-TACE-Seg (TCIA via IDC) | Multiphase CT of 105 HCC patients with expert segmentations (liver, mass, portal vein, aorta) | real | clinical table (105 x 59); pre-treatment CT + SEG for **10 patients** (33 series, 1.07 GB) | CC BY 4.0 | `idc-index` | CT previews, measured sizes; image pipeline roadmap |
| TCGA-LIHC (TCIA via IDC) | Imaging and pathology of 377 liver cancer cases | real | series list and clinical table only (no images; 681.8 GB in IDC) | CC BY 3.0 / 4.0 | `idc-index` | roadmap |
| PLC-CECT (Science Data Bank) | CECT of primary liver cancer subtypes | real | **skipped: requires login** (2 files, 42.05 GB) | CC BY 4.0 | DataCite metadata only | roadmap |
| Stress-test generator, demo samples S1-S10 | Reports generated from known feature vectors; demo reports | **synthetic** | 200 / 10 | project | generated | controlled-ambiguity benchmark, demo |
| AMPLIFAI | Multiphase CT with LI-RADS feature labels | real | none | gated | **requested / pending** | planned feature-level evaluation |
| MIMIC-IV-Note | Radiology reports | real | none | PhysioNet credentialed | **requested / pending** | planned text evaluation |
| Ramaiah hospital reports | De-identified institutional reports | real | none | ethics approval | **requested / pending** (via guide) | planned text evaluation |

**Columns related to LI-RADS that the open datasets contain** (reported as found, not interpreted):

* WAW-TACE: `lesion1..3_LIRADS` (pre-TACE category: lesion 1 = 222 LR-5, 6 LR-4, 5 LR-M),
  `lesion1..3_diameter` (maximal axial diameter, portal phase), `lesions_number`, `lab_afp`, `bclc`,
  `cps` (Child-Pugh), etiology flags, `initial_LR_TR` (treatment response). No feature columns.
* HCC-TACE-Seg: `tr_size`, `tumor_nodul`, `vascular_invasion`, `portal_vein_thrombosis`,
  `evidence_of_cirh`, `afp`, `bclc`, `cps`, `pathology`, `hepatitis`, RECIST/mRECIST responses.
* TCGA-LIHC: histology, grade, TNM stage; no imaging features.

**Outputs from the data.**
`data/real/ct_lesion_sizes.csv` gives the maximum axial diameter measured from 378 WAW-TACE masks and
10 HCC-TACE-Seg segmentations. Against WAW-TACE's own clinical diameters (233 patients), the
median absolute difference is 4.3 mm (55 % within 5 mm, 77 % within 10 mm; masks read about 4 mm
larger, plausibly because most masks are on a different phase than the portal-phase clinical
measurement). `docs/figures/ct_preview_*.png` shows arterial and portal-venous phases with the
expert tumour outline for three HCC-TACE-Seg patients; phases are labelled from measured aortic
attenuation.

**Limitations.** Europe PMC candidates are machine-extracted and need human review before use; the
label is the category the authors stated, and published cases over-represent clear-cut LR-5 and
LR-M. The CT datasets are TACE cohorts with large tumours (HCC-TACE-Seg masks 32-172 mm), so they
do not test small, equivocal observations, and they contain no report text for the text pipeline.
WAW-TACE phase codes (0-3) are used as given and are **unverified against the dataset paper**; no
analysis here depends on which contrast phase a code denotes. The WAW-TACE CT archives (44.9 GB)
are deliberately not downloaded.
