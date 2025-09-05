KW: microfluidic synthesis of lipid nanoparticles microfluidic synthesis of LNP microfluidic formulation of lipid nanoparticle microfluidic formulation of LNP

The synthesis of nanoparticles using microfluidics has recently been brought to the spotlight following the success of the mRNA-LNP based COVID-19 vaccine.

As a matter of fact,  a majority of the final drug formulation characteristics such as delivery efficiency, cell uptake, toxicity and side effects are linked to the composition and physicochemical characteristics of the lipid nanoparticle, acting as a vessel for the mRNA cargo.

Amongst the numerous methods available for lipid nanoparticle synthesis, microfluidic has established itself as the leading technique for the synthesis of Lipid nanoparticles.

Thanks to its unique capability of very finely controlling the final LNP characteristics and handling very low and large volumes of liquids, microfluidics offers a unique tool to assist RNA-LNP drug makers throughout the therapeutic development process.

## Introduction lipid nanoparticle formulation with microfluidics

The synthesis of lipid nanoparticles with microfluidics is mainly based on a nanoprecipitation process.

The core part of the process consists of mixing a solvent phase, usually ethanol, containing the lipid mixture, together with an aqueous phase containing the material to be encapsulated (an Active Pharmaceutical Ingredient -API -such as a small molecule, an oligonucleotide, a peptide…). During the mixing process, the drop in ethanol concentration will lead to a decrease in the lipid's solubility which then triggers the LNP self-assembly process.

A detailed explanation of the 4 steps (supersaturation, nucleation, growth, and maturation) leading to the self-assembly of the LNP can be found in our LNP formation mechanism review.

From this, four main parameters can be identified as the main drivers of the LNP synthesis process:

1. Mixing time has a major impact on the LNP size. Slower mixing leads to a longer growth step, thus large nanoparticles.
2. Increase in surfactants or amphiphilic stabilizing agents decreases the final size of the produced LNPs.
3. High lipid concentration leads to the formation of a higher number of nuclei, thus increasing the coalescence events and ultimately increasing the final size of the lipid nanoparticles.
4. Though having an impact on the final size of the LNP, Viscosity and temperature 's impact is hard to predict and highly material dependent.

Note that this mixing step is generally followed by a equilibration step, followed by a buffer exchange step used to remove the excess ethanol from the solution.

In practice, for optimal control of the synthesized LNP physiochemical parameters this translates to a careful selection of the lipid composition of the solvent phase and a good control of the environmental mixing parameters (mixing speed, viscosity, temperature…) .

Considering the influence of the mixing speed in the LNP formation process, the use of microfluidics, which offers precise and reproducible control of the environmental parameters, is highly advised.

In the following sections, we provide you with a general overview of microfluidics before diving into the use of microsystems and microfluidic instruments to synthesize LNPs with the best control of their physicochemical parameters.

## Introduction to microfluidics

## A bit of theory

Microfluidics is a science that studies the behavior of fluids at a very low scale. At this scale, physics changes drastically compared to what we are used to at the macroscale, and fluids show rather astonishing properties. To understand this, let's consider the Navier -Stokes equation which drives the fluid velocity field:

The importance of each physical phenomena in the Navier stokes equation can be characterized by dimensionless numbers. The most important one is the Reynolds number Re which determines the influence of inertial over viscous forces in the fluid flow and helps determine the fluidic regime.

At the microscale, the characteristic system length L is very small so both the inertial and convective terms can be neglected, and the fluid flow can be considered laminar (considering a sufficiently low flow speed v).

Gravity's impact being also negligible, the fluid flow can thus be simplified to the Stokes equation:

<!-- formula-not-decoded -->

In simple terms, this equation tells us that applying pressure on a fluid creates a flow. When in a single dimension, such as in a microchannel, this equation can even further be simplified to:

<!-- formula-not-decoded -->

Where P is the pressure, R is the fluidic resistance and Q the flow rate. This tells us that fluid flow is controlled by the drop in pressure in the system.

## A practical approach to microfluidics for LNP synthesis

In practical terms, a microfluidic system is composed of 2 elements: a microfluidic chip, where the liquids interact with each other, and a flow control system, which drives the fluid flow in the system. Those two should be carefully chosen as their requirements can greatly vary depending on the application, and we will develop their choice in the context of LNP synthesis hereafter.

## What is a microfluidic chip?

A microfluidic chip is a network of engraved microchannels.

Those channels are connected to the external environment via holes dug in the chip, through which liquids are either injected or evacuated.

Their design, and thus the interaction between the different fluids, will depend on the intended use. In the context of LNP synthesis with microfluidics, microfluidics chips' design should allow for efficient mixing of the liquids inside the chip.

The most common chip material for chip prototyping is PDMS, however, it is not well adapted to LNP synthesis with microfluidics as it is very adsorbent, and thus can cause cross-contamination. Moreover, PDMS has low chemical compatibility with organic solvents.

For the formulation of lipid nanoparticles with microfluidics, the use of thermoplastics with low adsorption such as COP, or glass should be preferred.

## Which mixing chip to use for LNP synthesis?

As previously discussed, the mixing time has a major impact on the final LNP size. Choosing a chip design allowing for efficient mixing is thus essential.

Several designs of micromixers are available to carefully control mixing. Those can either be active (external forces generating the mixing) or passive (the channel geometry and design generate the mixing). Most common micromixers design for LNP synthesis can be found hereafter, to get more detail about them have a look at our detailed micromixer review.

## T- and Y-shaped mixers for lipid nanoparticle manufacturing

Mixing in these designs is purely diffusive, this means that a very long channel is required for the thorough mixing of the 2 fluids at a high flow rate. Mixing time is total flow rate independent. However, the mixing efficiency can be influenced by the angle between the 2 channels:

