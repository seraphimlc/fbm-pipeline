from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime
from typing import Any

from .common import ContractError, canonical_json_bytes, canonical_sha256_hex


DATABASE_SOURCE_MANIFEST_SCHEMA = "integration_hardening_database_source_manifest_v1"
DATABASE_SOURCE_MANIFEST_GENERATION = 1
LEGACY_PROJECTION_VERSION = "legacy_stylesnap_projection_v1"
_GENERATION_ONE_I64_MIN = -(1 << 63)
_GENERATION_ONE_U64_MAX = (1 << 64) - 1

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema",
        "generation",
        "source",
        "table_snapshots",
        "projection_snapshots",
        "backup",
        "consistency_proof",
    }
)
_SOURCE_FIELDS = frozenset(
    {"server_uuid", "server_version", "source_schema", "snapshot_utc"}
)
_TABLE_FIELDS = frozenset(
    {
        "table_name",
        "row_count",
        "primary_key_columns",
        "primary_key_min",
        "primary_key_max",
        "canonical_checksum_sha256",
    }
)
_PROJECTION_FIELDS = frozenset(
    {
        "projection_id",
        "projection_version",
        "row_count",
        "canonical_checksum_sha256",
    }
)
_BACKUP_FIELDS = frozenset(
    {
        "dump_mode",
        "tool",
        "backup_sha256",
        "archive_members",
        "archive_member_manifest_sha256",
        "snapshot_position",
    }
)
_TOOL_FIELDS = frozenset({"name", "version", "argv_safe_summary"})
_ARCHIVE_MEMBER_FIELDS = frozenset({"relative_path", "size_bytes", "sha256"})
_SNAPSHOT_POSITION_FIELDS = frozenset({"kind", "value"})
_CONSISTENCY_PROOF_FIELDS = frozenset(
    {
        "proof_mode",
        "manifest_snapshot_position",
        "writer_quiesced",
        "global_read_lock_held",
        "storage_snapshot_id",
    }
)

_GENERATION_ONE_TABLE_SNAPSHOT_NAMES = frozenset(
    {
        "aplus_upload_items",
        "amazon_listing_captures",
        "amazon_stylesnap_candidates",
        "catalog_products",
        "product_data",
        "products",
    }
)
_REQUIRED_PROJECTIONS = (
    "amazon_listing_captures",
    "amazon_stylesnap_candidates",
    "aplus_upload_items.success",
    "catalog_products.downstream",
    "product_data.matching_and_template",
    "products.workflow",
)
_PROJECTION_SOURCE_TABLE = {
    "aplus_upload_items.success": "aplus_upload_items",
    "amazon_listing_captures": "amazon_listing_captures",
    "amazon_stylesnap_candidates": "amazon_stylesnap_candidates",
    "catalog_products.downstream": "catalog_products",
    "product_data.matching_and_template": "product_data",
    "products.workflow": "products",
}
_GENERATION_ONE_TOOL_OPTIONS = {
    "mysqldump": frozenset({"--single-transaction", "--set-gtid-purged=OFF"}),
    "xtrabackup": frozenset({"--backup", "--compress"}),
}
_GENERATION_ONE_DUMP_MODE_POLICY = {
    "logical_single_transaction": (
        "mysqldump",
        frozenset({"--single-transaction"}),
    ),
    "physical_archive": (
        "xtrabackup",
        frozenset({"--backup"}),
    ),
}
_DUMP_MODES = frozenset(_GENERATION_ONE_DUMP_MODE_POLICY)
_SNAPSHOT_POSITION_KINDS = frozenset(
    {
        "mysql_gtid",
        "mysql_binlog",
        "storage_snapshot",
        "fixture_copy",
        "historical_archive_sha256",
    }
)

_ASCII_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_]+\Z")
_PROTECTED_SOURCE_SCHEMA_RE = re.compile(r"fbm_pipeline_ih_[0-9a-f]{16}_source\Z")
_LOWER_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_UTC_MICROSECOND_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_SENSITIVE_RE = re.compile(
    r"secret|credential|password|token|authorization|database_url|defaults-file",
    re.IGNORECASE,
)
_WINDOWS_ABSOLUTE_RE = re.compile(r"[A-Za-z]:[\\/]")
_DETACHED_DIGEST_RE = re.compile(rb"[0-9a-f]{64}\n\Z")


def _require_exact_fields(value: Any, expected: frozenset[str], *, path: str) -> dict:
    if type(value) is not dict:
        raise ContractError(f"{path}: expected an object")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractError(f"{path}: field mismatch; missing={missing}, extra={extra}")
    return value


