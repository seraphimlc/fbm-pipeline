from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.services import amazon_search_page
from app.services.amazon_search_page import (
    AmazonSearchEvidenceContext,
    AmazonSearchPageError,
    ChromeAmazonSearchPageAdapter,
    classify_amazon_search_page,
    get_amazon_search_page_adapter,
    parse_amazon_search_results_html,
    run_amazon_search_queries,
)


async def _assert_default_fail_closed() -> None:
    original_adapter = settings.AMAZON_SEARCH_PAGE_ADAPTER
    original_enabled = settings.AMAZON_SEARCH_ENABLE_REAL_BROWSER
    try:
        settings.AMAZON_SEARCH_PAGE_ADAPTER = "unconfigured"
        settings.AMAZON_SEARCH_ENABLE_REAL_BROWSER = False
        try:
            await run_amazon_search_queries([{"query": "modular sofa fabric", "intent": "core_product"}])
        except AmazonSearchPageError as exc:
            assert exc.error_type == "adapter_not_configured", exc.error_type
        else:
            raise AssertionError("default Amazon search adapter must fail closed")

        settings.AMAZON_SEARCH_PAGE_ADAPTER = "chrome"
        settings.AMAZON_SEARCH_ENABLE_REAL_BROWSER = False
        assert get_amazon_search_page_adapter().__class__.__name__ == "UnconfiguredAmazonSearchPageAdapter"
    finally:
        settings.AMAZON_SEARCH_PAGE_ADAPTER = original_adapter
        settings.AMAZON_SEARCH_ENABLE_REAL_BROWSER = original_enabled


async def _assert_chrome_unavailable_typed_failure_with_evidence() -> None:
    original_evidence_dir = settings.AMAZON_SEARCH_EVIDENCE_DIR
    original_navigate = amazon_search_page.chrome_ctrl.chrome_navigate
    original_last_error = amazon_search_page.chrome_ctrl.chrome_last_error
    original_execute_js = amazon_search_page.chrome_ctrl.chrome_execute_js
    try:
        with tempfile.TemporaryDirectory() as tmp:
            settings.AMAZON_SEARCH_EVIDENCE_DIR = Path(tmp)

            async def fake_navigate(url: str, wait: float = 0) -> bool:
                return False

            def fake_last_error() -> str:
                return "Not authorized to send Apple events to Google Chrome"

            async def fake_execute_js(js_code: str, timeout: int = 30) -> str | None:
                return None

            amazon_search_page.chrome_ctrl.chrome_navigate = fake_navigate
            amazon_search_page.chrome_ctrl.chrome_last_error = fake_last_error
            amazon_search_page.chrome_ctrl.chrome_execute_js = fake_execute_js

            adapter = ChromeAmazonSearchPageAdapter()
            context = AmazonSearchEvidenceContext(task_run_id=9101, task_step_id=9202, product_id=93, item_code="TEST93", query_index=2)
            try:
                await adapter.search("modular sofa fabric", evidence_context=context)
            except AmazonSearchPageError as exc:
                assert exc.error_type == "browser_permission_denied", exc.error_type
            else:
                raise AssertionError("Chrome permission failure must not produce candidates")

            evidence = settings.AMAZON_SEARCH_EVIDENCE_DIR / "run-9101" / "step-9202" / "query-2.json"
            assert evidence.exists(), evidence
            text = evidence.read_text(encoding="utf-8")
            assert '"task_run_id": 9101' in text
            assert '"task_step_id": 9202' in text
            assert '"query_index": 2' in text
            assert '"error_type": "browser_permission_denied"' in text
    finally:
        settings.AMAZON_SEARCH_EVIDENCE_DIR = original_evidence_dir
        amazon_search_page.chrome_ctrl.chrome_navigate = original_navigate
        amazon_search_page.chrome_ctrl.chrome_last_error = original_last_error
        amazon_search_page.chrome_ctrl.chrome_execute_js = original_execute_js


