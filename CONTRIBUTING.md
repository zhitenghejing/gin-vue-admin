
### Contributing Guide
#### 1 Issue Guidelines

- Issues are exclusively for bug reports, feature requests and design-related topics. Other questions may be closed directly. If any questions come up when you are using Element, please hit [Gitter](https://gitter.im/element-en/Lobby) for help.

- Before submitting an issue, please check if similar problems have already been issued.

#### 2 Pull Request Guidelines

- Fork this repository to your own account. Do not create branches here.

- Use semantic commits: `type(scope): description` (for example, `feat(build): embed frontend assets`).

- <font color=red>Make sure PRs are created to `develop` branch instead of `master` branch.</font>

- If your PR fixes a bug, please provide a description about the related bug.

- Merging a PR takes two maintainers: one approves the changes after reviewing, and then the other reviews and merges.

#### 3 Local development and verification

Follow [the repository development workflow](aiDoc/relations/development-workflow.md).
Use the pinned Node/pnpm toolchain and committed lockfile. Run `make setup-hooks` once,
then `make verify` before pushing. CI runs `make verify-all`, which adds full Go vet
and race checks. Report failed, skipped and unverified checks separately.

Include reproduction or acceptance steps and the checks you actually ran in the PR.
Agent/browser checks and human acceptance are distinct; deployment follows explicit
user authorization. The target branch is selected for the task; upstream contributions
continue to follow the `develop` policy above.
