# Multi-Format Skill Installation

## Context

The Engrammic installer CLI currently installs skills as directories (`engrammic-<name>/SKILL.md`). This works for Claude Code and Pi Agents, but other harnesses need different formats:

- **Cursor** uses `.mdc` files with frontmatter in `.cursor/rules/`
- **Gemini CLI** uses a single concatenated `GEMINI.md` file
- **Antigravity** shares Gemini's `~/.gemini/GEMINI.md` path

Additionally, Windows path handling needs verification.

## Goals

1. Support Cursor's `.mdc` format for project-level skills
2. Support Gemini's `GEMINI.md` format with safe merge/uninstall
3. Ensure Windows compatibility for all paths

## Non-Goals

- Converting existing directory-format skills to new formats (users reinstall)
- Supporting Cursor user-level (only project-level rules exist)

---

## Implementation

### 1. Data Structures (`src/tools.rs`)

Add `SkillFormat` enum:

```rust
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum SkillFormat {
    Directory,   // engrammic-<name>/SKILL.md
    CursorMdc,   // .cursor/rules/engrammic-<name>.mdc
    GeminiMd,    // Single GEMINI.md with markers
}
```

Extend `SkillDest` with `format` field and add new destinations:

| Harness | Path | Format | Scope |
|---------|------|--------|-------|
| Cursor | `.cursor/rules/` | CursorMdc | Project |
| Gemini CLI | `~/.gemini/GEMINI.md` | GeminiMd | User |
| Gemini CLI | `GEMINI.md` | GeminiMd | Project |

### 2. New Module (`src/skill_format.rs`)

Handles format conversion logic:

**Frontmatter parsing:**
- `parse_skill_metadata(content) -> SkillMetadata` - extract name, description
- `extract_body(content) -> &str` - content after frontmatter

**Cursor conversion:**
- `to_cursor_mdc(skill_content) -> String` - convert SKILL.md to .mdc format

**Gemini merge/uninstall:**
- Markers: `<!-- ENGRAMMIC:START -->` and `<!-- ENGRAMMIC:END -->`
- `build_gemini_section(skills) -> String` - create marked section
- `merge_into_gemini_md(existing, skills) -> String` - replace or append
- `remove_from_gemini_md(content) -> String` - remove marked section, preserve user content

### 3. Skills Module Updates (`src/skills.rs`)

Add format-aware functions:

```rust
// Installation - dispatch based on format
fn install_skills_formatted(src: &Path, dest: &SkillDest) -> Result<usize>

// Format-specific installers
fn copy_skills_as_mdc(src: &Path, dest_dir: &Path) -> Result<usize>
fn merge_skills_to_gemini(src: &Path, dest_file: &Path) -> Result<usize>

// Removal - dispatch based on format  
fn remove_skills_formatted(dest: &SkillDest) -> Result<usize>

// Format-specific removers
fn remove_mdc_skills(dir: &Path) -> Result<usize>
fn remove_gemini_skills(file: &Path) -> Result<usize>
```

### 4. Main Module Updates (`src/main.rs`)

Update call sites to pass `&SkillDest` instead of just paths, so format info is available.

### 5. Windows Paths

- `dirs::home_dir()` already handles Windows correctly
- Use `PathBuf::join()` consistently (already done)
- Gemini paths: `home.join(".gemini").join("GEMINI.md")` works cross-platform

---

## Gemini Merge Behavior

**Install:**
1. If markers exist, replace content between them
2. If no markers, append marked section at end
3. Preserve all user content outside markers

**Uninstall:**
1. Find and remove content between markers (inclusive)
2. Clean up extra newlines at join point
3. If file becomes empty, delete it

**Example GEMINI.md after install:**
```markdown
# My Custom Rules
Some user content here...

<!-- ENGRAMMIC:START -->
## engrammic-recall
Search memory for relevant context...

## engrammic-learn
Store new knowledge with evidence...
<!-- ENGRAMMIC:END -->
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `installer-cli/src/tools.rs` | Add `SkillFormat` enum, update `SkillDest`, add new destinations |
| `installer-cli/src/skill_format.rs` | **NEW** - format conversion logic |
| `installer-cli/src/skills.rs` | Add format-aware install/remove, update main functions |
| `installer-cli/src/main.rs` | Update to pass `&SkillDest` to skill functions |
| `installer-cli/src/lib.rs` or `main.rs` | Add `mod skill_format;` |

---

## Error Handling

- Missing/invalid SKILL.md frontmatter: skip skill, continue
- Permission errors: propagate with context
- Empty skill content: skip, don't create empty files
- Partial failures: report count of successful installs

---

## Verification

1. **Build:** `cargo build --release`
2. **Test Cursor format:**
   ```bash
   cargo run -- install --skill-path .cursor/rules
   # Verify .mdc files created with correct frontmatter
   ```
3. **Test Gemini format:**
   ```bash
   cargo run -- install --skill-path ~/.gemini/GEMINI.md
   # Verify markers and content
   # Run again - verify merge replaces, doesn't duplicate
   ```
4. **Test Gemini uninstall:**
   ```bash
   cargo run -- uninstall
   # Verify markers removed, user content preserved
   ```
5. **Run tests:** `cargo test`
6. **Windows:** Test on Windows VM or CI

---

## Task Breakdown

1. [ ] Add `SkillFormat` enum to `tools.rs`
2. [ ] Add `format` field to `SkillDest` struct
3. [ ] Add Cursor and Gemini destinations to `SkillDest::all()`
4. [ ] Create `skill_format.rs` with frontmatter parsing
5. [ ] Add Cursor `.mdc` conversion function
6. [ ] Add Gemini merge/remove functions with markers
7. [ ] Update `skills.rs` with format-aware install
8. [ ] Update `skills.rs` with format-aware remove
9. [ ] Update `main.rs` call sites
10. [ ] Add unit tests for `skill_format.rs`
11. [ ] Add integration tests for new formats
12. [ ] Manual testing on Linux + Windows
