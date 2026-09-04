# Changelog

## v0.1.0 (2026-09-04)

### BREAKING CHANGE

- merging to main no longer bumps the version, updates
CHANGELOG.md, or creates a v* tag. Releasing (bumping + changelog +
tag + mirror publish) now requires manually running the "Release
(Prod Stage)" workflow.
- the dev repo no longer produces wheel/sdist GitHub
Release artifacts or Linux/Windows pre-release binaries. Production
consumers must install from the public mirror repo instead.
- removes the multibest.imagej public API (imagej package
deleted). Users must migrate to multibest.gui.image_processing.

### Feat

- **ci**: auto-bump version and changelog on merge to main (#102)
- **ebsd**: run DREAM3D-NX in an external user-installed environment (never bundled) (#95)
- **ci**: credit dev-repo contributors in the public mirror (file + GitHub attribution) (#93)
- **ci**: code-only public mirror with a production README (#92)
- **ci**: make the public mirror code-only with a production README
- **license**: third-party notices + bundle redistributability scan (#89)
- **license**: add third-party notices and bundle redistributability scan
- **ci**: publish product code + Linux/Windows binaries to a public mirror repo (#87)
- relicense to GPL-3.0-or-later, add example datasets (LFS), and adopt full README (#84)
- added markdown files documentation the usage and functionalitie… (#70)
- added markdown files documentation the usage and functionalities of each computational module. Added mkdocs and the just docs command for creating mdocs html pages from the md files and linked them to the corresponding ui module and enabled the help button in main_ui.py
- removed apply refinement select (#60)
- **image-processing**: replace Fiji round-trip with integrated in-p… (#54)
- **gui**: add Image Processing module with Fiji round-trip (#49)
- **ci**: add PR review and project board Telegram notifications (#47)
- add interactive ImageJ UI roundtrip example and Fiji integration (#28)
- integrate ImageJ as the image processing module with core funct… (#16)
- integrate SonarCloud for code quality analysis and coverage rep… (#15)
- integrate SonarCloud for code quality analysis and coverage reporting

### Fix

- **ci**: auto-changelog job token + changelog Telegram notification (#104)
- **ci**: use default GITHUB_TOKEN for the auto-changelog push, not an unset secret
- **license**: add SPDX headers to scripts/ and extend the SPDX gate to cover them (#94)
- **ci**: repair Windows conda setup + add per-platform build checkboxes (#88)
- updated input convertor script and updated the corresponding test (#61)
- **image-processing**: UI polish — free resize, toolbar wrap, empty fields, CI sonar skip (#58)
- **image-processing**: fix to_grayscale white assertion for luminosity rounding (#57)
- **image-processing**: fix to_grayscale white assertion to account for luminosity coefficient rounding
- update Telegram notifier scripts to improve error handling and m… (#23)
- update Telegram notifier scripts to improve error handling and message formatting

### Refactor

- **ci**: move version bump/tag/changelog from merge-time to release-time (#106)
- update agent documentation for scientific Python developmen… (#12)
- update agent documentation for scientific Python development and testing
- update documentation and workflows for GitHub Copilot agents (#10)

