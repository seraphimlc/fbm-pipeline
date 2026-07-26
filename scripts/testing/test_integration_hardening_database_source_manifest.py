#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = ROOT / "scripts"
MODULE_PATH = SCRIPTS_ROOT / "integration_hardening" / "database_source_manifest.py"
MODULE_NAME = "integration_hardening.database_source_manifest"

SCHEMA = "integration_hardening_database_source_manifest_v1"
PROJECTION_VERSION = "legacy_stylesnap_projection_v1"
I64_MIN = -(1 << 63)
U64_MAX = (1 << 64) - 1
REQUIRED_PROJECTIONS = (
    "amazon_listing_captures",
    "amazon_stylesnap_candidates",
    "aplus_upload_items.success",
    "catalog_products.downstream",
    "product_data.matching_and_template",
    "products.workflow",
)
OUTER_FACT_FIELDS = frozenset(
    {
        "source_manifest_sha256",
        "candidate_sha",
        "database_copy_id",
        "target_schema",
        "sandbox",
        "session",
        "user",
        "url",
        "path",
        "fd",
    }
)


def canonical_oracle(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_oracle(value: object) -> str:
    return hashlib.sha256(canonical_oracle(value)).hexdigest()


def archive_member(relative_path: str, size_bytes: int, fill: str) -> dict:
    return {
        "relative_path": relative_path,
        "size_bytes": size_bytes,
        "sha256": fill * 64,
    }


def valid_logical_body() -> dict:
    members = [archive_member("database/source.sql", 4096, "9")]
    snapshot_position = {
        "kind": "mysql_gtid",
        "value": "3E11FA47-71CA-11E1-9E33-C80AA9429562:1-42",
    }
    return {
        "schema": SCHEMA,
        "generation": 1,
        "source": {
            "server_uuid": "123e4567-e89b-12d3-a456-426614174000",
            "server_version": "8.0.36",
            "source_schema": "fbm_pipeline_source_01",
            "snapshot_utc": "2026-07-25T08:09:10.123456Z",
        },
        "table_snapshots": sorted([
            {
                "table_name": "aplus_upload_items",
                "row_count": 0,
                "primary_key_columns": ["id"],
                "primary_key_min": [None],
                "primary_key_max": [None],
                "canonical_checksum_sha256": "0" * 64,
            },
            {
                "table_name": "amazon_listing_captures",
                "row_count": 0,
                "primary_key_columns": ["id"],
                "primary_key_min": [None],
                "primary_key_max": [None],
                "canonical_checksum_sha256": "1" * 64,
            },
            {
                "table_name": "amazon_stylesnap_candidates",
                "row_count": 0,
                "primary_key_columns": ["id"],
                "primary_key_min": [None],
                "primary_key_max": [None],
                "canonical_checksum_sha256": "2" * 64,
            },
            {
                "table_name": "catalog_products",
                "row_count": 0,
                "primary_key_columns": ["id"],
                "primary_key_min": [None],
                "primary_key_max": [None],
                "canonical_checksum_sha256": "7" * 64,
            },
            {
                "table_name": "product_data",
                "row_count": 0,
                "primary_key_columns": ["id"],
                "primary_key_min": [None],
                "primary_key_max": [None],
                "canonical_checksum_sha256": "8" * 64,
            },
            {
                "table_name": "products",
                "row_count": 3,
                "primary_key_columns": ["id"],
                "primary_key_min": [101],
                "primary_key_max": [103],
                "canonical_checksum_sha256": "3" * 64,
            },
        ], key=lambda item: item["table_name"]),
        "projection_snapshots": sorted([
            {
                "projection_id": "aplus_upload_items.success",
                "projection_version": PROJECTION_VERSION,
                "row_count": 0,
                "canonical_checksum_sha256": "0" * 64,
            },
            {
                "projection_id": "amazon_listing_captures",
                "projection_version": PROJECTION_VERSION,
                "row_count": 0,
                "canonical_checksum_sha256": "4" * 64,
            },
            {
                "projection_id": "amazon_stylesnap_candidates",
                "projection_version": PROJECTION_VERSION,
                "row_count": 0,
                "canonical_checksum_sha256": "5" * 64,
            },
            {
                "projection_id": "catalog_products.downstream",
                "projection_version": PROJECTION_VERSION,
                "row_count": 0,
                "canonical_checksum_sha256": "7" * 64,
            },
            {
                "projection_id": "product_data.matching_and_template",
                "projection_version": PROJECTION_VERSION,
                "row_count": 0,
                "canonical_checksum_sha256": "8" * 64,
            },
            {
                "projection_id": "products.workflow",
                "projection_version": PROJECTION_VERSION,
                "row_count": 0,
                "canonical_checksum_sha256": "6" * 64,
            },
        ], key=lambda item: item["projection_id"]),
        "backup": {
            "dump_mode": "logical_single_transaction",
            "tool": {
                "name": "mysqldump",
                "version": "8.0.36",
                "argv_safe_summary": [
                    "mysqldump",
                    "--single-transaction",
                    "--set-gtid-purged=OFF",
                ],
            },
            "backup_sha256": "a" * 64,
            "archive_members": members,
            "archive_member_manifest_sha256": digest_oracle(members),
            "snapshot_position": copy.deepcopy(snapshot_position),
        },
        "consistency_proof": {
            "proof_mode": "logical_single_transaction_global_read_lock",
            "manifest_snapshot_position": copy.deepcopy(snapshot_position),
            "writer_quiesced": True,
            "global_read_lock_held": True,
            "storage_snapshot_id": None,
        },
    }


def valid_physical_body() -> dict:
    body = valid_logical_body()
    members = [
        archive_member("archive/ibdata1", 8192, "7"),
        archive_member("archive/mysql.ibd", 16384, "8"),
    ]
    snapshot_position = {"kind": "storage_snapshot", "value": "snap-fbm-20260725-0001"}
    body["backup"] = {
        "dump_mode": "physical_archive",
        "tool": {
            "name": "xtrabackup",
            "version": "8.0.35-31",
            "argv_safe_summary": ["xtrabackup", "--backup", "--compress"],
        },
        "backup_sha256": "b" * 64,
        "archive_members": members,
        "archive_member_manifest_sha256": digest_oracle(members),
        "snapshot_position": copy.deepcopy(snapshot_position),
    }
    body["consistency_proof"] = {
        "proof_mode": "physical_atomic_snapshot",
        "manifest_snapshot_position": copy.deepcopy(snapshot_position),
        "writer_quiesced": None,
        "global_read_lock_held": None,
        "storage_snapshot_id": snapshot_position["value"],
    }
    return body


def valid_fixture_body() -> dict:
    body = valid_logical_body()
    body["source"]["source_schema"] = "fbm_pipeline_ih_0123456789abcdef_source"
    position = {"kind": "fixture_copy", "value": "legacy-inventory-nonempty-v1-copy-01"}
    body["backup"]["snapshot_position"] = copy.deepcopy(position)
    body["consistency_proof"] = {
        "proof_mode": "fixture_quiesced_logical_backup",
        "manifest_snapshot_position": copy.deepcopy(position),
        "writer_quiesced": True,
        "global_read_lock_held": False,
        "storage_snapshot_id": None,
    }
    return body


def valid_historical_archive_body() -> dict:
    body = valid_logical_body()
    body["source"]["source_schema"] = "fbm_pipeline_ih_0123456789abcdef_source"
    position = {"kind": "historical_archive_sha256", "value": "c" * 64}
    body["backup"]["snapshot_position"] = copy.deepcopy(position)
    body["consistency_proof"] = {
        "proof_mode": "historical_archive_restored_quiesced_logical_backup",
        "manifest_snapshot_position": copy.deepcopy(position),
        "writer_quiesced": True,
        "global_read_lock_held": False,
        "storage_snapshot_id": None,
    }
    return body


def load_contract_module(*, fresh: bool = False):
    if not MODULE_PATH.is_file():
        raise AssertionError(f"missing database source manifest contract module: {MODULE_PATH}")
    if str(SCRIPTS_ROOT) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_ROOT))
    if fresh:
        sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


