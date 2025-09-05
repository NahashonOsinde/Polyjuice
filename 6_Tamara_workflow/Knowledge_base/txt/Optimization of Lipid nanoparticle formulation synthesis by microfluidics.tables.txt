KW1: Lipid nanoparticle formulation formulation

KW2: Optimization of lipid nanoparticle

## How to optimize lipid nanoparticle formulation?

In the field of pharmaceutical advancements, the optimization of lipid nanoparticle LNP adobe formulation stands as a critical pursuit for the next generation of RNA vaccines and therapeutics.

The success of the BioNTech and Moderna Covid-19 vaccines can be attributed to two primary factors: the capacity to produce RNA in substantial quantities with high quality, and the development of a new generation of carrier specially engineered for RNA: the LNP .

Though efficient, those vaccines showed several limitations through the number of doses required, the potential side effects, and the poor long-term efficiency. While acceptable in the context of a global pandemic, especially considering the lack of regulatory framework, the forthcoming generation of RNA vaccines and therapeutics should be refined to address these concerns and establish a higher level of safety and effectiveness .

Multiple studies have shown that a promising approach to achieving this lies in optimizing the delivery mechanism of the RNA by the lipid nanoparticles. Such optimization has the potential to significantly enhance both the specificity and efficiency of these novel medicines by orders of magnitude while reducing toxicity.

In this article, we delve into the various strategies that can be used to optimize lipid nanoparticle formulation synthesized using nanoprecipitation methods, such as microfluidics. Explore which parameters play the most crucial role in this process, and how to optimize your manufacturing method to reach the highest efficiency.

## Lipid nanoparticle definition

Lipid nanoparticles (LNP) are, as their name indicates, particles of a size comprised between 10 and 100 nm , composed of lipids. Those nanoparticles have been specifically engineered for the encapsulation of RNA and oligonucleotides, which standard nanoparticles such as liposomes or PLGA cannot efficiently encapsulate due to the negative charge of the RNA. Lipid nanoparticles are generally composed of 4 lipids (Ionizable, PEG, Phospholipid, and sterol lipid). Learn more about those in our LNP introduction guide.

## LNP composition

Naturally, the first factor to consider when going towards the optimization of the RNA-LNP formulation relates to their composition . Several factors can be explored to optimize it: the choice of lipids, their respective ratios, and N/P ratio.

## Choice of lipids

When considering the currently FDA-approved therapeutics, it appears that there is a near consensus on the choice of the Sterol Lipid: Cholesterol.

When it comes to the neutral Phospholipid, DOPE appears to be the most commonly used as is the case in all the FDA-approved vaccines - though several other alternatives can sometimes be considered such as DSPC or POPE which also shows good efficiency; https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9113778/

## Ionizable lipids

## PEG-Lipids

The choice of ionizable lipids appears cornerstone of the RNA-LNP structure as it corresponds to the lipid that bonds to the RNA to encapsulate it. As discussed in our article on the screening of ionizable lipids for LNP, the choice of the optimal ionizable lipid can improve the transcription efficiency by at least 100-fold. However, due to dense the ionizable lipid landscape patents, finding the right ionizable lipid can appear challenging, and going towards a commercially available solution might be the easiest.

The same goes for the PEG-Lipid , which plays a major role in both the lipid nanoparticle protection from the immune system through stealth effect -, the toxicity - through the endosomal effect efficiency - and delivery efficiency - via its effect on the nanoparticle size.

It has indeed been shown that adding even a very small amount (&lt;1%) of PEG to the nanoparticle's final composition leads can lead to a halving its size.

While PEG-2000 and its variants (DSPE-PEG, DOPE-PEG, and DMG-PEG) are most popular, commercial RNA-LNP vaccines also use other alternatives such as ALC-0159.

## Lipid Ratios

In addition to the careful choice of lipids, the partial ratio of each lipid is of major importance in the lipid nanoparticle formulation.

Each lipid has its own role to play, finding the best ratio to optimize each of them is thus key to get the maximum out of the drug carrier.

LNP used in commercial formulation generally have a ratio of lipids close to the following:

An example of the Spikevax from Moderna.

Nevertheless, as shown through the commercialized RNA-LNP therapeutics, the ratio of each phase can also be modulated depending on the payload and composition, to optimize them.