def _require_printable_ascii(value: Any, *, path: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{path}: expected a non-empty printable ASCII string")
    if not value.isascii() or any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise ContractError(f"{path}: expected a non-empty printable ASCII string")
    return value


def _require_ascii_identifier(value: Any, *, path: str) -> str:
    if type(value) is not str or _ASCII_IDENTIFIER_RE.fullmatch(value) is None:
        raise ContractError(f"{path}: expected an ASCII identifier")
    return value


def _require_nonnegative_int(value: Any, *, path: str) -> int:
    if type(value) is not int or not 0 <= value <= _GENERATION_ONE_U64_MAX:
        raise ContractError(f"{path}: expected an integer in generation 1 range 0..2^64-1")
    return value


def _require_lower_sha256(value: Any, *, path: str) -> str:
    if type(value) is not str or _LOWER_SHA256_RE.fullmatch(value) is None:
        raise ContractError(f"{path}: expected 64 lowercase hexadecimal characters")
    return value


def _reject_sensitive_or_url(value: str, *, path: str) -> None:
    if _SENSITIVE_RE.search(value):
        raise ContractError(f"{path}: secret or credential material is forbidden")
    if _URL_RE.search(value):
        raise ContractError(f"{path}: URL material is forbidden")


def _validate_source(source: Any) -> None:
    source = _require_exact_fields(source, _SOURCE_FIELDS, path="$.source")
    server_uuid = source["server_uuid"]
    if type(server_uuid) is not str:
        raise ContractError("$.source.server_uuid: expected a canonical lowercase UUID")
    try:
        parsed_uuid = uuid.UUID(server_uuid)
    except (AttributeError, ValueError) as exc:
        raise ContractError("$.source.server_uuid: expected a canonical lowercase UUID") from exc
    if str(parsed_uuid) != server_uuid:
        raise ContractError("$.source.server_uuid: expected a canonical lowercase UUID")

    _require_printable_ascii(source["server_version"], path="$.source.server_version")
    _require_ascii_identifier(source["source_schema"], path="$.source.source_schema")
    timestamp = source["snapshot_utc"]
    if type(timestamp) is not str or _UTC_MICROSECOND_RE.fullmatch(timestamp) is None:
        raise ContractError(
            "$.source.snapshot_utc: expected RFC3339 UTC with exactly six fractional digits"
        )
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ContractError("$.source.snapshot_utc: invalid UTC timestamp") from exc


def _validate_primary_key_value(value: Any, *, path: str) -> None:
    if value is None or type(value) is str:
        return
    if type(value) is int:
        if _GENERATION_ONE_I64_MIN <= value <= _GENERATION_ONE_U64_MAX:
            return
        raise ContractError(
            f"{path}: integer primary-key bound must be in generation 1 range -2^63..2^64-1"
        )
    raise ContractError(f"{path}: expected only integer, string, or null")


def _validate_table_snapshots(table_snapshots: Any) -> set[str]:
    if type(table_snapshots) is not list or not table_snapshots:
        raise ContractError("$.table_snapshots: expected a non-empty array")

    table_names: list[str] = []
    for index, table in enumerate(table_snapshots):
        path = f"$.table_snapshots[{index}]"
        table = _require_exact_fields(table, _TABLE_FIELDS, path=path)
        table_name = _require_ascii_identifier(table["table_name"], path=f"{path}.table_name")
        table_names.append(table_name)
        row_count = _require_nonnegative_int(table["row_count"], path=f"{path}.row_count")

        columns = table["primary_key_columns"]
        if type(columns) is not list or not columns:
            raise ContractError(f"{path}.primary_key_columns: expected a non-empty array")
        validated_columns = [
            _require_ascii_identifier(column, path=f"{path}.primary_key_columns[{column_index}]")
            for column_index, column in enumerate(columns)
        ]
        if len(validated_columns) != len(set(validated_columns)):
            raise ContractError(f"{path}.primary_key_columns: values must be unique")

        primary_key_min = table["primary_key_min"]
        primary_key_max = table["primary_key_max"]
        if type(primary_key_min) is not list or len(primary_key_min) != len(validated_columns):
            raise ContractError(f"{path}.primary_key_min: arity must match primary_key_columns")
        if type(primary_key_max) is not list or len(primary_key_max) != len(validated_columns):
            raise ContractError(f"{path}.primary_key_max: arity must match primary_key_columns")
        for bound_name, values in (("primary_key_min", primary_key_min), ("primary_key_max", primary_key_max)):
            for value_index, value in enumerate(values):
                _validate_primary_key_value(value, path=f"{path}.{bound_name}[{value_index}]")
            if row_count == 0 and any(value is not None for value in values):
                raise ContractError(f"{path}.{bound_name}: empty tables require all-null bounds")
            if row_count > 0 and any(value is None for value in values):
                raise ContractError(f"{path}.{bound_name}: non-empty tables forbid null bounds")

        _require_lower_sha256(
            table["canonical_checksum_sha256"],
            path=f"{path}.canonical_checksum_sha256",
        )

    if table_names != sorted(table_names):
        raise ContractError("$.table_snapshots: entries must be strictly sorted by table_name")
    if len(table_names) != len(set(table_names)):
        raise ContractError("$.table_snapshots: table_name values must be unique")
    actual_table_names = set(table_names)
    missing_tables = sorted(_GENERATION_ONE_TABLE_SNAPSHOT_NAMES - actual_table_names)
    extra_tables = sorted(actual_table_names - _GENERATION_ONE_TABLE_SNAPSHOT_NAMES)
    if missing_tables or extra_tables:
        raise ContractError(
            "$.table_snapshots: generation 1 table set mismatch; "
            f"missing={missing_tables}, extra={extra_tables}"
        )
    return actual_table_names


def _validate_projection_snapshots(projection_snapshots: Any, table_names: set[str]) -> None:
    if type(projection_snapshots) is not list:
        raise ContractError("$.projection_snapshots: expected an array")

    projection_ids: list[str] = []
    for index, projection in enumerate(projection_snapshots):
        path = f"$.projection_snapshots[{index}]"
        projection = _require_exact_fields(projection, _PROJECTION_FIELDS, path=path)
        projection_id = projection["projection_id"]
        if type(projection_id) is not str or not projection_id:
            raise ContractError(f"{path}.projection_id: expected a non-empty string")
        projection_ids.append(projection_id)
        if projection["projection_version"] != LEGACY_PROJECTION_VERSION:
            raise ContractError(
                f"{path}.projection_version: expected {LEGACY_PROJECTION_VERSION}"
            )
        _require_nonnegative_int(projection["row_count"], path=f"{path}.row_count")
        _require_lower_sha256(
            projection["canonical_checksum_sha256"],
            path=f"{path}.canonical_checksum_sha256",
        )

    if projection_ids != sorted(projection_ids):
        raise ContractError(
            "$.projection_snapshots: entries must be strictly sorted by projection_id"
        )
    if tuple(projection_ids) != _REQUIRED_PROJECTIONS:
        missing = sorted(set(_REQUIRED_PROJECTIONS) - set(projection_ids))
        extra = sorted(set(projection_ids) - set(_REQUIRED_PROJECTIONS))
        raise ContractError(
            f"$.projection_snapshots: projection set mismatch; missing={missing}, extra={extra}"
        )
    for projection_id, source_table in _PROJECTION_SOURCE_TABLE.items():
        if source_table not in table_names:
            raise ContractError(
                f"$.projection_snapshots: {projection_id} requires source table {source_table}"
            )


def _validate_argv_safe_summary(value: Any, *, tool_name: str, path: str) -> list[str]:
    if type(value) is not list or not value:
        raise ContractError(f"{path}: expected a non-empty printable ASCII token array")
    allowed_options = _GENERATION_ONE_TOOL_OPTIONS.get(tool_name)
    if allowed_options is None:
        raise ContractError(f"$.backup.tool.name: unsupported generation 1 backup tool {tool_name!r}")
    tokens = [
        _require_printable_ascii(token, path=f"{path}[{index}]")
        for index, token in enumerate(value)
    ]
    if tokens[0] != tool_name:
        raise ContractError(f"{path}[0]: must exactly match $.backup.tool.name")
    for index, option in enumerate(tokens[1:], start=1):
        if option not in allowed_options:
            raise ContractError(
                f"{path}[{index}]: option is not approved for generation 1 tool {tool_name}"
            )
    return tokens


def _validate_archive_relative_path(value: Any, *, path: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{path}: expected a non-empty archive-relative UTF-8 path")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ContractError(f"{path}: Unicode surrogates are forbidden") from exc
    if value.startswith(("/", "\\", "~")) or _WINDOWS_ABSOLUTE_RE.match(value):
        raise ContractError(f"{path}: absolute paths are forbidden")
    if "\\" in value:
        raise ContractError(f"{path}: backslashes are forbidden")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ContractError(f"{path}: C0 and DEL control characters are forbidden")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ContractError(f"{path}: empty, dot, and traversal segments are forbidden")
    return value


def _validate_archive_members(value: Any) -> list[dict]:
    if type(value) is not list or not value:
        raise ContractError("$.backup.archive_members: expected a non-empty array")
    relative_paths: list[str] = []
    for index, member in enumerate(value):
        path = f"$.backup.archive_members[{index}]"
        member = _require_exact_fields(member, _ARCHIVE_MEMBER_FIELDS, path=path)
        relative_paths.append(
            _validate_archive_relative_path(member["relative_path"], path=f"{path}.relative_path")
        )
        _require_nonnegative_int(member["size_bytes"], path=f"{path}.size_bytes")
        _require_lower_sha256(member["sha256"], path=f"{path}.sha256")
    if relative_paths != sorted(relative_paths):
        raise ContractError("$.backup.archive_members: entries must be strictly sorted by relative_path")
    if len(relative_paths) != len(set(relative_paths)):
        raise ContractError("$.backup.archive_members: relative_path values must be unique")
    return value


def _validate_snapshot_position(value: Any, *, path: str) -> dict:
    value = _require_exact_fields(value, _SNAPSHOT_POSITION_FIELDS, path=path)
    if type(value["kind"]) is not str or value["kind"] not in _SNAPSHOT_POSITION_KINDS:
        raise ContractError(f"{path}.kind: unsupported snapshot position kind")
    position = _require_printable_ascii(value["value"], path=f"{path}.value")
    _reject_sensitive_or_url(position, path=f"{path}.value")
    if value["kind"] == "historical_archive_sha256":
        _require_lower_sha256(position, path=f"{path}.value")
    return value


def _validate_backup(backup: Any) -> dict:
    backup = _require_exact_fields(backup, _BACKUP_FIELDS, path="$.backup")
    dump_mode = backup["dump_mode"]
    if type(dump_mode) is not str or dump_mode not in _DUMP_MODES:
        raise ContractError("$.backup.dump_mode: unsupported dump mode")

    tool = _require_exact_fields(backup["tool"], _TOOL_FIELDS, path="$.backup.tool")
    tool_name = _require_printable_ascii(tool["name"], path="$.backup.tool.name")
    _require_printable_ascii(tool["version"], path="$.backup.tool.version")
    argv = _validate_argv_safe_summary(
        tool["argv_safe_summary"],
        tool_name=tool_name,
        path="$.backup.tool.argv_safe_summary",
    )
    expected_tool, required_options = _GENERATION_ONE_DUMP_MODE_POLICY[dump_mode]
    if tool_name != expected_tool:
        raise ContractError(
            f"$.backup.tool.name: {dump_mode} requires generation 1 tool {expected_tool}"
        )
    missing_options = sorted(required_options - set(argv[1:]))
    if missing_options:
        raise ContractError(
            "$.backup.tool.argv_safe_summary: missing generation 1 required options "
            f"for {dump_mode}: {missing_options}"
        )

    _require_lower_sha256(backup["backup_sha256"], path="$.backup.backup_sha256")
    archive_members = _validate_archive_members(backup["archive_members"])
    member_manifest_sha = _require_lower_sha256(
        backup["archive_member_manifest_sha256"],
        path="$.backup.archive_member_manifest_sha256",
    )
    if member_manifest_sha != canonical_sha256_hex(archive_members):
        raise ContractError(
            "$.backup.archive_member_manifest_sha256: does not bind canonical archive_members"
        )
    _validate_snapshot_position(backup["snapshot_position"], path="$.backup.snapshot_position")
    return backup


def _validate_consistency_proof(proof: Any, backup: dict, source: dict) -> None:
    proof = _require_exact_fields(proof, _CONSISTENCY_PROOF_FIELDS, path="$.consistency_proof")
    manifest_position = _validate_snapshot_position(
        proof["manifest_snapshot_position"],
        path="$.consistency_proof.manifest_snapshot_position",
    )
    backup_position = backup["snapshot_position"]
    if manifest_position != backup_position:
        raise ContractError(
            "$.consistency_proof.manifest_snapshot_position: must exactly match backup.snapshot_position"
        )

    if backup["dump_mode"] == "logical_single_transaction":
        proof_mode = proof["proof_mode"]
        if proof_mode == "logical_single_transaction_global_read_lock":
            if backup_position["kind"] not in {"mysql_gtid", "mysql_binlog"}:
                raise ContractError(
                    "$.backup.snapshot_position.kind: locked logical proof requires mysql_gtid or mysql_binlog"
                )
            if proof["writer_quiesced"] is not True:
                raise ContractError("$.consistency_proof.writer_quiesced: logical proof requires true")
            if proof["global_read_lock_held"] is not True:
                raise ContractError(
                    "$.consistency_proof.global_read_lock_held: locked logical proof requires true"
                )
            if proof["storage_snapshot_id"] is not None:
                raise ContractError(
                    "$.consistency_proof.storage_snapshot_id: logical proof requires null"
                )
            return
        if proof_mode == "fixture_quiesced_logical_backup":
            if _PROTECTED_SOURCE_SCHEMA_RE.fullmatch(source["source_schema"]) is None:
                raise ContractError(
                    "$.source.source_schema: fixture proof requires a protected temporary source schema"
                )
            if backup_position["kind"] != "fixture_copy":
                raise ContractError(
                    "$.backup.snapshot_position.kind: fixture proof requires fixture_copy"
                )
            if proof["writer_quiesced"] is not True:
                raise ContractError("$.consistency_proof.writer_quiesced: fixture proof requires true")
            if proof["global_read_lock_held"] is not False:
                raise ContractError(
                    "$.consistency_proof.global_read_lock_held: fixture proof requires false"
                )
            if proof["storage_snapshot_id"] is not None:
                raise ContractError(
                    "$.consistency_proof.storage_snapshot_id: fixture proof requires null"
                )
            return
        if proof_mode == "historical_archive_restored_quiesced_logical_backup":
            if _PROTECTED_SOURCE_SCHEMA_RE.fullmatch(source["source_schema"]) is None:
                raise ContractError(
                    "$.source.source_schema: historical archive proof requires a protected temporary source schema"
                )
            if backup_position["kind"] != "historical_archive_sha256":
                raise ContractError(
                    "$.backup.snapshot_position.kind: historical archive proof requires historical_archive_sha256"
                )
            _require_lower_sha256(
                backup_position["value"],
                path="$.backup.snapshot_position.value",
            )
            if proof["writer_quiesced"] is not True:
                raise ContractError(
                    "$.consistency_proof.writer_quiesced: historical archive proof requires true"
                )
            if proof["global_read_lock_held"] is not False:
                raise ContractError(
                    "$.consistency_proof.global_read_lock_held: historical archive proof requires false"
                )
            if proof["storage_snapshot_id"] is not None:
                raise ContractError(
                    "$.consistency_proof.storage_snapshot_id: historical archive proof requires null"
                )
            return
        raise ContractError("$.consistency_proof.proof_mode: invalid logical proof mode")

    if proof["proof_mode"] != "physical_atomic_snapshot":
        raise ContractError("$.consistency_proof.proof_mode: invalid physical proof mode")
    if backup_position["kind"] != "storage_snapshot":
        raise ContractError(
            "$.backup.snapshot_position.kind: physical proof requires storage_snapshot"
        )
    if proof["writer_quiesced"] is not None:
        raise ContractError("$.consistency_proof.writer_quiesced: physical proof requires null")
    if proof["global_read_lock_held"] is not None:
        raise ContractError(
            "$.consistency_proof.global_read_lock_held: physical proof requires null"
        )
    storage_snapshot_id = _require_printable_ascii(
        proof["storage_snapshot_id"],
        path="$.consistency_proof.storage_snapshot_id",
    )
    _reject_sensitive_or_url(
        storage_snapshot_id,
        path="$.consistency_proof.storage_snapshot_id",
    )
    if storage_snapshot_id != backup_position["value"]:
        raise ContractError(
            "$.consistency_proof.storage_snapshot_id: must match storage snapshot position"
        )


def _validate_database_source_manifest_body(body: Any) -> dict:
    canonical_json_bytes(body)
    body = _require_exact_fields(body, _TOP_LEVEL_FIELDS, path="$")
    if body["schema"] != DATABASE_SOURCE_MANIFEST_SCHEMA:
        raise ContractError(f"$.schema: expected {DATABASE_SOURCE_MANIFEST_SCHEMA}")
    if type(body["generation"]) is not int or body["generation"] != DATABASE_SOURCE_MANIFEST_GENERATION:
        raise ContractError("$.generation: expected integer 1")
    _validate_source(body["source"])
    table_names = _validate_table_snapshots(body["table_snapshots"])
    _validate_projection_snapshots(body["projection_snapshots"], table_names)
    backup = _validate_backup(body["backup"])
    _validate_consistency_proof(body["consistency_proof"], backup, body["source"])
    return body


def validate_database_source_manifest_body(body: Any) -> dict:
    """Validate a source-side database manifest body without external side effects."""

    try:
        return _validate_database_source_manifest_body(body)
    except ContractError:
        raise
    except RecursionError as exc:
        raise ContractError("database source manifest nesting is too deep") from exc


def serialize_database_source_manifest_body(body: Any) -> bytes:
    """Return the validated canonical body bytes with no trailing newline."""

    validated = validate_database_source_manifest_body(body)
    return canonical_json_bytes(validated)


def database_source_manifest_sha256(body: Any) -> str:
    """Return the lowercase digest of the validated canonical manifest body."""

    validated = validate_database_source_manifest_body(body)
    return canonical_sha256_hex(validated)


def detached_database_source_manifest_digest(body: Any) -> bytes:
    """Return the exact detached digest file bytes for a validated body."""

    return database_source_manifest_sha256(body).encode("ascii") + b"\n"


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _reject_json_number(source: str) -> None:
    raise ContractError(f"JSON floats and non-finite numbers are forbidden: {source}")


def _parse_generation_one_json_integer(source: str) -> int:
    digits = source[1:] if source.startswith("-") else source
    maximum_digits = 19 if source.startswith("-") else 20
    if len(digits) > maximum_digits:
        raise ContractError(
            "JSON integer is outside generation 1 range -2^63..2^64-1"
        )
    try:
        value = int(source)
    except ValueError as exc:
        raise ContractError(f"cannot parse JSON integer: {exc}") from exc
    if not _GENERATION_ONE_I64_MIN <= value <= _GENERATION_ONE_U64_MAX:
        raise ContractError(
            "JSON integer is outside generation 1 range -2^63..2^64-1"
        )
    return value


def parse_and_verify_database_source_manifest(body_bytes: Any, digest_bytes: Any) -> dict:
    """Parse canonical bytes and verify an exact detached digest without I/O."""

    try:
        if type(body_bytes) is not bytes:
            raise ContractError("database source manifest body must be bytes")
        if type(digest_bytes) is not bytes:
            raise ContractError("database source manifest detached digest must be bytes")
        if _DETACHED_DIGEST_RE.fullmatch(digest_bytes) is None:
            raise ContractError(
                "database source manifest detached digest must be 64 lowercase hex characters plus one LF"
            )
        source = body_bytes.decode("utf-8", errors="strict")
        body = json.loads(
            source,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_int=_parse_generation_one_json_integer,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
        validated = validate_database_source_manifest_body(body)
        if canonical_json_bytes(validated) != body_bytes:
            raise ContractError("database source manifest body bytes are not canonical JSON")
        expected_digest = hashlib.sha256(body_bytes).hexdigest().encode("ascii") + b"\n"
        if not hmac.compare_digest(expected_digest, digest_bytes):
            raise ContractError("database source manifest detached digest does not match body bytes")
        return validated
    except ContractError:
        raise
    except RecursionError as exc:
        raise ContractError("database source manifest nesting is too deep") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot parse database source manifest body: {exc}") from exc
    except ValueError as exc:
        raise ContractError(f"cannot parse database source manifest JSON integer: {exc}") from exc


def verify_backup_sha256_binding(body: Any, actual_backup_sha256: Any) -> dict:
    """Verify that a separately calculated backup digest matches the body fact."""

    validated = validate_database_source_manifest_body(body)
    actual = _require_lower_sha256(actual_backup_sha256, path="actual_backup_sha256")
    if not hmac.compare_digest(actual, validated["backup"]["backup_sha256"]):
        raise ContractError("actual_backup_sha256 does not match body backup_sha256")
    return validated


def source_manifest_proves_legacy_source_empty(body: Any) -> bool:
    """Return only the source-side legacy emptiness fact; this is not restore proof."""

    validated = validate_database_source_manifest_body(body)
    table_counts = {
        table["table_name"]: table["row_count"] for table in validated["table_snapshots"]
    }
    projection_counts = {
        projection["projection_id"]: projection["row_count"]
        for projection in validated["projection_snapshots"]
    }
    return (
        table_counts["amazon_listing_captures"] == 0
        and table_counts["amazon_stylesnap_candidates"] == 0
        and all(projection_counts[projection_id] == 0 for projection_id in _REQUIRED_PROJECTIONS)
    )
