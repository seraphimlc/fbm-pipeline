"""Product task status constants."""

# Status values for products.status
CREATED = "created"
STEP1_COLLECTING = "step1_collecting"
STEP1_DONE = "step1_done"
STEP2_PRICING = "step2_pricing"
STEP2_DONE = "step2_done"
STEP3_KEYWORDS = "step3_keywords"
STEP4_CATEGORY = "step4_category"
STEP3_4_DONE = "step3_4_done"
STEP5_LISTING = "step5_listing"
STEP5_DONE = "step5_done"
STEP6_CURATING = "step6_curating"
STEP6_DONE = "step6_done"
STEP7_APLUS_PLAN = "step7_aplus_plan"
STEP7_DONE = "step7_done"
STEP8_APLUS_SCRIPT = "step8_aplus_script"
STEP8_DONE = "step8_done"
STEP9_APLUS_IMAGE = "step9_aplus_image"
STEP9_DONE = "step9_done"
STEP10_AMAZON_TEMPLATE = "step10_amazon_template"
STEP10_DONE = "step10_done"
PENDING_REVIEW = "pending_review"
COMPLETED = "completed"
UNAVAILABLE = "unavailable"
SOURCE_UNAVAILABLE = "source_unavailable"
DUPLICATE_SKIPPED = "duplicate_skipped"
FAILED = "failed"
PAUSED = "paused"

# Ordered step list for pipeline
STEP_ORDER = [
    CREATED,
    STEP1_COLLECTING, STEP1_DONE,
    STEP2_PRICING, STEP2_DONE,
    STEP3_KEYWORDS, STEP4_CATEGORY, STEP3_4_DONE,
    STEP5_LISTING, STEP5_DONE,
    STEP6_CURATING, STEP6_DONE,
    STEP7_APLUS_PLAN, STEP7_DONE,
    STEP8_APLUS_SCRIPT, STEP8_DONE,
    STEP9_APLUS_IMAGE, STEP9_DONE,
    STEP10_AMAZON_TEMPLATE, STEP10_DONE,
    PENDING_REVIEW,
    COMPLETED,
    UNAVAILABLE,
    SOURCE_UNAVAILABLE,
    DUPLICATE_SKIPPED,
]

# Step number → display name
STEP_LABELS = {
    0: "待处理",
    1: "商品采集",
    2: "利润计算",
    3: "关键词获取",
    4: "类目获取",
    5: "图片分析",
    6: "Listing构建",
    7: "A+规划",
    8: "A+脚本",
    9: "A+出图",
    10: "导入表格",
}

# Step number → status prefix
STEP_STATUS_MAP = {
    0: CREATED,
    1: STEP1_COLLECTING,
    2: STEP2_PRICING,
    3: STEP3_KEYWORDS,
    4: STEP4_CATEGORY,
    5: STEP6_CURATING,
    6: STEP5_LISTING,
    7: STEP7_APLUS_PLAN,
    8: STEP8_APLUS_SCRIPT,
    9: STEP9_APLUS_IMAGE,
    10: STEP10_AMAZON_TEMPLATE,
}
