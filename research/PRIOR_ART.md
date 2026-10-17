# Prior-art review: budgeted evidence acquisition for timing-aware cross-system diagnosis

Review date: 17 October 2026. Repository state when the review was made: branch `research/evidence-acquisition` at commit `e8b0e03` (the same commit as `eng/v0.5-telemetry-integration`). Hypothesis labels follow [`PROTOCOL.md`](PROTOCOL.md): H0 normal operation with nuisance variation, HB battery-current measurement bias b, HT relative timing error δ between the electrical stream and the motor-side stream, HL increased opposing longitudinal force ΔF, HU unmodelled behaviour.

The research question has five parts: (1) recognise competing explanations for an inconsistency; (2) state which explanations the evidence can separate; (3) choose more records within byte and latency budgets (buffered pre-event window, future window, clock-synchronisation metadata, less-decimated channel export, waiting for an informative operating condition); (4) beat strong baselines on correct diagnosis; (5) abstain when no unique cause is supported.

## 1. Summary

**Read in full.** Six peer-reviewed papers, each in the copy the publisher itself distributes. They come from the repositories behind the Proceedings of Machine Learning Research (PMLR), `github.com/mlresearch/vNN`, from which proceedings.mlr.press is served:

- Trapeznikov and Saligrama (2013);
- Javdani et al. (2014);
- Chen et al. (2015);
- Geifman and El-Yaniv (2019);
- Zaffran et al. (2022);
- Prinster et al. (2023).

Also read in full: primary documentation in the authors' own repositories.

- the Fault Diagnosis Toolbox user manual and reference list;
- the OpenVINS calibration documentation;
- the `rosbag_snapshot` README;
- the released code and README for arXiv:2609.14595;
- the README and module docstrings of the code release for a manuscript by Zhou and Liang.

**Not readable.** None of the eight sources on the study plan's reading list (S1 to S8) could be read in full:

| Source | Why it could not be read |
|---|---|
| S1 | IET, paywalled. No author copy was found. |
| S2 | Elsevier, paywalled. A precursor conference paper and a thesis are on HAL, which this review did not use (section 5). |
| S3 | Author-hosted copies are reported at NASA DASHlink and Vanderbilt; this review did not use them (section 5). |
| S4 | CC BY full text exists at PMC and in the KIT repository. mdpi.com refused, and no GitHub copy was found. |
| S5 | opencommons.uconn.edu refused. A digitalcommons.lib.uconn.edu record with a matching abstract appeared in search results, but its title and author were not confirmed. |
| S6 | arXiv refused. No GitHub copy was found. |
| S7 | arXiv refused. The authors' code repository was read instead. |
| S8 | SSRN refused. The associated Zenodo record was not used (section 5). |

**Details that differ from the reading list or could not be confirmed.**

- **S2.** The DOI is correct. A DOI-string search matched PubMed record PMID 25109542: ISA Transactions 54 (January 2015) 92-100, online August 2014, first author M. A. Sid (CRAN, Université de Lorraine). The reading list gives no authors, and the full author list was not verified.
- **S3.** The NASA DASHlink record gives the venue as the 7th IFAC SAFEPROCESS symposium, 2009. Volume, pages and DOI were not verified.
- **S5.** Title, year and degree could not be confirmed. Only an abstract on the same topic was seen.
- **S6.** Exists: arXiv:2512.12844, by Xu, Guo and Wei (New Jersey Institute of Technology), submitted 14 December 2025.
- **S7.** Exists: arXiv:2609.14595, submitted 13 September 2026.
  - The abstract page and the authors' repository use the title "... with Minimum Description Length". One search summary reports that the PDF header reads "... via ...".
  - The third author is spelt "Kuhse" in search results and "Kuhe" in the repository's BibTeX.
- **S8.** Exists as an SSRN posting (abstract 7226337) by Tavish Pattanayak: posted 3 August 2026, 18 pages, apparently not peer reviewed. A Zenodo software record, "LiveTwin" (v0.1.0, 11 July 2026), is associated with it.

**Resulting limits on novelty claims.**

1. Everything said here about S1 to S8 and the other summary-only sources rests on search-engine summaries, not on the papers. This review does not show that any method is absent from any of them.
2. Each component of the proposed study already has prior art:

| Component | Prior art |
|---|---|
| Selecting measurements or tests to discriminate between candidate diagnoses | A4, A2 |
| Budgeted sequential acquisition with a reject option | A1 |
| Active diagnosis by input or test design | S3, S5, A6 |
| Scheduling sensors for isolability under bandwidth limits | S2 |
| Structural isolability and sensor placement | A5 |
| Estimating a time offset jointly with sensor biases | A7, A8 |
| Data-driven detection of temporal misalignment | S7 |
| Cause attribution with synchronisation for digital twins | S8, summary only |
| Calibrated abstention | A9, S6, A10 |
| A structural-plus-conformal verifier that accepts, rejects or escalates fault hypotheses | A14, code only |

3. The specific combination was not found: choosing which buffered telemetry records to retrieve according to the remaining ambiguity, within byte and latency budgets, to separate HB, HT and HL, with abstention. The search could not query arXiv, Crossref, OpenAlex, Semantic Scholar, SSRN or MDPI directly, so not finding it is weak evidence, not proof of absence.
4. The contribution should be framed as an experimentally demonstrated extension and a reproducible systems contribution, not as a new method class (section 4.4).

## 2. Source table

Notes on the table:

- **PMLR route.** The `mlresearch` repositories are the publisher's own: proceedings.mlr.press is served from them, and each PDF states "Copyright ... by the author(s)". They are not third-party re-hosts.
- **Large repositories.** These were cloned with `git clone --depth 1 --filter=blob:none --no-checkout`, followed by a sparse checkout of one PDF and its metadata file.
- **Text extraction.** All PDFs were converted with `pdftotext -layout`.
- **Nothing from a download was executed.**

| ID | Source | Identifier | Access level | Route | Relevance |
|---|---|---|---|---|---|
| S1 | Geng, Liang, Xu (2015), Fault detection for multi-rate sensor fusion under multiple uncertainties, IET Control Theory & Applications 9(11) 1709-1716 | DOI 10.1049/iet-cta.2014.1134 | search summary only | web search, standard mode (two queries) | multirate fault detection with unknown inputs |
| S2 | Sid et al. (2015), Sensor scheduling strategies for fault isolation in networked control system, ISA Transactions 54 92-100 | DOI 10.1016/j.isatra.2014.07.005; PMID 25109542 | search summary only | web search, standard then extended (DOI string) | sensor scheduling for isolability under bandwidth limits |
| S3 | Daigle, Koutsoukos, Biswas (2009), Improving Diagnosability of Hybrid Systems through Active Diagnosis, 7th IFAC SAFEPROCESS | no DOI verified; NASA DASHlink resource 887 | search summary only | web search, standard (two queries) | active diagnosis to improve diagnosability |
| S4 | Li, Frey, Gauterin (2023), Model-Based Condition Monitoring of the Sensors and Actuators of an Electric and Automated Vehicle, Sensors 23(2) 887 | DOI 10.3390/s23020887; PMC9861315 | search summary only | web search, standard (one general query, one restricted to github.com) | electric-vehicle sensor and actuator monitoring; closest application domain |
| S5 | Palmer (2018), Optimal Selection of Test Designs and Sensor Sets for Active Fault Diagnosis, PhD dissertation, University of Connecticut (title not confirmed) | not confirmed; candidate record digitalcommons.lib.uconn.edu/dissertations/2038 | search summary only | web search, standard and extended (three queries) | joint test design and sensor selection |
| S6 | Xu, Guo, Wei (2025), Selective Conformal Risk Control | arXiv:2512.12844 | search summary only | web search, standard (two queries) | selection followed by conformal risk control |
| S7 | Buschjäger, Frichert, Kuhse (or Kuhe), Chen (2026), Diagnosing Temporal Misalignment in Multichannel Time-Series Classification with Minimum Description Length | arXiv:2609.14595 | search summary only for the paper; full text of the authors' code and README | web search, standard and extended; `git clone --depth 1` of github.com/sbuschjaeger/mdl-temporal-misalignment at `c68392af9ea3` | data-driven detection of inter-stream lag |
| S8 | Pattanayak (2026), Identifiability-preserving synchronization and uncertainty decomposition for hybrid digital twins: a reproducible benchmark, SSRN preprint | SSRN abstract 7226337; Zenodo record 21308351 (software) | search summary only | web search, standard (no hit) then extended | identifiability, cause attribution, benchmark design |
| A1 | Trapeznikov, Saligrama (2013), Supervised Sequential Classification Under Budget Constraints, AISTATS, PMLR 31:581-589 | proceedings.mlr.press/v31/trapeznikov13a | full text | github.com/mlresearch/v31 at `b5b261a2dab6` | budgeted sequential acquisition with reject |
| A2 | Javdani, Chen, Karbasi, Krause, Bagnell, Srinivasa (2014), Near Optimal Bayesian Active Learning for Decision Making, AISTATS, PMLR 33:430-438 | proceedings.mlr.press/v33/javdani14 | full text | github.com/mlresearch/v33 at `b2b9c05b87e5` | test selection until the decision is determined |
| A3 | Chen, Hassani, Karbasi, Krause (2015), Sequential Information Maximization: When is Greedy Near-optimal?, COLT, PMLR 40:338-363 | proceedings.mlr.press/v40/Chen15b | full text | github.com/mlresearch/v40 at `0b4b7e7ef9f2` | greedy information gain under persistent noise |
| A4 | de Kleer, Williams (1987), Diagnosing multiple faults, Artificial Intelligence 32 97-130 | DOI not verified | search summary only | web search, standard | consistency-based diagnosis with next-measurement selection |
| A5 | Frisk, Krysander, Jung (2017), A Toolbox for Analysis and Design of Model Based Diagnosis Systems for Large Scale Models, IFAC World Congress; Fault Diagnosis Toolbox user manual v0.13 (release of 2024-02-22); Krysander, Frisk (2008), Sensor placement for fault diagnosis, IEEE TSMC-A 38(6) 1398-1410 | DOI 10.1016/j.ifacol.2017.08.504; DOI 10.1109/TSMCA.2008.2003968 | full text of manual and README; the two papers not read | `git clone --depth 1` of github.com/faultdiagnosistoolbox/pyfaultdiagnosistoolbox at `661b993050fe`; sparse clone of github.com/faultdiagnosistoolbox/faultdiagnosistoolbox.github.io at `e3005e4c725e` | structural detectability, isolability, sensor placement, test selection |
| A6 | Scott, Findeisen, Braatz, Raimondo (2014), Input design for guaranteed fault diagnosis using zonotopes, Automatica 50 1580-1589 | DOI not verified | search summary only | web search, standard | set-based guaranteed active fault diagnosis |
| A7 | Li, Mourikis (2014), Online temporal calibration for camera-IMU systems: Theory and algorithms, International Journal of Robotics Research 33(7) 947-964 | DOI not verified | search summary only | web search, standard (two queries) | time offset as an estimated state; identifiability |
| A8 | OpenVINS documentation (calibration and estimator pages) | github.com/rpng/open_vins at `69488123ed93`, `docs/*.dox` | full text (documentation) | sparse clone of the documentation sources | joint online estimation of time offset and biases; excitation requirement |
| A9 | Geifman, El-Yaniv (2019), SelectiveNet: A Deep Neural Network with an Integrated Reject Option, ICML, PMLR 97:2151-2159 | proceedings.mlr.press/v97/geifman19a | full text | github.com/mlresearch/v97 at `31ef0a7c93aa` | selective risk and coverage |
| A10 | Zaffran, Féron, Goude, Josse, Dieuleveut (2022), Adaptive Conformal Predictions for Time Series, ICML, PMLR 162:25834-25866 (states the ACI update of Gibbs and Candès, NeurIPS 2021) | proceedings.mlr.press/v162/zaffran22a | full text | github.com/mlresearch/v162 at `76fcebd56ef1` | conformal calibration under temporal dependence |
| A11 | Barber, Candès, Ramdas, Tibshirani (2023), Conformal prediction beyond exchangeability, Annals of Statistics 51(2) 816-845 | DOI 10.1214/23-AOS2276 | search summary only | web search, standard | coverage gap without exchangeability |
| A12 | Prinster, Saria, Liu (2023), JAWS-X: Addressing Efficiency Bottlenecks of Conformal Prediction Under Standard and Feedback Covariate Shift, ICML, PMLR 202:28167-28190; with Fannjiang et al. (2022), PNAS 119(43) e2204569119 | proceedings.mlr.press/v202/prinster23a; PMC9618043 (Fannjiang) | full text (Prinster); search summary only (Fannjiang) | github.com/mlresearch/v202 at `3c987f88bec5` | calibration when the data used were selected by the model |
| A13 | rosbag_snapshot, README (software documentation) | github.com/ros/rosbag_snapshot at `b7a3d78fb18c` | full text (README) | `git clone --depth 1` | buffered pre-event recording with a triggered, windowed write |
| A14 | Zhou, Liang (2026), Diagnosability-Bounded Admissibility Verification for LLM Agents in Industrial Cyber-Physical Systems, manuscript submitted to IEEE Transactions on Industrial Cyber-Physical Systems; code release | github.com/chenxuanzhou/diagnosability-bounded-verification at `2dc8d2048095` | README and module docstrings read in full; paper unavailable | sparse clone; docstrings read by static parsing; nothing executed | closest overlap: structural indiscernibility with a conformal accept, reject or escalate verifier |

