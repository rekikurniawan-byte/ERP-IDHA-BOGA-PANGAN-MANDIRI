---
name: Portal Lapangan Nusantara
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#5a4138'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#8e7166'
  outline-variant: '#e2bfb2'
  surface-tint: '#a73a00'
  primary: '#a33900'
  on-primary: '#ffffff'
  primary-container: '#cc4900'
  on-primary-container: '#fffbff'
  inverse-primary: '#ffb599'
  secondary: '#565e74'
  on-secondary: '#ffffff'
  secondary-container: '#dae2fd'
  on-secondary-container: '#5c647a'
  tertiary: '#515c71'
  on-tertiary: '#ffffff'
  tertiary-container: '#6a758a'
  on-tertiary-container: '#fefcff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdbce'
  primary-fixed-dim: '#ffb599'
  on-primary-fixed: '#370e00'
  on-primary-fixed-variant: '#7f2b00'
  secondary-fixed: '#dae2fd'
  secondary-fixed-dim: '#bec6e0'
  on-secondary-fixed: '#131b2e'
  on-secondary-fixed-variant: '#3f465c'
  tertiary-fixed: '#d8e3fb'
  tertiary-fixed-dim: '#bcc7de'
  on-tertiary-fixed: '#111c2d'
  on-tertiary-fixed-variant: '#3c475a'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
  brand-primary-hover: '#C2410C'
  background-surface: '#F8FAFC'
  card-surface: '#FFFFFF'
  card-border: '#E2E8F0'
  text-heading: '#0F172A'
  text-body: '#334155'
  text-muted: '#64748B'
  status-success-bg: '#DCFCE7'
  status-success-text: '#15803D'
  status-warning-bg: '#FEF3C7'
  status-warning-text: '#B45309'
  status-danger-bg: '#FEE2E2'
  status-danger-text: '#B91C1C'
  status-info-bg: '#E0F2FE'
  status-info-text: '#0369A1'
typography:
  display-hero:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  title-menu:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
  body-default:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-medium:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  body-bold:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '700'
    lineHeight: 20px
  caption-regular:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-badge:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.01em
  micro-meta:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-mobile: 0.75rem
  margin: 1rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.25rem
  space-xl: 1.5rem
---

## Brand & Style

The design system establishes a mobile-first, high-utility operational portal tailored for on-site corporate catering, remote project mess camps, and agro-industrial field sites across Indonesia. It fuses the rapid clarity of tier-one Indonesian super-apps with industrial reliability and high-contrast outdoor readability. 

### Visual Direction & Aesthetics
- **Style:** Clean Industrial Super-App. Borrowing UX conventions familiar to daily users of top Indonesian logistics and food delivery platforms, the interface prioritizes immediate comprehension over ornamental decoration.
- **Atmosphere:** Energetic, grounded, and unmistakably Indonesian. Warm culinary tones balance deep institutional slate navy, communicating prompt service and strict operational accountability.
- **Ergonomics & Thumb-Zone Primacy:** Interactive components, order steppers, and billing triggers are concentrated within the lower 60% of the mobile viewport. Every critical touch surface complies strictly with a minimum 48×48px boundary to serve field foremen (mandor) operating under bright daylight and physical constraints.
- **Authenticity Standard:** Avoid artificial UI cliches, neon synthetic purples, or placeholder abstractions. All flows represent authentic site parameters: real mess encampments, strict cut-off timers, multi-shift logistics, and 3-digit verification transfers.

## Colors

The color palette addresses both thermal culinary appetite and strict financial rigor.

### Key Roles
- **Primary (`#EA580C`):** Warm Deep Catering Orange. Guides attention directly to core progression actions, portion increment buttons, and live order states. Its hover/pressed variant is `#C2410C`.
- **Secondary (`#0F172A`):** Deep Navy Slate. Serves as the authoritative backdrop for the financial e-wallet card, top app bars, and high-contrast typography readable under direct sunlight.
- **Tertiary (`#1E293B`):** Dark Slate Fill. Completes linear gradients on financial cards and surfaces supporting navigation anchors.
- **Neutral (`#64748B`):** Cool Slate Mid-tone. Drives sub-labels, metadata, stepper dividers, and secondary iconography.

### Semantic Status Tokens
Field operations depend on rapid at-a-glance status recognition without reading small print:
- **Lunas / Selesai (Success):** `#DCFCE7` surface paired with `#15803D` text.
- **Menunggu / Jatuh Tempo (Warning):** `#FEF3C7` surface paired with `#B45309` text.
- **Terkunci / Blokir / Ditolak (Danger):** `#FEE2E2` surface paired with `#B91C1C` text.
- **Diantar / Dapur Aktif (Info):** `#E0F2FE` surface paired with `#0369A1` text.

## Typography

Typography relies entirely on **Plus Jakarta Sans**, modern geometric proportions, open apertures, and distinctive counters engineered for mobile screens.

### Design Decisions
- **Legibility in Extreme Lighting:** Field mandors verify daily delivery quantities under outdoor sunlight. Headings use Deep Slate `#0F172A` at weights 600 and 700 to eliminate glare washout.
- **Numerical Stature:** Currency values (`Rp 4.250.412`), portion tallies (`40 Porsi`), and lockdown timers use tight letter spacing and prominent weights to prevent data misinterpretation.
- **Scale Restraint:** Hero sizes cap at 28px on mobile viewports to prevent word wrapping on compound Indonesian phrases and formal organization titles.

## Layout & Spacing

Layout conforms to a single-column fluid mobile canvas structured specifically for hand-held viewports (360px to 428px wide).

