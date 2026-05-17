from datetime import datetime
from sqlalchemy import Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gigab2b_url: Mapped[str] = mapped_column(Text, nullable=False)
    gigab2b_product_id: Mapped[str | None] = mapped_column(String(50))
    competitor_asin: Mapped[str | None] = mapped_column(String(20))
    amazon_asin: Mapped[str | None] = mapped_column(String(20))
    asin_sync_status: Mapped[str | None] = mapped_column(String(20), default="not_synced")
    asin_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    asin_sync_error: Mapped[str | None] = mapped_column(Text)
    aplus_upload_status: Mapped[str | None] = mapped_column(String(20), default="not_uploaded")
    aplus_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    aplus_upload_error: Mapped[str | None] = mapped_column(Text)
    upc: Mapped[str | None] = mapped_column(String(32))
    brand: Mapped[str] = mapped_column(String(100), default="Vindhvisk")
    status: Mapped[str] = mapped_column(String(30), default="created")
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    data: Mapped["ProductData | None"] = relationship("ProductData", back_populates="product", uselist=False, cascade="all, delete-orphan")
    images: Mapped["ProductImage | None"] = relationship("ProductImage", back_populates="product", uselist=False, cascade="all, delete-orphan")
    aplus: Mapped["ProductAplus | None"] = relationship("ProductAplus", back_populates="product", uselist=False, cascade="all, delete-orphan")
    files: Mapped[list["ProductFile"]] = relationship("ProductFile", back_populates="product", cascade="all, delete-orphan")
    catalog_item: Mapped["CatalogProduct | None"] = relationship("CatalogProduct", back_populates="source_product", uselist=False, cascade="all, delete-orphan")

    @property
    def source_url(self) -> str:
        return self.gigab2b_url

    @property
    def source_item_id(self) -> str | None:
        return self.gigab2b_product_id


class CatalogProduct(Base):
    __tablename__ = "catalog_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), unique=True)
    gigab2b_url: Mapped[str] = mapped_column(Text, nullable=False)
    gigab2b_product_id: Mapped[str | None] = mapped_column(String(50))
    competitor_asin: Mapped[str | None] = mapped_column(String(20))
    amazon_asin: Mapped[str | None] = mapped_column(String(20))
    asin_sync_status: Mapped[str | None] = mapped_column(String(20), default="not_synced")
    asin_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    asin_sync_error: Mapped[str | None] = mapped_column(Text)
    aplus_upload_status: Mapped[str | None] = mapped_column(String(20), default="not_uploaded")
    aplus_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    aplus_upload_error: Mapped[str | None] = mapped_column(Text)
    upc: Mapped[str | None] = mapped_column(String(32))
    brand: Mapped[str] = mapped_column(String(100), default="Vindhvisk")
    item_code: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(Text)
    leaf_category: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="created")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    source_product: Mapped["Product"] = relationship("Product", back_populates="catalog_item")

    @property
    def source_url(self) -> str:
        return self.gigab2b_url

    @property
    def source_item_id(self) -> str | None:
        return self.gigab2b_product_id


class AsinSyncBatch(Base):
    __tablename__ = "asin_sync_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store: Mapped[str] = mapped_column(String(100), default="Andy店-US")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    not_found_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["AsinSyncItem"]] = relationship("AsinSyncItem", back_populates="batch", cascade="all, delete-orphan")


class AsinSyncItem(Base):
    __tablename__ = "asin_sync_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("asin_sync_batches.id"))
    catalog_product_id: Mapped[int] = mapped_column(Integer, ForeignKey("catalog_products.id"))
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"))
    lookup_code: Mapped[str | None] = mapped_column(String(100))
    lookup_type: Mapped[str | None] = mapped_column(String(20))
    matched_code: Mapped[str | None] = mapped_column(String(100))
    amazon_asin: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    batch: Mapped["AsinSyncBatch"] = relationship("AsinSyncBatch", back_populates="items")


class AplusUploadBatch(Base):
    __tablename__ = "aplus_upload_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store: Mapped[str] = mapped_column(String(100), default="Andy店-US")
    submit_for_approval: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["AplusUploadItem"]] = relationship("AplusUploadItem", back_populates="batch", cascade="all, delete-orphan")


class AplusUploadItem(Base):
    __tablename__ = "aplus_upload_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("aplus_upload_batches.id"))
    catalog_product_id: Mapped[int] = mapped_column(Integer, ForeignKey("catalog_products.id"))
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"))
    amazon_asin: Mapped[str | None] = mapped_column(String(20))
    item_code: Mapped[str | None] = mapped_column(String(100))
    document_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    uploaded_images: Mapped[str | None] = mapped_column(Text)
    lingxing_response: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    batch: Mapped["AplusUploadBatch"] = relationship("AplusUploadBatch", back_populates="items")