async def _assert_empty_results_writes_attributed_evidence() -> None:
    original_evidence_dir = settings.AMAZON_SEARCH_EVIDENCE_DIR
    original_between_query_delay = settings.AMAZON_SEARCH_BETWEEN_QUERY_DELAY_SECONDS
    original_navigate = amazon_search_page.chrome_ctrl.chrome_navigate
    original_last_error = amazon_search_page.chrome_ctrl.chrome_last_error
    original_execute_js = amazon_search_page.chrome_ctrl.chrome_execute_js
    try:
        with tempfile.TemporaryDirectory() as tmp:
            settings.AMAZON_SEARCH_EVIDENCE_DIR = Path(tmp)
            settings.AMAZON_SEARCH_BETWEEN_QUERY_DELAY_SECONDS = 0

            async def fake_navigate(url: str, wait: float = 0) -> bool:
                return True

            def fake_last_error() -> str:
                return ""

            async def fake_execute_js(js_code: str, timeout: int = 30) -> str | None:
                if "documentElement.outerHTML" in js_code:
                    return json.dumps({
                        "url": "https://www.amazon.com/s?k=modular+sofa",
                        "title": "Amazon.com : modular sofa",
                        "html": """
                            <html><body>
                              <div data-component-type="s-search-result"></div>
                              <script>var nav = "/dp/B0FAKE0001";</script>
                            </body></html>
                        """,
                        "body_text": "Results for modular sofa",
                    })
                return "ok"

            amazon_search_page.chrome_ctrl.chrome_navigate = fake_navigate
            amazon_search_page.chrome_ctrl.chrome_last_error = fake_last_error
            amazon_search_page.chrome_ctrl.chrome_execute_js = fake_execute_js

            adapter = ChromeAmazonSearchPageAdapter()
            context = AmazonSearchEvidenceContext(task_run_id=9301, task_step_id=9402, product_id=95, item_code="TEST95", query_index=3)
            try:
                await adapter.search("modular sofa", evidence_context=context)
            except AmazonSearchPageError as exc:
                assert exc.error_type == "empty_results", exc.error_type
            else:
                raise AssertionError("DOM without parseable ASIN must fail as empty_results")

            evidence = settings.AMAZON_SEARCH_EVIDENCE_DIR / "run-9301" / "step-9402" / "query-3.json"
            assert evidence.exists(), evidence
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            assert payload["task_run_id"] == 9301, payload
            assert payload["task_step_id"] == 9402, payload
            assert payload["query_index"] == 3, payload
            assert payload["error_type"] == "empty_results", payload
            assert payload["candidate_count"] == 0, payload
            assert payload["page_url"] == "https://www.amazon.com/s?k=modular+sofa", payload
            assert payload["page_title"] == "Amazon.com : modular sofa", payload
            assert payload["classification"] is None, payload
            assert payload["dom_summary"]["result_count_hint"] == 1, payload
            assert payload["dom_summary"]["data_asin_hint"] == 0, payload
            assert payload["dom_summary"]["dp_link_hint"] == 0, payload
            assert payload["dom_summary"]["result_block_snippets"], payload
            assert "/dp/B0FAKE0001" not in payload["dom_summary"]["result_block_snippets"][0], payload
            assert payload.get("finished_at"), payload
            assert payload.get("error_message"), payload
    finally:
        settings.AMAZON_SEARCH_EVIDENCE_DIR = original_evidence_dir
        settings.AMAZON_SEARCH_BETWEEN_QUERY_DELAY_SECONDS = original_between_query_delay
        amazon_search_page.chrome_ctrl.chrome_navigate = original_navigate
        amazon_search_page.chrome_ctrl.chrome_last_error = original_last_error
        amazon_search_page.chrome_ctrl.chrome_execute_js = original_execute_js