**Leads found but not relied on.** Each should be read before any claim is drafted.

- **"Resource-Aware Safety-First Active Sensor Acquisition with Few-Shot Commissioning for Edge Fault Warning"**, reported DOI 10.3390/s26165065 (Sensors, 2026).
  - Seen once as a search hit. Its snippet described a budgeted feature-acquisition layer for fault warning, and reported that fixed-periodic and random-budget policies are not guided by diagnostic uncertainty.
  - A second search did not find the record. Overlap risk on research question (3); verify first.
- **Sid, Aberkane, Sauter, Maquin**, "Fault isolation filter and sensors scheduling co-design for networked control systems", CCA 2012, pp. 1691-1696, HAL hal-00702667. The precursor of S2; a related thesis is on HAL (tel-01750745).
- **Li, Sauter, Xu (2011)**, "Fault Isolation Filter for Networked Control System with Event-Triggered Sampling Scheme", Sensors (PMC3274084). Send-on-delta transmission for fault isolation; search summary only.
- **Work related to S5 (search summaries only):**
  - Palmer and Bollas, "Sensor Selection Embedded in Active Fault Diagnosis Algorithms", IEEE Transactions on Control Systems Technology (2019);
  - Palmer, Hale and Bollas, "Active Fault Identification by Optimization of Test Designs", same journal (2018);
  - Awasthi, Palmer and Bollas, "Optimal test and sensor selection for active fault diagnosis using integer programming", Journal of Process Control 92 (2020).
- **Yang, Geneva, Eckenhoff, Huang**, "Degenerate Motion Analysis for Aided INS With Online Spatial and Temporal Sensor Calibration". Cited by A8 as IEEE document 8616792; a 2018 technical report of the same work was found, but the published venue was not confirmed.
- **"Bias estimation for asynchronous multi-rate multi-sensor fusion with unknown inputs"**, by the research group of S1. Listing only.
- **Related to S6:** arXiv:2603.24704, "Conformal Selective Prediction with General Risk Control"; SCoRE (github.com/Tian-Bai/SCoRE), a different selective conformal risk-control method.
- **Sequential model-based diagnosis:** Siddiqi and Huang, "Sequential Diagnosis by Abstraction" (JAIR; arXiv:1401.3892); Rodler et al., measurement proposal for sequential model-based diagnosis (arXiv:1705.09879).
- **Vehicle diagnostic patents with pre- and post-trigger rolling buffers around fault codes** (numbers as reported by search, not checked): US 6,601,015 "Embedded datalogger for an engine control system"; US 6,745,151 "Remote diagnostics and prognostics methods for complex systems"; US 11,080,950 "Cooperative vehicle diagnosis system". Prior art for buffered pre-event capture as such.
- **An IEEE DataPort dataset page** reported to accompany the A14 manuscript.

## 3. Sources

Each entry gives:

- citation and verification;
- access and route;
- relevant content;
- assumptions;
- reuse;
- candidate contribution;
- closest competing baseline.

Where only a summary was seen, "Relevant content" paraphrases the summary and is marked as such: nothing from a summary is quoted as if it were the paper. Baseline labels B0 to B11 refer to section 4.1.

### S1. Geng, Liang, Xu (2015): multi-rate fault detection

- **Citation.** H. Geng, Y. Liang, L. Xu, "Fault detection for multi-rate sensor fusion under multiple uncertainties", IET Control Theory & Applications 9(11):1709-1716, 2015. DOI 10.1049/iet-cta.2014.1134.
- **Verification.** Authors (Northwestern Polytechnical University), title, volume, issue, pages, DOI and date (16 July 2015) agree across two independent search summaries. Those summaries cite the university research portal and two bibliographic index pages. Not checked with the publisher (doi.org and Crossref refused).
- **Access and route.** Search summary only, from two standard-mode web searches. The publisher copy is paywalled, no author copy was found, and third-party copies were not used.
- **Relevant content (summary only, nothing read).** The summaries describe:
  - a time-varying multi-rate observer, lifted to a single-rate system with a causality constraint for parameter design;
  - parameters chosen to decouple unknown inputs and attenuate noise;
  - a multi-rate residual generator, with a hypothesis test whose threshold is adaptive;
  - validation on a numerical example.
- **Assumptions.** Not readable. The summaries imply a linear lifted model with a known sampling pattern, and unknown inputs entering through a known structure. Whether sampling instants are assumed exactly known could not be checked; it is the assumption that matters most for HT.
- **Reuse.** Lifting streams of different rates to a common model is the standard way to build a residual across the project's controller frames (10 ms and 100 ms), wheel windows (100 ms), GNSS (10 Hz), PPS (1 Hz) and uplink summary (2 Hz). The adaptive threshold is a candidate for the H0 nuisance band.
- **Candidate contribution (conditional on the full text).**
  - Treat an unknown relative offset between streams as a competing hypothesis rather than assuming known sampling instants.
  - Decide which further records to retrieve when the residual cannot separate hypotheses.
- **Closest competing baseline.** A passive multi-rate residual detector with an adaptive threshold and a binary alarm (B1).

### S2. Sid et al. (2015): sensor scheduling for fault isolation

- **Citation.** M. A. Sid et al., "Sensor scheduling strategies for fault isolation in networked control system", ISA Transactions 54:92-100, January 2015 (online August 2014). DOI 10.1016/j.isatra.2014.07.005; PMID 25109542.
- **Verification.** A standard search on the title found no match. An extended search on the DOI string matched the PubMed record, which gives:
  - the title, as on the reading list;
  - first author and affiliation (CRAN, Université de Lorraine);
  - volume, pages and dates;
  - keywords: fault isolation, improved Kalman filtering, networked control systems, sensor scheduling.

  The full author list was not verified, and the DOI was not resolved directly.