class ProductData(Base):
    __tablename__ = "product_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), unique=True)

    # 模块1：商品采集
    item_code: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(100))
    material: Mapped[str | None] = mapped_column(String(100))
    filler: Mapped[str | None] = mapped_column(String(100))
    product_type: Mapped[str | None] = mapped_column(String(100))
    dimension_length: Mapped[float | None] = mapped_column(Float)
    dimension_width: Mapped[float | None] = mapped_column(Float)
    dimension_height: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)
    packages: Mapped[str | None] = mapped_column(Text)           # JSON
    value_total: Mapped[float | None] = mapped_column(Float)     # 货值 G
    estimated_total: Mapped[float | None] = mapped_column(Float) # 含运费成本 T
    shipping_cost: Mapped[float | None] = mapped_column(Float)     # 一件代发物流费
    shipping_cost_min: Mapped[float | None] = mapped_column(Float) # 云送仓最低物流费
    shipping_cost_max: Mapped[float | None] = mapped_column(Float) # 云送仓最高物流费
    features: Mapped[str | None] = mapped_column(Text)           # JSON
    description: Mapped[str | None] = mapped_column(Text)        # 大建五点描述(characteristic)
    variants: Mapped[str | None] = mapped_column(Text)           # JSON
    stock: Mapped[int | None] = mapped_column(Integer)
    seller: Mapped[str | None] = mapped_column(String(200))
    origin: Mapped[str | None] = mapped_column(String(100))
    image_count: Mapped[int | None] = mapped_column(Integer)
    material_dir: Mapped[str | None] = mapped_column(Text)       # 素材文件夹路径

    # 模块2：利润计算
    suggested_price: Mapped[float | None] = mapped_column(Float)
    cost_total: Mapped[float | None] = mapped_column(Float)
    profit: Mapped[float | None] = mapped_column(Float)
    profit_rate: Mapped[float | None] = mapped_column(Float)
    pricing_detail: Mapped[str | None] = mapped_column(Text)    # JSON

    # 模块3：关键词
    keywords_top: Mapped[str | None] = mapped_column(Text)       # JSON
    keyword_excel_path: Mapped[str | None] = mapped_column(Text)

    # 模块4：类目
    categories: Mapped[str | None] = mapped_column(Text)         # JSON
    leaf_category: Mapped[str | None] = mapped_column(String(200))

    # 模块5：Listing文案
    listing_title: Mapped[str | None] = mapped_column(Text)
    listing_bullets: Mapped[str | None] = mapped_column(Text)    # JSON
    listing_search_terms: Mapped[str | None] = mapped_column(Text)
    listing_title_zh: Mapped[str | None] = mapped_column(Text)
    listing_bullets_zh: Mapped[str | None] = mapped_column(Text)    # JSON
    listing_search_terms_zh: Mapped[str | None] = mapped_column(Text)
    listing_check: Mapped[str | None] = mapped_column(Text)      # JSON
    listing_primary_keyword: Mapped[str | None] = mapped_column(String(200))
    listing_removed_keywords: Mapped[str | None] = mapped_column(Text)  # JSON

    # 模块10：Amazon导入模板
    amazon_template_path: Mapped[str | None] = mapped_column(Text)
    amazon_template_warnings: Mapped[str | None] = mapped_column(Text)  # JSON
    amazon_template_fill_summary: Mapped[str | None] = mapped_column(Text)  # JSON
    amazon_template_generated_at: Mapped[datetime | None] = mapped_column(DateTime)

    collected_at: Mapped[datetime | None] = mapped_column(DateTime)

    product: Mapped["Product"] = relationship("Product", back_populates="data")


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), unique=True)

    # VLM分析
    contact_sheet_path: Mapped[str | None] = mapped_column(Text)
    image_analysis: Mapped[str | None] = mapped_column(Text)         # JSON
    image_selling_points: Mapped[str | None] = mapped_column(Text)   # JSON
    category_style: Mapped[str | None] = mapped_column(String(100))

    # 主图/副图选择
    main_image_path: Mapped[str | None] = mapped_column(Text)
    main_image_source: Mapped[str | None] = mapped_column(String(50))
    gallery_images: Mapped[str | None] = mapped_column(Text)         # JSON
    gallery_order: Mapped[str | None] = mapped_column(Text)          # JSON
    main_image_summary: Mapped[str | None] = mapped_column(Text)

    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
    vlm_model: Mapped[str] = mapped_column(String(50), default="qwen3.6-plus")

    product: Mapped["Product"] = relationship("Product", back_populates="images")


class ProductAplus(Base):
    __tablename__ = "product_aplus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), unique=True)

    # 模块7：A+规划
    aplus_plan: Mapped[str | None] = mapped_column(Text)             # JSON
    aplus_plan_summary: Mapped[str | None] = mapped_column(Text)

    # 模块8：A+脚本
    aplus_scripts: Mapped[str | None] = mapped_column(Text)          # JSON
    aplus_scripts_summary: Mapped[str | None] = mapped_column(Text)

    # 模块9：A+出图
    aplus_images: Mapped[str | None] = mapped_column(Text)           # JSON
    aplus_image_count: Mapped[int | None] = mapped_column(Integer)
    aplus_status: Mapped[str | None] = mapped_column(String(20))

    planned_at: Mapped[datetime | None] = mapped_column(DateTime)
    scripted_at: Mapped[datetime | None] = mapped_column(DateTime)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    llm_model: Mapped[str] = mapped_column(String(50), default="gpt-5.5")

    product: Mapped["Product"] = relationship("Product", back_populates="aplus")


class AplusRegenerateTask(Base):
    __tablename__ = "aplus_regenerate_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"))
    module_position: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    stage: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProductFile(Base):
    __tablename__ = "product_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"))
    file_type: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Text)
    directory: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    product: Mapped["Product"] = relationship("Product", back_populates="files")
