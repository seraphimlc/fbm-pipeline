#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from integration_hardening.legacy_backup_sanitizer import (  # noqa: E402
    LegacyBackupSanitizationError,
    scan_mysql_dump,
)


SQL_MODE_NORMALIZE = (
    b"/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;\n"
)
SQL_MODE_RESTORE = b"/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;\n"


def with_normalized_sql_mode(source: bytes) -> bytes:
    return SQL_MODE_NORMALIZE + source + SQL_MODE_RESTORE


SAFE_DUMP = b"""-- ordinary header comment
/* DROP DATABASE ignored_inside_ordinary_comment */
# SOURCE ignored_inside_hash_comment
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!50503 SET NAMES utf8mb4 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
DROP TABLE IF EXISTS `products`;
/*!40101 SET @saved_cs_client = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `products` (`id` int NOT NULL, `title` text, PRIMARY KEY (`id`));
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40000 ALTER TABLE `products` DISABLE KEYS */;
LOCK TABLES `products` WRITE;
INSERT INTO `products` VALUES (1,'text; -- DROP DATABASE hidden'),(2,'backslash \\\\ and quote \\'');
UNLOCK TABLES;
/*!40000 ALTER TABLE `products` ENABLE KEYS */;
/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
"""


def scan(
    source: bytes,
    *,
    chunk_size: int = 64,
    target_mysql_version: str = "8.0.46",
) -> dict:
    return scan_mysql_dump(
        io.BytesIO(source),
        expected_backup_sha256=hashlib.sha256(source).hexdigest(),
        target_mysql_version=target_mysql_version,
        chunk_size=chunk_size,
    )


