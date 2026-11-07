# Reference verification log (`paper/refs.bib`)

Checked on 2026-11-12. Every field in `paper/refs.bib` (authors, title, venue, year,
volume/pages, DOI) comes from one of the lookups below. Nothing was filled in from memory.

**How each source was used**

- **Crossref**: `api.crossref.org/works?query.bibliographic=...` to find the record, then
  `api.crossref.org/works/<DOI>` for the full record. Author lists use the publisher's
  given/family split.
- **arXiv**: `export.arxiv.org/api/query` (id_list or ti: search). Also checked for a
  journal-ref or a venue comment. arXiv DOIs (`10.48550/arXiv.*`) were checked against the
  DataCite API.
- **OpenReview**: `api2.openreview.net` / `api.openreview.net` `notes/search`. Gives the
  official venue for ICLR, COLM and TMLR papers, and also holds DBLP-imported records.
- **Publisher pages**: PMLR volume pages (v267, v306), the NeurIPS proceedings site (index plus
  the official `-Bibtex-*.bib` files), and Springer chapter pages ("Cite this paper" block, for
  LNCS volume numbers).
- **DBLP**: `dblp.org/search/publ/api` returned an anti-bot challenge page (HTTP 202, "Making
  sure you're not a bot") on every query, including the mirrors, so it was not used directly.
  The DBLP records that OpenReview mirrors, plus the publisher pages, were used instead.
- **Software**: PyPI JSON API (`pypi.org/pypi/<pkg>/<ver>/json`), the versions installed in
  `.venv` (`crosshair_tool-0.0.113.dist-info`, `icontract-2.7.3.dist-info`), and HTTP 200 from
  the GitHub repository page.
- **Final link check**: all 29 DOIs return 302 from `https://doi.org/<doi>`. All 16 non-DOI URLs
  (OpenReview, PMLR, arXiv, GitHub) return HTTP 200.

## Verified entries (41)

| key | title | where verified | DOI or URL used | notes |
|---|---|---|---|---|
| ye2026verina | VERINA: Benchmarking Verifiable Code Generation | arXiv 2505.23135; OpenReview (ICLR 2026 Poster) | https://openreview.net/forum?id=0A4Uf88pog | Hint correct. 6 authors. ICLR has no DOI. |
| thakur2025clever | CLEVER: A Curated Benchmark for Formally Verified Code Generation | arXiv 2505.13938; OpenReview (NeurIPS 2025 D&B Track); NeurIPS proceedings .bib; Crossref DOI | https://doi.org/10.52202/085713-3857 | Hint correct. NeurIPS 38, pp. 128165-128199 (pages from Crossref). OpenReview's auto-BibTeX says year 2026, but the proceedings and Crossref both say 2025, so 2025 is used. |
| aggarwal2025alphaverus | AlphaVerus: Bootstrapping Formally Verified Code Generation through Self-Improving Translation and Treefinement | arXiv 2412.06176; OpenReview (ICML 2025 poster); PMLR page | https://proceedings.mlr.press/v267/aggarwal25a.html | Hint correct. PMLR 267:587-615. No DOI. |
| yang2025autoverus | AutoVerus: Automated Proof Generation for Rust Code | Crossref DOI | https://doi.org/10.1145/3763174 | OOPSLA 2025, published in PACMPL 9(OOPSLA2):3454-3482, so it is an @article. 13 authors. |
| chen2025safe | Automated Proof Generation for Rust Code via Self-Evolution | arXiv 2410.15756; OpenReview (ICLR 2025 Poster) | https://openreview.net/forum?id=2NqssmiXLu | Hint correct. 14 authors. "Peng CHENG" normalized to "Peng Cheng" (arXiv form). |
| loughridge2025dafnybench | DafnyBench: A Benchmark for Formal Software Verification | arXiv 2406.08467; OpenReview (TMLR, accepted) | https://openreview.net/forum?id=yBgTVWccIx | **Venue found:** published in Transactions on Machine Learning Research (2025), so it is an @article, not arXiv. 10 authors. |
| misu2024dafnysynthesis | Towards AI-Assisted Synthesis of Verified Dafny Methods | Crossref DOI | https://doi.org/10.1145/3643763 | Hint correct. FSE 2024, published in PACMSE 1(FSE):812-835. |
| sun2024clover | Clover: Closed-Loop Verifiable Code Generation | Crossref DOI; Springer chapter page | https://doi.org/10.1007/978-3-031-65112-0_7 | Hint correct. SAIV 2024, LNCS vol. 14846, pp. 134-155. Volume number from the Springer page. |
| ma2025specgen | SpecGen: Automated Generation of Formal Program Specifications via Large Language Models | Crossref DOI | https://doi.org/10.1109/icse55347.2025.00129 | Hint correct. ICSE 2025, pp. 16-28. 5 authors. |
| wen2024autospec | Enchanting Program Specification Synthesis by Large Language Models Using Static Analysis and Program Verification | Crossref DOI; Springer chapter page | https://doi.org/10.1007/978-3-031-65630-9_16 | Hint correct. CAV 2024, LNCS vol. 14682, pp. 302-328. 9 authors. |
| endres2024nl2postcond | Can Large Language Models Transform Natural Language Intent into Formal Method Postconditions? | Crossref DOI | https://doi.org/10.1145/3660791 | Hint correct. FSE 2024, published in PACMSE 1(FSE):1889-1912. |
| mugnier2025laurel | Laurel: Unblocking Automated Verification with Large Language Models | Crossref DOI; arXiv 2405.16792 | https://doi.org/10.1145/3720499 | **Venue found:** OOPSLA 2025, PACMPL 9(OOPSLA1):1519-1545. Crossref has the last author's given and family names swapped ("Zhou Yuanyuan"); fixed to Yuanyuan Zhou as on arXiv. Author order follows the publisher record (Polikarpova before Jhala); arXiv v2 lists Jhala first. Crossref splits "Emmanuel Anaya Gonzalez" as given "Emmanuel Anaya", family "Gonzalez"; that split is kept. |
| chakraborty2025fstar | Towards Neural Synthesis for SMT-Assisted Proof-Oriented Programming | Crossref DOI | https://doi.org/10.1109/icse55347.2025.00002 | Hint correct. ICSE 2025, pp. 1755-1767. 7 authors. |
| wang2025errors | Towards Understanding the Characteristics of Code Generation Errors Made by Large Language Models | Crossref DOI | https://doi.org/10.1109/icse55347.2025.00180 | Hint correct. ICSE 2025, pp. 2587-2599. 7 authors. |
| hossain2025togll | TOGLL: Correct and Strong Test Oracle Generation with LLMs | Crossref DOI | https://doi.org/10.1109/icse55347.2025.00098 | Hint correct. ICSE 2025, pp. 1475-1487. Crossref capitalizes "LLMS"; written as "LLMs". |
| leino2010dafny | Dafny: An Automatic Program Verifier for Functional Correctness | Crossref DOI; Springer chapter page | https://doi.org/10.1007/978-3-642-17511-4_20 | Hint correct. LPAR 2010, LNCS vol. 6355, pp. 348-370. |
| demoura2008z3 | Z3: An Efficient SMT Solver | Crossref DOI; Springer chapter page | https://doi.org/10.1007/978-3-540-78800-3_24 | Hint correct. TACAS 2008, LNCS vol. 4963, pp. 337-340. |
| lattuada2023verus | Verus: Verifying Rust Programs using Linear Ghost Types | Crossref DOI | https://doi.org/10.1145/3586037 | Hint correct. OOPSLA 2023, published in PACMPL 7(OOPSLA1):286-315. 9 authors. |
| chen2021codex | Evaluating Large Language Models Trained on Code | arXiv 2107.03374; DataCite | https://arxiv.org/abs/2107.03374 | arXiv only: no journal-ref and no venue version found. Full list of 58 authors taken from the arXiv API. doi = 10.48550/arXiv.2107.03374. |
| austin2021mbpp | Program Synthesis with Large Language Models | arXiv 2108.07732; DataCite | https://arxiv.org/abs/2108.07732 | arXiv only. 11 authors. doi = 10.48550/arXiv.2108.07732. |
| yao2023react | ReAct: Synergizing Reasoning and Acting in Language Models | OpenReview (ICLR 2023 notable top 5%) | https://openreview.net/forum?id=WE_vluYUL-X | Hint correct. 7 authors, including Nan Du (the NeurIPS'22 workshop version has 6). |
| shinn2023reflexion | Reflexion: Language Agents with Verbal Reinforcement Learning | OpenReview (NeurIPS 2023 poster); NeurIPS proceedings .bib; Crossref DOI | https://doi.org/10.52202/075280-0377 | Hint correct. NeurIPS 36, pp. 8634-8652. The proceedings use lowercase after the colon; here it is title-cased, with the same words. |
| madaan2023selfrefine | Self-Refine: Iterative Refinement with Self-Feedback | OpenReview (NeurIPS 2023 poster); NeurIPS proceedings .bib; Crossref DOI | https://doi.org/10.52202/075280-2019 | Hint correct. NeurIPS 36, pp. 46534-46594. 16 authors. |
| chen2024selfdebug | Teaching Large Language Models to Self-Debug | OpenReview (ICLR 2024 poster) | https://openreview.net/forum?id=KuPixIqPiq | Hint correct. Authors: Xinyun Chen, Maxwell Lin, Nathanael Schärli, Denny Zhou. |
| chen2023codet | CodeT: Code Generation with Generated Tests | OpenReview (ICLR 2023 poster) | https://openreview.net/forum?id=ktrw68Cmu9c | Hint correct. 7 authors. |
| zhong2024ldb | Debug like a Human: A Large Language Model Debugger via Verifying Runtime Execution Step by Step | Crossref DOI | https://doi.org/10.18653/v1/2024.findings-acl.49 | Hint correct. Findings of ACL 2024, pp. 851-870. |
| yang2024sweagent | SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering | OpenReview (NeurIPS 2024 poster); NeurIPS proceedings .bib; Crossref DOI | https://doi.org/10.52202/079017-1601 | Hint correct. NeurIPS 37, pp. 50528-50652. Author names as in Crossref ("Carlos Jimenez"; OpenReview has "Carlos E. Jimenez"). |
| wu2024lemur | Lemur: Integrating Large Language Models in Automated Program Verification | OpenReview (ICLR 2024 poster) | https://openreview.net/forum?id=Q3YaCghZNt | Hint correct. Authors: Haoze Wu, Clark Barrett, Nina Narodytska. |
| first2023baldur | Baldur: Whole-Proof Generation and Repair with Large Language Models | Crossref DOI | https://doi.org/10.1145/3611643.3616243 | Hint correct. ESEC/FSE 2023, pp. 1229-1241. |
| thakur2024copra | An In-Context Learning Agent for Formal Theorem-Proving | OpenReview (COLM 2024) | https://openreview.net/forum?id=V7HRrxXUhN | Hint correct. Authors: Thakur, Tsoukalas, Wen, Xin, Chaudhuri. |
| meyer1992dbc | Applying "Design by Contract" | Crossref DOI | https://doi.org/10.1109/2.161279 | Hint correct. IEEE Computer 25(10):40-51, Oct. 1992. Crossref has only the initial "B. Meyer", so it is kept as an initial (IEEE style prints initials anyway). |
| shefer2025mainstream | Can LLMs Enable Verification in Mainstream Programming? | arXiv 2503.14183; DataCite; OpenReview/DBLP; Crossref search | https://arxiv.org/abs/2503.14183 | **No venue version found.** arXiv v1 only with no journal-ref, DBLP (via OpenReview) lists only CoRR 2025, and Crossref has no match. Cited as an arXiv preprint. 6 authors. |
| hou2024llm4se | Large Language Models for Software Engineering: A Systematic Literature Review | Crossref DOI | https://doi.org/10.1145/3695988 | Hint correct. ACM TOSEM 33(8):1-79, 2024. 10 authors. |
| wilcoxon1945individual | Individual Comparisons by Ranking Methods | Crossref DOI; OpenAlex | https://doi.org/10.2307/3001968 | Hint correct. Biometrics Bulletin 1(6), 1945. **Pages omitted:** Crossref and OpenAlex give only the start page (80), and JSTOR blocks automated access, so the end page was not guessed. |
| mcnemar1947note | Note on the Sampling Error of the Difference Between Correlated Proportions or Percentages | Crossref DOI | https://doi.org/10.1007/BF02295996 | Hint correct. Psychometrika 12(2):153-157, 1947. |
| crosshair | CrossHair (software) | PyPI `crosshair-tool` 0.0.113 JSON; `.venv` dist-info; GitHub page (HTTP 200) | https://github.com/pschanely/CrossHair | Version 0.0.113 confirmed. PyPI upload date is 2026-11-05, so year is 2026. Author from PyPI: Phillip Schanely. |
| icontract | icontract (software) | PyPI `icontract` JSON; `.venv` dist-info; GitHub page (HTTP 200) | https://github.com/Parquery/icontract | The installed version is **2.7.3**, released 2026-01-29 on PyPI, so year is 2026. Author from PyPI: Marko Ristin. |
| poesia2024dafnyannotator | dafny-annotator: AI-Assisted Verification of Dafny Programs | arXiv 2411.15143; DataCite; OpenAlex; OpenReview/Crossref search | https://arxiv.org/abs/2411.15143 | Candidate #37. **arXiv only (2024)**: v1, no journal-ref, and no venue version in Crossref, OpenAlex or OpenReview. It is not a main-track paper, so the next three entries were added. |
| baksys2026minif2fdafny | miniF2F-Dafny: LLM-Guided Mathematical Theorem Proving via Auto-Active Verification | OpenReview (ICML 2026 regular); PMLR v306 page; arXiv 2512.10187 (journal-ref) | https://proceedings.mlr.press/v306/baksys26a.html | Candidate #37, main track. ICML 2026, PMLR 306:5699-5716. LLMs write Dafny proof annotations. |
| pascoalfaria2025dafnyinv | Automatic Generation of Loop Invariants in Dafny with Large Language Models | Crossref DOI; Springer chapter page | https://doi.org/10.1007/978-3-031-87054-5_10 | Candidate #37. FSEN 2025 (main conference proceedings), LNCS vol. 15593, pp. 138-154. |
| li2026loopinv | Guiding LLM-Based Loop Invariant Synthesis via Feedback on Local Reasoning Errors | Crossref DOI | https://doi.org/10.1145/3806652 | Candidate #37. ACM TOPLAS 48(2):1-30, 2026, a journal paper on LLM loop-invariant synthesis. |

## Not verified / left out of refs.bib

- **No candidate was dropped.** All of candidates 1-37 were found in at least one authoritative
  source.
- **Extra, verified but not added:** "Proving the Coding Interview: A Benchmark for Formally
  Verified Code Generation" (FVAPPS), by Quinn Dougherty and Ronak Mehta. It appeared at the
  2025 IEEE/ACM LLM4Code Workshop (pp. 72-79), Crossref DOI `10.1109/llm4code66737.2025.00014`,
  arXiv 2502.05714. An older draft of the paper cited `fvapps2025`, but no current `.tex` file
  cites it, so it is not in refs.bib. If it is cited again, add it as `@inproceedings` using
  that DOI.

## Corrections and clarifications vs. the hints

1. **DafnyBench (#6)** was published in TMLR 2025. It is an `@article` in TMLR, not an arXiv preprint.
2. **Laurel (#12)**: the venue is OOPSLA 2025 (PACMPL 9, OOPSLA1). The last author's name was
   corrected to Yuanyuan Zhou, because Crossref has the given and family names swapped. The
   author order follows the publisher record.
3. **Shefer et al. (#32)**: no venue version exists in Crossref, DBLP-via-OpenReview, or the
   arXiv journal-ref, so it stays an arXiv preprint.
4. **icontract (#36)**: the version actually used is 2.7.3, the one installed in `.venv`.
5. **Dafny-annotator (#37)** is an arXiv-only 2024 preprint, not a main-track paper. Three
   verified 2025-26 papers were added: ICML 2026, FSEN 2025 (LNCS) and TOPLAS 2026.
6. **CLEVER (#2)**: OpenReview's generated BibTeX gives year 2026. The NeurIPS proceedings and
   Crossref give 2025, which is used.
7. **NeurIPS papers have DOIs.** Reflexion, Self-Refine, SWE-agent and CLEVER have registered
   NeurIPS/Curran DOIs (`10.52202/...`), so these entries use doi.org links rather than
   proceedings URLs.
8. **Small name and casing fixes** taken from the lookups: "Peng CHENG" becomes "Peng Cheng";
   middle initials get a period ("Shuvendu K. Lahiri", "Chloe R. Loughridge",
   "Karthik R. Narasimhan"); "LLMS" becomes "LLMs" (TOGLL).
9. All other hints (authors, venue, year) matched the lookups.

## Link policy in refs.bib

- **Entry has a DOI:** `doi = {<doi>}` and `url = {https://doi.org/<doi>}`.
- **arXiv-only entry:** `url` is the arXiv abs page, and `doi` holds the arXiv DataCite DOI
  (`10.48550/arXiv.<id>`).
- **ICLR / ICML / COLM / TMLR paper:** `url` is the official OpenReview forum page or PMLR page.
  These venues have no DOI.
- **Software:** `url` is the GitHub repository.

All 41 entries have a `url` field (`IEEEtran.bst` prints it).
