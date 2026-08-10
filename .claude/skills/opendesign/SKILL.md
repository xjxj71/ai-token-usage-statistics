---
name: opendesign
description: Use when the user wants to design web pages, prototypes, decks, mobile app screens, dashboards, landing pages, or any visual design artifact using Open Design (open-design.ai). Triggers on requests like "design a page", "create a prototype", "make a landing page", "build a dashboard UI", "design a mobile screen", "create a pitch deck".
---

# Open Design Skill

## Overview

Open Design (OD) is the open-source alternative to Claude Design / Figma. It runs locally, uses your existing coding agent (Claude Code, Codex, Gemini CLI, etc.) as the design engine, and ships **132 composable Skills** and **150 brand-grade Design Systems**.

**Core principle:** The agent doesn't freestyle — it follows a structured design workflow: discovery form → direction picker → skill template → five-dimensional critique → artifact output.

## Prerequisites

Open Design must be installed and running. Verify:

```bash
# Check if Open Design daemon is running
curl -s http://localhost:7456/api/health || echo "OD not running"
```

If not installed, choose one:

```bash
# Option 1: Desktop app (no build required)
# Download from https://open-design.ai/ or GitHub releases

# Option 2: Docker
git clone https://github.com/nexu-io/open-design.git
cd open-design/deploy
cp .env.example .env
# Generate token: openssl rand -hex 32 → paste into .env
docker compose up -d
# Open http://localhost:7456

# Option 3: From source
git clone https://github.com/nexu-io/open-design.git
cd open-design
corepack enable
pnpm install
pnpm tools-dev start
```

## Usage Patterns

### 1. Design via Open Design Web UI

The primary workflow — open `http://localhost:7456`, pick a skill, pick a design system, type your brief. The interactive question form locks down design decisions before the agent writes code.

### 2. Design via Claude Code Directly

When you want to use Open Design's skill templates and design philosophy without the web UI:

```bash
# Browse available skills
ls ~/.open-design/skills/ 2>/dev/null || ls <open-design-path>/skills/

# Read a specific skill template
cat <open-design-path>/skills/web-prototype/SKILL.md
cat <open-design-path>/skills/saas-landing/SKILL.md
```

### 3. Use Open Design Skills as Reference

Import OD's design patterns into your own project:

```bash
# Copy a skill template to your project
cp -r <open-design-path>/skills/web-prototype/ .claude/skills/web-prototype/
```

## Available Skills (132 total)

### Design & Prototyping (prototype mode)

| Skill | Description |
|-------|-------------|
| `web-prototype` | Single-page HTML — landings, marketing, hero pages (default) |
| `saas-landing` | Hero / features / pricing / CTA marketing layout |
| `dashboard` | Admin / analytics with sidebar + dense data layout |
| `pricing-page` | Standalone pricing + comparison tables |
| `docs-page` | 3-column documentation layout |
| `blog-post` | Editorial long-form |
| `mobile-app` | iPhone 15 Pro / Pixel framed app screen(s) |
| `mobile-onboarding` | Multi-screen mobile onboarding flow |
| `gamified-app` | Three-frame gamified mobile-app prototype |
| `email-marketing` | Brand product-launch HTML email |
| `social-carousel` | 3-card 1080x1080 social carousel |
| `magazine-poster` | Single-page magazine-style poster |
| `motion-frames` | Motion-design hero with CSS animations |
| `sprite-animation` | Pixel / 8-bit animated explainer slide |
| `dating-web` | Consumer dating dashboard mockup |
| `wireframe-sketch` | Hand-drawn ideation sketch |
| `critique` | Five-dimensional self-critique scoresheet |

### Deck / Presentation (deck mode)

| Skill | Description |
|-------|-------------|
| `guizang-ppt` | Magazine-style web PPT (default for deck) |
| `simple-deck` | Minimal horizontal-swipe deck |
| `replit-deck` | Product-walkthrough deck |
| `weekly-update` | Team weekly cadence as a swipe deck |

### Office & Operations

| Skill | Description |
|-------|-------------|
| `pm-spec` | PM specification doc with TOC + decision log |
| `team-okrs` | OKR scoresheet |
| `meeting-notes` | Meeting decision log |
| `kanban-board` | Board snapshot |
| `eng-runbook` | Incident runbook |
| `finance-report` | Exec finance summary |
| `invoice` | Single-page invoice |
| `hr-onboarding` | Role onboarding plan |

