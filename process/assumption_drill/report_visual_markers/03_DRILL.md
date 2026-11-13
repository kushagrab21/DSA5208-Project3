# Drill: why the report looks dense, and what human reports do instead

**Question:** our report looks very dense on screen. How do human-written documents of this kind keep dense technical
content readable? Which visual devices do they use, and which do they avoid? Is the fix emphasis at all, or structure and
layout?

**Short answer:** the problem is structure and layout, not emphasis. On emphasis our report already matches the human
documents: no bold in running text, and italics only for defined terms. It differs in five ways:
- its text blocks are larger;
- its paragraph breaks are the weakest of any document in the set;
- its lines are longer than in the grader's own papers;
- it sets almost no formulas on their own line;
- one section runs 37 lines with no entry point.

None of the seven human documents adds marks to make results stand out. Instead they make each block of text smaller
and make its edges visible.

## How this was done

- **Rendering.** Pages were rendered with `pdftoppm -r 60` into `/Users/kushagra/.claude/jobs/99011104/tmp/vis/` and
  viewed. For each source I looked at both method pages and results pages. Our report was viewed on all of pages 1-25.
  Two crops of our pages 7 and 9 were rendered at 90 dpi to check how visible the paragraph breaks are.
- **Counting.** A rendered page cannot show which font is bold or how long a line is, so I counted with PyMuPDF over the
  same pages (scripts in `tmp/scripts/`). The counts were:
  - bold and italic spans in body-size text, with maths fonts and caption labels excluded;
  - run-in heads;
  - prose lines and paragraph lengths (a break is a vertical gap, a first-line indent or a short last line);
  - characters per line;
  - numbers per 100 words of results prose;
  - the page of each float against the page of its first mention;
  - prose lines between headings.
- **Comparing paragraph lengths.** Line widths differ between documents, so paragraph lengths are also given "at 108
  characters per line": the length a block of that size would have on our page.
- **Measuring page cost.** I compiled a scratch copy of the current `.tex` with tectonic in `tmp/compile/report/`, with
  the code appendix left out. It has the same page count to References as the PDF (25 pages). Nothing in the project
  was edited.
- **Ignored.** The red "waiting for cluster data" boxes and the orange "To write once the cluster runs are in" boxes are
  temporary, so I left them out of every judgement.

## 1. Per-source observations

### Emphasis and other marks

"Pages looked at" are the rendered pages I viewed. The counts also cover a few more pages that were measured only.

| Source | Pages looked at | Bold in running text | Italic in running text | Run-in heads | Boxes or shading | Lists | Numbered findings |
|---|---|---|---|---|---|---|---|
| Chen & Jablonowski 2024 (grader; Elsevier preprint, 12 pt) | 1, 3, 6, 10, 12, 15, 18 | none | none (subsection titles such as "3.1. Grids on a Sphere" are italic, on their own line) | none | none | none | none |
| Chen & Krasny 2025 (grader; SIAM, 10 pt) | 1, 3, 5, 9, 14, 17, 20 | none | none | bold run-in subsection heads ("9.5. Parallel runtime.") and bold paragraph labels ("Cluster-particle interaction.", "Cluster-cluster interaction." p9; "Gaussian vortex." p20), 1-2 per page. All are noun-phrase labels, never claims | none (pseudocode on pp11-12 only) | none | none |
| Heroux & Dongarra 2013 (Sandia, Word, 12 pt) | 7, 8, 10, 15 | only as labels opening list items: "Problem setup:" (p9), "Neighborhood collective:", "All-reduce collective:" (pp15-16). **p10 has five bold claim phrases opening list items** ("Rewards investment in high-performance collectives:"), the one human example of a bold lead-in. Reported only; the user has ruled this device out | math variables only | labels in lists only | none | numbered lists on most pages: p8 (2 requirements), pp9-10 (5 steps with a-d sub-items), p10 (5 reasons), p15 (4 operations per iteration), pp15-16 (2 communication patterns) | none |
| UMBC 2020, Poisson blocking/non-blocking | 1, 2, 3, 4, 6, 7 | none | none | none | none | none | yes: "(1) ... (2) ..." open two paragraphs of conclusions in the introduction (p2) |
| UMBC 2019, Poisson on taki | 1, 6, 9, 13 | none | none | none (unnumbered subsection headings) | none | none | none |
| UMBC REU 2014 | 2, 6, 8, 14 | rare: acronym letters set in bold ("FLoating-point OPerations", p2), and a bold label in table captions ("Poisson Test Problem:") | none | none | none | none | none |
| RPI student report 2020 (acmart, two columns) | 1, 3, 6, 8 | bold run-in subsubsection heads ("3.1.1 Matrix-vector Multiplication.", "3.3.3 Writing Final Result."), 1-2 per page | defined terms and tool names ("Compressed Row Storage", "GProf", "NVProf"), about 1 per page | as in the bold column | none | numbered: the three kernels (p3) and two output options (p6) | none |
| Lecture 12 slides (pp37-39) | 37 | n/a: these are slides with ▶ bullets | | | | | |