|                            | Patisiran       | BNT162b2          | mRNA-1273       |
|----------------------------|-----------------|-------------------|-----------------|
| Cargo                      | siRNA           | mRNA              | mRNA            |
| Ionizable Cationic Lipidic | DLin-MC3-DMA    | ALC-0315          | mRNA            |
| Neutral Phospholipid       | 1,2-DSPC        | 1,2-DSPC          | 1,2-DSPC        |
| Sterol Lipid               | Cholesterol     | Cholesterol       | Cholesterol     |
| PEGylated Lipid            | C-DMG-PEG(2000) | ALC-0159          | C-DMG-PEG(2000) |
| Lipid Molar Ratio          | 50:10:38.5:1.5  | 46.3:9.4:42.7:1.6 | 50:10:38.5:1.5  |

## LNP N/P ratio

The N/P ratio corresponds to the ratio between the Amine groups (N) of the ionizable lipid and the Phosphate group (P) of the cargo (1 per base for RNA, 2 for DNA). The N/P ratio is critical as it affects most of the nanoparticle physicochemical parameters such as size, encapsulation efficiency… Typical N/P ratios are around six , but they will vary depending on the cargo and the ionizable lipid type and should thus be characterized for each combination.

## pH buffer solution

The pH of the buffer solution is of major importance as it allows for the ionizable lipid to protonate , thus highly increasing the RNA encapsulation efficiency . For that reason, a pH of 4 to 5 is commonly used for the aqueous precursor solution. Bear in mind that the pH should brought back to neutral (7.4) for, purification, storage, and use after formulation.

Lipid concentration

The concentration of lipids can also be tailored to optimize the nanoparticle formulation. The nanoparticle concentration highly impacts the yield of the final RNA-LNP solution, it should ideally be maximized to maximize .

However, when too high, the lipid concentration can also induce an impact on the nanoparticle size (due to more coalescence) and lead to micelles formation.

## Synthesis methods

In addition to optimizing the composition of the lipid and RNA precursor solution, the nanoparticle production method should be carefully chosen to optimize nanoparticle delivery efficiency , as it impacts all the nanoparticle critical parameters.

As introduced in our review on lipid nanoparticle characterization, both the size, the PDI, and the Zeta potential, have a major impact on the cellular uptake, the nanoparticle toxicity, and the RNA-LNP stability, and should therefore be optimized.

Numerous preparation methods are available for LNP synthesis, the below table summarizes

## the main ones.

|                          | Batch Methods              | High Energy                            | Macrofluidic IJMIT-junctions                | Microfluidics                        |
|--------------------------|----------------------------|----------------------------------------|---------------------------------------------|--------------------------------------|
| Size control             | Poor                       | Poor                                   | Average                                     | Excellent                            |
| Homogeneity              | Low (PDI ~0.5)             | Low (multi steps)                      | Average                                     | Great (PDI <0.2)                     |
| Encapsulation efficiency | Low                        | Poor                                   | Good                                        | Excellent (?959)                     |
| Repeatability            | Low                        | Low                                    | Low                                         | Great                                |
| Achievable volumes       | pL/mL                      |                                        | mL/L                                        | pL/mL/L                              |
| Commercial available     | Yes                        | Yes                                    | Yes                                         | Yes                                  |
| Main characterstics      | Affordable Poor NP control | Complex /Expensive/ Payload alteration | Good scalability Repeatability / NP control | Best NP controll Scalability Solvent |

Considering the importance of the LNP physicochemical parameters for optimal drug delivery efficiency, in the following section we will assume the synthesis solution offering the best control of those parameters, namely microfluidics.

Introduction to lipid nanoparticle synthesis by microfluidics Schema mixing?

LNP synthesis by nanoprecipitation relies on the mixing of 2 phases : a solvent - usually ethanol with lipids dissolved, and an antisolvent - usually water - with RNA dissolved. By mixing the 2, the drop of solvent concentration will lead to the self-assembly of the nanoparticles. As introduced in our review of the nanoparticle formation mechanism, it appears that the mixing speed has a major impact on the final nanoparticle formation and size (slow mixing leads to more time for growth and coalescence, so larger nanoparticles). To ensure a uniform nanoparticle population, one should choose a reproducible and uniform mixing method, thus the use of microfluidics.

