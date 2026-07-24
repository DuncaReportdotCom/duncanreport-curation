# duncanreport-curation
Curation core

curation/
  core/                      Shared, invariant contract — edit once, all engines inherit
    SCHEMA.md                The exact stories.json shape every engine must emit
    FORMAT-LOCK.md           Locked site formatting — never emit anything that violates it
    DEPLOY-CONTRACT.md       Rules the deploy/merge pipeline enforces
  sections/                  Per-page, independently editable
    main/          RULES.md · CONFIG.md · CHANGELOG.md
    politics/      RULES.md · CONFIG.md · CHANGELOG.md
    markets/       RULES.md · CONFIG.md · CHANGELOG.md
    world/         RULES.md · CONFIG.md · CHANGELOG.md
    sports/        RULES.md · CONFIG.md · CHANGELOG.md
    life-culture/  RULES.md · CONFIG.md · CHANGELOG.md
.claude/
  skills/                    One thin Skill per section
    curate-main/       SKILL.md
    curate-politics/   SKILL.md
    curate-markets/    SKILL.md
    curate-world/      SKILL.md
    curate-sports/     SKILL.md
    curate-life-culture/ SKILL.md