def _assert_search_results_with_location_nav_are_not_region_page() -> None:
    html = """
<html>
  <head><title>Amazon.com : cabinet adjustable freestanding mdf bathroom</title></head>
  <body>
    <div>Results</div>
    <div>Filters</div>
    <div id="nav-global-location-slot">Deliver to RMA-J72611</div>
    <a id="nav-global-location-popover-link">Choose your location</a>
    <div data-component-type="s-search-result" data-asin="B0CABNT001">
      <h2><a class="a-link-normal" href="/dp/B0CABNT001"><span>Freestanding Bathroom Cabinet</span></a></h2>
      <img class="s-image" src="https://images.example/cabinet.jpg" />
      <span class="a-price"><span class="a-offscreen">$89.99</span></span>
      <span class="a-icon-alt">4.4 out of 5 stars</span>
      <span class="a-size-base s-underline-text">48</span>
    </div>
  </body>
</html>
"""
    assert classify_amazon_search_page(html) is None
    candidates = parse_amazon_search_results_html(html, query="cabinet adjustable freestanding mdf bathroom")
    assert len(candidates) == 1, candidates
    assert candidates[0].asin == "B0CABNT001", candidates[0]
    assert candidates[0].title == "Freestanding Bathroom Cabinet", candidates[0]


def _assert_result_attribute_order_variants_parse() -> None:
    html = """
<html><body>
  <div data-asin='B0ORDER001' class='sg-col' data-component-type='s-search-result'>
    <h2><a href='/dp/B0ORDER001'><span>Data ASIN Before Component Type</span></a></h2>
    <img class='s-image' src='https://images.example/order-1.jpg'>
  </div>
  <div class="sg-col" data-component-type = "s-search-result" data-asin = "B0ORDER002">
    <h2><a class="a-link-normal" href="/dp/B0ORDER002/ref=sxin"><span>Data ASIN After Component Type</span></a></h2>
    <img class="s-image" src="https://images.example/order-2.jpg">
  </div>
</body></html>
"""
    candidates = parse_amazon_search_results_html(html, query="cabinet", limit=4)
    assert [candidate.asin for candidate in candidates] == ["B0ORDER001", "B0ORDER002"], candidates
    assert candidates[0].title == "Data ASIN Before Component Type", candidates[0]
    assert candidates[1].title == "Data ASIN After Component Type", candidates[1]


def _assert_dp_link_fallback_with_empty_data_asin_parse() -> None:
    html = """
<html><body>
  <div class="sg-col" data-component-type="s-search-result" data-asin="">
    <h2><a class="a-link-normal a-text-normal" href="/dp/B0FALLBK01?ref_=sr_1_1"><span>Fallback Product Link Cabinet</span></a></h2>
    <img class="s-image" src="https://images.example/fallback.jpg" />
    <span class="a-price"><span class="a-offscreen">$64.99</span></span>
  </div>
</body></html>
"""
    candidates = parse_amazon_search_results_html(html, query="cabinet")
    assert len(candidates) == 1, candidates
    assert candidates[0].asin == "B0FALLBK01", candidates[0]
    assert candidates[0].url == "https://www.amazon.com/dp/B0FALLBK01?ref_=sr_1_1", candidates[0]
    assert candidates[0].title == "Fallback Product Link Cabinet", candidates[0]


def _assert_script_and_navigation_asins_do_not_create_candidates() -> None:
    html = """
<html><body>
  <nav><a href="/dp/B0NAVIG001">Navigation Promo</a></nav>
  <script>window.prefetch = {"asin": "B0SCRIPT01", "href": "/dp/B0SCRIPT01"};</script>
  <div data-component-type="s-search-result" data-asin="">
    <script>window.prefetch = {"asin": "B0INSCRPT1", "href": "/dp/B0INSCRPT1"};</script>
    <span>Sponsored shell without product link</span>
  </div>
</body></html>
"""
    assert classify_amazon_search_page(html) is None
    try:
        parse_amazon_search_results_html(html, query="cabinet")
    except AmazonSearchPageError as exc:
        assert exc.error_type == "empty_results", exc.error_type
    else:
        raise AssertionError("script/navigation ASINs must not become product candidates")


