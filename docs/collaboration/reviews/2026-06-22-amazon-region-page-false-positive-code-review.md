# CODE_REVIEW / PASS_WITH_SCOPE

Date: 2026-06-22 CST
Reviewer: 镜花（agentKey: `jinghua`）
Scope: focused code review for `MSG-20260622-067 - AMAZON_SEARCH_REGION_PAGE_FALSE_POSITIVE`

## Review Scope

Reviewed:

- `backend/app/services/amazon_search_page.py`
- `scripts/test_amazon_search_page_real_adapter_boundaries.py`
- `scripts/test_project_rules.py` only for the专项 test entry that runs the boundary script
- Real evidence shape from `tmp/qa-evidence-20260622-s4-real-chrome/amazon-search-page/run-756/step-762/query-1.json`

Not reviewed:

- Full S2/S3 implementation outside this classifier boundary
- Real Chrome S4 rerun after this fix
- Candidate landing, workflow advancement, commit/push readiness, or external Amazon stability

## Conclusion

`MSG-20260622-067` passes this focused code review. I found no P0/P1 issue in the region-page false-positive fix.

观止 is allowed to rerun real Chrome S4 after this code gate. This PASS only means the classifier/test fix is acceptable within the requested scope; it does not mean real Amazon candidates have landed or that the end-to-end QA has passed.

## Evidence

The triggering evidence was a real Chrome page evidence file with:

- `page_title`: `Amazon.com : cabinet adjustable freestanding mdf bathroom`
- `classification`: previous `region_page`
- `dom_summary.result_count_hint`: `48`
- `dom_summary.body_text_sample`: starts with `Skip to / Main content / Results / Filters`, then Amazon navigation and delivery text such as `Deliver to ...`

The fix addresses that shape by making `classify_amazon_search_page()` keep hard blockers first, then allowing reliable search-result structure before checking generic delivery/location navigation text:

- `captcha`: still checked before search-result structure
- `bot_check`: still checked before search-result structure
- `rate_limited`: still checked before search-result structure
- `login_required`: still checked before search-result structure
- `_has_search_result_structure(html)`: now prevents normal search pages with delivery navigation from being misclassified as `region_page`
- `region_page`: still returned for location-only blockers without search-result structure
- `unsupported_page_structure`: still returned when there is no search-result structure and no `data-asin` signal
- `empty_results`: still raised by parsing when a page has search-result structure but no parseable candidate, and the existing evidence-writing regression remains covered

The new boundary test is not only a bare substring assertion. It constructs a minimal page matching the real evidence class: `Results`, `Filters`, delivery navigation text, `choose your location`, `data-component-type="s-search-result"`, and a parseable ASIN. It asserts both classifier behavior and parser output. The region blocker regression also includes a decoy `data-asin` inside script text, which helps prove bare ASIN-like text does not override a location blocker.

## Passed Checks

- Normal search result page plus delivery/location navigation text is no longer classified as `region_page`.
- True location-only blocker still returns `region_page`.
- Captcha, bot check, rate limit, and login still fail closed before search-result structure can allow parsing.
- `unsupported_page_structure` remains fail-closed for pages without search-result structure.
- `empty_results` remains distinct from `unsupported_page_structure`: a page with search-result structure but no parseable ASIN reaches parser failure and writes attributed evidence in the Chrome adapter path.
- The project rule entry invokes the boundary script from `make test-project-rules`; I did not review unrelated project-rule additions in this pass.
- No fixture/mock result is used to claim real Amazon success. The tests use controlled HTML only as classifier/parser regression coverage, and the review conclusion remains before real Chrome S4 rerun.

## Validation Commands

Ran from `/Users/liuchang/Documents/gitproject/fbm-pipeline`:

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
git diff --check --no-index -- /dev/null scripts/test_amazon_search_page_real_adapter_boundaries.py
```

Results:

- `python -m compileall backend/app`: PASS
- `make test-project-rules`: PASS, 62 project rule tests
- `scripts/test_amazon_search_page_real_adapter_boundaries.py`: PASS
- scoped `git diff --check`: PASS
- supplemental `--no-index` diff check for the untracked boundary script: PASS

## Residual Risks

- This remains a regex/HTML-boundary parser, not a browser-semantic DOM parser. Amazon markup can still change.
- A page that contains real search-result markup behind a location overlay may now be parsed instead of classified as `region_page`. Within this task, that is acceptable because hard blockers still fail first, location-only blockers still fail closed, and parse failure remains typed as `empty_results` with evidence.
- The synthetic regression is a minimized representation of the real evidence shape, not a replay of the full 2.5 MB Amazon DOM. Real Chrome S4 must still be rerun.

## Gate Meaning

Allowed next step: 观止 may rerun real Chrome S4 for `MSG-20260622-067`.

This gate does not authorize commit/push by itself and does not assert real Amazon candidate landing.