## Design Systems (150 built-in)

Product-grade design systems with full token specs:

| System | Style |
|--------|-------|
| Linear | Minimal, monochrome, sharp |
| Stripe | Clean, trustworthy, gradient-heavy |
| Vercel | Black/white, geometric, developer-first |
| Airbnb | Warm, rounded, photography-led |
| Tesla | Dark, cinematic, premium |
| Notion | Neutral, content-first, wiki-style |
| Apple | Precise, white-space, SF Pro |
| Anthropic | Ethical, calm, earth-tones |
| Cursor | Dark IDE, code-native |
| Supabase | Green accent, developer dashboard |
| Xiaohongshu | Pink, social, mobile-first |

Plus 139 more. Each system is a 9-section `DESIGN.md`: color, typography, spacing, layout, components, motion, voice, brand, anti-patterns.

## Five Visual Directions

When the user has no brand preference, OD offers 5 curated schools:

| Direction | Palette | Font Stack |
|-----------|---------|------------|
| Editorial Monocle | High-contrast, serif | Playfair Display + Inter |
| Modern Minimal | Neutral, geometric | Geist + Geist Mono |
| Warm Soft | Earthy, rounded | Plus Jakarta Sans + DM Mono |
| Tech Utility | Monospace, terminal | JetBrains Mono + Inter |
| Brutalist Experimental | Raw, high-saturation | Space Grotesk + IBM Plex Mono |

## Design Philosophy

OD enforces a structured workflow to prevent "AI freestyle":

1. **Discovery Form** — Lock brief: surface, audience, tone, brand context, scale
2. **Direction Picker** — Choose visual direction (5 curated schools)
3. **Skill Template** — Agent reads SKILL.md + assets/template.html
4. **Five-Dimensional Critique** — Philosophy / Hierarchy / Detail / Function / Innovation
5. **Artifact Output** — Single `<artifact>` rendered in sandboxed iframe

### Anti-AI-Slop Checklist

Before emitting any artifact, the agent must verify:
- No generic gradient backgrounds
- No placeholder "Lorem ipsum" text
- No mismatched font pairings
- No inconsistent spacing
- No accessibility violations (contrast, alt text, semantic HTML)

## Integration with Claude Code

When used alongside Claude Code:

```bash
# Claude Code acts as the design engine
# OD's daemon spawns claude CLI with:
#   cwd = .od/projects/<id>/
#   tools = Read, Write, Bash, WebFetch
#   prompt = DISCOVERY + identity + DESIGN.md + SKILL.md + project metadata
```

The agent reads the skill template, follows the design system tokens, and produces a single HTML artifact with inline assets.

## Export Formats

| Format | Method |
|--------|--------|
| HTML | Inline assets, single file |
| PDF | Browser print, deck-aware |
| PPTX | Agent-driven via skill |
| ZIP | Archiver (HTML + assets) |
| Markdown | Text extraction |

## Common Workflows

### Landing Page
```
User: "Design a SaaS landing page for our AI analytics product"
→ OD: discovery form → direction picker → saas-landing skill → artifact
```

### Mobile Prototype
```
User: "Create a mobile app prototype for a fitness tracker"
→ OD: discovery form → mobile-app skill → iPhone frame → artifact
```

### Pitch Deck
```
User: "Make a seed round pitch deck"
→ OD: discovery form → guizang-ppt skill → magazine-style slides → artifact
```

### Dashboard
```
User: "Design an admin dashboard for user management"
→ OD: discovery form → dashboard skill → sidebar + data layout → artifact
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Daemon not responding | `pnpm tools-dev status` or `docker compose logs -f` |
| Agent not detected | Verify CLI is on PATH: `which claude` |
| Skill not appearing | Restart daemon after adding skill folder |
| Export fails | Check browser console; try HTML export first |
| Port conflict | `pnpm tools-dev start --daemon-port 7457` |

## Resources

- **GitHub**: https://github.com/nexu-io/open-design
- **Website**: https://open-design.ai/
- **Discord**: https://discord.gg/qhbcCH8Am4
- **Skills Protocol**: `docs/skills-protocol.md` in repo
- **Design System Schema**: 9-section `DESIGN.md` format from `awesome-design-md`