**On the slides:** they ask for plots that "effectively convey information" with log axes, defined terminology, and a
report that "has to make sense". They say nothing about layout or emphasis.

### Layout

| Source | Characters per line | Text block, share of page width | Paragraph cue | Paragraph length in lines: median / p90 (at 108 chars) | Displayed equations | Floats against their discussion | Lines between headings | Numbers per 100 words of results prose |
|---|---|---|---|---|---|---|---|---|
| Chen & Jablonowski 2024 | 76 | 64 % | first-line indent | 4.5 / 13 (3.2 / 9.1) | many on method pages (7 on p3); about 0-3 on results pages (eq. 28 on p12 defines the error) | at the top of a page, 0-1 pages after the mention ("The parallel performance results are presented in Fig. 3", p10) | 8-30, subsections short | 3.1 |
| Chen & Krasny 2025 | 81 | 60 % | indent | 4 / 10 (3.0 / 7.5) | very many (7 on p9, 4 on p5); a one-line error definition is displayed as (9.1) on p14 | on the same or the facing page; most results subsections open with "Figure N plots ..." | 10-20 per subsection | 7.2 |
| Heroux & Dongarra 2013 | 91 | 76 % | full blank line, no indent | 3 / 6 (2.5 / 5.1) | none (inline only, Word) | no figures in the body | 15-30 | 2.4 |
| UMBC 2020 | 114 | 84 % | indent | 6 / 12 (6.3 / 12.7) | setup only (3 on p3), none in results | Fig 1.1 at the top of p2 near its mention; Table 4.1 on its own page after the text (p7) | 25-60 | 7.3 |
| UMBC 2019 | 113 | 84 % | indent | 8.5 / 15 (8.9 / 15.7) | setup only | tables and figures together on their own page (p9) | 30-60 | 6.8 |
| UMBC REU 2014 | 123 | 88 % | indent | 6 / 11 (6.8 / 12.5) | few | p8 is a full page of results text; its tables come on later pages | 15-50 (node, GPU and software each get a subsection, 2.1-2.3) | 8.3 |
| RPI student 2020 | 59 (per column) | two columns | indent | 4 / 12 column lines (2.2 / 6.6) | many (about 5 on p3) | interleaved in the columns, 0-1 pages away | 8-20 column lines | 4.4 |

**Paragraph cue is the one point where every source agrees.** All seven mark the start of a paragraph clearly. The six
LaTeX documents use a first-line indent, and the Word report uses a full blank line.

**What none of them uses:**
- bold or italic on a result or a number;
- shaded or boxed key results, or a takeaway box;
- underlining;
- colour in the text;
- bulleted lists with bold sentence heads, except Sandia p10.

Run-in heads and list labels are always short noun phrases, apart from that same Sandia page.

## 2. Our report, pages 1-25 (PDF of 13 Nov, 11:18)

- **Typesetting.** 10 pt Latin Modern on A4, with 2.2 cm margins and `\linespread{1.06}`. Section headings are sans-serif
  bold. Paragraphs are set with `\parskip` 3 pt and no indent (preamble lines 7, 8 and 21).
- **Line length.** About 108 characters per line (pages 2, 9, 14 and 21). The text block is 79 % of the page width.
- **Paragraph cue.** The gap between paragraphs is 3 pt, about a quarter of a line, and there is no indent. At 90 dpi
  the breaks on pp7 and 9 are only just visible. When a paragraph's last line is nearly full, the break disappears.
