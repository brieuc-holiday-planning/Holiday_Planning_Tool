"""Single source of truth for the application version.

Read by .gitlab-ci.yml when building the release artifact, and asserted
against the git tag so a release can never ship a mismatched version.
Bump this, update CHANGELOG.md, then tag `v<version>`.
"""

__version__ = "1.1.0"
