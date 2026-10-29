# Login redesign visual QA

## Final result

**PASSED** — no unresolved P0, P1, or P2 visual or interaction issues were found in the verified login flow.

## Compared source and state

- Reference: `design-qa-assets/login-reference-mobbin.png`
- Implementation: `design-qa-assets/login-implementation-final.png`
- Combined evidence: `design-qa-assets/login-comparison-final.jpg`
- Focus comparisons: `design-qa-assets/login-comparison-left-focus.jpg` and `design-qa-assets/login-comparison-wall-focus.jpg`
- Viewport/state: 2560 × 1271 CSS px, DPR 1, signed-out login screen, light theme.

## Visual findings

- **Split and background:** The page keeps the reference's exact 1:1 desktop split and a single continuous neutral surface behind the right-side wall. Every track wrapper, marquee layer, and overlay resolves to `transparent`; the inter-card and inter-track gaps therefore expose the same `#f1f1ef` wall surface, with no per-track strips or column-shaped shadow tint.
- **Left hierarchy:** Logo, `Welcome back`, form controls, and legal line are centered and intentionally restrained. The implementation is slightly higher than geometric center, matching the latest requested adjustment.
- **Form:** The account/password form is 424 px wide, uses muted filled fields and a 50 px black pill CTA. The disabled phone-code option is visually subordinate and non-interactive.
- **Wall geometry:** Seven vertical marquee tracks are rotated 45 degrees so cards lean `/` and move along their long axis. Adjacent tracks alternate directions.
- **Card scale/crop:** Each 300 × 450 card produces an approximately 477 × 477 px rotated viewport footprint at the reference size. Edge tracks and cards are intentionally clipped rather than all being fully exposed.
- **Motion:** Track durations are independently set from 840 s to 1380 s, with distinct negative phase offsets. This gives a calm 14–23 minute loop range and avoids synchronized rows.
- **Asset quality:** Sixteen 1024 × 1536 high-quality WebP screens are used. Every screen includes recognizable mobile-app structure: status/navigation, a core task or content area, an explicit Agent action/result, and bottom navigation or an input/action control.
- **Variety and cohesion:** The set spans bidding, companionship, content creation, oral care, development, finance, fitness, furniture, legal review, health, nutrition, recruiting, sales, support, travel, and learning. The palette is intentionally varied but anchored by neutral white/black surfaces and a limited set of cobalt, yellow, coral, lavender, sage, and photographic tones.
- **Safety/content:** The oral-care and health screens contain no mouth, gum, tooth, X-ray, anatomical, or clinical imagery.

## Interaction and responsive checks

- Empty submission shows both required-field messages: `请输入账号` and `请输入密码`.
- Account/password remains the selected tab; phone-code login is disabled.
- Existing redirect handling, remembered username, login request, loading state, and error message behavior are preserved.
- 1280 × 800: split layout remains within the viewport with no page overflow.
- 390 × 844: the decorative wall is hidden, the form remains fully visible, and there is no horizontal overflow.
- `prefers-reduced-motion: reduce` falls back to static columns.

## Intentional differences from the reference

- Product logo and Chinese account/password controls replace Mobbin's branding, Google login, and email-only flow.
- The right-side screens depict multi-industry AI Agent products rather than Mobbin's original third-party app examples.
- The phone verification option is present but disabled, as requested.

## Verification

- `pnpm type-check` — passed.
- `pnpm build` — passed (3705 modules transformed).