- **Paragraph length.** Of the 93 paragraphs of two or more lines, the median is 6 lines and the 90th percentile 10. Six
  paragraphs run to 12 lines or more:
  - the Summary, 15 lines (p1);
  - the first paragraph of Section 4, 18 lines (p7);
  - the first results paragraph of Section 5, 13 lines (p9);
  - Section 8.6, 13 lines (p20);
  - Section 8.7, 14 lines (p21);
  - Section 8.9, 12 lines (p24).

  This is the same as the UMBC student reports and about twice the grader's own papers, whose median is 3 lines and 90th
  percentile 7.5-9 at our line width.
- **Lines between headings.** Most sections have 11-25 prose lines between headings. The exceptions are:
  - Section 3, 44 lines, though it already has five italic run-in heads;
  - Section 4, 37 lines with no heading, run-in head or float (the whole of p7);
  - Section 5, 33 lines (28 of them unbroken on p9);
  - Section 2.5, about 30 lines;
  - Sections 8.6 and 8.7, 25-27 lines each.
- **Bold in running text.** There is none, apart from the "Summary" run-in and the G1-G3 item labels in Section 8.4.
- **Italic in running text.** There are 18 uses of `\emph`. Twelve are defined terms through `\term`, about one per page,
  the same as the RPI report. Six are run-in heads: five in Section 3 and "Limitations." in Section 9. Three of the
  Section 3 heads are claims, not labels:
  - "Parallel runs equal the serial run (V3, V4)."
  - "The tests detect errors in the halo exchange."
  - "How accurate pipelined CG can be."
- **Boxes.** There are two ruled algorithm boxes (pp2 and 4) and no other boxes, apart from the temporary ones.
- **Lists.** There are two itemize lists: the three exchange methods (Section 8.3) and G1-G3 (Section 8.4).
- **Displayed and inline maths.** Pages 1-25 have 4 displayed equations: the stencil (p1), u(x) (p2), T_mem (p4) and
  eq. (1) (p17). There are about 225 inline maths segments. Long formulas sit inline in the prose:
  - κ = cot²(πh/2) ≈ (2(n+1)/π)² (Section 1.2, p2);
  - ρ = ‖b−Ax‖/‖b‖ and ‖x_p−x_s‖/‖x_s‖ ≤ κ(ρ_p+ρ_s)/(1−κρ_s) (Section 3, V5, p6);
  - (x_c)_v = ((b_c)_v + Σ_{u∼v}(x_c)_u)/(d_v+a), the spectrum [a, λ_max+a], λ_max ≤ 2d_max and the condition bound
    (2d_max+a)/a (Section 8.2, p17);
  - span{b_c, (L+aI)b_c, …, (L+aI)^{k−1}b_c} (Section 8.2, p18).
- **Floats.** All figures and tables use `[H]`, so each sits 0-1 pages from its first mention. Six of the 12 figures are
  never referenced in the text:
  - Figs 3, 4 and 5 (strong scaling, weak scaling, efficiency);
  - Fig 7 (layouts);
  - Figs 10 and 11 (graph strong scaling, graph communication).

  Tables 18 and 19 are not referenced either. `[H]` also leaves part-empty pages (p7 bottom, p10, p22), which will change
  once the data arrive.
- **Numbers in the prose.** Results prose (pp9, 11, 12, 14, 19, 20, 21 and 24) has 8.5 numbers per 100 words. This is
  the top of the human range (REU 8.3, UMBC 6.8-7.3, Chen & Krasny 7.2, RPI 4.4, Chen & Jablonowski 3.1, Sandia 2.4).
  Most come as 2D/3D pairs, often with units or powers of ten. Method prose (pp2, 3, 4, 7) has 3.5.

**Where our pages differ from the human ones:**
1. The paragraph cue is the weakest in the set.
2. Text blocks are about twice the size of the grader's.
3. Lines are 108 characters against his 76-81.
4. Long formulas are inline where his papers display them.
5. Section 4 is one 37-line run.
6. The number density is high, though still within the genre.

Emphasis is not on this list.

## 3. Chains

Each chain runs: the device in a human source → why it works there → the condition it depends on → whether that holds
for the grader reading on screen as one of many → what we do.

