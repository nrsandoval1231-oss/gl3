# Sentinel-2 change detection at flagged parcels: research spike

**Date:** 2026-11-04 · **Status:** research only. No production code, no dependency, no registry entry, no large download. Part of [workstream 4b](../engineering/early-signal-sources-more-20261103.md); the strategy line is in the [ingestion strategy](ingestion-strategy-20261103.md) ("confirm it with free Sentinel-2 imagery (10 m resolution, a new image about every 5 days) at parcels flagged by earlier signals").

## Question

Can GridLens cheaply and honestly confirm that site work has started on a parcel that an earlier signal (a land-purchase notice, an abatement agenda, a registry row, a substation docket) flagged, and what would that confirmation be worth?

## What is verified and what is not

**Verified on 2026-11-04 (a single metadata request):** the Earth Search STAC endpoint answered without a key; 120 Sentinel-2 L2A scenes matched a small Tulsa box over September to October 2026; each scene lists cloud-optimized GeoTIFF assets, the red and near-infrared assets report a 10 m ground sample distance and SCL 20 m; per-scene cloud cover is in the metadata (four of six returned scenes 100 percent cloudy).

**Unverified background, not findings:** every statement below about licensing and regulation (Copernicus terms, Regulation (EU) No 1159/2013, attribution wording), egress or billing, revisit time and the number or names of operating satellites, band and resolution tables beyond the asset metadata above, typical file sizes, and the other imagery programs (Copernicus Data Space, Planetary Computer, NAIP, Sentinel-1) is general knowledge written from memory. None of it was read from a source during this spike and none should be relied on before the owner confirms it from the publishers.

## Findings

**Access path (verified).** One metadata request on 2026-11-04 to the public Earth Search STAC API (`earth-search.aws.element84.com/v1`, a catalog of public datasets on AWS, no key) for a 0.05 by 0.05 degree box near Tulsa over September to October 2026 returned 120 matching Sentinel-2 L2A scenes (about 113 KB of JSON for six). Each scene lists cloud-optimized GeoTIFF assets in the public `sentinel-cogs` bucket: red (B04) and near-infrared (B08) at 10 m, the scene classification layer (SCL) at 20 m, a true-colour image at 10 m. Cloud cover per scene is in the metadata (four of the six returned scenes were 100 percent cloudy, two 11 to 19 percent). Because the files are cloud-optimized, a parcel-sized window (a few hundred pixels) can be read with HTTP range requests without downloading a 100 km tile (a full tile is on the order of a gigabyte). Other open paths: the Copernicus Data Space Ecosystem (free account, STAC/OData, larger archive) and the Microsoft Planetary Computer (STAC, token for bulk). Nothing was downloaded beyond the metadata above.

**Cost and licensing (unverified background).** Sentinel-2 data are free to access and use, including commercially, under the Copernicus open data terms (Regulation (EU) No 1159/2013 and the Copernicus Sentinel data licence): attribution is required ("contains modified Copernicus Sentinel data [year]"), no warranty is given. The AWS bucket is a public-dataset listing; read requests are not billed to the reader but egress from a cloud region other than us-west-2 may be billed by that cloud, so reading small windows from a us-west-2 worker is the cheap path. Compute for a parcel stack is small (kilobytes to a few megabytes per parcel per date). The honest cost is engineering and review time, not data. Confirm the current licence text and the bucket terms before enabling; they were not re-read for this spike.

**Resolution and revisit (unverified background except the asset resolutions above).** 10 m for visible and near-infrared bands, 20 m for shortwave infrared, 60 m for atmospheric bands. With two operating satellites the revisit is about 5 days at the equator and a little better at 36 degrees north where orbits overlap (the Tulsa box matched scenes from two tiles and more than one relative orbit). The cloud-free fraction is the binding limit: in the 120-scene sample many dates were unusable, so a usable observation every 2 to 4 weeks is a safer planning figure than every 5 days.