- **Access and route.** Search summary only, from web search (standard, then extended).
- **Relevant content (summary only).** No text was read. The keywords and the summarised precursor (Sid, Aberkane, Sauter and Maquin, CCA 2012) describe co-designing a sensor transmission schedule and a fault isolation filter under limited bandwidth. The summary describes the filter as a special structure of the Kalman filter.
- **Assumptions.** Not readable. The keywords suggest a linear stochastic networked plant, with a bandwidth limit on how many sensors transmit at each step.
- **Reuse.** The problem has the same form as choosing which channels to send over the uplink, or which log segments to retrieve, while keeping the faults isolable.
- **Candidate contribution (conditional on the full text).**
  - Selection triggered by an observed inconsistency and directed by the remaining ambiguity, rather than a schedule designed in advance.
  - Retrospective retrieval of buffered data and metadata, plus a waiting action.
  - An explicit timing-error hypothesis.
- **Closest competing baseline.** A static or periodic export schedule designed offline for isolability (B6).

### S3. Daigle, Koutsoukos, Biswas (2009): active diagnosis of hybrid systems

- **Citation.** M. Daigle, X. Koutsoukos, G. Biswas, "Improving Diagnosability of Hybrid Systems through Active Diagnosis", Proceedings of the 7th IFAC Symposium on Fault Detection, Supervision and Safety of Technical Processes (SAFEPROCESS), 2009. NASA DASHlink resource 887. No DOI verified.
- **Verification.** Title, authors and venue come from the NASA DASHlink resource page, as summarised by two searches; affiliations are UC Santa Cruz and NASA Ames (Daigle) and Vanderbilt. Volume and pages were not verified.
- **Access and route.** Search summary only. Author-hosted PDFs are reported on c3.ndc.nasa.gov and cs.vuse.vanderbilt.edu; they were not downloaded (section 5).
- **Relevant content (summary only).**
  - A qualitative, event-based approach that automatically generates diagnosers. These determine whether a hybrid system is diagnosable passively or actively.
  - Active diagnosis executes or blocks controllable events.
  - Applied to an electrical power distribution system.
  - Motivated as an alternative to adding sensors.
- **Assumptions.** Not readable. The summaries imply a discrete-event abstraction of the hybrid dynamics, with controllable events.
- **Reuse.**
  - The passive-against-active diagnosability test is the formal counterpart of research question (2).
  - The project cannot command anything from the pit: there is no request path from the pit to the vehicle ([`PROTOCOL.md`](PROTOCOL.md) section 3), and no inbound message may lead to a CAN write ([`../docs/ICD.md`](../docs/ICD.md)).
  - So the only active move is waiting for an uncontrolled event, such as an acceleration transient, that makes the system actively diagnosable in this sense.
- **Candidate contribution (conditional on the full text).**
  - Actions that change the evidence available rather than the trajectory.
  - Byte and latency costs.
  - Continuous-valued measurement models that include timing error.
- **Closest competing baseline.** A passive diagnosability check, plus a fixed rule that waits for a transient (B7).

### S4. Li, Frey, Gauterin (2023): condition monitoring of an electric vehicle's sensors and actuators

- **Citation.** S. Li, M. Frey, F. Gauterin, "Model-Based Condition Monitoring of the Sensors and Actuators of an Electric and Automated Vehicle", Sensors 23(2):887, published 12 January 2023. DOI 10.3390/s23020887. Licence CC BY.
- **Verification.** Title, authors (Karlsruhe Institute of Technology), journal, article number, date, DOI and licence agree across search summaries citing PMC (PMC9861315) and the KIT library record 1000154511. Not checked on mdpi.com (refused).
- **Access and route.** Search summary only.
  - A legitimately redistributable published copy was sought with a search restricted to github.com; none was found.
  - CC BY copies exist at PMC and KIT; this review did not use those hosts (section 5).
- **Relevant content (summary only).**
  - A model-based method decides whether a sensor is faulty and reconstructs its signal. It then checks the actuators for abnormal behaviour, using the reconstructed signals.
  - Validated on simulation data from a vehicle model in complex road conditions. The demonstrator covers six sensors and four actuators (two steering, two driving).
  - The summary reports that the output is only normal or abnormal, without classifying the fault type. It also reports that faults can be missed at low speed with a small steering angle.
- **Assumptions.** Not readable. The summaries suggest a validated vehicle model and validation by simulation only.
- **Reuse.** The closest application domain. The low-excitation blind spot reported in the summary agrees with the excitation dependence expected for HT and HL, and supports including the waiting action.
- **Candidate contribution (conditional on the full text).**
  - Attribution among named competing causes, including inter-stream timing error.
  - Explicit abstention.
  - Budgeted retrieval of records.
- **Closest competing baseline.** A model-based residual monitor with sensor reconstruction and a binary output (B1). Adding attribution gives B2.

### S5. Palmer (2018): test design and sensor selection for active fault diagnosis

- **Citation, as given on the reading list.** K. Palmer, "Optimal Selection of Test Designs and Sensor Sets for Active Fault Diagnosis", PhD dissertation, University of Connecticut, 2018. Not confirmed.
- **Verification.** Not confirmed.
  - Searches found a UConn Digital Commons record (digitalcommons.lib.uconn.edu/dissertations/2038). As summarised, its abstract describes a framework that improves fault identifiability through active fault diagnosis and optimal sensor selection and placement, and states simultaneous test design and sensor selection as a mixed-integer nonlinear program. The snippet showed no title, author or date.
  - Related peer-reviewed work by K. A. Palmer with G. M. Bollas was found in search summaries only (see the leads list in section 2).
  - Two further records may be one paper: a 2019 ISA Transactions paper listed under DOI 10.1016/j.isatra.2019.02.034 in an AIChE abstract, and PubMed 30850204 ("Active fault diagnosis for uncertain systems using optimal test designs and detection through classification"). That they are the same was not verified.
- **Access and route.** Search summary only, from standard and extended web searches. opencommons.uconn.edu refused and was not contacted again.
- **Relevant content (summary only).** Offline optimisation of test conditions (inputs) and sensor sets to maximise fault identifiability. The reported outcome is fewer false alarms and fewer missed detections.
- **Assumptions.** Not readable. The summaries imply:
  - a parametric model with fault parameters, and information criteria built from parametric sensitivities;
  - test inputs that can be designed and applied.
- **Reuse.** Score candidate record types offline with an information criterion: for example, Fisher information about b, δ and ΔF for each record type under typical drive cycles. The integer-programming form gives the optimal offline plan, for comparison.
- **Candidate contribution (conditional on the full text).**
  - Choosing records online, after an inconsistency, from the evidence already observed.
  - Byte and latency costs, and abstention.
  - No designed excitation.
- **Closest competing baseline.** An offline optimal acquisition plan chosen by an information criterion, the same for every case (B6).

### S6. Xu, Guo, Wei (2025): selective conformal risk control

- **Citation.** Y. Xu, W. Guo, Z. Wei, "Selective Conformal Risk Control", arXiv:2512.12844, submitted 14 December 2025 (cs.ML).
- **Verification.** Existence, identifier, title, authors, affiliation (New Jersey Institute of Technology) and date agree across search summaries of the arXiv listing. Not checked on arxiv.org (refused).
- **Access and route.** Search summary only, from two standard web searches. No GitHub copy of the paper or code was found. A similarly named repository (SCoRE) implements a different method.
- **Relevant content (summary only).**
  - A two-stage framework. Stage one decides which test inputs are accepted for prediction (selection control); stage two builds calibrated prediction sets for the accepted inputs only (risk control).
  - SCRC-T computes thresholds over the calibration and test samples together, and is reported to give exact finite-sample guarantees.
  - SCRC-I calibrates on the calibration set only, and gives PAC-style guarantees at lower computational cost.
  - Experiments on CIFAR-10 and diabetic-retinopathy detection appear only in third-party summaries and were not verified.
- **Assumptions.** Not readable. Guarantees of this kind usually rest on exchangeable calibration and test data. Adaptive acquisition and temporal dependence violate that assumption (see A10 and A12). Whether the paper treats dependence could not be checked.
- **Reuse.** The two-stage structure (abstain or accept, then output a calibrated set of causes) matches research question (5). A set-valued output fits "the explanations consistent with the evidence".
- **Candidate contribution (conditional on the full text).**
  - Calibration that stays valid when the evidence is itself chosen adaptively for each case, and when windows are dependent.
  - Linking the decision not to accept a case to an acquisition action, rather than a final refusal.
- **Closest competing baseline.** A selective conformal classifier on the passive evidence that abstains whenever the cause set is not a single cause (B4).

### S7. Buschjäger et al. (2026): temporal misalignment through minimum description length