**A. Visible paragraph breaks.**
- **Source:** all seven sources. Six indent the first line (Chen & Jablonowski p10, Chen & Krasny p17, UMBC 2020 p6,
  REU p8, RPI p6). Sandia leaves a blank line (p7).
- **Why it works:** the eye sees where one point ends before reading it, so a 30-line run reads as three or four blocks.
- **Condition:** the paragraphs are already one point each. The earlier language pass set "one paragraph per finding".
- **Holds?** Yes. On screen the 3 pt gap almost disappears.
- **So:** strengthen the cue (recommendation 1).

**B. Shorter lines.**
- **Source:** Chen & Jablonowski (76 characters, 64 % of the width), Chen & Krasny (81, 60 %) and Sandia (91, 76 %).
- **Why it works:** a shorter line is easier to track back to the next line, and the wider margin frames each block.
- **Condition:** the reader's habit and the page budget. The UMBC and REU reports run 113-123 characters and look as dense
  as ours, so the genre tolerates long lines. The grader's own writing does not use them.
- **Holds?** Partly. No page limit was given (earlier frame). Cost in the scratch build: margins of 2.8 cm give 98
  characters and 27 pages to References (+2). 11 pt with 2.5 cm gives 92 characters and 30 pages (+5).
- **So:** offer the 2.8 cm option (recommendation 4). It is ranked below the cheaper local fixes because it costs pages
  and the genre evidence is split.

**C. Long formulas on their own line.**
- **Source:** Chen & Krasny p9 (7 displays), p5 (4), p14 (a one-line error definition displayed as 9.1); Chen &
  Jablonowski p3 (7) and p12 (eq. 28 defines the error); RPI p3; UMBC 2020 p3 (the setup).
- **Why it works:** a formula with fractions, norms or sums interrupts reading when it sits inline. Displayed, it
  becomes an anchor, and the prose either side becomes two shorter blocks.
- **Condition:** the formula is long, or it is a definition or bound that a later sentence uses. The human reports keep
  short relations inline: both UMBC 2019 and the REU report write S_p = T_1/T_p in the running text.
- **Holds?** Yes for the four long formulas listed in Section 2. No for the short S and E definitions on p10.
- **So:** display the long ones and leave S and E inline (recommendation 2).

**D. Entry points in a long section.**
- **Source:**
  - REU pp2-3 gives the same content as our Section 4 three subsections (2.1 Node Architecture, 2.2 GPU Architecture,
    2.3 Software Specification);
  - Chen & Krasny p9 and p20 and RPI pp3-6 use short run-in labels for parallel sub-topics;
  - our own Section 3 already uses italic run-in heads.
- **Why it works:** the reader looking for one fact (how times were measured, which GPU) jumps to its label.
- **Condition:** the paragraphs are separate items to look up, not steps in one argument, and every human label is a
  noun phrase, not a claim.
- **Holds?** Yes for Section 4, which holds the hardware, compilers, timing and repeats. No for Section 5, whose
  paragraphs are one argument with topic sentences that already lead.
- **So:** add labels at the topic changes in Section 4, and turn the three claim-style heads in Section 3 into labels
  (recommendation 3). Keep them italic. Bold would bring back the rejected look.

**E. Showing a count the prose already makes.**
- **Source:**
  - Sandia p15: "Each PCG iteration requires these basic operations: 1. ... 4.";
  - Sandia pp15-16: "The key communication patterns in PCG are: 1. Neighborhood collective ... 2. All-reduce
    collective". This is the same content as our Discussion paragraph 1;
  - RPI p3: the three kernels as a numbered list;
  - UMBC 2020 p2: "(1)", "(2)".