**What 10 m can and cannot see.** One pixel is 100 square metres. A data-center parcel of 10 to 100 acres is about 400 to 4,000 pixels, so clearing, grading and a large rectangular pad are visible as a persistent drop in vegetation index (NDVI from B04/B08), a rise in bare-soil or built-up indices (NDBI, BSI from SWIR) and a brightness change in the true-colour image. A 20,000 to 100,000 sq ft building shell on a larger parcel is a few pixels to a few tens of pixels and is hard to separate from mixed pixels. Individual vehicles, cranes, chillers, substations and fences are invisible. The imagery cannot say who is building, what is being built, its power, or whether it is a data center rather than a warehouse, solar farm, quarry or housing.

**A feasible approach.**

1. Input: a parcel polygon or point with a buffer, from an earlier signal. The input is the hard part: the registry, notices and agendas give names and counties, not parcels. A parcel is available only where a notice, plat, docket or permit gives a legal description or an address that a county GIS can resolve (a separate join). Without a polygon, a change at "somewhere in Tulsa County" is meaningless.
2. Per scene over a stable pre-flag baseline (for example a 12-month window ending before the flag) and a recent window: read the red, near-infrared and SCL windows for the polygon, mask cloud, shadow, snow and water with SCL, compute NDVI and a bare-soil index per clear scene.
3. Compare median indices of the recent clear scenes with the baseline median, with the seasonal cycle of the same calendar months in prior years as a control. Flag only if the fraction of polygon pixels whose vegetation index dropped by more than a fixed threshold persists across at least three clear scenes spanning at least 30 days and exceeds a minimum area (for example 2 hectares, 200 pixels).
4. Store the result as evidence: scene IDs, dates, cloud fractions, thresholds, the indices and the pixel counts, plus the attribution. State it as "vegetation loss consistent with clearing observed", never as "construction of a data center", and never as MW.

**Accuracy limits (the reason this is a research item).**

- Agriculture confounds: tillage, harvest, fallow, drought and burning also drop NDVI over tens of hectares. Rural parcels, where data centers are bought, are mostly cropland and pasture; the seasonal control reduces but does not remove false positives. Expect many false positives on cropland and a lower detection rate in winter and in cloudy regions.
- Clear scenes are scarce and uneven; absence of a flagged change is **unknown, not zero** (it can mean cloud, not no construction).
- A change inside one or two pixels of a parcel edge, or a parcel smaller than about 2 hectares, is not reliable.
- No ground truth exists in the repository. A retained sample of parcels with known construction starts (for example permit-dated sites) is required to measure precision and recall; without it no accuracy number may be claimed.
- Lead time over the other signals is untested: imagery shows site work only after it starts, which is usually after land-purchase notices and abatement agendas but may precede a building permit. The strategy's own measure (days between first early signal and first permit on a retained sample) applies.

**Alternatives (unverified background).** Commercial sub-metre imagery (tens of cm) would resolve buildings and cranes but is paid and licence-restricted (the strategy treats any paid provider as a separate authorization). Free NAIP aerial imagery (about 0.6 to 1 m, US only, a few years' cycle) is too infrequent for change timing but good for a one-off look at an existing site. Sentinel-1 radar (C-band, 10 m, cloud-independent) can detect built structures as backscatter changes through clouds, at the cost of a harder interpretation; it would be the second experiment if cloud cover proves the binding limit.

## Recommendation

Do not build this as a collection source yet. It is a **confirmation step on a short list of flagged parcels**, not a discovery feed, and it needs a parcel polygon that the current sources do not provide.

1. First build the parcel join: a county-GIS or appraisal-district resolution from addresses and legal descriptions that notices, plats, permits and dockets give, as evidence with its own quote and an `unknown` when it cannot resolve.
2. Then run a bounded offline experiment (a notebook or script, no registry entry) on 20 to 30 parcels with known construction dates (permit-dated data-center and non-data-center sites) and 20 control cropland parcels, using the STAC path above and parcel-window reads. Record precision, recall and days of lead over the permit.
3. Only if precision on cropland controls is acceptable and lead time is positive, add a read-only confirmation job: per flagged parcel, a few windowed reads per week, results as evidence with scene IDs and attribution, labelled as inferred vegetation-loss evidence (a distinct basis from documented), never creating a project, need or card, and never feeding MW.

Open questions for the owner: whether free-but-unverified imagery inference is acceptable as a displayed signal at all; the confidence labelling; which cloud region the worker runs in (egress); and whether a one-time paid imagery check on a handful of high-value parcels is wanted.