A

T- and Y- shaped micromixers design

## Hydrodynamics flow focusing (HFF) for LNP synthesis

This method also relies on diffusive mixing. In this case, the solvent phase is squeezed between the two streams of the aqueous phase. The number of interfaces is thus doubled, and the mixing time is reduced as is the diffusion length. While the total flow rate (TFR) still has no impact on the nanoparticle size, the ratio between the flow rate of the aqueous phase and the flow rate of the organic phase (also know as flow rate ratio -FRR) can influence the diffusion length and thus impact the final LNP size.

Issues with this chip design can arise as product can easily adsorb on the microchip 's walls and clog the channels. To solve this problem, 3D HFF chips -where a capillary is carefully inserted and aligned in the microfluidic channel -can be used. This also helps increase the interface surface, and thus the mixing efficiency.

This system nevertheless shows 2 main limitations for LNP synthesis.

- -High amount of aqueous phase are required to focus the organic phase (middle stream), which can be problematic as the reagent for LNP synthesis can be very expensive
- -High flow rate ratios are required for short mixing times, so the middle stream gets heavily diluted into the external one and the encapsulation efficiency tends to decrease.

## 2D and 3D HFF mixers

## Herringbone mixers

Staggered herringbone mixers fall into the class of chaotic mixers -misleading name as the Reynold number remains low and thus the flow regime is still laminar -where the mixing is enhanced by advection in addition to the diffusion effect.

The herringbone mixer consists of a series of grooves in the channels, forcing the fluid to follow a curved path while traveling through the channels, as illustrated by the picture below.

The mixing speed in the channel is here proportional to the total flow rate of liquid through the herringbone. The size of the synthesized LNP can thus be tuned by varying the flow rate.

In addition to this, as the flow of liquid in the channels can be considered laminar, the repeatability of the mixing process in steady-state conditions is excellent.

The choice of a herringbone mixer is thus advised as a starting point for the synthesis of lipid nanoparticles.

## Other micromixers

More complex micromixer designs can be used to enhance mixing such as triangle baffled mixers, square baffled mixers, bifurcating, droplet-based … or active micromixers like those using acoustofluidics.

## Choice of a microfluidic flow control system for LNP synthesis

Following the choice of the suitable micromixer for the formulation of the LNP, the 2 nd most important aspect is choosing the appropriate flow control to drive the fluid flow into the system. To start with, the most important parameters to consider are:

## -Flow rate stability and accuracy:

As discussed above, the influence of the flow rate parameters -TFR and FRR -is critical for the accurate control of the synthesized LNP characteristics.

The highest accuracy and stability of the flow control throughout the manufacturing process is required for good batch-to-batch reproducibility and good PDI within the same batch.

## -Accessible volume:

Considering the change of volume requirements through the LNP synthesis development process, it is preferred to use a system that can scale up from 100s of µL (for the screening phase) to Liters (for the production phase.)

## -Response time:

To optimize volume usage and size spread, the transition phase -also known as head and tail -during which the flow is brought from 0 to the target flow rate (or opposed) should be minimized. A fast response time is thus required, especially at low volumes, for an optimized PDI.

In practice, different methods are available to drive fluids in a microfluidic system. The most common microfluidic pumps are namely peristaltic, syringe, and pressure pumps.

The first two use mechanical actuation to literally push the fluid in the microfluidic tubing. By compressing a flexible tubing that holds the liquid, peristaltic pumps generate high shear forces on the fluid and can be damaging for biological fluids such as blood or a suspension of cells. Syringe pumps are widely used in microfluidics and known for their ease of use, although they have a long responsivity (i.e. time required to reach the desired flow rate) and the pump size has to be adapted to the volume of the syringes. Pressure pumps on the other hand, pressurize the liquids in reservoirs of various volumes without mechanical part in contact with the fluid and result in a pulseless flow rate with a fast responsivity.

## Example of microfluidic setup for LNP synthesis

Following the previous discussion, one can conclude that for optimal control of the physiochemical parameters of the synthesized LNP, using microfluidics is the most appropriate option as it permits fine control of the LNP synthesis condition.

To build a microfluidic system, 2 elements should be considered: a micromixer and a flow control system.

The currently most used micromixers are the herringbone chips as they permit a fine-tuning of the nanoparticle size by playing with the total flow rate in the system. For the flow control system, pressure driven controllers should be preferred as they offer the best performances both in terms of repeatability of the flow rate (and thus synthesize LNP), the response time (thus allowing the optimized work with small volumes) and flexibility on the large volumes (up to several L)

The below schematic illustrates a typical example of a microfluidic lipid nanoparticle synthesis system using pressure-driven flow controllers:

## It is composed of:

- -A pressure controller for accurate control of the pressure inside the 2 reservoirs containing the liquids.
- -2 pressurized reservoirs containing the aqueous phase and the solvent with the dissolved lipids.
- -2 flow sensors for accurate flow monitoring or control via a feedback loop
- -A herringbone microfluidic chip for an optimal liquid mixing
- -The corresponding set of tubing, fittings, and connector to ensure a good connection between the different elements of the setup

## Typical results

The following graph illustrates the typical results ones can obtain with the abovementioned setup including a herringbone micromixer, a pressure-driven controller, and different types of cationic lipids

One can quickly notice that most of the synthesized nanoparticles are in the 50 to 200 nm range and that the PDI remains low (below 0.2).

In addition to this, as predicted above increase in the total flow rate leads to a decrease in the nanoparticle size (increase in mixing speed)

Should you be interested in learning more and/or synthesizing your own nanoparticle, have a look at our nanoparticle synthesis pack userguide available here:

GROS LIEN VERS LE LNP PACK