- **Why it works:** parallel items that the reader checks against a slide can be ticked off.
- **Condition:**
  - the items are parallel and a sentence or two each;
  - the reader matches them to his own list (Lecture 9's four MPI+OpenMP questions, and grading item 5: "how different
    parts of the problem were parallelized using different techniques, which parts need the most communication");
  - the items have no bold heads.
- **Holds?** Yes for Section 7 (p15) and Section 9 paragraph 1 (p25).
- **So:** recommendation 5.

**F. Pointing from prose to plot.**
- **Source:** Chen & Krasny p14 ("Figure 5 plots ...", "Figure 7 plots ..."), p17 ("Figure 9 plots the parallel
  runtime ..."); Chen & Jablonowski p10 ("presented in Fig. 3").
- **Why it works:** the reader knows which plot a paragraph is reading.
- **Condition:** the figures carry graded content. Figs 3-5 are the speedup and efficiency plots that the grading slide
  asks for.
- **Holds?** Yes. Being next to the text (`[H]`) is not the same as being referred to.
- **So:** recommendation 6. This helps orientation more than it reduces density.

**Dropped:**
- **Bold or italic on results or numbers.** Zero uses in the seven sources, so this changes nothing in the right
  direction.
- **Boxes and shading.** None in the sources apart from pseudocode, and the user has ruled them out.
- **Bold lead-in phrases.** The only precedent is Sandia p10. Reported above, not recommended.
- **Underlining.** None in the sources, and ruled out.
- **Numbered findings in the Summary** (UMBC 2020 p2). Their function is close to the rejected key-results box, and the
  Summary will be rewritten when the data arrive. See Section 5.
- **Table reading guides** (UMBC: "Reading along the first column ..."). They add content, and the language pass
  covers them.
- **Tables on their own pages** (UMBC). This would move tables away from their text, and our `[H]` adjacency is better
  on screen.
- **Two columns** (RPI). Too large a change.
- **More subsections everywhere.** Our 11-25 lines between headings already matches Chen & Krasny's 10-20 at his line
  width. Only Section 4 is an outlier.
- **Fewer italic terms.** We are at the RPI rate, and the grader asks for defined terms.
- **Changing the number density.** It is already set by the earlier language pass (assumption 6), and this drill may
  not remove generated numbers.

## 4. Recommendations, ranked

Each is cheap by hand in LaTeX, adds no claims or numbers, and leaves every `\val{}` in place.

**1. Make paragraph breaks visible.**
- **Change:** in preamble line 21, raise `\parskip` from 3 pt to half a line (`0.5\baselineskip`, about 6 pt), keeping
  no indent. The alternative is the grader's own convention, `\parindent` 1.2-1.5 em with `\parskip` 0.
- **Sources:** all seven: indent in Chen & Jablonowski p10, Chen & Krasny p17, UMBC 2020 p6, REU p8 and RPI p6; a blank
  line in Sandia p7.
- **Where:** the whole report. Most visible on p7 (Section 4), p9 (Section 5), pp20-21 (Sections 8.6-8.7) and p24
  (Section 8.9).
- **Effect:** each text page reads as 3-6 blocks instead of one slab. The scratch build keeps 25 pages to References
  with the half-line skip, because the extra space fills `[H]` gaps. With the indent it is 24 pages.
- **Check after the change:** the spacing in the two lists and the algorithm boxes.

**2. Display the long inline formulas, and leave short relations inline.**
- **Change:** move four formulas from inline to `\[ \]`. Number one only where it is referred to.
  - κ = cot²(πh/2) ≈ (2(n+1)/π)² (Section 1.2, p2);
  - the V5 bound ‖x_p−x_s‖/‖x_s‖ ≤ κ(ρ_p+ρ_s)/(1−κρ_s), with ρ (Section 3, p6);
  - row v of eq. (1), (x_c)_v = ((b_c)_v + Σ(x_c)_u)/(d_v+a), and the condition bound (2d_max+a)/a (Section 8.2, p17);
  - the Krylov span (Section 8.2, p18).
- **Leave inline:** S, E (p10) and short relations such as √κ ∝ n. UMBC 2019 and the REU report write these inline.
- **Sources:** Chen & Krasny pp5, 9, 14; Chen & Jablonowski pp3, 12; RPI p3; UMBC 2020 p3.
- **Effect:** four of the heaviest prose blocks (7-10 lines each) split around an anchor, and the lines with stacked
  fractions leave the prose. The report gains about 10-15 lines.

**3. Give Section 4 entry points, and turn Section 3's claim heads into labels.**
- **Change in Section 4:** split the 18-line first paragraph at "A GPU node, named ...". Then put the report's own italic
  run-in labels at the 3-4 topic changes, for example "The nodes.", "The GPU node.", "Compilers.", "Timing and
  repeats." Label only the topic changes, not every paragraph.
- **Change in Section 3:** rephrase the three claim heads as labels, for example "Parallel against serial runs (V3,
  V4).", "Broken halo exchanges.", "Accuracy of pipelined CG beyond the tests." The claims stay in the paragraph
  bodies.
- **Sources:** REU pp2-3 (the same content as subsections 2.1-2.3); Chen & Krasny p9 and p20; RPI pp3-6. Every human
  label is a noun phrase.
- **Where:** p7 (Section 4) and pp5-6 (Section 3).
- **Effect:** the densest page (37 lines in one run, with an 18-line paragraph) becomes 4 labelled blocks of 10 lines or
  fewer. The grader's "how was it measured" becomes findable. Section 3 loses the one device that resembles the
  rejected lead-in sentence.

**4. Shorten the line (optional, costs pages).**
- **Change:** in preamble line 8, change `margin=2.2cm` to `margin=2.8cm`.
- **Sources:** Chen & Jablonowski (76 characters, 64 % of the width), Chen & Krasny (81, 60 %), Sandia (91, 76 %). Against
  it: UMBC and REU (113-123 characters).
- **Where:** the whole report.
- **Effect:** lines go from 108 to 98 characters, and the text block from 79 % to about 71 % of the width. The scratch
  build reaches References on p27 instead of p25. (11 pt with 2.5 cm margins gives 92 characters but 30 pages.)
- **When:** after the data are in, because the reflow moves every `[H]` float.

**5. Show the counts the prose already makes, as plain numbered items.**
- **Change:** use full sentences, no bold heads, and tight spacing (`enumitem` is already loaded).
  - Section 7 (p15): mark Lecture 9's four questions (1)-(4) in the existing sentences, or set them as a 4-item
    `enumerate`.
  - Section 9, paragraph 1 (p25): set the parts and their techniques as a 3-item list: stencil and vector updates, inner
    products, halo exchange. Keep the GPU sentence after the list.
- **Sources:** Sandia p15 (operations per iteration) and pp15-16 (communication patterns, the same content as our
  Discussion); RPI p3; UMBC 2020 p2.
- **Effect:** two 7-8-line paragraphs become short items that the grader can tick off against Lecture 9 and grading
  item 5. The report gains about 2-4 lines each.

**6. Point to every figure and table from the paragraph that reads it.**
- **Change:** add a `(Figure~\ref{...})` reference where each is discussed:
  - Fig 3 (Section 6.1, p11);
  - Fig 4 (Section 6.2, p12);
  - Fig 5 (Sections 6.1-6.2, p13);
  - Fig 7 (Section 7, p16);
  - Figs 10 and 11 (Section 8.8, pp22-23);
  - Tables 18 and 19 (pp22-23).
- **Sources:** Chen & Krasny pp14 and 17 ("Figure N plots ..."); Chen & Jablonowski p10.
- **Effect:** little on density. It gives the graded speedup and efficiency plots an entry point from the text. Do it
  when the cluster-data paragraphs are written.

## 5. Not settled

- **How the grader views the PDF.** Fit-to-width or whole page decides how much recommendation 4 is worth. No source
  tells us.
- **Whether the user accepts italic run-in labels.** Recommendation 3 rests on the difference between a 2-4-word italic
  label (which the report already uses) and the rejected bold lead-in sentence. The user should confirm that the
  difference holds for them.
- **The Summary (15 lines, p1).** It is the densest block on the first page. Human abstracts run 5-8 lines in the
  grader's papers and about 11 at 125 characters in UMBC's. It could be split into what was done, validation, and
  results, but its content changes when the data arrive. Decide then.
- **Float gaps.** `[H]` leaves part-empty pages (p7, p10, p22). The grader's papers float figures to the top of the
  page, which closes gaps but moves floats away from their text. The gaps will change with the data, so look again then.
- **Number density.** At 8.5 per 100 words the results prose is at the top of the human range. Whether the earlier
  language pass (one or two numbers per claim, the full sets in tables) has already brought it down cannot be seen in
  this PDF, which may predate that pass on these sections.
- **The measured PDF is slightly older than the `.tex`.** The PDF dates from 11:18 and the `.tex` from 11:28. The
  scratch build of the current `.tex` gives the same page count, so the measurements should hold.