def _assert_post_result_navigation_fallback_does_not_create_candidate() -> None:
    html = """
<html><body>
  <div data-component-type="s-search-result" data-asin="">
    <h2><span>Shell Without Product Link</span></h2>
  </div>
  <nav><a href="/dp/B0NAVIG001">Navigation Promo</a></nav>
</body></html>
"""
    assert classify_amazon_search_page(html) is None
    try:
        parse_amazon_search_results_html(html, query="cabinet")
    except AmazonSearchPageError as exc:
        assert exc.error_type == "empty_results", exc.error_type
    else:
        raise AssertionError("post-result navigation product links must not become fallback candidates")

    malformed_html = """
<html><body>
  <div data-component-type="s-search-result" data-asin="">
    <h2><span>Malformed Shell Without Closing Div</span></h2>
  <nav><a href="/dp/B0NAVIG001">Navigation Promo</a></nav>
</body></html>
"""
    assert classify_amazon_search_page(malformed_html) is None
    try:
        parse_amazon_search_results_html(malformed_html, query="cabinet")
    except AmazonSearchPageError as exc:
        assert exc.error_type == "empty_results", exc.error_type
    else:
        raise AssertionError("malformed result shells must still not absorb post-result navigation links")


def _assert_valid_data_asin_does_not_use_mismatched_url() -> None:
    html = """
<html><body>
  <div data-component-type="s-search-result" data-asin="B0RIGHT001">
    <h2><span>Right Result</span></h2>
    <a href="/dp/B0WRONG001">Wrong Product Link</a>
  </div>
</body></html>
"""
    candidates = parse_amazon_search_results_html(html, query="cabinet")
    assert len(candidates) == 1, candidates
    assert candidates[0].asin == "B0RIGHT001", candidates[0]
    assert candidates[0].url is None, candidates[0]


def _assert_true_region_page_still_fails_closed() -> None:
    html = """
<html>
  <body>
    <h1>Choose your location</h1>
    <p>Deliver to a US address to see products available in your region.</p>
    <script>window.prefetch = {"data-asin":"B0SHOULDNOTWIN"};</script>
    <button>Update location</button>
  </body>
</html>
"""
    assert classify_amazon_search_page(html) == "region_page"
    try:
        parse_amazon_search_results_html(html, query="cabinet")
    except AmazonSearchPageError as exc:
        assert exc.error_type == "region_page", exc.error_type
    else:
        raise AssertionError("location-only page must fail as region_page")


def _assert_unsupported_page_structure_still_fails_closed() -> None:
    html = "<html><body><main>Amazon navigation without search results</main></body></html>"
    assert classify_amazon_search_page(html) == "unsupported_page_structure"
    try:
        parse_amazon_search_results_html(html, query="cabinet")
    except AmazonSearchPageError as exc:
        assert exc.error_type == "unsupported_page_structure", exc.error_type
    else:
        raise AssertionError("page without search result structure must fail closed")


async def main() -> None:
    _assert_search_results_with_location_nav_are_not_region_page()
    _assert_result_attribute_order_variants_parse()
    _assert_dp_link_fallback_with_empty_data_asin_parse()
    _assert_script_and_navigation_asins_do_not_create_candidates()
    _assert_post_result_navigation_fallback_does_not_create_candidate()
    _assert_valid_data_asin_does_not_use_mismatched_url()
    _assert_true_region_page_still_fails_closed()
    _assert_unsupported_page_structure_still_fails_closed()
    await _assert_default_fail_closed()
    await _assert_chrome_unavailable_typed_failure_with_evidence()
    await _assert_empty_results_writes_attributed_evidence()


if __name__ == "__main__":
    asyncio.run(main())