Microfluidics is the science of handling fluids on a small scale . At that scale, due to the decrease of the viscous forces influence, the fluidic flow can be considered a purely laminar (i.e. with no turbulences and fluctuation). Thanks to its unique ability to maintain and reproduce flow conditions, microfluidics can hence be used for the accurate and reproducible mixing of the solvent and antisolvent solution, leading to the most uniform and controllable LNP size population.

Multiple microfluidic mixing strategies are available: diffusive, chaotic… Considering the initial goal of getting both a uniform and controllable lipid nanoparticle size population at a high yield, the use of a high-efficiency mixer , for which we can control the mixing speed is required. For these reasons, we will suggest using chaotic mixers , such as herringbone or baffled mixers , for optimized lipid nanoparticle formulation.

Always bear in mind that depending on the micromixer used, the microfluidic synthesis parameters will impact the final nanoparticle characterized differently.

Impact of the Microfluidics Mixing Parameters

Several parameters should be considered to control microfluidic mixing, here is the list of the most important ones:

## Total Flow Rate (TFR)

The total flow rate is the most important parameter when it comes to herringbone mixers as it greatly impacts final nanoparticle size .

TFR is defined as the sum of the flow rate of the aqueous and organic phases. In the context of a herringbone mixer, the higher the flow rate, the faster the mixing of the solutions will be, so the smaller the nanoparticles. For this reason, TFR is generally used to tune the final nanoparticle size.

## Flow Rate Ratio (FRR)

The flow rate ratio has a broader impact as it affects both the size and encapsulation efficiency .

FRR is defined as the ratio of the flow rate of the aqueous phase and the organic phase. While greatly affecting the encapsulation efficiency (usually values of FRR of 3:1 are used to reach encapsulation efficiency &gt;95% for RNA-LNP), it also has an impact on size , though much smaller than the TFR.

Additionally, other parameters such as Temperature can play a role in the final RNA-LNP characteristics.

## Downstream processing steps

Following the nanoparticle synthesis by microfluidics, the downstream processing of the now-formulated RNA-LNP nanoparticle can also affect their physicochemical characteristics, and thus delivery efficiency.

## Purification

The most critical downstream processing step is the purification.

There are multiple goals for purification, with the main ones being the removal of the excess solvent and stabilization of the lipid nanoparticle solution.

Depending on the volume of the solution, and the target concentration, several lipid nanoparticle purification strategies can be adopted including dialysis, ultrafiltration, and tangential flow focusing . Due to the removal of the excess solvent from the nanoparticle solution, nanoparticle physicochemical parameters can be greatly affected.

The below table summarizes the impact of dialysis on the different nanoparticle parameters:

More can be found in our review on the importance of dialysis in the lipid nanoparticle synthesis process.

## Active targeting

In addition to the LNP critical parameters optimization by design, also referred to as passive targeting, the lipid nanoparticles can also be functionalized to improve their specificity , also known as active targeting .

Numerous, though generally tedious, approaches can be used to improve the lipid nanoparticle capability to be more specific to one type of cell: in general, they rely on the surface functionalization of the LNP by a ligand , which will preferably conjugate to the target cell. These ligands can be of multiple forms including peptides , carbohydrates , antibodies … This LNP functionalization is generally achieved using 2 ways: One pot or Postinsertion.

## One pot assembly

LNP one-pot assembly consists of a preprocessing step , before the synthesis of the nanoparticle, where the ligand is bonded to one of the lipids usually located at the surface of the nanoparticle ( PEG for instance).

Though easy to implement, this process has 2 major limitations : the ligands can be degraded during the synthesis process and the lipid-ligand complex can end up trapped within the LNP core, making it inefficient.

## Post insertion

To overcome those limitations, ligands can also be inserted following the synthesis process. This process usually offers more efficient targeting but requires a much more complex chemical process as it should not affect the nanoparticle structure while ensuring efficient bonding to the LNP.

## Conclusion

In summary, the optimization of LNP formulation is a multidimensional process that involves careful consideration of various factors from composition to synthesis methods and downstream processing.

While general guidelines for the optimization of the lipid nanoparticle formulation can be drawn from this study - for instance the typical lipids ratios, or the use of microfluidics for synthesis - considering the unique influence of both the cargo and lipids on the final delivery efficiency, careful screening of the formulation parameters is highly advised until finding the optimal one for each of your target RNA-LNP complex.

By carefully evaluating each of these parameters, researchers can work towards developing safer and more effective RNA vaccines and therapeutics, allowing for the advent of a new generation of RNA vaccines and therapeutics.
