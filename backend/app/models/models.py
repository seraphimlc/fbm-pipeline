from datetime import datetime
from sqlalchemy import Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint
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
    amazon_product_status: Mapped[str | None] = mapped_column(String(100))
    amazon_product_status_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    amazon_product_status_error: Mapped[str | None] = mapped_column(Text)
    aplus_upload_status: Mapped[str | None] = mapped_column(String(20), default="not_uploaded")
    aplus_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    aplus_upload_error: Mapped[str | None] = mapped_column(Text)
    upc: Mapped[str | None] = mapped_column(String(32))
    brand: Mapped[str] = mapped_column(String(100), default="Vindhvisk")
    source_data_source_id: Mapped[int | None] = mapped_column(Integer)
    source_site: Mapped[str | None] = mapped_column(String(20))
    source_batch_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="created")
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    workflow_node: Mapped[str | None] = mapped_column(String(80))
    workflow_status: Mapped[str | None] = mapped_column(String(40))
    workflow_error: Mapped[str | None] = mapped_column(Text)
    workflow_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    data: Mapped["ProductData | None"] = relationship("ProductData", back_populates="product", uselist=False, cascade="all, delete-orphan")
    images: Mapped["ProductImage | None"] = relationship("ProductImage", back_populates="product", uselist=False, cascade="all, delete-orphan")
    aplus: Mapped["ProductAplus | None"] = relationship("ProductAplus", back_populates="product", uselist=False, cascade="all, delete-orphan")
    files: Mapped[list["ProductFile"]] = relationship("ProductFile", back_populates="product", cascade="all, delete-orphan")
    catalog_item: Mapped["CatalogProduct | None"] = relationship("CatalogProduct", back_populates="source_product", uselist=False, cascade="all, delete-orphan")
    competitor_search_candidates: Mapped[list["AmazonCompetitorSearchCandidate"]] = relationship(
        "AmazonCompetitorSearchCandidate",
        back_populates="product",
        cascade="all, delete-orphan",
    )

    @property
    def source_url(self) -> str:
        return self.gigab2b_url

    @property
    def source_item_id(self) -> str | None:
        return self.gigab2b_product_id


class UpcPoolItem(Base):
    __tablename__ = "upc_pool_items"
    __table_args__ = (UniqueConstraint("upc", name="uq_upc_pool_items_upc"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upc: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="available")
    source: Mapped[str | None] = mapped_column(String(50))
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("products.id"))
    bound_item_code: Mapped[str | None] = mapped_column(String(100))
    bound_source_product_id: Mapped[str | None] = mapped_column(String(50))
    bound_source_url: Mapped[str | None] = mapped_column(Text)
    bound_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProductDataSource(Base):
    __tablename__ = "product_data_sources"
    __table_args__ = (UniqueConstraint("name", name="uq_product_data_sources_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), default="giga")
    sales_channel: Mapped[str] = mapped_column(String(30), default="amazon")
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(20), nullable=False)
    fulfillment_mode: Mapped[str] = mapped_column(String(30), default="dropship")
    api_base: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(Text)
    client_secret: Mapped[str | None] = mapped_column(Text)
    shipping_cost_mode: Mapped[str] = mapped_column(String(30), default="giga_shipping_fee")
    packing_fee: Mapped[float | None] = mapped_column(Float)
    inventory_mode: Mapped[str] = mapped_column(String(30), default="available_qty")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    remark: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class OfflineTask(Base):
    __tablename__ = "offline_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    success_steps: Mapped[int] = mapped_column(Integer, default=0)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0)
    running_steps: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(100))
    payload_json: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    steps: Mapped[list["OfflineTaskStep"]] = relationship(
        "OfflineTaskStep",
        back_populates="task",
        cascade="all, delete-orphan",
    )


