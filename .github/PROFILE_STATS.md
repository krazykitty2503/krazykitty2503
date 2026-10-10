# Private aggregate profile statistics

The profile workflow always renders public contribution data. Private repository statistics are optional and remain aggregate-only: the renderer publishes only the number of selected private repositories and the combined top-language percentages. Repository names, URLs, descriptions, commit messages, file paths, and source code are never written to an SVG or workflow log.

## Enable private aggregates

1. Create a fine-grained personal access token owned by `krazykitty2503`.
2. Give it access only to the private repositories you want represented.
3. Keep every configurable permission at read-only. GitHub's automatically included **Metadata: read** permission is sufficient for the repository list and language totals used here.
4. Choose a short expiry date and rotate the token before it expires.
5. Add it to `krazykitty2503/krazykitty2503` as a repository Actions secret named `PROFILE_STATS_TOKEN`.
6. Run **Refresh profile statistics** manually and confirm the activity card reports the expected selected-repository count.

Do not paste the token into the README, workflow file, issue, commit, or chat. The secret is consumed only by the first-party `render_profile_activity.py` step in `generate-activity-cards`. The third-party summary-card generator runs in a separate job and receives only GitHub's short-lived repository token.

To disable private aggregates, delete the `PROFILE_STATS_TOKEN` repository secret. The card will safely fall back to public-only mode on the next refresh.