### Architectural Rules
- **Margins & Safe Zones:** Canvas side padding is anchored at 16px (`1rem`). The bottom edge respects mobile navigation dock allowances with 64px bar height + safe area inset (`padding-bottom: calc(4rem + env(safe-area-inset-bottom))`).
- **No Horizontal Desktop Tables:** Complex data sets (billing statements, shift rations, driver manifest) must never render horizontal scroll tables. Instead, every row translates into a dedicated structured mobile card.
- **Rhythm & Stacking:** Vertical separation between functional sections sits at 20px (`1.25rem`), while internal item gap is locked to 12px or 16px.

## Elevation & Depth

Visual depth follows a controlled hierarchy to balance flat mobile surfaces with tactile, tap-ready cards.

### Layering Hierarchy
1. **Canvas (Base 0):** `#F8FAFC` Cool Off-White. Grounding canvas, completely flat.
2. **Operational Cards (Level 1):** `#FFFFFF` Pure White. Outlined with `#E2E8F0` (1px solid border) and lifted with an ambient drop: `box-shadow: 0 4px 12px -2px rgba(15, 23, 42, 0.05)`.
3. **Financial Hero Card (Elevated Level 2):** Gradient `linear-gradient(135deg, #0F172A 0%, #1E293B 100%)`. Enhanced depth via `box-shadow: 0 10px 24px -4px rgba(15, 23, 42, 0.25)`.
4. **Persistent Navigation Dock (Level 3):** Fixed `#FFFFFF` surface with top structural rule `border-top: 1px solid #E2E8F0` and subtle upward ambient blur `box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.04)`.
5. **Modal BottomSheet (Level 4):** Draggable sheet positioned above an ultra-dim overlay (`rgba(15, 23, 42, 0.60)`), equipped with a rounded pull handle and `box-shadow: 0 -12px 32px rgba(0, 0, 0, 0.16)`.

## Shapes

The geometric form language communicates warmth and tactical precision through varied corner radiuses calibrated to element scale:

- **Large Surfaces (16px - 20px / `rounded-lg` to `rounded-xl`):** Applied to mobile content cards, financial wallet cards, and BottomSheet containers.
- **Action Triggers & Inputs (12px / `rounded`):** Applied to primary CTA buttons, steppers, and field inputs.
- **Counters & Stepper Triggers (12px):** Applied to the `[ - ]` and `[ + ]` 48×48px square touch targets.
- **Semantic Pills & Status Badges (9999px / Full Pill):** Applied to all status chips to maintain clear visual differentiation from functional buttons.

## Components

### Buttons
- **Primary Action (CTA):** Full-width or inline button, height 48px to 52px, border-radius 12px, solid `#EA580C` background, pure white bold text. Pressed state shifts to `#C2410C`.
- **Secondary / Ghost on Dark:** Height 44px, border-radius 12px, background `rgba(255, 255, 255, 0.12)`, border 1px solid `rgba(255, 255, 255, 0.25)`, text `#FFFFFF`.
- **Destructive:** Light tint `#FEE2E2` with red `#B91C1C` text and 1px border `#FECACA`.

### Financial Hero Wallet Card (GoPay/OVO Pattern)
- Deep Navy gradient container (`#0F172A` to `#1E293B`), 16px corner radius, internal padding of 20px.
- Top row: Company identification ("PT Musi Agro Lestari - Barak Mess KM 12") alongside a verified billing status pill.
- Middle tier: Prominent balance title ("Sisa Tagihan Periode Berjalan") with numerical readout `Rp 4.250.412` (incorporating 3-digit verification code) in 24px bold.
- Bottom actions: Dual trigger split including "Bayar Sekarang" (Orange `#EA580C`) and "Upload Bukti" (Translucent white).

### Touch-Friendly Portion Counter Card
- Designed to adjust daily mess headcounts under strict cut-off deadlines.
- Contains menu title, meal session badge (Siang / Malam), and lockdown countdown ("Terkunci dalam 1 jam 45 menit (10.00 WIB)").
- Step controller: Left `[ - ]` button (48×48px, background `#F1F5F9`, icon `#0F172A`), centered value display (`40 Porsi`, 20px bold), and right `[ + ]` button (48×48px, background `#EA580C`, icon `#FFFFFF`).

### BottomSheet Reason Selector (Zero Portion Fallback)
- Triggers immediately when a foreman steps a meal counter down to `0`.
- Bottom sheet animates upward with a top drag handle (36×4px, `#CBD5E1`).
- Offers selectable field-validated radio options:
  1. Libur hari ini saja
  2. Libur sampai tanggal... (dengan kalender picker)
  3. Berhenti sementara
  4. Proyek / pekerjaan selesai
  5. Pekerja sedang tidak di lokasi
  6. Lainnya (dengan catatan teks terbuka)
- Accompanied by a 48px confirmation button: "Konfirmasi Alasan".

### Live Delivery Visual Stepper
- A continuous horizontal progress track connecting 4 status nodes:
  1. Diterima
  2. Dimasak Dapur (Air Sugihan)
  3. Diantar Driver
  4. Tiba di Barak
- Active segment filled in `#EA580C`; pending segments in `#E2E8F0`.
- Driver card attachment: Includes driver photo avatar (44×44px), vehicle descriptor ("Pick-up Box Carry BG 8124 XY"), and a direct 1-tap WhatsApp trigger button with icon.

### Persistent Bottom Navigation Bar
- 64px fixed container resting at bottom viewport.
- 4 primary tabs: **Beranda**, **Pesanan**, **Tagihan**, **Akun**.
- Active tab displays `#EA580C` icon and label accompanied by an active indicator dot (4×4px pill) placed directly underneath. Inactive tabs tinted in `#64748B`.