# Sign-in visual review

Source: owner-attached 1280 × 853 approved reference in the conversation. Implementation: `screenshots/sign-in-1280x853.png`, same viewport, DPR1, initial unauthenticated state after local fonts loaded and controls blurred. Additional captures: 1440 × 900, 768 × 1024, 390 × 844 and 320 × 568 (full page).

The implementing agent viewed the conversation image and rendered captures. The reference was not supplied as a filesystem asset, so no saved side-by-side/pixel-difference artifact is available. This is a qualitative review of the adapted scope, not a claim of exact pixel parity. Astra's independent attachment-access limitation is in independent-review.md.

Surfaces checked:
- Typography: existing local Inter, restrained tracking/weights, large two-line left headline, readable form labels and mobile hierarchy. The brief explicitly requests “Real projects. Real power.” rather than the image's different headline.
- Layout: desktop 58/42 split, branding/accent near left top, architectural construction at sunrise, footer at image bottom, clean white form panel; tablet 48/52 with vertical footer; compact mobile branding and form, natural vertical scrolling at 320. No horizontal overflow in browser tests.
- Colors: existing navy/slate/fog/white tokens, teal accent/action, visible focus and error styling. Decorative architectural mask is separated from content.
- Assets: unchanged approved repository SVG (intentional difference from mockup's metallic logo), optimized WebP background with the same architectural art direction; real library icons. The approved mockup is not stretched into a background.
- Copy/content: full tagline, requested headline and Identify/Qualify/Pursue. Shared-password control and administrator recovery guidance reflect the owner's explicit access-policy decision. OAuth, email account identity and public signup omitted because unsupported.
- Controls: explicit label, keyboard order, reveal/hide, required validation, pending state, safe errors, focus recovery and repeat-submit protection tested.

Iteration history: removed duplicated tagline from the initial primary-logo asset by using the unchanged horizontal logo; tightened tagline placement in logo whitespace; changed inner input outline to a complete field focus ring. Raised the close glass facade to approximately the upper 20% of the desktop image to match the source composition; replaced a clipped light wash with a full-canvas fade to remove its horizontal seam. Fresh captures and the 14-case rerun verify the final layout; Astra independently inspected it again.

Residual: exact source-photo match and metallic rendering are not claimed. The source artwork file and an explicit resolution of screenshot-versus-brief headline differences would be needed for a strict pixel-match acceptance gate. The delivered layout implements the requested adapted scope; owner visual acceptance remains reviewable in the draft PR.