def matching_digest(body_bytes: bytes) -> bytes:
    return hashlib.sha256(body_bytes).hexdigest().encode("ascii") + b"\n"


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(item) for item in value)) if value else set()
    return set()


def assert_retired_candidate_surface_absent(
    repo_root: Path, project_rules_source: str
) -> None:
    """Fail when a retired I1/I3 candidate surface becomes active again."""

    retired_paths = (
        "scripts/integration_hardening/candidate_command_manifest.json",
        "scripts/testing/test_integration_hardening_manifest.py",
        "scripts/testing/integration_mysql.py",
        "scripts/testing/test_integration_hardening_mysql_contract.py",
    )
    for relative_path in retired_paths:
        candidate_path = repo_root / relative_path
        if candidate_path.exists() or candidate_path.is_symlink():
            raise AssertionError(f"retired candidate path is active: {relative_path}")

    retired_project_rule_identifiers = (
        "test_integration_hardening_manifest_contract_gate",
        "test_integration_hardening_mysql_contract_gate",
        "candidate_command_manifest.json",
        "test_integration_hardening_manifest.py",
        "integration_mysql.py",
        "test_integration_hardening_mysql_contract.py",
    )
    for identifier in retired_project_rule_identifiers:
        if identifier in project_rules_source:
            raise AssertionError(f"retired project-rule reference is active: {identifier}")