class LegacyBackupSanitizerTests(unittest.TestCase):
    def test_safe_mysqldump_stream_is_deterministic_across_chunk_boundaries(self) -> None:
        expected = scan(SAFE_DUMP, chunk_size=4096)
        for chunk_size in (1, 2, 7, 31):
            with self.subTest(chunk_size=chunk_size):
                self.assertEqual(scan(SAFE_DUMP, chunk_size=chunk_size), expected)
        self.assertEqual(expected["backup_sha256"], hashlib.sha256(SAFE_DUMP).hexdigest())
        self.assertEqual(expected["size_bytes"], len(SAFE_DUMP))
        self.assertEqual(expected["created_table_count"], 1)
        self.assertEqual(expected["executable_comment_count"], 10)
        self.assertEqual(expected["target_mysql_version"], "8.0.46")
        self.assertNotIn("statements", expected)
        self.assertNotIn("table_names", expected)

    def test_forbidden_keywords_inside_quoted_identifiers_are_not_commands(self) -> None:
        safe = (
            b"CREATE TABLE `t` (`event` varchar(10), `trigger` varchar(10), "
            b"`function` varchar(10), `definer` varchar(10), "
            b"`tablespace` varchar(10));",
            b"CREATE TABLE `event``trigger` (`function``definer` varchar(10), "
            b"`tablespace` varchar(10));",
            b"CREATE TABLE `event\\`trigger` (`function\\`definer` varchar(10));",
            b"CREATE TABLE `event``trigger` (`id` int); "
            b"INSERT INTO `event\\`trigger` VALUES (1);",
        )
        for statement in safe:
            source = with_normalized_sql_mode(statement)
            for chunk_size in (1, 2, 7, 64):
                with self.subTest(
                    source_sha256=hashlib.sha256(source).hexdigest()[:12],
                    chunk_size=chunk_size,
                ):
                    result = scan(source, chunk_size=chunk_size)
                    self.assertEqual(result["created_table_count"], 1)

    def test_quoted_identifier_masking_preserves_structural_cross_schema_rejection(self) -> None:
        statements = (
            b"CREATE TABLE `t` (`id` int, FOREIGN KEY (`id`) "
            b"REFERENCES `other`.`event` (`id`));",
            b"CREATE TABLE `t` (`id` int, FOREIGN KEY (`id`) "
            b"REFERENCES `other``schema`.`event` (`id`));",
            b"CREATE TABLE `t` (`id` int, FOREIGN KEY (`id`) "
            b"REFERENCES `other\\`schema`.`event` (`id`));",
        )
        for statement in statements:
            source = with_normalized_sql_mode(statement)
            with self.subTest(source_sha256=hashlib.sha256(source).hexdigest()[:12]):
                with self.assertRaisesRegex(
                    LegacyBackupSanitizationError,
                    "cross_schema_reference",
                ):
                    scan(source, chunk_size=1)

    def test_forbidden_keywords_remain_commands_outside_quoted_identifiers(self) -> None:
        unsafe = (
            b"CREATE EVENT event_name ON SCHEDULE EVERY 1 DAY DO SELECT 1;",
            b"CREATE FUNCTION function_name() RETURNS INT RETURN 1;",
            b"CREATE TABLESPACE tablespace_name ADD DATAFILE '/tmp/data';",
            b"CREATE DEFINER=root@localhost TRIGGER trigger_name "
            b"BEFORE INSERT ON t FOR EACH ROW SET @x=1;",
            with_normalized_sql_mode(
                b"CREATE TABLE `event` (`id` int) TABLESPACE tablespace_name;"
            ),
        )
        for source in unsafe:
            with self.subTest(source_sha256=hashlib.sha256(source).hexdigest()[:12]):
                with self.assertRaisesRegex(
                    LegacyBackupSanitizationError,
                    "forbidden_server_or_file_command",
                ):
                    scan(source)

    def test_closed_session_set_and_alter_keys_allowlist(self) -> None:
        unsafe = (
            b"SET GLOBAL max_connections=100;",
            b"SET SESSION sql_log_bin=0;",
            b"SET @UNREVIEWED=1;",
            with_normalized_sql_mode(
                b"CREATE TABLE `t` (`id` int); ALTER TABLE `t` ADD COLUMN `x` int;"
            ),
            with_normalized_sql_mode(b"ALTER TABLE `not_created` DISABLE KEYS;"),
            with_normalized_sql_mode(b"/*!40000 ALTER TABLE `t` ENABLE KEYS */;"),
        )
        for source in unsafe:
            with self.subTest(source=source[:32]):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan(source)

    def test_rejects_server_account_file_cross_schema_and_executable_comment_commands(self) -> None:
        unsafe = (
            b"CREATE DATABASE escaped;",
            b"DROP SCHEMA escaped;",
            b"USE escaped;",
            b"CREATE USER attacker IDENTIFIED BY 'x';",
            b"GRANT ALL ON *.* TO attacker;",
            b"LOAD DATA LOCAL INFILE '/tmp/x' INTO TABLE t;",
            b"SELECT 1 INTO OUTFILE '/tmp/x';",
            with_normalized_sql_mode(b"CREATE TABLE `other`.`t` (`id` int);"),
            b"/*!80046 DROP DATABASE escaped */;",
            b"/*!80046 DEFINER=root@localhost TRIGGER x BEFORE INSERT ON t FOR EACH ROW SET @x=1 */;",
        )
        for source in unsafe:
            with self.subTest(source=source[:32]):
                with self.assertRaises(LegacyBackupSanitizationError) as raised:
                    scan(source)
                self.assertNotIn("attacker", str(raised.exception))
                self.assertNotIn("/tmp/x", str(raised.exception))

    def test_create_and_insert_full_statement_grammar_rejects_query_engine_and_file_suffixes(self) -> None:
        unsafe = (
            with_normalized_sql_mode(
                b"CREATE TABLE `t` (`id` int) AS SELECT `id` FROM `business`.`products`;"
            ),
            with_normalized_sql_mode(
                b"CREATE TABLE `t` (`id` int) ENGINE=FEDERATED CONNECTION='remote';"
            ),
            with_normalized_sql_mode(
                b"CREATE TABLE `t` (`id` int) ENGINE=MERGE UNION=(`business`.`products`);"
            ),
            with_normalized_sql_mode(
                b"CREATE TABLE `t` (`id` int); "
                b"INSERT INTO `t` VALUES ((SELECT `id` FROM `business`.`products`));"
            ),
            with_normalized_sql_mode(
                b"CREATE TABLE `t` (`id` text); "
                b"INSERT INTO `t` VALUES (LOAD_FILE('/etc/passwd'));"
            ),
        )
        for source in unsafe:
            with self.subTest(source_sha256=hashlib.sha256(source).hexdigest()[:12]):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan(source)

    def test_sql_mode_normalization_order_is_required_for_all_data_statements(self) -> None:
        exact_no_backslash_escape_bypass = (
            b"CREATE TABLE `t` (`v` text,`stolen` text); "
            b"INSERT INTO `t` VALUES ('x\\', (SELECT `id` FROM `business`.`products` LIMIT 1)); "
            b"# ');\n"
        )
        unsafe = (
            exact_no_backslash_escape_bypass,
            b"CREATE TABLE `t` (`id` int);" + SQL_MODE_NORMALIZE + SQL_MODE_RESTORE,
            SQL_MODE_NORMALIZE + b"CREATE TABLE `t` (`id` int);",
            SQL_MODE_RESTORE
            + SQL_MODE_NORMALIZE
            + b"CREATE TABLE `t` (`id` int);"
            + SQL_MODE_RESTORE,
            SQL_MODE_NORMALIZE
            + SQL_MODE_NORMALIZE
            + b"CREATE TABLE `t` (`id` int);"
            + SQL_MODE_RESTORE,
            SQL_MODE_NORMALIZE
            + b"CREATE TABLE `t` (`id` int);"
            + SQL_MODE_RESTORE
            + b"INSERT INTO `t` VALUES (1);",
            SQL_MODE_NORMALIZE + SQL_MODE_RESTORE,
            SQL_MODE_NORMALIZE
            + b"CREATE TABLE `t` (`id` int);"
            + SQL_MODE_RESTORE
            + b"SET NAMES utf8mb4;",
        )
        for source in unsafe:
            with self.subTest(source_sha256=hashlib.sha256(source).hexdigest()[:12]):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan(source)

    def test_executable_comment_version_gate_uses_verified_target_mysql_version(self) -> None:
        executed = (
            ("8.0.46", b"/*!40101 DROP DATABASE escaped */;"),
            ("8.0.46", b"/*!80046 DROP DATABASE escaped */;"),
            ("10.2.3", b"/*!100202 DROP DATABASE escaped */;"),
            ("10.2.3", b"/*!100203 DROP DATABASE escaped */;"),
            ("8.0.46", b"/*! DROP DATABASE escaped */;"),
        )
        for target_mysql_version, source in executed:
            with self.subTest(target_mysql_version=target_mysql_version, source=source[:12]):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan(source, target_mysql_version=target_mysql_version)

        ignored = (
            ("8.0.46", b"/*!80047 DROP DATABASE escaped */;"),
            ("10.2.3", b"/*!100204 DROP DATABASE escaped */;"),
        )
        for target_mysql_version, source in ignored:
            with self.subTest(target_mysql_version=target_mysql_version, source=source[:12]):
                result = scan(source, target_mysql_version=target_mysql_version)
                self.assertEqual(result["statement_count"], 0)
                self.assertEqual(result["executable_comment_count"], 1)

        high_version_bypass = (
            b"/*!999999 SET @OLD_SQL_MODE=@@SQL_MODE, "
            b"SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;\n"
            b"CREATE TABLE `t` (`v` text,`stolen` text); "
            b"INSERT INTO `t` VALUES ('x\\', "
            b"(SELECT `id` FROM `business`.`products` LIMIT 1)); "
            b"# ');\n"
            b"/*!999999 SET SQL_MODE=@OLD_SQL_MODE */;\n"
        )
        with self.assertRaises(LegacyBackupSanitizationError):
            scan(high_version_bypass, target_mysql_version="8.0.46")

    def test_comment_boundaries_preserve_ignored_and_standalone_execution_semantics(
        self,
    ) -> None:
        cases = (
            ("ordinary", b"SET/* ignored */NAMES utf8mb4;", 0),
            ("above_target", b"SET/*!999999 ignored */NAMES utf8mb4;", 1),
            ("equal_target", b"/*!80046 SET NAMES utf8mb4 */;", 1),
            ("below_target", b"/*!40101 SET NAMES utf8mb4 */;", 1),
        )
        for label, source, executable_comment_count in cases:
            for chunk_size in (1, 2, 7, 64):
                with self.subTest(label=label, chunk_size=chunk_size):
                    result = scan(
                        source,
                        target_mysql_version="8.0.46",
                        chunk_size=chunk_size,
                    )
                    self.assertEqual(
                        result["statement_type_counts"],
                        {"set_session": 1},
                    )
                    self.assertEqual(result["statement_count"], 1)
                    self.assertEqual(
                        result["executable_comment_count"],
                        executable_comment_count,
                    )

    def test_inline_executable_fragments_fail_closed(self) -> None:
        for source in (
            b"SET/*!80046 NAMES */utf8mb4;",
            b"SET/*!40101 NAMES */utf8mb4;",
        ):
            for chunk_size in (1, 2, 7, 64):
                with self.subTest(source=source[:16], chunk_size=chunk_size):
                    with self.assertRaisesRegex(
                        LegacyBackupSanitizationError,
                        "inline executable comment fragments are not supported",
                    ):
                        scan(source, chunk_size=chunk_size)

    def test_executable_comment_body_lexical_state_cannot_escape_its_boundary(
        self,
    ) -> None:
        unsafe = (
            (
                "nested_block",
                b"/*!40101 SET NAMES utf8mb4 /* nested */; "
                b"DROP DATABASE escaped; */",
                "unterminated block comment",
            ),
            (
                "dash_comment",
                b"/*!40101 SET NAMES utf8mb4 -- */; DROP DATABASE escaped;",
                "unterminated executable comment body line comment",
            ),
            (
                "hash_comment",
                b"/*!40101 SET NAMES utf8mb4 # */; DROP DATABASE escaped;",
                "unterminated executable comment body line comment",
            ),
            (
                "single_quote",
                b"/*!40101 SET NAMES utf8mb4 ' */'; DROP DATABASE escaped;",
                "unterminated quoted string",
            ),
            (
                "double_quote",
                b'/*!40101 SET NAMES utf8mb4 " */"; DROP DATABASE escaped;',
                "unterminated quoted string",
            ),
            (
                "backtick",
                b"/*!40101 SET NAMES utf8mb4 ` */`; DROP DATABASE escaped;",
                "unterminated quoted string",
            ),
        )
        for label, source, error_pattern in unsafe:
            for chunk_size in (1, 2, 7, 64):
                with self.subTest(label=label, chunk_size=chunk_size):
                    with self.assertRaisesRegex(
                        LegacyBackupSanitizationError,
                        error_pattern,
                    ):
                        scan(source, chunk_size=chunk_size)

    def test_target_mysql_version_and_executable_comment_gate_must_be_canonical(self) -> None:
        source = b""
        digest = hashlib.sha256(source).hexdigest()
        with self.assertRaises(TypeError):
            scan_mysql_dump(io.BytesIO(source), expected_backup_sha256=digest)

        invalid_versions = (
            None,
            True,
            80046,
            "",
            "8.0",
            "8.0.46.0",
            "08.0.46",
            "8.00.46",
            "8.0.046",
            "8.0.100",
            "100.0.0",
            "8.0.46-commercial",
        )
        for target_mysql_version in invalid_versions:
            with self.subTest(target_mysql_version=target_mysql_version):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan_mysql_dump(
                        io.BytesIO(source),
                        expected_backup_sha256=digest,
                        target_mysql_version=target_mysql_version,
                    )

        for malformed_gate in (
            b"/*!4010 SET NAMES utf8mb4 */;",
            b"/*!1000000 SET NAMES utf8mb4 */;",
        ):
            with self.subTest(malformed_gate=malformed_gate[:12]):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan(malformed_gate)

    def test_rejects_all_mysql_client_meta_command_surfaces(self) -> None:
        unsafe = (
            b"\\! id\n",
            b"SYSTEM id;",
            b"CONNECT db.example;",
            b"SOURCE /tmp/escape.sql;",
            b"DELIMITER $$\nCREATE TABLE t(id int)$$",
            b"TEE /tmp/mysql.log;",
            b"PAGER cat;",
            b"PROMPT secret;",
            b"\\q\n",
        )
        for source in unsafe:
            with self.subTest(source=source[:16]):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan(source)

    def test_hash_mismatch_and_unterminated_lexical_state_fail_closed(self) -> None:
        with self.assertRaises(LegacyBackupSanitizationError):
            scan_mysql_dump(
                io.BytesIO(SAFE_DUMP),
                expected_backup_sha256="0" * 64,
                target_mysql_version="8.0.46",
                chunk_size=3,
            )
        for source in (
            b"INSERT INTO t VALUES ('unterminated);",
            b"CREATE TABLE `unterminated (`id` int);",
            b"/* unterminated",
        ):
            with self.subTest(source=source):
                with self.assertRaises(LegacyBackupSanitizationError):
                    scan(source)


if __name__ == "__main__":
    unittest.main()