- **Citation.** S. Buschjäger, M. Frichert, D. Kuhse (spelt "Kuhe" in the authors' BibTeX), J.-J. Chen, "Diagnosing Temporal Misalignment in Multichannel Time-Series Classification with Minimum Description Length", arXiv:2609.14595, submitted 13 September 2026.
- **Verification.**
  - Existence, identifier, authors and date come from search summaries of the arXiv abstract page and listing pages.
  - The title, identifier and authors also appear in the README of the authors' repository, which was read.
  - One summary reports a PDF header reading "... Classification via ..."; not checked. The affiliation was not verified.
- **Access and route.**
  - The paper: search summary only.
  - The authors' code repository was read as text, not executed: `git clone --depth 1` of github.com/sbuschjaeger/mdl-temporal-misalignment, commit `c68392af9ea3`, 21 September 2026. Files read: README and `src/metric.py`.
- **Relevant content (from the repository, not the paper).**
  - README: "The experiments impose temporal delays on one sensor group while keeping the remaining channels fixed." The cost is `alignment_cost_bits(tau) = max_tau gain_bits(tau) - gain_bits(tau)`, which "is an unnormalized codelength in bits, is non-negative by construction, and must be minimized."
  - In `src/metric.py`, for each candidate group G and non-negative integer lag τ, the shifted group is coded in two ways:
    - directly, as the entropy of the first symbol plus the entropy of the within-window differences;
    - through "an anchored rank-``rank`` PCA representation of its unshifted complement", with a non-negative least-squares reconstruction, 16 bits per coefficient by default, and the entropy of the residuals.

    The gain is the difference between the two code lengths.
  - Lines 117-119 standardise each channel by its dataset mean and standard deviation, and quantise to 64 units per standard deviation, before any coding.
  - Labels are optional. The comparison method is a learned synchroniser (SyncNet). The configured datasets include FordChallenge, Opportunity, PAMAP2, UCIActivity, Skoda and two synthetic SyncSine sets.
  - Reported results (summaries only): stable nonzero optima on FordChallenge, Opportunity, PAMAP2 and UCIActivity; accuracy recovered under induced drift.
- **Assumptions (from the code).**
  - An integer, non-negative lag grid on a common sample grid.
  - One group delayed against a fixed complement.
  - Shared low-rank structure between the group and the complement.
  - Channel statistics that hold across the whole dataset.

  An inference from lines 117-119, not a claim made by the authors: a constant additive offset on a channel leaves the cost unchanged. The metric therefore neither confuses a constant bias with a lag nor detects one.
- **Reuse.**
  - A label-free lag-scan score for HT on logged streams, for example battery current against acceleration derived from wheel speed, or controller rotor speed against wheel speed.
  - The repository's protocol (impose known delays on one group, then measure recovery) is a template for injecting timing errors.
- **Candidate contribution (conditional on the full paper, which may treat some of this).**
  - Separating HT from HB and HL, rather than only detecting misalignment.
  - Deciding when the data cannot support a lag estimate (low excitation), and which record would make it estimable: a less-decimated export, a transient window, or clock metadata.
  - Sub-sample offsets on non-uniform receive stamps.
- **Closest competing baseline.** A lag scan (MDL cost and plain cross-correlation) on the passive streams, declaring HT when the optimum lag differs from zero by more than a calibrated margin (B3).

### S8. Pattanayak (2026): identifiability-preserving synchronisation for hybrid digital twins

- **Citation.** T. Pattanayak, "Identifiability-preserving synchronization and uncertainty decomposition for hybrid digital twins: a reproducible benchmark", SSRN abstract 7226337, posted 3 August 2026, 18 pages.
- **Verification.**
  - A standard search on the exact title found nothing. An extended search returned the SSRN record (author, date, page count).
  - The same search returned an associated Zenodo record: "LiveTwin: identifiability-preserving synchronization and uncertainty decomposition for hybrid digital twins", record 21308351, v0.1.0, dated 11 July 2026. It is described as code and an evaluation harness, with battery and N-CMAPSS DS01 benchmarks and fixed seeds.
  - Not checked on SSRN (refused). Zenodo was not used (section 5). No GitHub repository was found.
- **Access and route.** Search summary only, from web search (standard, then extended).
- **Relevant content (summary only).**
  - Indirect measurement of hidden health parameters: turbine efficiency, and battery capacity and internal resistance.
  - A benchmark that scores tracking, uncertainty calibration, divergence detection and cause attribution against hidden ground truth, with baselines and fixed seeds.
  - "Licensed adaptation": model-discrepancy signals are projected away from directions that are sensitive to health parameters.
  - An "uncertainty ledger" that adds measured model-form error to the filter posteriors.
  - Reported results:
    - on a battery testbed, a fourfold reduction in health-estimate bias, with 0.93 interval coverage and zero false alarms;
    - on N-CMAPSS, turbine-efficiency tracking at 0.023 to 0.033 percent RMSE.

  From the summary, "synchronization" here appears to mean keeping a twin's state and parameters consistent with the physical asset, not aligning the clocks of data streams. Unconfirmed.
- **Assumptions.** Not readable.
- **Reuse.**
  - The evaluation design: hidden ground truth, attribution scored separately from detection, fixed seeds, explicit accounting for uncertainty.
  - Stopping adaptation from absorbing a health-parameter change has a counterpart here: an estimate of b must not absorb a change in ΔF.
- **Candidate contribution (conditional on the full text).** An explicit inter-stream timing hypothesis, budgeted acquisition of records, and abstention, in vehicle telemetry.
- **Closest competing baseline.** If the code becomes accessible, its attribution pipeline run on the project's simulated data. Otherwise, its benchmark protocol as the evaluation template.

### A1. Trapeznikov, Saligrama (2013): sequential classification under budget constraints

- **Citation.** K. Trapeznikov, V. Saligrama, "Supervised Sequential Classification Under Budget Constraints", Proceedings of the 16th International Conference on Artificial Intelligence and Statistics (AISTATS), PMLR 31:581-589, 2013. proceedings.mlr.press/v31/trapeznikov13a.html.
- **Verification.** From the PDF and the volume metadata file (`_posts/2013-04-29-trapeznikov13a.md`) in the publisher's repository.
- **Access and route.** Full text. github.com/mlresearch/v31 at `b5b261a2dab6`; file `trapeznikov13a.pdf`, SHA-256 `15446c6fdaca315caf7e75976f8b434e29b5300931a1b7cbe56c7f86bc6cf557`.
- **Relevant content.**
  - Abstract: "For each instance, a sensor is first chosen for acquiring measurements and then based on the available information one decides (rejects) to seek more measurements from a new sensor/modality or to terminate by classifying the example based on the available information."
  - Section 2, Eq. 1: system risk R = Σ_k S^k(x^k) R_k(f^k, x^k, y). Rejecting at stage k costs δ^{k+1}; misclassifying costs 1.
  - With a known distribution (Theorem 1, Eq. 7), the optimal stage rule classifies when max_j P(y = j | x^k) > 1 − δ̃^k(x^k), where δ̃^k is the expected cost-to-go, and rejects otherwise.
  - The empirical version learns each rejector as a weighted binary classification (Lemma 2, Eq. 12).
  - Section 2: "The system has K stages, the order of the stages is fixed, and kth stage acquires a kth measurement."
  - Table 2 (p. 588) gives the share of the maximum budget needed to reach a target error, myopic strategy against the proposed one:

    | Dataset | Target error | Myopic | Proposed |
    |---|---|---|---|
    | pima | 0.245 | 41% | 15% |
    | landsat | 0.17 | 56% | 31% |
    | letter | 0.25 | 81% | 51% |
- **Assumptions.**
  - A fixed order of acquisition stages.
  - Training data with every modality and its label.
  - Independent, identically distributed instances.
  - Known per-stage costs.
  - The last stage must classify: there is no final abstention.
- **Reuse.** The cost-to-go rule applies directly: acquire when the expected risk after acquisition, plus the acquisition cost, is below the risk of deciding now. Record types can be ordered as stages by byte cost: uplink summary, buffered window, full-rate export, metadata. The myopic strategy is a ready baseline.
- **Candidate contribution.**
  - A free choice of the next record, not a fixed order.
  - Evidence structured by hypothesis (b, δ, ΔF).
  - A final abstain outcome.
  - Latency as well as bytes.
  - Physically modelled relations instead of learned features.
- **Closest competing baseline.** A fixed-order cascade with learned reject thresholds tuned to the byte budget, and its myopic variant (B8).

### A2. Javdani et al. (2014): active learning for decision making

- **Citation.** S. Javdani, Y. Chen, A. Karbasi, A. Krause, J. A. Bagnell, S. Srinivasa, "Near Optimal Bayesian Active Learning for Decision Making", Proceedings of the 17th AISTATS, PMLR 33:430-438, 2014. proceedings.mlr.press/v33/javdani14.html.
- **Verification.** From the PDF and metadata in the publisher's repository.
- **Access and route.** Full text. github.com/mlresearch/v33 at `b2b9c05b87e5`; file `javdani14.pdf`, SHA-256 `f7e025e4d3f3ec6cd617d84466a45c2e0352b5cc93866bc4ff749229bac82299`.
- **Relevant content.**
  - Abstract: "Instead of minimizing uncertainty per se, we consider a set of overlapping decision regions of these hypotheses. Our goal is to drive uncertainty into a single decision region as quickly as possible."
  - The version space is V(S) = {h ∈ H : ∀(t, o) ∈ S, h(t) = o} (Eq. 1).
  - The Decision Region Determination (DRD) problem (Eq. 2) asks for the policy of least expected cost under which, for every hypothesis, the remaining consistent set lies inside some decision region.
  - Theorem 1 (p. 433): "All consistent hypotheses lie in some decision region if and only if all hyperedges are cut".
  - The greedy Hyperedge Cutting (HEC) policy satisfies C(π_HEC) ≤ (k ln(1/p_min) + 1) C(π*) (Theorem 3).
  - Special cases: Equivalence Class Determination, solved with EC2 (Golovin et al. 2010) when regions are disjoint (k = 2), and Generalized Binary Search.
  - Footnote 2: "while we focus on tests with unit cost, our results generalize to tests with non-uniform costs."
  - Section 6: "our current scheme assumes noise-free observations, where a hypothesis deterministically maps a test to an observation."
  - Results:
    - Section 5.1, MovieLens with 8 regions: on average 6.7 queries for HEC, against 8 for EC2-HEC, 8.5 for GBS-HEC and 10.3 for myopic value of information.
    - Section 5.2: on the robot task myopic value of information "performs essentially the same as HEC", which the authors attribute to the short horizon.
- **Assumptions.**
  - A finite hypothesis set with a prior.
  - Deterministic test outcomes.
  - Known decision regions.
  - Unit or known test costs.
  - Computation exponential in the hyperedge cardinality k.
- **Reuse.**
  - The DRD stopping rule is the formal version of research questions (2), (3) and (5). Stop acquiring when every hypothesis still consistent with the evidence leads to the same diagnostic action. If no affordable test can cut the remaining hyperedges, the hypotheses are indistinguishable with that evidence and the diagnosis should abstain.
  - With noise, hypotheses can be expanded into pairs of hypothesis and noise realisation, as in EC2, at a computational cost.
- **Candidate contribution.**
  - Noisy, continuous-valued tests (telemetry windows) with persistent nuisance.
  - Budgets in bytes and latency rather than numbers of tests.
  - Regions defined by maintenance actions.
  - An explicit abstain outcome when the budget runs out.
  - A demonstration on vehicle telemetry.
- **Closest competing baselines.** EC2 or HEC over a discretised grid of hypotheses (H0, b, δ, ΔF) with byte-weighted costs, and myopic value of information (B10).

### A3. Chen, Hassani, Karbasi, Krause (2015): when greedy information maximisation is near-optimal

- **Citation.** Y. Chen, S. H. Hassani, A. Karbasi, A. Krause, "Sequential Information Maximization: When is Greedy Near-optimal?", Proceedings of the 28th Conference on Learning Theory (COLT), PMLR 40:338-363, 2015.
- **Verification.** From the PDF and metadata in the publisher's repository.
- **Access and route.** Full text. github.com/mlresearch/v40 at `0b4b7e7ef9f2`; file `Chen15b.pdf`, SHA-256 `3f1a9bf62ba0d1f4f7028a019164e24f3dbae344c7e994d13da1a4a746b4a47a`.
- **Relevant content.**
  - Section 1: "Unfortunately, the mutual information criterion violates the adaptive submodularity condition, and hence does not fall into this framework."
  - Section 1 again: "However, in many applications, noise is persistent: Repeating a test is impossible, or will produce identical observations. Experiments, for example, might be systematically biased due to environmental conditions."
  - Definition 1 (p. 6) defines the separability S(W) of a noise channel: the minimum, over pairs of distinct inputs, of the squared total-variation distance between their output distributions.
  - Theorem 2 (p. 7) bounds what the greedy policy collects after k' tests against the optimal policy with k tests: I(π_Greedy[k']; Y) ≥ (I(π_OPT[k]; Y) − δ)(1 − exp(−k' / (kγ max{log n, log(1/δ)}))), with n = |Y| and γ = 7/S_min.
  - Abstract: "if it is too small, then the greedy policy fails to select informative tests."
- **Assumptions.**
  - A finite hypothesis set.
  - Tests whose noise-free outcome is a deterministic function of the hypothesis, passed through a known channel (persistent noise).
  - A budget counted in numbers of tests.
  - A known prior and channel.
- **Reuse.**
  - Supports greedy expected information gain per byte as a baseline, and gives a caution. A battery-current bias is persistent noise in this sense: another window of the same kind reproduces it, so more windows of the same kind are worth less and less.
  - The separability parameter suggests a pre-check. Exclude actions whose outcome distributions are nearly the same under competing hypotheses (for example, any window at steady current, for HB against HT), or replace them with the waiting action.
- **Candidate contribution.**
  - Costs of different kinds (bytes and latency).
  - Hypothesis parameters that mix discrete and continuous values.
  - Abstention.
  - Measured separability for each of the project's record types.
- **Closest competing baseline.** Greedy expected information gain per byte (B9).

### A4. de Kleer, Williams (1987): diagnosing multiple faults

- **Citation.** J. de Kleer, B. C. Williams, "Diagnosing multiple faults", Artificial Intelligence 32:97-130, 1987. Issue number and DOI not verified.
- **Verification.** Journal, volume and pages agree across search summaries of a course copy hosted at Linköping University and of secondary sources.
- **Access and route.** Search summary only, from a standard web search. The course copy was not used: its redistribution status is unclear.
- **Relevant content (summary only).**
  - The paper introduces the General Diagnostic Engine (GDE) for multiple simultaneous faults.
  - The summary attributes to it two statements: further measurements are usually needed to isolate the faulted components, and the best next measurement is the one that, on average, finds the faulted set in the fewest measurements.
  - Secondary sources describe GDE's one-step lookahead as minimising the expected Shannon entropy over candidate diagnoses, and note that it scales poorly when candidates are many.
- **Assumptions.** Not readable. Typically: consistency-based diagnosis over component models, discrete or interval predictions, independent priors on component failure.
- **Reuse.** The consistency-based view fits research question (1): a diagnosis is a set of fault assumptions consistent with the observations, and several may remain. Minimum expected entropy is the classical baseline for research question (3).
- **Candidate contribution (conditional on the full text).**
  - Measurements are record retrievals with byte and latency costs.
  - The observations themselves carry timing uncertainty.
  - Abstention when entropy cannot be reduced within the budget.
- **Closest competing baseline.** One-step minimum expected entropy over candidate diagnoses (B9).

### A5. Frisk, Krysander, Jung (2017) and the Fault Diagnosis Toolbox: structural isolability and sensor placement

- **Citation.**
  - E. Frisk, M. Krysander, D. Jung, "A Toolbox for Analysis and Design of Model Based Diagnosis Systems for Large Scale Models", IFAC World Congress, 2017. DOI 10.1016/j.ifacol.2017.08.504.
  - E. Frisk, Fault Diagnosis Toolbox v0.13, user manual (release file `user-manual_2024-02-22.pdf`).
  - M. Krysander, E. Frisk, "Sensor placement for fault diagnosis", IEEE Transactions on Systems, Man, and Cybernetics, Part A, 38(6):1398-1410, 2008. DOI 10.1109/TSMCA.2008.2003968.
- **Verification.** Citations as the authors give them in the repository README and on the references page of their site repository. DOIs not resolved.
- **Access and route.** Full text of the manual and the README; the IFAC and IEEE papers were not read.
  - `git clone --depth 1` of github.com/faultdiagnosistoolbox/pyfaultdiagnosistoolbox, commit `661b993050fe`, MIT licence.
  - Blobless sparse clone of github.com/faultdiagnosistoolbox/faultdiagnosistoolbox.github.io, commit `e3005e4c725e`: files `_releases/user-manual_2024-02-22.pdf` (SHA-256 `690563b90666611a31a52edb1613be07f49ae1d9c9f9083849c1e6823b88bc31`) and `_pages/references.md`.
- **Relevant content (manual).**
  - Section 5, p. 15: "Here, diagnosability means to analyze which faults that are structurally detectable and structurally isolable."
  - On the isolability matrix: "a non-zero element at position (i, j) means that fault in column j can not be isolated from fault in row i." The analysis can assume derivative, integral or mixed causality.
  - Section 6, test selection: minimal hitting sets over the fault signature matrix, an approximate method, or random-forest selection. Of the exact method: "The above problem has poor complexity properties and can very quickly become intractable".
  - Section 7, pp. 16-17: "Sensor placement, or possible sensor selection, is the task of choosing a set of sensors such that diagnosis specifications are possible to reach. This toolbox implements the methods in [10]". Reference [10] is Krysander and Frisk (2008). Also: "As a principle of the approach, sensors measure single variables among the unknown variables."
  - The manual PDF carries a draft watermark.
- **Assumptions.**
  - Structural, that is generic, analysis: results hold for generic parameter values and state what is possible in principle, not what a given noise level, excitation or sampling achieves.
  - Faults are modelled as variables in specific equations.
  - New sensors enter as new equations, each measuring a single variable.
- **Reuse.**
  - Structural isolability of the project's hypotheses:
    - HB as a fault in the battery-current measurement equation;
    - HL as a fault in the longitudinal force balance;
    - HT as a fault in the equation linking a receive-stamped sample to the true signal. A delay is not a standard structural element, so this modelling choice must be documented.
  - Records not in the uplink play the role of candidate sensors.
  - The toolbox yields the static indiscernibility classes, which say when abstention is unavoidable at any budget.
- **Candidate contribution.**
  - Moving from structural ("possible in principle") to quantitative distinguishability that depends on excitation, on the actual windows.
  - Selecting time windows and resolutions of existing signals, rather than new sensor locations.
  - Choosing online, case by case, after an inconsistency.
- **Closest competing baseline.** Offline structural analysis that labels each inconsistency with its indiscernibility class, and abstains whenever the class has more than one member (B5). A14 is built on this.

### A6. Scott, Findeisen, Braatz, Raimondo (2014): input design for guaranteed fault diagnosis

- **Citation.** J. K. Scott, R. Findeisen, R. D. Braatz, D. M. Raimondo, "Input design for guaranteed fault diagnosis using zonotopes", Automatica 50:1580-1589, 2014. DOI not verified.
- **Verification.** Authors, journal, volume and pages agree across search summaries of the journal's first page and of repository listings.
- **Access and route.** Search summary only, from a standard web search.
- **Relevant content (summary only).**
  - Faults are modelled as discrete switches between linear models, with bounded disturbances and measurement errors.
  - Zonotopes characterise the set of inputs guaranteed to produce outputs consistent with at most one fault scenario.
  - The resulting nonconvex problem is shown to be equivalent to a mixed-integer quadratic program.
- **Assumptions (from the summary).** Bounded (set-membership) uncertainty, linear models, inputs that can be designed.
- **Reuse.** A set-membership consistency test is a guaranteed, non-probabilistic route to research questions (2) and (5): a hypothesis is rejected only when no admissible values of noise, bias and offset explain the data. Its separation condition (consistent with at most one fault scenario) is the deterministic counterpart of the DRD condition in A2. It matches the set-valued reference diagnosis in [`PROTOCOL.md`](PROTOCOL.md) section 5.
- **Candidate contribution (conditional on the full text).** Inputs cannot be designed from the pit. The counterpart is choosing which windows to retrieve, or waiting until the uncontrolled trajectory supplies separating excitation, with a bounded timing error as one more uncertainty.
- **Closest competing baseline.** A set-membership consistency check on the passive evidence, abstaining when more than one hypothesis remains consistent (a variant of B5).

### A7. Li, Mourikis (2014): online temporal calibration

- **Citation.** M. Li, A. I. Mourikis, "Online temporal calibration for camera-IMU systems: Theory and algorithms", International Journal of Robotics Research 33(7):947-964, 2014. DOI not verified.
- **Verification.** Volume, issue and pages agree across a search summary citing the second author's publication list, his BibTeX page and DBLP.
- **Access and route.** Search summary only, from two standard web searches. The author-hosted PDF was not used (section 5).
- **Relevant content (summary only).**
  - The camera-to-IMU time offset is added as a state and estimated with pose, velocity, IMU biases, the camera-to-IMU transform and feature positions.
  - The paper includes an identifiability analysis of the offset.
  - A related patent states, per the summary, that the offset is identifiable except in a small number of degenerate motions.
- **Assumptions.** Not readable; specific to cameras and IMUs.
- **Reuse.**
  - Estimating δ jointly with biases (an augmented state) is the strongest passive competitor to acquisition based on hypotheses. If b, δ and ΔF can be estimated together from the available data with a useful covariance, no acquisition is needed.
  - The identifiability analysis is the template for deriving when HB, HT and HL can be separated.
- **Candidate contribution (conditional on the full text).**
  - An explicit decision on whether the passive data excite the offset enough.
  - When they do not, choosing records that supply excitation or direct timing evidence: PPS records, statistics of receive-time jitter, less-decimated frames.
  - Abstention.
- **Closest competing baseline.** An augmented-state estimator of (b, δ, ΔF) run on the passive evidence, with a model-selection decision and an abstention rule based on the covariance (B2). This is the multiple-hypothesis baseline of [`PROTOCOL.md`](PROTOCOL.md) section 7.

### A8. OpenVINS documentation: online time offset and bias estimation

- **Citation.** OpenVINS project documentation, github.com/rpng/open_vins, documentation sources `docs/*.dox`, commit `69488123ed93` (30 November 2025). GPL-3.0 licence. This is documentation, not a peer-reviewed source. The project's associated papers were not read.
- **Verification.** Read directly.
- **Access and route.** Full text of the documentation sources, from a blobless clone with a sparse checkout of `docs/*.dox`, `ReadMe.md` and `LICENSE`.
- **Relevant content.**
  - `docs/gs-calibration.dox`, lines 19-20: "An IMU requires estimating of additional bias terms and requires highly accurate calibration between the camera and IMU. Additionally small errors in the relative timestamps between the sensors can also degrade performance very quickly in dynamic trajectories."
  - Line 21: the project advocates "the *online* estimation of these extrinsic and time offset parameters".
  - Line 120: "One needs to have at least one translational motion along with two degrees of orientation change for these calibration parameters to be observable". The line cites "Degenerate Motion Analysis for Aided INS With Online Spatial and Temporal Sensor Calibration" (IEEE document 8616792).
  - The README lists "Camera to IMU time offset" among the estimated quantities.
- **Assumptions.** Visual-inertial sensors, a kinematic motion model, sufficient excitation.
- **Reuse.** Practitioner-level confirmation that time offset and biases are estimated together, and that their observability depends on motion. This supports defining "informative operating condition" for the waiting action. For the project that means current transients and longitudinal accelerations, not rotations.
- **Candidate contribution.** As for A7: deciding when the data do not excite the offset enough, and what to acquire instead, in telemetry rather than visual-inertial sensing.
- **Closest competing baseline.** As for A7 (B2).

### A9. Geifman, El-Yaniv (2019): selective prediction with a reject option

- **Citation.** Y. Geifman, R. El-Yaniv, "SelectiveNet: A Deep Neural Network with an Integrated Reject Option", Proceedings of the 36th International Conference on Machine Learning (ICML), PMLR 97:2151-2159, 2019.
- **Verification.** From the PDF and metadata in the publisher's repository.
- **Access and route.** Full text. github.com/mlresearch/v97 at `31ef0a7c93aa`; file `geifman19a/geifman19a.pdf`, SHA-256 `121c044e3fc396f0b274a1bdbbddd1f73f016814ee76a7aed8a6898fb51388f9`.
- **Relevant content.**
  - Section 2: a selective model is a pair (f, g) that returns f(x) when g(x) = 1 and "don't know" when g(x) = 0.
  - Coverage is φ(g) = E_P[g(x)]. Selective risk is R(f, g) = E_P[ℓ(f(x), y) g(x)] / φ(g). Performance is summarised by the risk-coverage curve.
  - Section 5, Table 1 (CIFAR-10): "when the target coverage is 75%, the realized coverage of SR is 64.16% and that of SelectiveNet is 80.17%". The average coverage violation is 3.625% against 11.98%. This motivates calibrating the selection threshold τ after training, on an independent validation set.
- **Assumptions.** Independent, identically distributed data; fixed inputs (no acquisition); coverage calibrated on held-out data from the same distribution.
- **Reuse.**
  - Metric definitions (coverage, selective risk, risk-coverage curve) for research questions (4) and (5). They match "risk at matched coverage" in [`PROTOCOL.md`](PROTOCOL.md) section 8.
  - The gap reported between target and realised coverage argues for setting abstention thresholds on held-out episodes, never on training episodes.
- **Candidate contribution.** Abstention as the last step after acquisition, so that results become risk against coverage at each byte and latency budget: a surface rather than a curve.
- **Closest competing baseline.** Confidence thresholding on the passive classifier, in the style of softmax response (B4).

### A10. Zaffran et al. (2022): adaptive conformal prediction for time series

- **Citation.** M. Zaffran, O. Féron, Y. Goude, J. Josse, A. Dieuleveut, "Adaptive Conformal Predictions for Time Series", Proceedings of the 39th ICML, PMLR 162:25834-25866, 2022.

  Adaptive conformal inference (ACI) itself is I. Gibbs, E. Candès, "Adaptive conformal inference under distribution shift", NeurIPS 2021, as cited in Zaffran et al. It was not read.
- **Verification.** From the PDF and metadata in the publisher's repository.
- **Access and route.** Full text of Zaffran et al. github.com/mlresearch/v162 at `76fcebd56ef1`; file `zaffran22a/zaffran22a.pdf`, SHA-256 `7f908bcc760fd0bd5192ca7d7b255c861136aa7912638171ad58a50a2ec54cad`.
- **Relevant content.**
  - Abstract: conformal prediction "requires exchangeable data, excluding time series".
  - The ACI update (section 2, Eq. 2) is α_{t+1} = α_t + γ(α − 1{y_t ∉ Ĉ_{α_t}(x_t)}).
  - Section 3 cites asymptotic validity (Proposition 4.1 of Gibbs and Candès) and adds: "this guarantee directly stems from the fact that" |(1/T) Σ_t 1{y_t ∉ Ĉ_{α_t}(x_t)} − α| ≤ 2/(γT).
  - Section 2: "Nothing prevents α_t ≤ 0 or α_t ≥ 1"; when α_t ≤ 0 the interval is the whole real line.
  - AR(1) example: coverage of 90% and 92% for γ ∈ {0.01, 0.05}, against 72.6% for γ = 0.
  - Theorem 3.1: in the exchangeable case ACI loses efficiency. AgACI aggregates ACI experts over γ.
  - Section 6, electricity prices: coverage around 88% on weekends and Mondays, and 93% from Tuesday to Friday.
- **Assumptions.** Sequential prediction in which the true outcome is revealed after each step. The guarantee is on miscoverage averaged over time, not conditional on each case.
- **Reuse.**
  - Windows within a run are dependent and drive cycles differ between runs, so H0 thresholds calibrated once can lose coverage.
  - Where ground truth arrives later, ACI-style online adjustment of the nuisance threshold is a cheap remedy.
  - The AR(1) example shows that dependence alone can break naive calibration.
- **Candidate contribution.** In diagnosis the true cause is seldom revealed at once, so the per-step feedback ACI needs is missing. The study needs calibration that works with delayed or partial labels (fault-injection episodes) and with evidence that depends on the acquisition.
- **Closest competing baseline.** Split-conformal residual thresholds recalibrated online with ACI (a variant of B4).

### A11. Barber et al. (2023): conformal prediction beyond exchangeability

- **Citation.** R. F. Barber, E. J. Candès, A. Ramdas, R. J. Tibshirani, "Conformal prediction beyond exchangeability", Annals of Statistics 51(2):816-845, 2023. DOI 10.1214/23-AOS2276; arXiv:2202.13415.
- **Verification.** Journal, volume, issue, pages and DOI from a search summary.
- **Access and route.** Search summary only, from a standard web search. The open-access publisher page and author copies were not used (section 5).
- **Relevant content (summary only).**
  - Weighted quantiles make conformal prediction robust to drift.
  - The coverage gap is bounded by a weighted sum of total-variation distances, between the data sequence and the sequence with the test point swapped for each training point, divided by one plus the sum of the weights.
  - A randomisation technique handles algorithms that do not treat data symmetrically.
- **Assumptions.** Not readable. The usual statement has weights fixed in advance, not chosen from the data; not verified here.
- **Reuse.** Recency-weighted calibration of the H0 thresholds across runs and operating conditions, with a stated, if loose, bound on the coverage gap.
- **Candidate contribution (conditional on the full text).** The bound is stated in distribution distances that cannot be observed. The study can instead report empirical coverage under controlled drift, for example in temperature, state of charge or track.
- **Closest competing baseline.** Weighted split conformal with recency weights (a variant of B4).

### A12. Prinster, Saria, Liu (2023), with Fannjiang et al. (2022): conformal prediction under feedback covariate shift

- **Citation.**
  - D. Prinster, S. Saria, A. Liu, "JAWS-X: Addressing Efficiency Bottlenecks of Conformal Prediction Under Standard and Feedback Covariate Shift", Proceedings of the 40th ICML, PMLR 202:28167-28190, 2023.
  - C. Fannjiang, S. Bates, A. N. Angelopoulos, J. Listgarten, M. I. Jordan, "Conformal prediction under feedback covariate shift for biomolecular design", PNAS 119(43):e2204569119, 2022. PMC9618043.
- **Verification.** Prinster et al. from the PDF and metadata in the publisher's repository. Fannjiang et al. from a search summary.
- **Access and route.**
  - Prinster et al.: full text. github.com/mlresearch/v202 at `3c987f88bec5`; file `prinster23a/prinster23a.pdf`, SHA-256 `352913f90f2d03ab216e5a86371f35f79d07ad2886e8f92a195d6a48d2b1bd17`.
  - Fannjiang et al.: search summary only.
- **Relevant content (Prinster et al.).**
  - Section 2.4, standard covariate shift (Eq. 4): "Crucially, SCS assumes that the test data distribution is independent of the training data".
  - Feedback covariate shift (Eq. 5) is the case "where the marginal distribution of the test inputs may depend on the realization of the training data", with Y given X unchanged.
  - The methods use the likelihood ratio w(x; D) = dP̃_{X;D}(x) / dP_X(x) (section 3).
  - Section 2.5: Fannjiang et al. describe how full conformal prediction for standard covariate shift "loses its formal guarantee under FCS".
  - Table 1, number of model fits: full CP-FCS needs (n+1)·m·|Y|; JAW-FCS needs n; JAW-KLOO and WCV+ need K ≤ n.
  - Eq. 2: jackknife+ guarantees coverage of at least 1 − 2α.
- **Assumptions.** Y given X unchanged; the input density induced by the selection (the likelihood ratio) known or computable; regression.
- **Reuse.** This states formally why calibration fails when the data behind a decision were chosen using the model. In the proposed study the records retrieved depend on the current posterior, so the evidence available at decision time depends on the policy. Two remedies:
  - calibrate the final decision and abstention thresholds on held-out episodes run end to end with the same acquisition policy, treating each episode as one exchangeable unit;
  - use a weighting of this kind where the policy's selection probabilities are known.
- **Candidate contribution.** Diagnosis with discrete causes and a known, deterministic acquisition policy, with calibration at episode level as the practical route.
- **Closest competing baseline.** Weighted split conformal with likelihood-ratio weights (Tibshirani et al. 2019, as described in Prinster et al.). It applies wherever selection probabilities can be written down.

### A13. rosbag_snapshot: buffered pre-event recording

- **Citation.** rosbag_snapshot package, README, github.com/ros/rosbag_snapshot, commit `b7a3d78fb18c` (13 May 2025). Software documentation, not peer reviewed.
- **Verification.** Read directly.
- **Access and route.** Full text of the README, from `git clone --depth 1`.
- **Relevant content.**
  - "It subscribes to topics and maintains a buffer of recent messages like a dash cam."
  - The use case is unexpected events in live testing, where "disk space limits make always running `rosbag record` impracticable", so "users may run snapshot in the background and save data from the recent past to disk as needed."
  - Options:
    - a duration limit per topic (default 30 s) and a memory limit;
    - pausing (freezing) the buffer;
    - a write of selected topics, on trigger;
    - a trigger service that accepts explicit start and stop times;
    - a status topic reporting, per topic, the window's start and stop, delivered and dropped messages, and statistics of message period and stamp age;
    - LZ4 or BZ2 compression.
- **Assumptions.** One host clock for message stamps; triggers from an operator or another node; no cost model and no diagnostic policy.
- **Reuse.**
  - The mechanism the telematics unit needs for "retrieve buffered pre-event windows": a choice of topics and an explicit window.
  - The status record (window bounds, drops, stamp-age statistics) is itself cheap metadata on timing quality, and could be one of the acquisition actions.
  - The STLG log already records every CAN frame with its receive stamp ([`../docs/ICD.md`](../docs/ICD.md)), so in principle the buffer exists. What is missing is selective, budgeted retrieval, and a request path from the pit, which does not exist today ([`PROTOCOL.md`](PROTOCOL.md) section 3).
- **Candidate contribution.** Deciding what to retrieve (which topics, which window, which resolution) from the diagnostic ambiguity, instead of retrieving everything around a trigger.
- **Closest competing baseline.** On every inconsistency, retrieve a fixed pre-event and post-event window of all channels at full rate, like a dash cam (B11). Its byte cost is the reference for budget savings. This corresponds to scheduler C of [`PROTOCOL.md`](PROTOCOL.md) section 7.

### A14. Zhou, Liang (2026, manuscript): verification bounded by diagnosability

- **Citation.** C. Zhou, C. J. Liang, "Diagnosability-Bounded Admissibility Verification for LLM Agents in Industrial Cyber-Physical Systems", manuscript submitted to IEEE Transactions on Industrial Cyber-Physical Systems (status as stated in the README). Code release: github.com/chenxuanzhou/diagnosability-bounded-verification, commit `2dc8d2048095` (14 September 2026).
- **Verification.** Authors, affiliation (University of Technology Sydney) and target journal come from the README only. A search found an IEEE DataPort dataset page for a manuscript of this title, but no preprint or published version.
- **Access and route.** The README and the module docstrings of `src/verifier/*.py`, read in full. The docstrings were extracted by static parsing with Python's `ast` module in isolated mode; no repository code was executed. The paper is not available.
- **Relevant content.**
  - README: "The layer uses the installed sensors and a structural model of the plant to accept, reject or escalate each proposal". It is evaluated on the Tennessee Eastman process and the voraus-AD robot dataset, and uses `faultdiagnosistoolbox` 0.12.5 (A5). The fault hypotheses come from a language-model agent.
  - `src/verifier/conformal.py`, docstring: residuals are standardised by a robust scale taken from a separate nominal block. Then: "the non-conformity score is the max over residuals of the standardised absolute residual. Taking the (1-alpha) empirical quantile of that score gives a single threshold with a distribution-free guarantee on the JOINT false-alarm rate". The decision rule, verbatim:

    ```text
    reject     the claimed fault cannot explain the firing pattern
    accept     it can, and it is the only fault mode that can
    escalate   it can, but so can other fault modes -- the observation
               lies inside a non-singleton indiscernibility class and the
               verifier is provably blind inside it
    ```

  - `src/verifier/annihilators.py`: a procedure that decides, from the structural model and the list of installed sensors alone, whether a colliding class can be separated by a relation over the installed instruments.
  - `src/verifier/residuals_robot.py`: a motor-side drivetrain relation "carries both the friction and the commutation fault of that axis, which is why those two are indiscernible."
- **Assumptions (from the docstrings).** Exchangeable nominal calibration windows; quasi-steady window statistics; structural fault signatures; hypotheses proposed from outside; a fixed set of installed sensors.
- **Reuse.** The closest existing realisation of research questions (1), (2) and (5):
  - hypotheses checked against a residual bank;
  - indiscernibility classes from structural analysis;
  - abstention (escalation) when the class has more than one member;
  - a joint conformal false-alarm threshold.

  Its order of work (structural bound first, then the residual bank, then calibrated thresholds) can be reused with A5.
- **Candidate contribution.** The README and docstrings do not describe acquiring further evidence to split an indiscernibility class, timing-error hypotheses, or budgets: escalation is fixed once the installed sensors are fixed. The study would add a step: from "escalate" to "acquire the record that splits the class, if affordable; then decide or escalate". This is conditional on the manuscript, which was not read and may already contain such an extension.
- **Closest competing baseline.** The static accept, reject or escalate verifier (structural classes plus a joint conformal threshold), applied to the passive evidence (B5). This should be the primary baseline for every abstention claim.

## 4. Implications for this study

### 4.1 Baselines to implement

Rules for every comparison:

- Each baseline sees the same records and the same budgets as the proposed scheduler.
- Results are reported at matched byte and latency budget, and at matched coverage.
- Every baseline's thresholds are calibrated on held-out episodes run end to end with that baseline (A9, A12).

The protocol column names the counterpart in [`PROTOCOL.md`](PROTOCOL.md) section 7, where one exists.

| ID | Baseline | Derived from | Acquisition | Abstention | Protocol counterpart |
|---|---|---|---|---|---|
| B0 | Full-information oracle: all records at full rate, no budget | ceiling | all | as the diagnostic engine | none (add as ceiling) |
| B1 | Passive multi-rate residual detector with adaptive threshold; binary alarm with a fixed fault-signature table | S1, S4 | none | none | aligned residual monitor; R3v |
| B2 | Augmented-state estimator of (b, δ, ΔF) with model selection and an abstention rule based on the covariance | A7, A8 | none | yes | multiple-hypothesis baseline |
| B3 | Lag scan on passive streams (cross-correlation and the MDL cost of S7) | S7 | none | by margin | none (add) |
| B4 | Selective or conformal classifier on passive features: softmax-response threshold, split conformal, weighted conformal, ACI | A9, S6, A10, A11 | none | yes | none (add) |
| B5 | Structural indiscernibility classes plus joint conformal threshold (accept, reject, escalate), and a set-membership variant | A5, A14, A6 | none | yes | reference set-valued diagnosis without acquisition |
| B6 | Static plans at equal budget: offline optimal record set by information criterion or isolability schedule; fixed low rate; fixed high rate; random bursts | S2, S5 | fixed | yes | schedulers A, B, D |
| B7 | Wait-only: no retrieval; wait for a transient above an excitation threshold, then re-test | S3, A8 | wait | yes | none (add) |
| B8 | Fixed-order cascade with learned reject thresholds, and its myopic variant | A1 | ordered | yes | none (add) |
| B9 | Greedy expected information gain per byte (minimum expected entropy) | A3, A4 | adaptive | yes | scheduler E |
| B10 | EC2 or HEC over a discretised hypothesis grid with byte-weighted costs; myopic value of information | A2 | adaptive | yes | none (add; closest algorithmic competitor to scheduler F) |
| B11 | Dash-cam retrieval: fixed pre- and post-event window of all channels at full rate on every inconsistency | A13, patents | fixed | yes | scheduler C |

B2, B5 and B10 are the strongest competitors. Gains over B1 or B6 alone would not support research question (4).

### 4.2 Claims that must not be made

1. That the study is the first to select measurements or tests to discriminate between candidate diagnoses, or to stop when the remaining candidates imply a single decision (A4, A2, S3, S5, A6).
2. That it is the first to combine acquisition budgets with a reject option (A1).
3. That it is the first to abstain when structural or statistical evidence cannot separate fault modes (A14, A5, A9, S6).
4. That it is the first to detect temporal misalignment between sensor streams from data (S7), or to estimate time offsets jointly with sensor biases (A7, A8).
5. That buffered pre-event capture, or upload of telemetry on a trigger, is new (A13; the vehicle diagnostic patents in the leads list).
6. That S1 to S8, A4, A6, A7 or A11 lack a feature, assume a condition or report a result beyond what their summaries say. Those papers were not read.
7. Distribution-free coverage or false-alarm guarantees for decisions made after adaptive acquisition or on dependent windows, unless calibration is done per episode with the deployed policy, or with a weighting under a known selection mechanism (A10, A12).

   The joint false-alarm guarantee described in A14 applies to a fixed residual bank on nominal data. It does not carry over to evidence acquired adaptively.
8. Approximation guarantees for HEC, EC2 or greedy information gain on this problem, unless their assumptions hold. A2's analysis assumes noise-free tests with unit or known cost; A3's bound needs channel separability and persistent noise modelled explicitly.
9. That HT is identifiable against HB and HL in general. A7 and A8 both tie observability of the offset to excitation. Separability must be shown for the project's signals and operating conditions, and stated as conditional on them.
10. Vehicle-level results. The vehicle firmware is not written ([`../docs/TELEMETRY_INTEGRATION.md`](../docs/TELEMETRY_INTEGRATION.md)), so results from the host simulation must be reported as host simulation.

### 4.3 Overlap risk

| Research component | Closest prior art | Overlap risk |
|---|---|---|
| (1) competing explanations | A4 (consistency-based diagnosis); A14 (accept, reject, escalate); S8 (cause attribution, summary only) | high |
| (2) which explanations are distinguishable | A5 (structural isolability); A14 (indiscernibility classes); A2 (DRD condition); A6 (separation); S3 (passive and active diagnosability) | high |
| (3) choosing records under budget | A1, A2, A3, A4 (test selection); S2 (scheduling); S5 (offline test and sensor selection); unverified Sensors 2026 lead | high for the method class; moderate for the concrete actions (retrospective buffered windows, clock metadata, decimation level, waiting) |
| HT as a competing hypothesis | S7 (MDL lag detection); A7, A8 (offset estimation with biases); S1 (assumptions unknown) | moderate |
| (4) improvement over strong baselines | depends on results against B2, B5 and B10 | not assessable before results |
| (5) abstention | A9, S6, A10, A14 | high for the mechanism; moderate for abstaining after the budget is exhausted |

**Overall.**

- **As a method class, the contribution already exists.** Choosing measurements by ambiguity, under a budget, with abstention, is established prior art, from GDE-style next-measurement selection (A4) through decision-region determination (A2) to budgeted reject cascades (A1).
- **As a static combination, the closest work is A14.** It combines structural indiscernibility, conformal calibration and escalation, but only its code was read.
- **The full combination was not found.** No source was found that retrieves buffered telemetry records under byte and latency budgets to separate a current-sensor bias, an inter-stream timing error and a load change, with calibrated abstention. That search was not exhaustive.
- **Risk level.** High for any claim of method novelty; moderate for an applied, experimentally demonstrated systems contribution.
- **Single largest risks.** The unread A14 manuscript and the unverified Sensors 2026 lead.

### 4.4 Suggested narrowed claim

Suggested wording, to be revised after the sources in section 4.6 are read:

> On an electric-vehicle telemetry chain whose controller and telemetry unit keep separate clocks, the study shows experimentally that choosing among concrete telemetry records by expected reduction in diagnostic ambiguity, per byte and per unit of latency, separates a battery-current bias, an inter-stream timing error and a change in opposing force more often than baselines B1 to B11 at equal budget. The records are buffered pre-event windows, future windows, clock-synchronisation metadata, less-decimated channel exports, and waiting for an informative operating condition. Selective risk stays at a calibrated level, and the method abstains when no affordable record can split the remaining hypotheses. The experiments use host simulation with injected faults, then bench data where available.

**Systems contribution.**

- An open implementation on the project's STLG log and uplink.
- A fault-injection benchmark with fixed seeds and the evidence-acquisition actions defined.
- Implementations of the baselines in section 4.1.
- Calibration at episode level for the acquisition policy.

### 4.5 Engineering note on the hypotheses (project analysis, not taken from any source)

These points come from the project's own model and documents, not from the literature. They are hypotheses for the identifiability gate in [`PROTOCOL.md`](PROTOCOL.md) section 5 to confirm or reject.

- **Where timing comes from.** The controller's CAN frames carry no source time except the supervisor's `src_time_ms` ([`../docs/TELEMETRY_INTEGRATION.md`](../docs/TELEMETRY_INTEGRATION.md) section 2). The timing of controller signals relative to the telemetry unit's own sensors (wheel windows, IMU, GNSS) therefore rests on receive stamps. HT is a property of that path.
- **Bias against timing error.** Write the battery current as seen by the diagnosis as i_meas(t) = i(t − δ) + b + n(t). For small δ, i(t − δ) ≈ i(t) − δ di/dt. A bias adds a constant; a timing error adds a term proportional to di/dt.
  - At steady current, HB and HT cannot be separated from this channel, and δ is not observable at all.
  - Windows with current transients, or direct timing evidence (PPS records, receive-stamp statistics), are what separate them.
- **Load change against bias.** A larger opposing force changes the longitudinal balance between force, acceleration and speed, and raises battery and phase currents together. [`PROTOCOL.md`](PROTOCOL.md) section 3 notes that the DC-meter-against-phase-current relationship stays consistent under HL for this reason. A bias in the bus meter shows in the battery current and in power and energy computed from it, but not in the phase currents.
  - The relationship between battery current and phase-current power is therefore informative for HB against HL.
  - The relationship between force and acceleration (wheel speed, IMU) is informative for HL against H0.
- **Candidate informative records** (hypotheses for the study to test):
  - pre-event buffer windows that contain a transient;
  - PPS and receive-stamp metadata;
  - full-rate `ctrl_currents` and `ctrl_motion` frames, instead of the 2 Hz summary;
  - full-rate wheel and IMU windows.

### 4.6 Access gaps to close before any novelty claim is drafted

In order of overlap risk:

1. **A14 manuscript.** Request it from the authors, or wait for publication.
2. **Sensors 2026 lead** (reported DOI 10.3390/s26165065). Confirm that it exists, then read it; if it is in MDPI Sensors it is likely CC BY.
3. **S7 full paper.** Check whether it treats bias against lag, and low excitation.
4. **S8 paper and the LiveTwin code.**
5. **S4 full text** (CC BY copies at PMC and KIT).
6. **S3, S5, S2 and S1.**
   - S3: author copies at NASA DASHlink or Vanderbilt.
   - S5: the UConn record.
   - S2: library access, plus the HAL precursor and thesis.
   - S1: library access.
7. **S6 full text.**
8. **Also to read:**
   - A7 (author copy);
   - A11 (open access at the publisher);
   - A4;
   - A6;
   - the degenerate-motion analysis cited by A8.
9. **Direct database searches** of arXiv, Crossref and Semantic Scholar, once access allows. Search for combinations of:
   - "active diagnosis" with "time offset";
   - "clock synchronization" with "fault isolation";
   - "budget" with "diagnosis" and "abstain".

## 5. Method record

- **Dates.** Searches and reading on 17 October 2026.
- **Routes.**
  - Web search, standard mode first and extended mode when a standard result was thin.
  - `git clone --depth 1` of public GitHub repositories that are legitimately redistributable: the authors' own repositories, and the publisher's own PMLR repositories. Large publisher repositories were cloned without file contents (blobless), with a sparse checkout of the needed files.
  - `pdftotext -layout` for PDFs.
- **What was not run.** Nothing from a download was executed. Python source in the A14 repository was read by static parsing only.
- **Hosts that could not be reached.** The review's network refused these hosts, and no mirror, cache or alternative route to them was used: arxiv.org, export.arxiv.org, api.crossref.org, api.openalex.org, mdpi.com, doi.org, papers.ssrn.com, opencommons.uconn.edu, api.semanticscholar.org.
- **Hosts not used.** Access was limited to web search and public GitHub repositories (the authors' own and the publisher's own), so these were not used either: PMC, the KIT repository, NASA DASHlink, Vanderbilt, HAL, Zenodo, author home pages. They are the first places to look when closing the gaps in section 4.6.
- **Git LFS.** No repository read needed Git LFS.
- **Files.** Downloaded papers and extracted text are not committed. Each entry gives the commit and SHA-256 of the file read, so the same file can be obtained and checked.