class OfflineTaskStep(Base):
    __tablename__ = "offline_task_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("offline_tasks.id"), nullable=False)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    data_source_name: Mapped[str | None] = mapped_column(String(100))
    site: Mapped[str | None] = mapped_column(String(20))
    batch_id: Mapped[str | None] = mapped_column(String(100))
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    task: Mapped["OfflineTask"] = relationship("OfflineTask", back_populates="steps")


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    payload_json: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    correlation_key: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    source_ref: Mapped[str | None] = mapped_column(String(200))
    superseded_by_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("task_runs.id"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_requested_by: Mapped[str | None] = mapped_column(String(100))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    groups: Mapped[list["TaskGroup"]] = relationship(
        "TaskGroup",
        back_populates="task_run",
        cascade="all, delete-orphan",
    )
    steps: Mapped[list["TaskStep"]] = relationship(
        "TaskStep",
        back_populates="task_run",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["TaskStepEvent"]] = relationship(
        "TaskStepEvent",
        back_populates="task_run",
        cascade="all, delete-orphan",
    )


class TaskGroup(Base):
    __tablename__ = "task_groups"
    __table_args__ = (UniqueConstraint("task_run_id", "group_key", name="uq_task_groups_run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("task_runs.id"), nullable=False)
    group_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    depends_on_group_keys_json: Mapped[str | None] = mapped_column(Text)
    failure_policy: Mapped[str] = mapped_column(String(50), default="require_all_success")
    retry_policy: Mapped[str] = mapped_column(String(50), default="failed_steps_only")
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    task_run: Mapped["TaskRun"] = relationship("TaskRun", back_populates="groups")
    steps: Mapped[list["TaskStep"]] = relationship(
        "TaskStep",
        back_populates="task_group",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["TaskStepEvent"]] = relationship(
        "TaskStepEvent",
        back_populates="task_group",
        cascade="all, delete-orphan",
    )


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = (UniqueConstraint("task_run_id", "step_key", name="uq_task_steps_run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("task_runs.id"), nullable=False)
    task_group_id: Mapped[int] = mapped_column(Integer, ForeignKey("task_groups.id"), nullable=False)
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    step_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    task_run: Mapped["TaskRun"] = relationship("TaskRun", back_populates="steps")
    task_group: Mapped["TaskGroup"] = relationship("TaskGroup", back_populates="steps")
    events: Mapped[list["TaskStepEvent"]] = relationship(
        "TaskStepEvent",
        back_populates="task_step",
        cascade="all, delete-orphan",
    )


class TaskStepEvent(Base):
    __tablename__ = "task_step_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("task_runs.id"), nullable=False)
    task_group_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("task_groups.id"))
    task_step_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("task_steps.id"))
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    data_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    task_run: Mapped["TaskRun"] = relationship("TaskRun", back_populates="events")
    task_group: Mapped["TaskGroup | None"] = relationship("TaskGroup", back_populates="events")
    task_step: Mapped["TaskStep | None"] = relationship("TaskStep", back_populates="events")


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
    amazon_product_status: Mapped[str | None] = mapped_column(String(100))
    amazon_product_status_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    amazon_product_status_error: Mapped[str | None] = mapped_column(Text)
    aplus_upload_status: Mapped[str | None] = mapped_column(String(20), default="not_uploaded")
    aplus_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    aplus_upload_error: Mapped[str | None] = mapped_column(Text)
    upc: Mapped[str | None] = mapped_column(String(32))
    brand: Mapped[str] = mapped_column(String(100), default="Vindhvisk")
    item_code: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(Text)
    leaf_category: Mapped[str | None] = mapped_column(String(200))
    stock: Mapped[int | None] = mapped_column(Integer)
    stock_sync_status: Mapped[str | None] = mapped_column(String(20), default="not_synced")
    stock_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    stock_sync_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="created")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime)
    export_task_id: Mapped[int | None] = mapped_column(Integer)
    export_file_path: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    source_product: Mapped["Product"] = relationship("Product", back_populates="catalog_item")
    inventory_sync_items: Mapped[list["InventorySyncItem"]] = relationship("InventorySyncItem", back_populates="catalog_product")

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
    amazon_product_status: Mapped[str | None] = mapped_column(String(100))
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


class InventorySyncBatch(Base):
    __tablename__ = "inventory_sync_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    unavailable_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["InventorySyncItem"]] = relationship("InventorySyncItem", back_populates="batch", cascade="all, delete-orphan")


class InventorySyncItem(Base):
    __tablename__ = "inventory_sync_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("inventory_sync_batches.id"))
    catalog_product_id: Mapped[int] = mapped_column(Integer, ForeignKey("catalog_products.id"))
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"))
    gigab2b_product_id: Mapped[str | None] = mapped_column(String(50))
    item_code: Mapped[str | None] = mapped_column(String(100))
    old_stock: Mapped[int | None] = mapped_column(Integer)
    new_stock: Mapped[int | None] = mapped_column(Integer)
    availability_status: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    batch: Mapped["InventorySyncBatch"] = relationship("InventorySyncBatch", back_populates="items")
    catalog_product: Mapped["CatalogProduct"] = relationship("CatalogProduct", back_populates="inventory_sync_items")


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
    gigab2b_raw_snapshot: Mapped[str | None] = mapped_column(Text) # JSON，保留采集原始关键字段
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
    listing_description: Mapped[str | None] = mapped_column(Text)
    listing_description_zh: Mapped[str | None] = mapped_column(Text)
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
    image_selection_analysis: Mapped[str | None] = mapped_column(Text)  # JSON
    image_selected_at: Mapped[datetime | None] = mapped_column(DateTime)

    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
    vlm_model: Mapped[str] = mapped_column(String(50), default="gpt-5.5")

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


class GigaSyncBatch(Base):
    __tablename__ = "giga_sync_batches"
    __table_args__ = (UniqueConstraint("batch_id", "site", "data_source_id", name="uq_giga_sync_batches_batch_site"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(String(100))
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    data_source_name: Mapped[str | None] = mapped_column(String(100))
    fulfillment_mode: Mapped[str | None] = mapped_column(String(30))
    current_category: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    raw_sku_count: Mapped[int] = mapped_column(Integer, default=0)
    sku_count: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    price_count: Mapped[int] = mapped_column(Integer, default=0)
    inventory_count: Mapped[int] = mapped_column(Integer, default=0)
    group_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_single_sku_group_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class GigaRawSkuDetail(Base):
    __tablename__ = "giga_raw_sku_details"
    __table_args__ = (UniqueConstraint("batch_id", "site", "data_source_id", "sku_code", name="uq_giga_raw_sku_details_batch_site_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    pulled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class GigaItem(Base):
    __tablename__ = "giga_items"
    __table_args__ = (UniqueConstraint("batch_id", "site", "data_source_id", "item_code", name="uq_giga_items_batch_site_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    data_source_name: Mapped[str | None] = mapped_column(String(100))
    fulfillment_mode: Mapped[str | None] = mapped_column(String(30))
    item_code: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_sku_code: Mapped[str | None] = mapped_column(String(100))
    item_name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(200))
    sku_count: Mapped[int] = mapped_column(Integer, default=0)
    sku_codes_json: Mapped[str | None] = mapped_column(Text)
    missing_related_skus_json: Mapped[str | None] = mapped_column(Text)
    raw_group_json: Mapped[str | None] = mapped_column(Text)
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    skus: Mapped[list["GigaSku"]] = relationship("GigaSku", back_populates="item")


class GigaSku(Base):
    __tablename__ = "giga_skus"
    __table_args__ = (UniqueConstraint("batch_id", "site", "data_source_id", "sku_code", name="uq_giga_skus_batch_site_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giga_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("giga_items.id"))
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    data_source_name: Mapped[str | None] = mapped_column(String(100))
    fulfillment_mode: Mapped[str | None] = mapped_column(String(30))
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(100))
    parent_sku_code: Mapped[str | None] = mapped_column(String(100))
    parentage: Mapped[str | None] = mapped_column(String(20))
    child_sequence: Mapped[int | None] = mapped_column(Integer)
    is_primary_child: Mapped[int | None] = mapped_column(Integer)
    product_name: Mapped[str | None] = mapped_column(Text)
    main_image_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    attributes_json: Mapped[str | None] = mapped_column(Text)
    variation_attributes_json: Mapped[str | None] = mapped_column(Text)
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    item: Mapped["GigaItem | None"] = relationship("GigaItem", back_populates="skus")


class GigaProductImage(Base):
    __tablename__ = "giga_product_images"
    __table_args__ = (
        UniqueConstraint("batch_id", "site", "data_source_id", "sku_code", "url_hash", name="uq_giga_product_images_batch_site_sku_url_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    item_code: Mapped[str | None] = mapped_column(String(100))
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text)
    image_type: Mapped[str | None] = mapped_column(String(50))
    sort_order: Mapped[int | None] = mapped_column(Integer)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    download_status: Mapped[str] = mapped_column(String(30), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    pulled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class GigaPrice(Base):
    __tablename__ = "giga_prices"
    __table_args__ = (UniqueConstraint("batch_id", "site", "data_source_id", "sku_code", name="uq_giga_prices_batch_site_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    fulfillment_mode: Mapped[str | None] = mapped_column(String(30))
    shipping_cost_mode: Mapped[str | None] = mapped_column(String(30))
    packing_fee: Mapped[float | None] = mapped_column(Float)
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str | None] = mapped_column(String(20))
    price: Mapped[float | None] = mapped_column(Float)
    exclusive_price: Mapped[float | None] = mapped_column(Float)
    discounted_price: Mapped[float | None] = mapped_column(Float)
    effective_price: Mapped[float | None] = mapped_column(Float)
    shipping_fee: Mapped[float | None] = mapped_column(Float)
    shipping_fee_min: Mapped[float | None] = mapped_column(Float)
    shipping_fee_max: Mapped[float | None] = mapped_column(Float)
    estimated_shipping_fee: Mapped[float | None] = mapped_column(Float)
    map_price: Mapped[float | None] = mapped_column(Float)
    srp_price: Mapped[str | None] = mapped_column(String(100))
    future_map_price: Mapped[float | None] = mapped_column(Float)
    exclusive_price_expire_time: Mapped[str | None] = mapped_column(String(100))
    promotion_from: Mapped[str | None] = mapped_column(String(100))
    promotion_to: Mapped[str | None] = mapped_column(String(100))
    purchase_limit: Mapped[str | None] = mapped_column(String(100))
    sku_available: Mapped[int | None] = mapped_column(Integer)
    seller_info_json: Mapped[str | None] = mapped_column(Text)
    spot_price_json: Mapped[str | None] = mapped_column(Text)
    rebates_price_json: Mapped[str | None] = mapped_column(Text)
    margin_price_json: Mapped[str | None] = mapped_column(Text)
    future_price_json: Mapped[str | None] = mapped_column(Text)
    raw_price_json: Mapped[str | None] = mapped_column(Text)
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    pulled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class GigaPriceAlert(Base):
    __tablename__ = "giga_price_alerts"
    __table_args__ = (
        UniqueConstraint("batch_id", "site", "data_source_id", "sku_code", "change_type", name="uq_giga_price_alert_batch_site_sku_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(100))
    product_name: Mapped[str | None] = mapped_column(Text)
    previous_batch_id: Mapped[str | None] = mapped_column(String(100))
    previous_effective_price: Mapped[float | None] = mapped_column(Float)
    current_effective_price: Mapped[float | None] = mapped_column(Float)
    previous_price: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)
    previous_exclusive_price: Mapped[float | None] = mapped_column(Float)
    current_exclusive_price: Mapped[float | None] = mapped_column(Float)
    previous_discounted_price: Mapped[float | None] = mapped_column(Float)
    current_discounted_price: Mapped[float | None] = mapped_column(Float)
    previous_shipping_fee: Mapped[float | None] = mapped_column(Float)
    current_shipping_fee: Mapped[float | None] = mapped_column(Float)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class GigaInventory(Base):
    __tablename__ = "giga_inventory"
    __table_args__ = (UniqueConstraint("batch_id", "site", "data_source_id", "sku_code", name="uq_giga_inventory_batch_site_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    fulfillment_mode: Mapped[str | None] = mapped_column(String(30))
    inventory_mode: Mapped[str | None] = mapped_column(String(30))
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(100))
    stock_qty: Mapped[int | None] = mapped_column(Integer)
    seller_available_inventory: Mapped[int | None] = mapped_column(Integer)
    total_buyer_available_inventory: Mapped[int | None] = mapped_column(Integer)
    seller_inventory_distribution: Mapped[str | None] = mapped_column(Text)
    buyer_inventory_distribution: Mapped[str | None] = mapped_column(Text)
    next_arrival_inventory: Mapped[str | None] = mapped_column(Text)
    availability_status: Mapped[str | None] = mapped_column(String(30))
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    pulled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class GigaInventoryAlert(Base):
    __tablename__ = "giga_inventory_alerts"
    __table_args__ = (
        UniqueConstraint("batch_id", "site", "data_source_id", "sku_code", "change_type", name="uq_giga_inventory_alert_batch_site_sku_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(100))
    product_name: Mapped[str | None] = mapped_column(Text)
    previous_batch_id: Mapped[str | None] = mapped_column(String(100))
    previous_stock_qty: Mapped[int | None] = mapped_column(Integer)
    current_stock_qty: Mapped[int | None] = mapped_column(Integer)
    previous_status: Mapped[str | None] = mapped_column(String(30))
    current_status: Mapped[str | None] = mapped_column(String(30))
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(30), default="GIGA")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class GigaGroup(Base):
    __tablename__ = "giga_groups"
    __table_args__ = (UniqueConstraint("batch_id", "site", "data_source_id", "group_code", name="uq_giga_groups_batch_site_group"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site: Mapped[str] = mapped_column(String(20), nullable=False)
    data_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("product_data_sources.id"))
    data_source_name: Mapped[str | None] = mapped_column(String(100))
    fulfillment_mode: Mapped[str | None] = mapped_column(String(30))
    group_code: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_sku_code: Mapped[str | None] = mapped_column(String(100))
    current_category: Mapped[str | None] = mapped_column(String(200))
    item_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    sku_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_related_skus_json: Mapped[str | None] = mapped_column(Text)
    variation_keys_json: Mapped[str | None] = mapped_column(Text)
    group_size: Mapped[int] = mapped_column(Integer, default=0)
    deleted_single_sku_group: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AmazonCompetitorSearchCandidate(Base):
    __tablename__ = "amazon_competitor_search_candidates"
    __table_args__ = (
        UniqueConstraint("product_id", "asin", name="uq_amazon_competitor_search_product_asin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    task_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("task_runs.id"))
    task_step_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("task_steps.id"))
    source_data_source_id: Mapped[int | None] = mapped_column(Integer)
    source_site: Mapped[str | None] = mapped_column(String(20))
    source_batch_id: Mapped[str | None] = mapped_column(String(100))
    item_code: Mapped[str | None] = mapped_column(String(100))
    sku_code: Mapped[str | None] = mapped_column(String(100))
    search_query: Mapped[str] = mapped_column(String(500), nullable=False)
    query_intent: Mapped[str | None] = mapped_column(String(80))
    query_index: Mapped[int | None] = mapped_column(Integer)
    search_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="amazon_search_page")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime)
    asin: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(String(100))
    rating: Mapped[str | None] = mapped_column(String(100))
    review_count: Mapped[str | None] = mapped_column(String(100))
    sponsored: Mapped[int] = mapped_column(Integer, default=0)
    is_accessory: Mapped[int] = mapped_column(Integer, default=0)
    is_replacement_part: Mapped[int] = mapped_column(Integer, default=0)
    is_cover_only: Mapped[int] = mapped_column(Integer, default=0)
    is_excluded: Mapped[int] = mapped_column(Integer, default=0)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    raw_candidate_json: Mapped[str | None] = mapped_column(Text)
    raw_search_page_json: Mapped[str | None] = mapped_column(Text)
    visual_similarity_score: Mapped[float | None] = mapped_column(Float)
    visual_same_product_type: Mapped[int | None] = mapped_column(Integer)
    visual_attribute_match_score: Mapped[float | None] = mapped_column(Float)
    visual_title_match_score: Mapped[float | None] = mapped_column(Float)
    visual_reject: Mapped[int | None] = mapped_column(Integer)
    visual_reject_reason: Mapped[str | None] = mapped_column(Text)
    visual_reason: Mapped[str | None] = mapped_column(Text)
    visual_sheet_path: Mapped[str | None] = mapped_column(Text)
    visual_sheet_page: Mapped[int | None] = mapped_column(Integer)
    visual_sheet_label: Mapped[str | None] = mapped_column(String(40))
    visual_rank: Mapped[int | None] = mapped_column(Integer)
    visual_selected_for_capture: Mapped[int] = mapped_column(Integer, default=0)
    visual_exclusion_reason: Mapped[str | None] = mapped_column(Text)
    visual_model: Mapped[str | None] = mapped_column(String(100))
    visual_raw_json: Mapped[str | None] = mapped_column(Text)
    visual_matched_at: Mapped[datetime | None] = mapped_column(DateTime)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    product: Mapped["Product"] = relationship("Product", back_populates="competitor_search_candidates")
