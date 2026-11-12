# GridLens sign-in implementation

User-approved scope: reproduce the supplied desktop split-screen reference with real React/CSS and the repository logo; preserve shared-password authentication (confirmed November 11, 2026). Email identities, OAuth, public signup and self-service recovery are unsupported and omitted. Recovery guidance points users to their workspace administrator without inventing a contact endpoint. Existing cookies, APIs, authorization and in-place destination preservation remain unchanged.

Implementation: update only LoginPage and scoped login CSS; add an optimized architectural background, using the existing Inter/Sora fonts, palette and lucide icons. Desktop is approximately 58/42 imagery/form, tablet 48/52, phone uses compact branding and prioritizes the form. Keep explicit labels, required validation, loading/error announcements, focus outlines and visibility toggle.

Verification plan:
- Extend browser coverage for 1280, 1440, 768, 390 and 320 widths; inspect screenshots and keyboard interaction.
- Run existing login tests, frontend regression, typecheck/build, backend suite and auth tests against disposable databases, plus available CI-equivalent checks.
- Astra independently reviews the integrated diff and screenshot evidence for fidelity/security/regressions.
- Publish a focused draft PR with screenshots and exact evidence. No merge or deploy.

Known intentional deviations: single password field, no OAuth/signup/recovery link; approved repository vector logo takes priority over the reference's metallic rendering. The brief explicitly names “Real projects. Real power.”, used as headline although the attached image shows “See demand before the grid does.”

The current UI canon removes Intelligence from product-facing UI. This user request explicitly retains “Commercial Intelligence for Constrained Power” in sign-in branding; that exception applies only to this sign-in page. Authenticated navigation and screens remain unchanged.

## Owner-requested mobile refinement

The owner requested that mobile look more like desktop. Mobile now retains architectural imagery, diagonal overlays, the two-line headline and Identify / Qualify / Pursue icon footer in a compact 340px hero (320px at narrow widths), followed by the white sign-in panel. The 390×844 sign-in button remains within the viewport. The previous no-image mobile treatment is superseded. Authentication and desktop/tablet layouts remain unchanged.
