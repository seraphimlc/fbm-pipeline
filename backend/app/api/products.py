from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime

from app.database import get_db
from app.models import Product, ProductData, ProductImage, ProductAplus
from app.models.status import STEP_STATUS_MAP
from app.api.schemas import (
    ProductCreate, ProductUpdate, ProductResponse, ProductDetail,
    PaginatedResponse,
)
from app.pipeline.engine import start_pipeline, cancel_pipeline, is_running
from app.pipeline.step1_collect import collect_product
from app.pipeline.step2_pricing import run_pricing
from app.pipeline.step3_keywords import run_keywords
from app.pipeline.step4_category import run_category
from app.pipeline.step5_listing import run_listing
from app.pipeline.step6_image import run_image_analysis
from app.pipeline.step7_aplus_plan import run_aplus_plan
from app.pipeline.step8_aplus_script import run_aplus_script
from app.pipeline.step9_aplus_image import run_aplus_image

# Step runners indexed by step number
STEP_RUNNERS = {
    1: collect_product,
    2: run_pricing,
    3: run_keywords,
    4: run_category,
    5: run_listing,
    6: run_image_analysis,
    7: run_aplus_plan,
    8: run_aplus_script,
    9: run_aplus_image,
}

router = APIRouter(prefix="/api/products", tags=["products"])


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(body: ProductCreate, db: AsyncSession = Depends(get_db)):
    """创建新商品任务"""
    product = Product(
        gigab2b_url=body.gigab2b_url,
        competitor_asin=body.competitor_asin,
        brand=body.brand,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    # 创建关联空子表
    db.add(ProductData(product_id=product.id))
    db.add(ProductImage(product_id=product.id))
    db.add(ProductAplus(product_id=product.id))
    await db.commit()
    await db.refresh(product)
    return product


@router.get("", response_model=PaginatedResponse)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """商品任务列表（分页）"""
    query = select(Product).order_by(Product.created_at.desc())
    count_query = select(func.count(Product.id))

    if status:
        query = query.where(Product.status == status)
        count_query = count_query.where(Product.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """商品详情（含子表数据）"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新商品任务"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)
    product.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """删除商品任务"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    await db.delete(product)
    await db.commit()


@router.post("/{product_id}/start", response_model=ProductResponse)
async def start_pipeline(product_id: int, db: AsyncSession = Depends(get_db)):
    """启动Pipeline（触发Step1）"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if product.status != "created":
        raise HTTPException(400, f"Cannot start: current status is {product.status}")

    product.status = "step1_collecting"
    product.current_step = 1
    product.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)
    
    # 触发Pipeline引擎
    start_pipeline(product.id)
    return product


@router.post("/{product_id}/retry", response_model=ProductResponse)
async def retry_step(product_id: int, db: AsyncSession = Depends(get_db)):
    """重试当前失败的步骤"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if product.status != "failed":
        raise HTTPException(400, "Can only retry failed tasks")

    step = product.current_step
    product.status = STEP_STATUS_MAP.get(step, "created")
    product.error_message = None
    product.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)
    
    # 重新触发Pipeline引擎
    start_pipeline(product.id)
    return product


@router.post("/{product_id}/step/{step}")
async def run_single_step(product_id: int, step: int, db: AsyncSession = Depends(get_db)):
    """单独执行某个步骤（调试/重试用）"""
    if step not in STEP_RUNNERS:
        raise HTTPException(400, f"Invalid step: {step}. Must be 1-9.")

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    try:
        runner = STEP_RUNNERS[step]
        data = await runner(product_id)
        return {"status": "ok", "step": step, "data": data}
    except Exception as e:
        raise HTTPException(500, f"Step {step} failed: {e}")


@router.post("/{product_id}/pause", response_model=ProductResponse)
async def pause_pipeline(product_id: int, db: AsyncSession = Depends(get_db)):
    """暂停Pipeline"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    product.status = "paused"
    product.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)
    
    # 取消后台任务
    cancel_pipeline(product.id)
    return product