def side_effect_probe_script(body: dict) -> str:
    body_bytes = canonical_oracle(body)
    digest_bytes = matching_digest(body_bytes)
    script = r'''
import builtins
import importlib
import os
import socket
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

ROOT = Path(__ROOT_LITERAL__)
sys.path.insert(0, str(ROOT / "scripts"))
body = __BODY_LITERAL__
body_bytes = __BODY_BYTES_LITERAL__
digest_bytes = __DIGEST_BYTES_LITERAL__


class SideEffectObserved(RuntimeError):
    pass


calls = Counter()


def forbidden(name):
    def detect(*args, **kwargs):
        calls[name] += 1
        raise SideEffectObserved(name)

    return detect


real_builtin_open = builtins.open
real_os_open = os.open
real_path_open = Path.open
write_flags = 0
for flag_name in ("O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_TRUNC"):
    write_flags |= getattr(os, flag_name, 0)


def monitored_builtin_open(file, mode="r", *args, **kwargs):
    if isinstance(mode, str) and any(marker in mode for marker in ("w", "a", "x", "+")):
        return forbidden("file_write")(file, mode, *args, **kwargs)
    return real_builtin_open(file, mode, *args, **kwargs)


def monitored_os_open(path, flags, *args, **kwargs):
    if flags & write_flags:
        return forbidden("file_write")(path, flags, *args, **kwargs)
    return real_os_open(path, flags, *args, **kwargs)


def monitored_path_open(self, mode="r", *args, **kwargs):
    if isinstance(mode, str) and any(marker in mode for marker in ("w", "a", "x", "+")):
        return forbidden("file_write")(self, mode, *args, **kwargs)
    return real_path_open(self, mode, *args, **kwargs)


def expect_detection(name, action):
    before = calls[name]
    try:
        action()
    except SideEffectObserved as exc:
        assert str(exc) == name, (name, exc)
    else:
        raise AssertionError(f"side-effect detector failed to catch {name}")
    assert calls[name] == before + 1, (name, calls)


def safe_network_probe():
    local_socket = None
    try:
        local_socket = socket.socket()
    finally:
        if local_socket is not None:
            local_socket.close()


with tempfile.TemporaryDirectory(prefix="fbm-i2-side-effect-probe-") as temporary_root:
    with ExitStack() as stack:
        stack.enter_context(mock.patch("os.getenv", new=forbidden("env_read")))
        stack.enter_context(mock.patch.object(os._Environ, "__getitem__", new=forbidden("env_read")))
        stack.enter_context(mock.patch.object(os._Environ, "__iter__", new=forbidden("env_read")))
        stack.enter_context(mock.patch.object(os._Environ, "__len__", new=forbidden("env_read")))
        stack.enter_context(mock.patch.object(os._Environ, "__setitem__", new=forbidden("env_write")))
        stack.enter_context(mock.patch.object(os._Environ, "__delitem__", new=forbidden("env_write")))
        stack.enter_context(mock.patch("os.putenv", new=forbidden("env_write")))
        stack.enter_context(mock.patch("os.unsetenv", new=forbidden("env_write")))

        stack.enter_context(mock.patch("builtins.open", new=monitored_builtin_open))
        stack.enter_context(mock.patch("os.open", new=monitored_os_open))
        stack.enter_context(mock.patch.object(Path, "open", new=monitored_path_open))
        for name in (
            "write",
            "pwrite",
            "mkdir",
            "makedirs",
            "remove",
            "unlink",
            "rename",
            "replace",
            "truncate",
        ):
            if hasattr(os, name):
                stack.enter_context(mock.patch.object(os, name, new=forbidden("file_write")))
        for name in ("write_bytes", "write_text", "touch", "mkdir", "unlink", "rename", "replace"):
            stack.enter_context(mock.patch.object(Path, name, new=forbidden("file_write")))

        for name in ("run", "Popen", "call", "check_call", "check_output"):
            stack.enter_context(mock.patch.object(subprocess, name, new=forbidden("process")))
        for name in (
            "system",
            "popen",
            "fork",
            "forkpty",
            "posix_spawn",
            "posix_spawnp",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
        ):
            if hasattr(os, name):
                stack.enter_context(mock.patch.object(os, name, new=forbidden("process")))

        stack.enter_context(mock.patch("socket.socket", new=forbidden("network")))
        stack.enter_context(mock.patch("socket.create_connection", new=forbidden("network")))
        if hasattr(socket, "socketpair"):
            stack.enter_context(mock.patch("socket.socketpair", new=forbidden("network")))
        stack.enter_context(mock.patch("urllib.request.urlopen", new=forbidden("network")))

        expect_detection("env_read", lambda: os.environ["FBM_I2_SIDE_EFFECT_PROBE"])
        expect_detection("env_write", lambda: os.environ.__setitem__("FBM_I2_SIDE_EFFECT_PROBE", "1"))
        expect_detection(
            "file_write",
            lambda: builtins.open(Path(temporary_root) / "probe.txt", "w", encoding="utf-8"),
        )
        expect_detection("process", lambda: subprocess.run(["never-executed"]))
        expect_detection("network", safe_network_probe)
        calls.clear()

        module = importlib.import_module("integration_hardening.database_source_manifest")
        module.validate_database_source_manifest_body(body)
        module.serialize_database_source_manifest_body(body)
        module.database_source_manifest_sha256(body)
        module.detached_database_source_manifest_digest(body)
        module.parse_and_verify_database_source_manifest(body_bytes, digest_bytes)
        module.verify_backup_sha256_binding(body, "a" * 64)
        module.source_manifest_proves_legacy_source_empty(body)
        assert not calls, calls

print("SIDE_EFFECT_MONITOR_OK")
'''
    return (
        script.replace("__ROOT_LITERAL__", repr(str(ROOT)))
        .replace("__BODY_LITERAL__", repr(body))
        .replace("__BODY_BYTES_LITERAL__", repr(body_bytes))
        .replace("__DIGEST_BYTES_LITERAL__", repr(digest_bytes))
    )


class DatabaseSourceManifestContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_contract_module()

    def assert_contract_error(self, body: object) -> None:
        with self.assertRaises(self.module.ContractError):
            self.module.validate_database_source_manifest_body(body)

    def assert_parse_error(self, body_bytes: bytes, digest_bytes: bytes | None = None) -> None:
        if digest_bytes is None:
            digest_bytes = matching_digest(body_bytes)
        with self.assertRaises(self.module.ContractError):
            self.module.parse_and_verify_database_source_manifest(body_bytes, digest_bytes)

    def table(self, body: dict, name: str) -> dict:
        return next(item for item in body["table_snapshots"] if item["table_name"] == name)

    def projection(self, body: dict, projection_id: str) -> dict:
        return next(
            item for item in body["projection_snapshots"] if item["projection_id"] == projection_id
        )

    def test_valid_logical_body_has_exact_canonical_bytes_hash_and_detached_digest(self) -> None:
        body = valid_logical_body()
        expected_bytes = canonical_oracle(body)
        expected_sha = hashlib.sha256(expected_bytes).hexdigest()

        self.assertEqual(self.module.validate_database_source_manifest_body(body), body)
        self.assertEqual(self.module.serialize_database_source_manifest_body(body), expected_bytes)
        self.assertEqual(self.module.database_source_manifest_sha256(body), expected_sha)
        self.assertEqual(
            self.module.detached_database_source_manifest_digest(body),
            expected_sha.encode("ascii") + b"\n",
        )
        self.assertFalse(expected_bytes.endswith(b"\n"))

        reordered = dict(reversed(list(body.items())))
        self.assertEqual(self.module.database_source_manifest_sha256(reordered), expected_sha)

    def test_valid_physical_body_round_trips(self) -> None:
        body = valid_physical_body()
        body_bytes = canonical_oracle(body)
        digest = matching_digest(body_bytes)
        self.assertEqual(self.module.validate_database_source_manifest_body(body), body)
        self.assertEqual(
            self.module.parse_and_verify_database_source_manifest(body_bytes, digest),
            body,
        )

    def test_body_contains_only_source_backup_facts_and_rejects_outer_facts(self) -> None:
        body = valid_logical_body()
        self.assertTrue(OUTER_FACT_FIELDS.isdisjoint(all_keys(body)))
        for field in sorted(OUTER_FACT_FIELDS):
            with self.subTest(field=field):
                mutated = copy.deepcopy(body)
                mutated[field] = "forbidden"
                self.assert_contract_error(mutated)

    def test_exact_field_sets_reject_unknown_and_missing_fields_at_every_level(self) -> None:
        locations = (
            ((), "schema"),
            (("source",), "server_uuid"),
            (("table_snapshots", 0), "table_name"),
            (("projection_snapshots", 0), "projection_id"),
            (("backup",), "dump_mode"),
            (("backup", "tool"), "name"),
            (("backup", "archive_members", 0), "relative_path"),
            (("backup", "snapshot_position"), "kind"),
            (("consistency_proof",), "proof_mode"),
            (("consistency_proof", "manifest_snapshot_position"), "kind"),
        )
        for path, required_field in locations:
            with self.subTest(path=path, mutation="missing"):
                body = valid_logical_body()
                target = body
                for component in path:
                    target = target[component]
                del target[required_field]
                self.assert_contract_error(body)
            with self.subTest(path=path, mutation="unknown"):
                body = valid_logical_body()
                target = body
                for component in path:
                    target = target[component]
                target["unknown_field"] = None
                self.assert_contract_error(body)

    def test_schema_generation_uuid_schema_name_and_timestamp_fail_closed(self) -> None:
        mutations = (
            (("schema",), "wrong"),
            (("generation",), True),
            (("generation",), 2),
            (("source", "server_uuid"), "123E4567-E89B-12D3-A456-426614174000"),
            (("source", "server_uuid"), "123e4567e89b12d3a456426614174000"),
            (("source", "server_uuid"), "not-a-uuid"),
            (("source", "source_schema"), ""),
            (("source", "source_schema"), "fbm-source"),
            (("source", "source_schema"), "数据库"),
            (("source", "snapshot_utc"), "2026-07-25T08:09:10Z"),
            (("source", "snapshot_utc"), "2026-07-25T08:09:10.123456+00:00"),
            (("source", "snapshot_utc"), "2026-02-30T08:09:10.123456Z"),
            (("source", "snapshot_utc"), "2026-07-25t08:09:10.123456z"),
        )
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                body = valid_logical_body()
                target = body
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_contract_error(body)

    def test_table_snapshots_require_sorted_unique_required_tables_and_integer_counts(self) -> None:
        unsorted_body = valid_logical_body()
        unsorted_body["table_snapshots"][0], unsorted_body["table_snapshots"][1] = (
            unsorted_body["table_snapshots"][1],
            unsorted_body["table_snapshots"][0],
        )
        self.assert_contract_error(unsorted_body)

        duplicate_body = valid_logical_body()
        duplicate_body["table_snapshots"][1]["table_name"] = "amazon_listing_captures"
        self.assert_contract_error(duplicate_body)

        missing_body = valid_logical_body()
        missing_body["table_snapshots"] = missing_body["table_snapshots"][1:]
        self.assert_contract_error(missing_body)

        for value in (-1, True, 1.0, "0"):
            with self.subTest(row_count=value):
                body = valid_logical_body()
                self.table(body, "products")["row_count"] = value
                self.assert_contract_error(body)

        bad_name = valid_logical_body()
        self.table(bad_name, "products")["table_name"] = "products-v2"
        self.assert_contract_error(bad_name)

    def test_generation_one_integer_bounds_reject_out_of_range_direct_values(self) -> None:
        invalid_bodies = []

        thousand_digit_count = valid_logical_body()
        self.table(thousand_digit_count, "products")["row_count"] = 10**999
        invalid_bodies.append(("thousand_digit_row_count", thousand_digit_count))

        row_count_overflow = valid_logical_body()
        self.table(row_count_overflow, "products")["row_count"] = U64_MAX + 1
        invalid_bodies.append(("row_count_overflow", row_count_overflow))

        projection_count_overflow = valid_logical_body()
        self.projection(projection_count_overflow, "products.workflow")["row_count"] = U64_MAX + 1
        invalid_bodies.append(("projection_count_overflow", projection_count_overflow))

        size_overflow = valid_logical_body()
        size_overflow["backup"]["archive_members"][0]["size_bytes"] = U64_MAX + 1
        size_overflow["backup"]["archive_member_manifest_sha256"] = digest_oracle(
            size_overflow["backup"]["archive_members"]
        )
        invalid_bodies.append(("size_overflow", size_overflow))

        primary_key_underflow = valid_logical_body()
        self.table(primary_key_underflow, "products")["primary_key_min"] = [I64_MIN - 1]
        invalid_bodies.append(("primary_key_underflow", primary_key_underflow))

        primary_key_overflow = valid_logical_body()
        self.table(primary_key_overflow, "products")["primary_key_max"] = [U64_MAX + 1]
        invalid_bodies.append(("primary_key_overflow", primary_key_overflow))

        for label, body in invalid_bodies:
            with self.subTest(label=label):
                self.assert_contract_error(body)

    def test_generation_one_integer_bounds_accept_exact_field_boundaries(self) -> None:
        body = valid_logical_body()
        product = self.table(body, "products")
        product["row_count"] = U64_MAX
        product["primary_key_min"] = [I64_MIN]
        product["primary_key_max"] = [U64_MAX]
        self.projection(body, "products.workflow")["row_count"] = U64_MAX
        body["backup"]["archive_members"][0]["size_bytes"] = U64_MAX
        body["backup"]["archive_member_manifest_sha256"] = digest_oracle(
            body["backup"]["archive_members"]
        )

        self.assertEqual(self.module.validate_database_source_manifest_body(body), body)
        body_bytes = canonical_oracle(body)
        self.assertEqual(
            self.module.parse_and_verify_database_source_manifest(
                body_bytes,
                matching_digest(body_bytes),
            ),
            body,
        )

    def test_generation_one_table_snapshot_set_rejects_extra_tables(self) -> None:
        body = valid_logical_body()
        extra_table = copy.deepcopy(self.table(body, "products"))
        extra_table["table_name"] = "target_prerequisite"
        extra_table["canonical_checksum_sha256"] = "7" * 64
        body["table_snapshots"].append(extra_table)

        with self.assertRaises(self.module.ContractError) as caught:
            self.module.validate_database_source_manifest_body(body)
        self.assertIn("missing=[]", str(caught.exception))
        self.assertIn("extra=['target_prerequisite']", str(caught.exception))

    def test_primary_key_shape_null_semantics_and_checksums_fail_closed(self) -> None:
        mutations = []

        body = valid_logical_body()
        self.table(body, "products")["primary_key_columns"] = []
        mutations.append(body)

        body = valid_logical_body()
        product = self.table(body, "products")
        product["primary_key_columns"] = ["id", "id"]
        product["primary_key_min"] = [101, 101]
        product["primary_key_max"] = [103, 103]
        mutations.append(body)

        body = valid_logical_body()
        self.table(body, "products")["primary_key_columns"] = ["bad-column"]
        mutations.append(body)

        body = valid_logical_body()
        self.table(body, "products")["primary_key_min"] = [101, 102]
        mutations.append(body)

        body = valid_logical_body()
        self.table(body, "products")["primary_key_min"] = [True]
        mutations.append(body)

        body = valid_logical_body()
        self.table(body, "products")["primary_key_max"] = [1.5]
        mutations.append(body)

        body = valid_logical_body()
        self.table(body, "products")["primary_key_min"] = [None]
        mutations.append(body)

        body = valid_logical_body()
        self.table(body, "amazon_listing_captures")["primary_key_min"] = [0]
        mutations.append(body)

        body = valid_logical_body()
        self.table(body, "amazon_listing_captures")["primary_key_max"] = ["unexpected"]
        mutations.append(body)

        for checksum in ("A" * 64, "a" * 63, "g" * 64, 7):
            body = valid_logical_body()
            self.table(body, "products")["canonical_checksum_sha256"] = checksum
            mutations.append(body)

        for index, body in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_contract_error(body)

    def test_projection_set_sort_version_counts_and_source_table_binding_fail_closed(self) -> None:
        unsorted_body = valid_logical_body()
        unsorted_body["projection_snapshots"].reverse()
        self.assert_contract_error(unsorted_body)

        duplicate_body = valid_logical_body()
        duplicate_body["projection_snapshots"][1]["projection_id"] = "amazon_listing_captures"
        self.assert_contract_error(duplicate_body)

        missing_body = valid_logical_body()
        missing_body["projection_snapshots"].pop()
        self.assert_contract_error(missing_body)

        extra_body = valid_logical_body()
        extra_body["projection_snapshots"].append(
            {
                "projection_id": "products.workflow.v2",
                "projection_version": PROJECTION_VERSION,
                "row_count": 0,
                "canonical_checksum_sha256": "7" * 64,
            }
        )
        self.assert_contract_error(extra_body)

        for field, value in (
            ("projection_version", "legacy_stylesnap_projection_v2"),
            ("row_count", True),
            ("row_count", -1),
            ("canonical_checksum_sha256", "F" * 64),
        ):
            with self.subTest(field=field, value=value):
                body = valid_logical_body()
                self.projection(body, "products.workflow")[field] = value
                self.assert_contract_error(body)

        source_binding = valid_logical_body()
        self.table(source_binding, "products")["table_name"] = "products_future"
        self.assert_contract_error(source_binding)

    def test_backup_mode_and_snapshot_position_fields_fail_closed(self) -> None:
        for path, value in (
            (("backup", "dump_mode"), "incremental"),
            (("backup", "dump_mode"), []),
            (("backup", "backup_sha256"), "A" * 64),
            (("backup", "snapshot_position", "kind"), "unknown"),
            (("backup", "snapshot_position", "kind"), {}),
            (("backup", "snapshot_position", "value"), ""),
            (("backup", "snapshot_position", "value"), "https://db.invalid/position"),
            (("backup", "snapshot_position", "value"), "password=secret"),
            (("backup", "snapshot_position", "value"), "binlog\nposition"),
        ):
            with self.subTest(path=path, value=value):
                body = valid_logical_body()
                target = body
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_contract_error(body)

    def test_logical_consistency_matrix_requires_mysqldump_transaction_position_and_locks(self) -> None:
        mutations = (
            (("backup", "tool", "name"), "mysqlpump"),
            (("backup", "tool", "argv_safe_summary"), ["mysqldump", "--quick"]),
            (("backup", "snapshot_position", "kind"), "storage_snapshot"),
            (("consistency_proof", "proof_mode"), "physical_atomic_snapshot"),
            (("consistency_proof", "writer_quiesced"), False),
            (("consistency_proof", "writer_quiesced"), 1),
            (("consistency_proof", "global_read_lock_held"), False),
            (("consistency_proof", "storage_snapshot_id"), "snap-1"),
            (("consistency_proof", "manifest_snapshot_position", "value"), "different-position"),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                body = valid_logical_body()
                target = body
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_contract_error(body)

        binlog = valid_logical_body()
        position = {"kind": "mysql_binlog", "value": "mysql-bin.000042:731"}
        binlog["backup"]["snapshot_position"] = copy.deepcopy(position)
        binlog["consistency_proof"]["manifest_snapshot_position"] = copy.deepcopy(position)
        self.assertEqual(self.module.validate_database_source_manifest_body(binlog), binlog)

    def test_quiesced_fixture_backup_has_a_non_global_lock_proof_mode(self) -> None:
        body = valid_fixture_body()
        self.assertEqual(self.module.validate_database_source_manifest_body(body), body)
        for path, value in (
            (("backup", "snapshot_position", "kind"), "mysql_gtid"),
            (("consistency_proof", "proof_mode"), "logical_single_transaction_global_read_lock"),
            (("consistency_proof", "writer_quiesced"), False),
            (("consistency_proof", "global_read_lock_held"), True),
            (("consistency_proof", "storage_snapshot_id"), "fixture-copy"),
            (("source", "source_schema"), "fbm_pipeline"),
        ):
            with self.subTest(path=path):
                mutated = valid_fixture_body()
                target = mutated
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_contract_error(mutated)

    def test_historical_archive_proof_binds_raw_archive_hash_and_protected_source(self) -> None:
        body = valid_historical_archive_body()
        self.assertEqual(self.module.validate_database_source_manifest_body(body), body)
        body_bytes = self.module.serialize_database_source_manifest_body(body)
        self.assertEqual(
            self.module.parse_and_verify_database_source_manifest(
                body_bytes,
                matching_digest(body_bytes),
            ),
            body,
        )

        mutations = (
            (("backup", "snapshot_position", "kind"), "fixture_copy"),
            (("backup", "snapshot_position", "value"), "not-a-sha256"),
            (("consistency_proof", "proof_mode"), "fixture_quiesced_logical_backup"),
            (("consistency_proof", "writer_quiesced"), False),
            (("consistency_proof", "global_read_lock_held"), True),
            (("consistency_proof", "storage_snapshot_id"), "archive-copy"),
            (("consistency_proof", "manifest_snapshot_position", "value"), "d" * 64),
            (("source", "source_schema"), "fbm_pipeline"),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                mutated = valid_historical_archive_body()
                target = mutated
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_contract_error(mutated)

        fixture = valid_fixture_body()
        self.assertEqual(self.module.validate_database_source_manifest_body(fixture), fixture)

    def test_historical_archive_manifest_builder_selects_archive_proof_without_changing_fixture_builder(self) -> None:
        from integration_hardening.legacy_inventory_mysql import (
            build_historical_archive_source_manifest,
            build_source_manifest,
        )

        oracle = valid_historical_archive_body()
        verification_snapshot = {
            "tables": {
                item["table_name"]: {
                    "row_count": item["row_count"],
                    "primary_key_min": item["primary_key_min"],
                    "primary_key_max": item["primary_key_max"],
                    "canonical_checksum_sha256": item["canonical_checksum_sha256"],
                }
                for item in oracle["table_snapshots"]
            },
            "projections": {
                item["projection_id"]: {
                    "row_count": item["row_count"],
                    "canonical_checksum_sha256": item["canonical_checksum_sha256"],
                }
                for item in oracle["projection_snapshots"]
            },
        }
        dump_path = mock.Mock()
        dump_path.stat.return_value = SimpleNamespace(st_size=4096)
        common = {
            "source_schema": "fbm_pipeline_ih_0123456789abcdef_source",
            "server_facts": oracle["source"],
            "verification_snapshot": verification_snapshot,
            "backup_path": dump_path,
            "backup_sha256": "a" * 64,
            "tool_version": "mysqldump 9.6.0",
        }
        historical = build_historical_archive_source_manifest(
            historical_archive_sha256="c" * 64,
            **common,
        )
        self.assertEqual(
            historical["backup"]["snapshot_position"],
            {"kind": "historical_archive_sha256", "value": "c" * 64},
        )
        self.assertEqual(
            historical["consistency_proof"]["proof_mode"],
            "historical_archive_restored_quiesced_logical_backup",
        )
        fixture = build_source_manifest(database_copy_id="fixture-copy-01", **common)
        self.assertEqual(
            fixture["backup"]["snapshot_position"],
            {"kind": "fixture_copy", "value": "fixture-copy-01"},
        )
        self.assertEqual(
            fixture["consistency_proof"]["proof_mode"],
            "fixture_quiesced_logical_backup",
        )

    def test_physical_consistency_matrix_requires_atomic_storage_snapshot(self) -> None:
        mutations = (
            (("backup", "dump_mode"), "logical_single_transaction"),
            (("backup", "snapshot_position", "kind"), "mysql_gtid"),
            (("consistency_proof", "proof_mode"), "logical_single_transaction_global_read_lock"),
            (("consistency_proof", "writer_quiesced"), False),
            (("consistency_proof", "global_read_lock_held"), False),
            (("consistency_proof", "storage_snapshot_id"), None),
            (("consistency_proof", "storage_snapshot_id"), "different-snapshot"),
            (("consistency_proof", "manifest_snapshot_position", "value"), "different-snapshot"),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                body = valid_physical_body()
                target = body
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_contract_error(body)

    def test_tool_summary_uses_generation_one_closed_allowlists(self) -> None:
        invalid_tokens = (
            "-phunter2",
            "MYSQL_PWD=hunter2",
            "api_key=hunter2",
            "--password=hunter2",
            "credential=abc",
            "authorization=Bearer",
            "DATABASE_URL=mysql://db.invalid/fbm",
            "--defaults-file=/tmp/mysql.cnf",
            "https://db.invalid",
            "/tmp/backup.sql",
            "C:\\backup.sql",
            "$(whoami)",
            "value;rm",
            "left|right",
            "line\nbreak",
            "--quick",
        )
        for token in invalid_tokens:
            with self.subTest(token=token):
                body = valid_logical_body()
                body["backup"]["tool"]["argv_safe_summary"].append(token)
                self.assert_contract_error(body)

        empty = valid_logical_body()
        empty["backup"]["tool"]["argv_safe_summary"] = []
        self.assert_contract_error(empty)

        for field, value in (("name", ""), ("version", "8.0\n36")):
            body = valid_logical_body()
            body["backup"]["tool"][field] = value
            self.assert_contract_error(body)

    def test_tool_summary_rejects_unknown_tools_and_tool_argv_mismatch(self) -> None:
        logical_mismatch = valid_logical_body()
        logical_mismatch["backup"]["tool"]["argv_safe_summary"][0] = "xtrabackup"
        self.assert_contract_error(logical_mismatch)

        physical_mismatch = valid_physical_body()
        physical_mismatch["backup"]["tool"]["argv_safe_summary"][0] = "mysqldump"
        self.assert_contract_error(physical_mismatch)

        unknown_tool = valid_physical_body()
        unknown_tool["backup"]["tool"]["name"] = "mariabackup"
        unknown_tool["backup"]["tool"]["argv_safe_summary"][0] = "mariabackup"
        self.assert_contract_error(unknown_tool)

    def test_tool_summary_preserves_approved_repeated_options(self) -> None:
        logical = valid_logical_body()
        logical["backup"]["tool"]["argv_safe_summary"].append("--single-transaction")
        self.assertEqual(self.module.validate_database_source_manifest_body(logical), logical)

        physical = valid_physical_body()
        physical["backup"]["tool"]["argv_safe_summary"].append("--compress")
        self.assertEqual(self.module.validate_database_source_manifest_body(physical), physical)

    def test_generation_one_dump_mode_policy_binds_physical_tool_and_required_option(self) -> None:
        mysqldump_physical = valid_physical_body()
        mysqldump_physical["backup"]["tool"] = {
            "name": "mysqldump",
            "version": "8.0.36",
            "argv_safe_summary": ["mysqldump", "--single-transaction"],
        }
        self.assert_contract_error(mysqldump_physical)

        missing_backup_option = valid_physical_body()
        missing_backup_option["backup"]["tool"]["argv_safe_summary"] = [
            "xtrabackup",
            "--compress",
        ]
        self.assert_contract_error(missing_backup_option)

    def test_logical_policy_independently_requires_single_transaction_option(self) -> None:
        body = valid_logical_body()
        body["backup"]["tool"]["argv_safe_summary"] = [
            "mysqldump",
            "--set-gtid-purged=OFF",
        ]

        with self.assertRaises(self.module.ContractError) as caught:
            self.module.validate_database_source_manifest_body(body)
        self.assertIn("missing generation 1 required options", str(caught.exception))
        self.assertIn("--single-transaction", str(caught.exception))

    def test_archive_members_require_sorted_safe_relative_paths_sizes_hashes_and_bound_manifest(self) -> None:
        body = valid_physical_body()
        body["backup"]["archive_members"].reverse()
        body["backup"]["archive_member_manifest_sha256"] = digest_oracle(
            body["backup"]["archive_members"]
        )
        self.assert_contract_error(body)

        duplicate = valid_physical_body()
        duplicate["backup"]["archive_members"][1]["relative_path"] = "archive/ibdata1"
        duplicate["backup"]["archive_member_manifest_sha256"] = digest_oracle(
            duplicate["backup"]["archive_members"]
        )
        self.assert_contract_error(duplicate)

        for relative_path in (
            "/absolute/file.sql",
            "../escape.sql",
            "archive/../escape.sql",
            "archive//empty.sql",
            "archive\\windows.sql",
            "C:/absolute.sql",
            "archive/./dot.sql",
            "archive/\ud800.sql",
            "archive/new\nline.sql",
            "archive/tab\tfile.sql",
            "archive/carriage\rfile.sql",
            "archive/null\x00file.sql",
            "archive/delete\x7ffile.sql",
        ):
            with self.subTest(relative_path=repr(relative_path)):
                body = valid_logical_body()
                body["backup"]["archive_members"][0]["relative_path"] = relative_path
                if "\ud800" not in relative_path:
                    body["backup"]["archive_member_manifest_sha256"] = digest_oracle(
                        body["backup"]["archive_members"]
                    )
                self.assert_contract_error(body)

        unicode_path = valid_logical_body()
        unicode_path["backup"]["archive_members"][0]["relative_path"] = "database/源数据.sql"
        unicode_path["backup"]["archive_member_manifest_sha256"] = digest_oracle(
            unicode_path["backup"]["archive_members"]
        )
        self.assertEqual(self.module.validate_database_source_manifest_body(unicode_path), unicode_path)

        for field, value in (
            ("size_bytes", -1),
            ("size_bytes", True),
            ("size_bytes", 1.5),
            ("sha256", "A" * 64),
        ):
            body = valid_logical_body()
            body["backup"]["archive_members"][0][field] = value
            self.assert_contract_error(body)

        wrong_manifest = valid_logical_body()
        wrong_manifest["backup"]["archive_member_manifest_sha256"] = "0" * 64
        self.assert_contract_error(wrong_manifest)

        empty_members = valid_logical_body()
        empty_members["backup"]["archive_members"] = []
        empty_members["backup"]["archive_member_manifest_sha256"] = digest_oracle([])
        self.assert_contract_error(empty_members)

    def test_canonical_parser_accepts_only_exact_canonical_body_bytes(self) -> None:
        body = valid_logical_body()
        canonical = canonical_oracle(body)
        self.assertEqual(
            self.module.parse_and_verify_database_source_manifest(canonical, matching_digest(canonical)),
            body,
        )

        noncanonical_documents = (
            json.dumps(body, ensure_ascii=False).encode("utf-8"),
            json.dumps(body, ensure_ascii=False, sort_keys=False, separators=(",", ":")).encode("utf-8"),
            canonical + b"\n",
        )
        for document in noncanonical_documents:
            with self.subTest(document=document[:40]):
                self.assert_parse_error(document)

        self.assert_parse_error(b'{"schema":"x","schema":"x"}')
        self.assert_parse_error(canonical.replace(b'"generation":1', b'"generation":1.0', 1))
        self.assert_parse_error(canonical.replace(b'"generation":1', b'"generation":NaN', 1))
        self.assert_parse_error(canonical.replace(b'"generation":1', b'"generation":Infinity', 1))

        surrogate_body = valid_logical_body()
        surrogate_body["source"]["source_schema"] = "bad\ud800schema"
        surrogate_bytes = json.dumps(
            surrogate_body,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self.assert_parse_error(surrogate_bytes)
        self.assert_parse_error(b"\xff")

        deep_document = b"[" * 100 + b"0" + b"]" * 100
        self.assert_parse_error(deep_document)

        for body_value, digest_value in (
            ("not-bytes", matching_digest(canonical)),
            (canonical, "not-bytes"),
        ):
            with self.subTest(body_type=type(body_value), digest_type=type(digest_value)):
                with self.assertRaises(self.module.ContractError):
                    self.module.parse_and_verify_database_source_manifest(body_value, digest_value)

    def test_canonical_parser_wraps_oversized_json_integer_conversion(self) -> None:
        canonical = canonical_oracle(valid_logical_body())
        oversized_integer = canonical.replace(
            b'"generation":1',
            b'"generation":' + b"9" * 5000,
            1,
        )
        self.assert_parse_error(oversized_integer)

        with mock.patch.object(
            self.module.json,
            "loads",
            side_effect=ValueError("Exceeds the limit for integer string conversion"),
        ):
            self.assert_parse_error(canonical)

    def test_canonical_parser_rejects_every_integer_token_outside_generation_one_range(self) -> None:
        canonical = canonical_oracle(valid_logical_body())
        thousand_digit_row_count = canonical.replace(
            b'"row_count":3',
            b'"row_count":' + b"9" * 1000,
            1,
        )

        primary_key_underflow = valid_logical_body()
        self.table(primary_key_underflow, "products")["primary_key_min"] = [I64_MIN - 1]

        primary_key_overflow = valid_logical_body()
        self.table(primary_key_overflow, "products")["primary_key_max"] = [U64_MAX + 1]

        documents = (
            thousand_digit_row_count,
            canonical_oracle(primary_key_underflow),
            canonical_oracle(primary_key_overflow),
        )
        for document in documents:
            with self.subTest(document=document[:80]):
                self.assert_parse_error(document)

    def test_public_parser_wires_generation_one_integer_hook(self) -> None:
        body = valid_logical_body()
        body_bytes = canonical_oracle(body)
        recorded_tokens: list[str] = []
        generation_one_parser = self.module._parse_generation_one_json_integer

        def recording_parser(source: str) -> int:
            recorded_tokens.append(source)
            return generation_one_parser(source)

        with mock.patch.object(
            self.module,
            "_parse_generation_one_json_integer",
            new=recording_parser,
        ):
            parsed = self.module.parse_and_verify_database_source_manifest(
                body_bytes,
                matching_digest(body_bytes),
            )

        self.assertEqual(parsed, body)
        self.assertEqual(
            recorded_tokens,
            [
                "4096",
                "1",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "103",
                "101",
                "3",
            ],
        )

    def test_detached_digest_format_rejects_uppercase_missing_or_extra_lf_and_mismatch(self) -> None:
        body_bytes = canonical_oracle(valid_logical_body())
        digest = matching_digest(body_bytes)
        invalid_digests = (
            digest.upper(),
            digest[:-1],
            digest + b"\n",
            b"0" * 64 + b"\n",
            b"g" * 64 + b"\n",
        )
        for invalid in invalid_digests:
            with self.subTest(invalid=invalid[:12]):
                self.assert_parse_error(body_bytes, invalid)

    def test_backup_sha256_binding_accepts_only_matching_lowercase_digest(self) -> None:
        body = valid_logical_body()
        self.assertEqual(
            self.module.verify_backup_sha256_binding(body, "a" * 64),
            body,
        )
        for actual in ("A" * 64, "a" * 63, "g" * 64, "b" * 64, b"a" * 64):
            with self.subTest(actual=actual):
                with self.assertRaises(self.module.ContractError):
                    self.module.verify_backup_sha256_binding(body, actual)

    def test_source_side_empty_proof_allows_nonempty_products_but_requires_old_tables_and_all_projections_empty(self) -> None:
        body = valid_logical_body()
        self.assertEqual(self.table(body, "products")["row_count"], 3)
        self.assertTrue(self.module.source_manifest_proves_legacy_source_empty(body))

        for table_name in ("amazon_listing_captures", "amazon_stylesnap_candidates"):
            with self.subTest(table=table_name):
                mutated = valid_logical_body()
                table = self.table(mutated, table_name)
                table["row_count"] = 1
                table["primary_key_min"] = [1]
                table["primary_key_max"] = [1]
                self.assertFalse(self.module.source_manifest_proves_legacy_source_empty(mutated))

        for projection_id in REQUIRED_PROJECTIONS:
            with self.subTest(projection=projection_id):
                mutated = valid_logical_body()
                self.projection(mutated, projection_id)["row_count"] = 1
                self.assertFalse(self.module.source_manifest_proves_legacy_source_empty(mutated))

    def test_single_field_mutations_cannot_false_pass(self) -> None:
        mutations = (
            (("source", "server_version"), ""),
            (("table_snapshots", 2, "row_count"), False),
            (("projection_snapshots", 2, "projection_id"), "products"),
            (("backup", "tool", "argv_safe_summary", 1), "--quick"),
            (("backup", "archive_member_manifest_sha256"), "f" * 64),
            (("consistency_proof", "global_read_lock_held"), None),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                body = valid_logical_body()
                target = body
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_contract_error(body)

    def test_import_and_public_calls_have_no_environment_process_network_or_write_side_effects(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-c", side_effect_probe_script(valid_logical_body())],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stdout.strip(), "SIDE_EFFECT_MONITOR_OK")

    def test_project_rule_focused_gates_are_exactly_the_active_pair(self) -> None:
        source = (ROOT / "scripts" / "test_project_rules.py").read_text(encoding="utf-8")
        assert_retired_candidate_surface_absent(ROOT, source)
        expected_argv = {
            "test_integration_hardening_database_source_manifest_contract_gate": (
                '[sys.executable, "-B", str(focused_test)]'
            ),
            "test_integration_hardening_legacy_inventory_executable_gate": (
                '["/usr/bin/python3", "-B", str(focused_test)]'
            ),
        }
        actual_gate_names = {
            line.removeprefix("def ").removesuffix("() -> None:")
            for line in source.splitlines()
            if line.startswith("def test_integration_hardening_")
            and line.endswith("_gate() -> None:")
        }
        self.assertEqual(actual_gate_names, set(expected_argv))
        for gate_name, argv_literal in expected_argv.items():
            with self.subTest(gate_name=gate_name):
                start = source.index(f"def {gate_name}")
                end = source.find("\ndef ", start + 1)
                section = source[start:] if end < 0 else source[start:end]
                self.assertIn(argv_literal, section)
                self.assertNotIn("shell=True", section)
                self.assertEqual(source.count(f"        {gate_name},"), 1)

        negative_path_cases = (
            "scripts/integration_hardening/candidate_command_manifest.json",
            "scripts/testing/test_integration_hardening_manifest.py",
            "scripts/testing/integration_mysql.py",
            "scripts/testing/test_integration_hardening_mysql_contract.py",
        )
        for relative_path in negative_path_cases:
            with self.subTest(retired_path=relative_path):
                with tempfile.TemporaryDirectory(prefix="fbm-i2-retired-path-") as temp_root:
                    resurrected_path = Path(temp_root) / relative_path
                    resurrected_path.parent.mkdir(parents=True)
                    resurrected_path.write_text("# retired surface\n", encoding="utf-8")
                    with self.assertRaises(AssertionError) as caught:
                        assert_retired_candidate_surface_absent(Path(temp_root), source)
                    self.assertIn(relative_path, str(caught.exception))

        negative_reference_cases = (
            "test_integration_hardening_manifest_contract_gate",
            "test_integration_hardening_mysql_contract_gate",
            "candidate_command_manifest.json",
            "test_integration_hardening_manifest.py",
            "integration_mysql.py",
            "test_integration_hardening_mysql_contract.py",
        )
        for identifier in negative_reference_cases:
            with self.subTest(retired_reference=identifier):
                source_with_regression = f"{source}\n# {identifier}\n"
                with self.assertRaises(AssertionError) as caught:
                    assert_retired_candidate_surface_absent(ROOT, source_with_regression)
                self.assertIn(identifier, str(caught.exception))


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
