# Dev 2 Brief: Organic Neo-Brutalist UI/UX, Speed Dial & Responsive Flows

## Role Summary
You own the **visual experience and interactive UI** in `index.html`, ensuring the Dribbble-inspired Organic Neo-Brutalist pill aesthetic works cleanly on both desktop and mobile.

---

## Your Core Responsibilities
1. **Organic Neo-Brutalist Design System**
   - Maintain Tailwind palette tokens (`ink`, `cream`, `butter`, `matcha`, `lilac`, `peach`, `berry`, `skyMint`).
   - Enforce chunky `2.5px solid #18181B` borders (`.nb-border`), pill buttons (`.nb-pill`), and hard offset drop shadows.
   - Ensure responsive dual navigation:
     * Desktop top pill navigation (`Home`, `Database`, `Auditor`, `My Needs`, `Settings`).
     * Mobile floating bottom pill bar.

2. **Visual Safety Speed Dial (`renderInspector()`)**
   - Animate `#dial-needle` smoothly from `-90deg` (0) to `+90deg` (100) based on `audit.safetyScore`.
   - Update risk pill (`UNSAFE / INCOMPLETE`, `CAUTION / PARTIAL`, `VERIFIED SAFE`) and missing-field cards.
   - Render missing nutrients in `#nutrition-ledger` with dashed peach warning cards labeled `MISSING` (and `MISSING — DO NOT INVENT` for ingredients).

3. **Database Grid & Filtering (`renderProductList()`, `setFilter()`)**
   - Search by name, brand, category, or SKU ID.
   - Filter pills: `All`, `Critical`, `High`, `Complete`.

4. **Personal Needs & Visual Verdict UI (`#view-needs`)**
   - Dynamic mascot SVG expressions (Happy Matcha = Match, Neutral Butter = Unknown/Incomplete, Alert Peach = Not Recommended).
   - Add Record Modal (`#add-modal`) & Toast notifications (`showToast()`).

---

## Acceptance Checklist
- [ ] Layout renders cleanly at both mobile (`375px`) and desktop (`1280px+`) widths with no horizontal overflow.
- [ ] Speed Dial needle rotates smoothly when switching between `PROD-101` (Critical) and `PROD-103` (Complete).
- [ ] All missing fields display clear `MISSING` / `UNVERIFIED` visual badges.
